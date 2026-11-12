// IW4x-32: the asset upload router of the native renderer - the game's texture and geometry requests
// answered with Vulkan images and buffers made beside the D3D9 ones. See VulkanAssetLoader.hpp for
// what this layer owns, when it is on, and what it deliberately does not do.

#include "VulkanAssetLoader.hpp"
#include "IW4x32.hpp" // r_backend, and the component that owns the device this is attached to
#include "Scheduler.hpp" // the renderer-frame check that re-installs after a vid_restart
#include "Logger.hpp" // a refusal has to be readable in a run's log, not only counted

#include <Utils/String.hpp> // the refusal lines: they name the numbers this layer saw

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>

namespace VulkanAssetLoader
{
  namespace
  {
    // ------------------------------------------------------------------- the calls this layer answers
    //
    // Slots of the engine's device vtable. iw4x32/reference/vulkan_boundary.json proves one call site
    // per call and names the slot; the displacement in the bytes at that site says the same number:
    //   CreateTexture        0x0051F0E9  mov edx, [edx + 0x5C]  slot 23
    //   CreateVertexBuffer   0x00508C0F  mov edx, [ecx + 0x68]  slot 26
    //   CreateIndexBuffer    0x0051E73C  mov eax, [ecx + 0x6C]  slot 27
    //   UpdateTexture        0x00525063  mov eax, [ecx + 0x7C]  slot 31
    // The same file's evidence names the other sites (two CreateTexture, five CreateVertexBuffer, two
    // CreateIndexBuffer) and every one of them loads the device out of the same global, which is why
    // one vtable swap covers the whole upload path instead of a patch per site.
    constexpr unsigned int SLOT_CREATE_TEXTURE = 23U;
    constexpr unsigned int SLOT_CREATE_VERTEX_BUFFER = 26U;
    constexpr unsigned int SLOT_CREATE_INDEX_BUFFER = 27U;
    constexpr unsigned int SLOT_UPDATE_TEXTURE = 31U;

    // How far the copy of the table reaches: the highest slot the boundary file proves is CreateQuery
    // at 118, so 119 entries. What the driver's table holds after that is not read at all - Install
    // stops at the end of the mapped region the table actually lives in and refuses when that is too
    // short to reach the four slots above.
    constexpr unsigned int DEVICE_VTABLE_SLOTS = 119U;

    // The device-shaped object the engine runs its resource calls through. The boundary file's evidence
    // names it as the global 0x066DEF88 for all four calls; the fork's own game header calls the same
    // word Game::dx_ptr (src/Game/Functions.cpp), and Renderer.cpp's BackendFrameHandler reads that
    // same word to hand the device to a frame callback - so it is used by name here rather than by the
    // reference build's number, and the header is the thing that has to be right.

    // The interface id of IDirect3DTexture9, spelled out with the numbers deps/dxsdk/Include/d3d9.h
    // gives it. The header's DEFINE_GUID leaves it an extern and this build links no d3d9iid library,
    // so the name would be an unresolved external - and the id is what a driver is asked for, not a
    // type to trust: a source that is not a 2D texture answers E_NOINTERFACE and is refused by name.
    const GUID G_TEXTURE9_INTERFACE = {0x85c31227, 0x3de5, 0x4f00,
                                       {0x9b, 0x3a, 0xf1, 0x1a, 0xc3, 0x8c, 0x18, 0xb5}};

    // How much the layer will hold. A game level asks for a few thousand textures and buffers, and
    // every one of them is a vkCreateImage of its own until this layer grows an allocator - so the
    // cap is generous and, more importantly, visible: past it the layer refuses and counts, which is
    // a number in iw4x32_vkas instead of a heap the run never sees.
    constexpr std::size_t MAX_RESOURCES = 8192U;

    // The four entries this layer puts on its copy of the table, in the shape the engine calls them:
    // the sites push the device pointer as the first argument and call the table entry, which is the
    // STDMETHODCALLTYPE convention d3d9.h declares, so a plain function with this as its first
    // parameter has exactly the right signature - no assembly, no calling-convention trick.
    using CreateTextureFn = HRESULT(WINAPI*)(IDirect3DDevice9* device, UINT width, UINT height, UINT levels,
                                            DWORD usage, D3DFORMAT format, D3DPOOL pool,
                                            IDirect3DTexture9** outTexture, HANDLE sharedHandle);
    using CreateVertexBufferFn = HRESULT(WINAPI*)(IDirect3DDevice9* device, UINT length, DWORD usage, DWORD fvf,
                                                 D3DPOOL pool, IDirect3DVertexBuffer9** outBuffer, HANDLE sharedHandle);
    using CreateIndexBufferFn = HRESULT(WINAPI*)(IDirect3DDevice9* device, UINT length, DWORD usage, D3DFORMAT format,
                                                D3DPOOL pool, IDirect3DIndexBuffer9** outBuffer, HANDLE sharedHandle);
    using UpdateTextureFn = HRESULT(WINAPI*)(IDirect3DDevice9* device, IDirect3DBaseTexture9* source,
                                             IDirect3DBaseTexture9* destination);

    // The four entries, in front of Install because Install puts them on the table. Each one calls the
    // driver's own entry first, so the D3D9 upload runs exactly as it always did, and then answers the
    // same request to Vulkan when r_backend says that is the backend. A router that failed its Vulkan
    // half returns the D3D9 result anyway: the game keeps running on the path that works, and the
    // refusal is counted and logged where a run can read it.
    HRESULT WINAPI CreateTexture_Router(IDirect3DDevice9* device, UINT width, UINT height, UINT levels,
                                        DWORD usage, D3DFORMAT format, D3DPOOL pool,
                                        IDirect3DTexture9** outTexture, HANDLE sharedHandle);
    HRESULT WINAPI CreateVertexBuffer_Router(IDirect3DDevice9* device, UINT length, DWORD usage, DWORD fvf,
                                             D3DPOOL pool, IDirect3DVertexBuffer9** outBuffer, HANDLE sharedHandle);
    HRESULT WINAPI CreateIndexBuffer_Router(IDirect3DDevice9* device, UINT length, DWORD usage, D3DFORMAT format,
                                            D3DPOOL pool, IDirect3DIndexBuffer9** outBuffer, HANDLE sharedHandle);
    HRESULT WINAPI UpdateTexture_Router(IDirect3DDevice9* device, IDirect3DBaseTexture9* source,
                                        IDirect3DBaseTexture9* destination);

    void* g_Table[DEVICE_VTABLE_SLOTS] = {};  // our copy: what the object is pointed at
    void* g_Original[DEVICE_VTABLE_SLOTS] = {}; // the driver's entries, kept to call through

    const VulkanDevice::Device* g_Device = nullptr;
    void** g_Object = nullptr;      // the engine's device slot (Game::dx_ptr): the word holding the vtable ptr
    void* g_OriginalTable = nullptr; // what that word held before us (null while uninstalled)
    std::vector<Resource> g_Resources;

    unsigned int g_Requests = 0U;
    unsigned int g_TexturesRouted = 0U;
    unsigned int g_TexturesMade = 0U;
    unsigned int g_PixelUploads = 0U;
    unsigned int g_GeometryMade = 0U;
    unsigned int g_Refusals = 0U;
    std::uint64_t g_Bytes = 0ULL;
    char g_Refusal[256] = "";
    bool g_Refreshing = false; // the renderer-frame check is asked for once, not once per attach

    // A reason the caller keeps: VulkanResources' reasons belong to that file and die at its next
    // call, so every reason handed out here is copied into a buffer of ours first.
    void refuse(const char* what)
    {
      g_Refusals++;
      std::snprintf(g_Refusal, sizeof(g_Refusal), "%s", what != nullptr ? what : "no reason given");
    }

    const char* keep(const char* reason)
    {
      static char kept[256];
      std::snprintf(kept, sizeof(kept), "%s", reason != nullptr ? reason : "no reason given");
      return kept;
    }

    // Copy out what VulkanResources answered, so a refusal says who refused and why.
    void refuse_layer(const char* what, const char* reason)
    {
      refuse(Utils::String::VA("%s: %s", what, reason != nullptr ? reason : "no reason given"));
    }

    // Is this memory readable, and does the range asked for stay inside the region it answers with?
    // Everything about the engine's objects is read before it is believed, because an exe that is not
    // the one the boundary file describes would otherwise be a call through a garbage pointer.
    bool Readable(const void* at, const std::size_t len)
    {
      MEMORY_BASIC_INFORMATION info{};

      if (at == nullptr ||
          VirtualQuery(at, &info, sizeof(info)) != sizeof(info) ||
          info.State != MEM_COMMIT ||
          (info.AllocationProtect & PAGE_GUARD) != 0U)
        return false;

      const auto readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ |
                            PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
      if ((info.Protect & readable) == 0U || (info.Protect & PAGE_GUARD) != 0U)
        return false;

      if (info.RegionSize < len)
        return false;

      const auto* base = static_cast<const unsigned char*>(info.BaseAddress);
      if (at < base)
        return false;

      return static_cast<std::size_t>(static_cast<const unsigned char*>(at) - base) <= info.RegionSize - len;
    }

    // The engine's device object, or NULL. The object is not created by us and the word that holds it
    // belongs to the engine, so it is checked rather than assumed: a pointer in it, a vtable of readable
    // entries, and every entry of the range we intend to copy non-null.
    void** DeviceObject()
    {
      auto* slot = reinterpret_cast<void**>(Game::dx_ptr);

      if (!Readable(slot, sizeof(void*)))
        return nullptr;

      const auto* table = *slot;
      if (table == nullptr || !Readable(table, DEVICE_VTABLE_SLOTS * sizeof(void*)))
        return nullptr;

      for (unsigned int i = 0U; i < DEVICE_VTABLE_SLOTS; i++)
        if (reinterpret_cast<void* const*>(table)[i] == nullptr)
          return nullptr;

      return slot;
    }

    // How many entries of that table are inside its own mapped region: a table the copy would run past
    // is not copied.
    unsigned int TableEntries(void* table)
    {
      unsigned int count = 0U;
      while (count < DEVICE_VTABLE_SLOTS &&
             Readable(static_cast<const unsigned char*>(table) + count * sizeof(void*), sizeof(void*)))
        count++;
      return count;
    }

    // The router's answer for one of the four calls: install / uninstall of the table.
    bool Install(char* reason, const std::size_t reasonSize)
    {
      if (g_Object != nullptr)
        return true;

      auto* object = DeviceObject();
      if (object == nullptr)
      {
        std::snprintf(reason, reasonSize,
                      "the engine's device slot %p does not hold an IDirect3DDevice9 vtable",
                      static_cast<const void*>(Game::dx_ptr));
        return false;
      }

      auto* table = *object;
      const auto entries = TableEntries(table);
      if (entries <= SLOT_UPDATE_TEXTURE)
      {
        std::snprintf(reason, reasonSize, "the device vtable %p ends at entry %u, before slot %u",
                      table, entries, SLOT_UPDATE_TEXTURE);
        return false;
      }

      for (unsigned int i = 0U; i < entries; i++)
      {
        g_Original[i] = reinterpret_cast<void* const*>(table)[i];
        g_Table[i] = g_Original[i];
      }

      g_Table[SLOT_CREATE_TEXTURE] = reinterpret_cast<void*>(&CreateTexture_Router);
      g_Table[SLOT_CREATE_VERTEX_BUFFER] = reinterpret_cast<void*>(&CreateVertexBuffer_Router);
      g_Table[SLOT_CREATE_INDEX_BUFFER] = reinterpret_cast<void*>(&CreateIndexBuffer_Router);
      g_Table[SLOT_UPDATE_TEXTURE] = reinterpret_cast<void*>(&UpdateTexture_Router);

      // The object's vtable pointer is data in the exe's own .data (the engine writes it when it
      // creates the device), and IW4x32's own table writes go through the same VirtualProtect pair.
      DWORD old = 0U;
      if (VirtualProtect(object, sizeof(void*), PAGE_READWRITE, &old) == 0U)
      {
        std::snprintf(reason, reasonSize, "the device slot %p is not writable",
                      static_cast<const void*>(Game::dx_ptr));
        return false;
      }

      g_OriginalTable = table;
      *object = static_cast<void*>(g_Table);
      VirtualProtect(object, sizeof(void*), old, &old);

      g_Object = object;
      return true;
    }

    void Uninstall()
    {
      if (g_Object == nullptr)
        return;

      DWORD old = 0U;
      if (VirtualProtect(g_Object, sizeof(void*), PAGE_READWRITE, &old) != 0U)
      {
        *g_Object = g_OriginalTable;
        VirtualProtect(g_Object, sizeof(void*), old, &old);
      }

      g_Object = nullptr;
      g_OriginalTable = nullptr;
    }

    // The engine's vtable pointer changed underneath us (a vid_restart made a new device, a device
    // recovery replaced the wrapper): our table is no longer in front of the calls. Drop it, and let
    // the next Refresh put it on the object that exists now.
    bool InFront()
    {
      return g_Object != nullptr && *g_Object == static_cast<void*>(g_Table);
    }

    Resource* FindByD3D(void* d3d)
    {
      for (auto& r : g_Resources)
        if (r.d3d == d3d)
          return &r;
      return nullptr;
    }

    // D3DFORMAT -> VkFormat for the formats this renderer converts to today. Anything else (a BC/DXT
    // compressed one, a packed 10-bit one) comes back UNDEFINED and the caller refuses it by name:
    // VulkanResources' texel table refuses to guess a mip chain for a format it does not know either,
    // so a compressed texture is a conversion for this phase, not a guess made here.
    VkFormat MapFormat(const D3DFORMAT format)
    {
      switch (format)
      {
      case D3DFMT_A8R8G8B8:
      case D3DFMT_X8R8G8B8:
        return VK_FORMAT_B8G8R8A8_UNORM;
      case D3DFMT_D24S8:
        return VK_FORMAT_D24_UNORM_S8_UINT;
      case D3DFMT_D32:
        return VK_FORMAT_D32_SFLOAT;
      default:
        return VK_FORMAT_UNDEFINED;
      }
    }

    // ------------------------------------------------------------------ what one request becomes
    //
    // The image the engine's texture turns into: the same extent, the same mip count, SAMPLED so the
    // renderer can bind it and TRANSFER_DST so the bytes can be copied into it. Memory is asked for as
    // DEVICE_LOCAL, which is what a texture wants, and as HOST_VISIBLE when this device has no
    // device-local heap at all - the resource layer reports that at Init, and a renderer that ignored
    // it would watch vkAllocateMemory fail on the hundredth material instead of drawing on an iGPU.
    bool RouteTexture(void* texture, const unsigned int width, const unsigned int height,
                      const unsigned int mipLevels, const unsigned int d3dFormat, const char** error)
    {
      const auto say = [error](const char* reason)
      {
        if (error != nullptr)
          *error = keep(reason);
      };

      if (g_Device == nullptr || texture == nullptr || width == 0U || height == 0U)
      {
        refuse("a texture request without a device, without the engine's object, or with no extent");
        say("the texture request was refused; see iw4x32_vkas");
        return false;
      }

      const auto vkFormat = MapFormat(static_cast<D3DFORMAT>(d3dFormat));
      if (vkFormat == VK_FORMAT_UNDEFINED)
      {
        refuse(Utils::String::VA("D3D texture format 0x%08X has no VkFormat here (a compressed format is a conversion, not a guess)",
                                 d3dFormat));
        say("the texture's format is not converted yet");
        return false;
      }

      if (g_Resources.size() >= MAX_RESOURCES)
      {
        refuse(Utils::String::VA("the layer holds its %u resources already - the cap is what keeps a leak from growing",
                                 MAX_RESOURCES));
        say("the layer's resource table is full");
        return false;
      }

      const VkImageCreateInfo info = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
                                      nullptr,
                                      0U,
                                      VK_IMAGE_TYPE_2D,
                                      vkFormat,
                                      {width, height, 1U},
                                      1U,
                                      mipLevels == 0U ? 1U : mipLevels,
                                      VK_SAMPLE_COUNT_1_BIT,
                                      VK_IMAGE_TILING_OPTIMAL,
                                      VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT |
                                          VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
                                      VK_SHARING_MODE_EXCLUSIVE,
                                      0U,
                                      nullptr,
                                      VK_IMAGE_LAYOUT_UNDEFINED};

      const auto properties = VulkanResources::HasDeviceLocalMemory()
                                  ? VkMemoryPropertyFlags{VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT}
                                  : VkMemoryPropertyFlags{VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                                                          VK_MEMORY_PROPERTY_HOST_COHERENT_BIT};

      VulkanResources::Image image{};
      const char* why = nullptr;
      if (!VulkanResources::CreateImage(*g_Device, info, properties, image, &why))
      {
        refuse_layer("vkCreateImage for the engine's texture", why);
        say("the Vulkan layer refused the image; see iw4x32_vkas");
        return false;
      }

      Resource record{};
      record.d3d = texture;
      record.image = image;
      record.width = width;
      record.height = height;
      record.d3dFormat = d3dFormat;
      record.bytes = image.size;
      record.isTexture = true;

      g_Resources.push_back(record);
      g_TexturesMade++;
      g_Bytes += image.size;

      if (error != nullptr)
        *error = nullptr;
      return true;
    }

    // Bytes per texel of the formats MapFormat accepts. The sizes this file works out have to agree with
    // the texel table inside VulkanResources' UploadBufferToImage, which is the code that walks the mip
    // chain, so a format outside that agreement is refused instead of uploaded at a guessed size.
    std::size_t TexelBytes(const D3DFORMAT format)
    {
      switch (format)
      {
      case D3DFMT_A8R8G8B8:
      case D3DFMT_X8R8G8B8:
      case D3DFMT_D24S8:
      case D3DFMT_D32:
        return 4U;
      default:
        return 0U;
      }
    }

    // The engine's own sysmem -> video copy (UpdateTexture), answered with vkCmdCopyBufferToImage into
    // the image made for that texture. The bytes are read out of the source the engine handed the D3D9
    // call - it owns that texture and it is a system-memory one by the contract of the call - and each
    // mip's rows are packed tightly, which is what the layer's copy expects per region.
    //
    // A destination this layer never made is a refusal, not a silent pass: it means the texture was
    // created before the Vulkan path was attached (a texture of the first level load, before the device
    // existed), and an upload that reaches half the game's textures while claiming to reach all of them
    // is exactly the claim this layer must not make.
    bool RoutePixels(void* sourceTexture, void* destinationTexture, const char** error)
    {
      const auto say = [error](const char* reason)
      {
        if (error != nullptr)
          *error = keep(reason);
      };

      auto* record = FindByD3D(destinationTexture);
      if (g_Device == nullptr || sourceTexture == nullptr || record == nullptr)
      {
        refuse(destinationTexture != nullptr && record == nullptr
                   ? "UpdateTexture's destination was not created while the Vulkan path was attached"
                   : "an UpdateTexture request without a device or without a source");
        say("this texture reached the Vulkan path too early to have an image; see iw4x32_vkas");
        return false;
      }

      // UpdateTexture's arguments are base textures, and only a 2D one has bytes this layer can read.
      // Asked through COM's own QueryInterface rather than by a cast, so a volume or a cube source is
      // refused by name instead of being treated as something it is not: the rect methods this layer
      // needs are not on the base interface, and calling them through the wrong vtable is a jump to
      // whatever the driver put at that slot.
      auto* base = static_cast<IDirect3DBaseTexture9*>(sourceTexture);
      auto* source = static_cast<IDirect3DTexture9*>(nullptr);

      if (FAILED(base->QueryInterface(G_TEXTURE9_INTERFACE, reinterpret_cast<void**>(&source))) || source == nullptr)
      {
        refuse("UpdateTexture's source is not an IDirect3DTexture9 (a volume or cube upload is not read here)");
        say("the source of this upload is not a 2D texture");
        return false;
      }

      const auto levels = source->GetLevelCount();
      const auto texelBytes = TexelBytes(static_cast<D3DFORMAT>(record->d3dFormat));

      if (levels == 0U || texelBytes == 0U)
      {
        source->Release();
        refuse(Utils::String::VA("UpdateTexture of a texture with %u levels and %zu bytes per texel",
                                 levels, texelBytes));
        say("the layer cannot size this texture's mip chain");
        return false;
      }

      std::vector<unsigned char> packed;
      for (UINT level = 0U; level < levels; level++)
      {
        D3DLOCKED_RECT locked{};
        if (FAILED(source->LockRect(level, &locked, nullptr, 0)) || locked.pBits == nullptr)
        {
          source->Release();
          refuse(Utils::String::VA("LockRect on the system-memory source, level %u", level));
          say("the source texture would not give up its bytes");
          return false;
        }

        D3DSURFACE_DESC desc{};
        const bool described = SUCCEEDED(source->GetLevelDesc(level, &desc));
        const auto rowBytes = described && desc.Width > 0U ? static_cast<std::size_t>(desc.Width) * texelBytes
                                                           : static_cast<std::size_t>(locked.Pitch);
        for (UINT row = 0U; described && row < desc.Height; row++)
        {
          const auto* from = static_cast<const unsigned char*>(locked.pBits) + static_cast<std::size_t>(row) * locked.Pitch;
          packed.insert(packed.end(), from, from + rowBytes);
        }

        source->UnlockRect(level);

        if (!described)
          break;
      }

      source->Release();

      if (packed.empty())
      {
        refuse("the system-memory source produced no bytes to copy");
        say("no pixels to upload");
        return false;
      }

      const char* why = nullptr;
      if (!VulkanResources::UploadBufferToImage(*g_Device, packed.data(),
                                                static_cast<VkDeviceSize>(packed.size()), record->image,
                                                VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, &why))
      {
        refuse_layer("vkCmdCopyBufferToImage of the engine's pixels", why);
        say("the Vulkan layer refused the upload; see iw4x32_vkas");
        return false;
      }

      record->uploaded = true;
      g_PixelUploads++;

      if (error != nullptr)
        *error = nullptr;
      return true;
    }

    // A vertex or index buffer: vkCreateBuffer of the length the engine asked for, with the usage its
    // role implies plus TRANSFER_DST so the bytes can be put in later. The bytes are NOT here: the
    // engine fills these objects through Lock on the buffer's own vtable (the boundary file says so for
    // CreateIndexBuffer, and the five CreateVertexBuffer sites are filled the same way), and that vtable
    // is not this layer's to change yet. A buffer of the right size with no vertices in it is recorded
    // as made, not as uploaded, and the two numbers are counted apart for that reason.
    bool RouteGeometry(void* buffer, const unsigned int length, const VkBufferUsageFlags usage,
                       const char** error)
    {
      const auto say = [error](const char* reason)
      {
        if (error != nullptr)
          *error = keep(reason);
      };

      if (g_Device == nullptr || buffer == nullptr || length == 0U)
      {
        refuse("a buffer request without a device, without the engine's object, or of zero length");
        say("the buffer request was refused; see iw4x32_vkas");
        return false;
      }

      if (g_Resources.size() >= MAX_RESOURCES)
      {
        refuse(Utils::String::VA("the layer holds its %u resources already", MAX_RESOURCES));
        say("the layer's resource table is full");
        return false;
      }

      VulkanResources::Buffer made{};
      const char* why = nullptr;
      const auto properties = VulkanResources::HasDeviceLocalMemory()
                                  ? VkMemoryPropertyFlags{VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT}
                                  : VkMemoryPropertyFlags{VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                                                          VK_MEMORY_PROPERTY_HOST_COHERENT_BIT};

      if (!VulkanResources::CreateBuffer(*g_Device, static_cast<VkDeviceSize>(length),
                                         usage | VK_BUFFER_USAGE_TRANSFER_DST_BIT, properties, made, &why))
      {
        refuse_layer("vkCreateBuffer for the engine's geometry", why);
        say("the Vulkan layer refused the buffer; see iw4x32_vkas");
        return false;
      }

      Resource record{};
      record.d3d = buffer;
      record.buffer = made;
      record.bytes = made.size;
      record.isTexture = false;

      g_Resources.push_back(record);
      g_GeometryMade++;
      g_Bytes += made.size;

      if (error != nullptr)
        *error = nullptr;
      return true;
    }

    // One refusal in the log, up to the first eight of them: a router that refuses every texture of a
    // level would otherwise print the level. The count and the last reason stay on iw4x32_vkas.
    void ReportRefusal()
    {
      if (g_Refusals <= 8U)
        Components::Logger::Print("IW4X32_VKAS_REFUSAL;{}\n", g_Refusal);
    }

    // ------------------------------------------------------------------ the four entries
    //
    // Each calls the driver's entry first. The D3D9 upload is what the game has always done, it runs in
    // full whether the Vulkan half works or not, and its HRESULT is what comes back - a router that
    // cannot answer its own half never changes what the engine sees.

    HRESULT WINAPI CreateTexture_Router(IDirect3DDevice9* device, UINT width, UINT height, UINT levels,
                                        DWORD usage, D3DFORMAT format, D3DPOOL pool,
                                        IDirect3DTexture9** outTexture, HANDLE sharedHandle)
    {
      const auto result = reinterpret_cast<CreateTextureFn>(g_Original[SLOT_CREATE_TEXTURE])(
          device, width, height, levels, usage, format, pool, outTexture, sharedHandle);

      g_Requests++;

      if (FAILED(result) || outTexture == nullptr || *outTexture == nullptr || !Routing())
        return result;

      const char* why = nullptr;
      if (!RouteTexture(*outTexture, width, height, levels, static_cast<unsigned int>(format), &why))
        ReportRefusal();
      else
        g_TexturesRouted++;

      return result;
    }

    HRESULT WINAPI CreateVertexBuffer_Router(IDirect3DDevice9* device, UINT length, DWORD usage, DWORD fvf,
                                             D3DPOOL pool, IDirect3DVertexBuffer9** outBuffer, HANDLE sharedHandle)
    {
      const auto result = reinterpret_cast<CreateVertexBufferFn>(g_Original[SLOT_CREATE_VERTEX_BUFFER])(
          device, length, usage, fvf, pool, outBuffer, sharedHandle);

      g_Requests++;

      if (FAILED(result) || outBuffer == nullptr || *outBuffer == nullptr || !Routing())
        return result;

      const char* why = nullptr;
      if (!RouteGeometry(*outBuffer, length, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT, &why))
        ReportRefusal();

      return result;
    }

    HRESULT WINAPI CreateIndexBuffer_Router(IDirect3DDevice9* device, UINT length, DWORD usage, D3DFORMAT format,
                                            D3DPOOL pool, IDirect3DIndexBuffer9** outBuffer, HANDLE sharedHandle)
    {
      const auto result = reinterpret_cast<CreateIndexBufferFn>(g_Original[SLOT_CREATE_INDEX_BUFFER])(
          device, length, usage, format, pool, outBuffer, sharedHandle);

      g_Requests++;

      if (FAILED(result) || outBuffer == nullptr || *outBuffer == nullptr || !Routing())
        return result;

      const char* why = nullptr;
      if (!RouteGeometry(*outBuffer, length, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, &why))
        ReportRefusal();

      return result;
    }

    HRESULT WINAPI UpdateTexture_Router(IDirect3DDevice9* device, IDirect3DBaseTexture9* source,
                                        IDirect3DBaseTexture9* destination)
    {
      const auto result = reinterpret_cast<UpdateTextureFn>(g_Original[SLOT_UPDATE_TEXTURE])(device, source, destination);

      g_Requests++;

      if (FAILED(result) || source == nullptr || destination == nullptr || !Routing())
        return result;

      const char* why = nullptr;
      if (!RoutePixels(source, destination, &why))
        ReportRefusal();

      return result;
    }

    // Free every resource the layer made, through the device that made them.
    void FreeResources()
    {
      if (g_Device != nullptr)
      {
        for (auto& record : g_Resources)
        {
          if (record.isTexture)
            VulkanResources::DestroyImage(*g_Device, record.image);
          else
            VulkanResources::DestroyBuffer(*g_Device, record.buffer);
        }
      }

      g_Resources.clear();
    }
  } // namespace

  // ------------------------------------------------------------------------ the layer

  bool Attach(const VulkanDevice::Device& device, const char** error)
  {
    const auto say = [error](const char* reason)
    {
      if (error != nullptr)
        *error = keep(reason);
    };

    if (!VulkanResources::Bound())
    {
      refuse("the Vulkan resource layer is not initialized on this device");
      say(g_Refusal);
      return false;
    }

    g_Device = &device;

    // The engine makes a new device on a vid_restart and on a device recovery, and a new device comes
    // with its own vtable pointer - which takes the calls out of our hands without telling us. The
    // renderer pipeline is where those restarts end and where the engine's own resource calls run, so
    // the check runs there: one read of one word per frame, and an install only when that word stopped
    // being ours.
    if (!g_Refreshing)
    {
      g_Refreshing = true;
      Components::Scheduler::Loop(Refresh, Components::Scheduler::Pipeline::RENDERER);
    }

    // Nothing to install while r_backend says d3d9 - and nothing is installed, which is the point of
    // the default: the game's device object keeps its own vtable and no Vulkan call of ours is in
    // reach of an upload.
    if (Components::IW4x32::RendererBackend() != Components::IW4x32::RENDERER_BACKEND_VULKAN)
      return true;

    char reason[256] = "";
    if (!Install(reason, sizeof(reason)))
    {
      refuse(reason);
      say(reason);
      return false;
    }

    if (error != nullptr)
      *error = nullptr;
    return true;
  }

  void Detach()
  {
    Uninstall();
    FreeResources();
    g_Device = nullptr;
  }

  bool Bound()
  {
    return g_Device != nullptr;
  }

  bool Installed()
  {
    return g_Object != nullptr;
  }

  // A vid_restart, a device recovery, or a player typing r_backend: whatever changed the engine's
  // device object or the backend the run wants, this puts the boundary where it belongs - or takes it
  // off. Called once per attached device at install, and by the renderer's own restart signals.
  void Refresh()
  {
    const auto wanted = g_Device != nullptr &&
                        Components::IW4x32::RendererBackend() == Components::IW4x32::RENDERER_BACKEND_VULKAN;

    if (!wanted)
    {
      Uninstall();
      return;
    }

    // The object's vtable pointer is not ours any more: the engine replaced the device (or the device
    // wrapper was rebuilt), so the calls go to the driver again. Forget the old install - the resources
    // made for a device that no longer exists are dropped, not destroyed.
    if (!InFront())
    {
      if (g_Object != nullptr)
      {
        Uninstall();
        ForgetAll();
      }

      char reason[256] = "";
      if (!Install(reason, sizeof(reason)))
      {
        refuse(reason);
        ReportRefusal();
      }
    }
  }

  void ForgetAll()
  {
    // The device is gone underneath the layer, so its images and buffers went with it: the records drop
    // their handles and stop being counted, and what is left in them is never destroyed.
    for (auto& record : g_Resources)
    {
      record.image.handle = VK_NULL_HANDLE;
      record.image.memory = VK_NULL_HANDLE;
      record.buffer.handle = VK_NULL_HANDLE;
      record.buffer.memory = VK_NULL_HANDLE;
    }

    g_Resources.clear();
  }

  bool Routing()
  {
    return g_Device != nullptr && g_Object != nullptr &&
           Components::IW4x32::RendererBackend() == Components::IW4x32::RENDERER_BACKEND_VULKAN;
  }

  // The public form of the same four answers, for a caller that reached the request some other way
  // (the native loader's own interception, or a check). Counted like a vtable request.
  bool UploadTexture(void* texture, const unsigned int width, const unsigned int height,
                     const unsigned int mipLevels, const unsigned int d3dFormat, const char** error)
  {
    g_Requests++;
    if (!RouteTexture(texture, width, height, mipLevels, d3dFormat, error))
      return false;

    g_TexturesRouted++;
    return true;
  }

  bool UploadPixels(void* sourceBaseTexture, void* destinationTexture, const char** error)
  {
    g_Requests++;
    return RoutePixels(sourceBaseTexture, destinationTexture, error);
  }

  bool UploadVertexBuffer(void* vertexBuffer, const unsigned int length, const char** error)
  {
    g_Requests++;
    return RouteGeometry(vertexBuffer, length, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT, error);
  }

  bool UploadIndexBuffer(void* indexBuffer, const unsigned int length, const unsigned int d3dFormat,
                         const char** error)
  {
    g_Requests++;
    (void)d3dFormat; // the format is the INDEX type (16 or 32 bit); it belongs to the draws, not to the buffer's size
    return RouteGeometry(indexBuffer, length, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, error);
  }

  bool SelfTest(const char** error)
  {
    const auto say = [error](const char* reason)
    {
      if (error != nullptr)
        *error = keep(reason);
    };

    // Half one: the default. r_backend d3d9 has to leave the game's device object exactly as it was -
    // a router that is always on would prove nothing about the switch and would sit in front of the
    // path every player uses.
    if (Components::IW4x32::RendererBackend() == Components::IW4x32::RENDERER_BACKEND_D3D9)
    {
      if (Routing())
      {
        say("the router routes with r_backend=d3d9: the default path is not left alone");
        return false;
      }

      if (Installed())
      {
        say("the router is installed on the engine's device object with r_backend=d3d9");
        return false;
      }

      say("r_backend is d3d9, so nothing is installed and nothing to probe: the negative half passed");
      return true;
    }

    // Half two: the switch actually reaches the engine's upload path. The probe is an image of the
    // game's own kind - the same Image_Setup every .iwi texture goes through, the same CreateTexture
    // the boundary file counted - so what it measures is the real call chain, not this file calling
    // itself.
    if (g_Device == nullptr)
    {
      say("r_backend is vulkan but no Vulkan device is attached to this process: the router has nothing to "
          "install onto, so none of the game's uploads can reach it (getting the device into this process "
          "is the loader half of this epic)");
      return false;
    }

    const auto before = g_Requests;

    Game::GfxImage probe{};
    Game::Image_Setup(&probe, 2U, 2U, 1U, 0x1000003, D3DFMT_A8R8G8B8);

    if (g_Requests == before)
    {
      say(Utils::String::VA("the probe's CreateTexture never reached this layer: r_backend is vulkan, the "
                            "router is %s on the engine's device slot %p, and the engine made 0 requests "
                            "in the probe",
                            Installed() ? "installed" : "NOT installed", static_cast<const void*>(Game::dx_ptr)));
      return false;
    }

    if (!Routing())
    {
      say("the probe was seen while the router was not routing");
      return false;
    }

    Game::Image_Release(&probe);

    say(Utils::String::VA("the probe's CreateTexture was seen (%u request(s) in the probe, %u routed, %u image(s) made)",
                          g_Requests - before, g_TexturesRouted, g_TexturesMade));
    return true;
  }

  std::uint32_t RequestsTotal()
  {
    return g_Requests;
  }

  std::uint32_t TexturesRouted()
  {
    return g_TexturesRouted;
  }

  std::uint32_t TexturesMade()
  {
    return g_TexturesMade;
  }

  std::uint32_t PixelUploads()
  {
    return g_PixelUploads;
  }

  std::uint32_t GeometryBuffersMade()
  {
    return g_GeometryMade;
  }

  std::uint32_t Refusals()
  {
    return g_Refusals;
  }

  std::uint64_t ResourceBytes()
  {
    return g_Bytes;
  }

  const char* LastRefusal()
  {
    return g_Refusal;
  }

  std::uint32_t LiveResources()
  {
    return static_cast<std::uint32_t>(g_Resources.size());
  }
}
