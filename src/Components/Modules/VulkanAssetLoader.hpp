// IW4x-32: the asset upload path of the native renderer - the game's textures and vertex / index
// buffers routed into Vulkan images and buffers instead of D3D9 surfaces.
//
// PRIVATE - not for publication.
//
// Phase 3 of the renderer epic converts what the engine owns into what Vulkan draws. The shader half
// (VulkanShaderCompiler.cpp) turns a program's bytecode into SPIR-V; this half turns the engine's
// resource requests into VkImages and VkBuffers. iw4x32/reference/vulkan_boundary.json names the
// requests: the engine asks for a texture with IDirect3DDevice9::CreateTexture (slot 23 - the call
// sites are 0x0051F0E9 and 0x0051F1C9, and the file's note says that is "every .iwi image and several
// render targets"), for geometry with CreateVertexBuffer (slot 26, five sites) and CreateIndexBuffer
// (slot 27, two sites), and it moves pixels from a system-memory texture into the one it samples with
// UpdateTexture (slot 31, one site, "the sysmem -> video upload used after a lost device"). Those four
// are this layer's upload path, and the same file's vk_equiv column is exactly what is called here:
// vkCreateImage + vkAllocateMemory, vkCreateBuffer + vkAllocateMemory, vkCmdCopyBufferToImage,
// vkCmdCopyBuffer - always through VulkanResources.cpp, never straight at the loader.
//
// How they are reached: the engine makes all four as vtable calls through the device-shaped object it
// keeps (the boundary file proves the object global 0x066DEF88 for every one of them, and the bytes at
// a site read mov eax, [0x66DEF88] / mov edx, [eax] / mov edx, [edx + slot*4] / push args / call edx),
// so the boundary is that object's vtable. This layer copies the table, puts its own entries on the
// four slots, and points the object at the copy - data, not the engine's code. Every entry calls the
// ORIGINAL first, so the D3D9 upload happens exactly as it did before and the Vulkan resource is made
// next to it. Taking the pointer back off uninstalls it, and an uninstall is what a vid_restart or a
// Detach runs.
//
// When it is active: only when r_backend (Components::IW4x32::RendererBackend) says "vulkan" AND a
// Vulkan device was attached. r_backend defaults to d3d9, and on that default the layer installs
// nothing at all: no copy, no pointer swap, no Vulkan call, and the game runs on the D3D9 path with
// every byte of it untouched. SelfTest() below checks both halves - that the router really is off by
// default, and that with vulkan selected it answers a real engine texture creation - because a probe
// that always reads "routed" would prove nothing.
//
// What this is NOT, and the part a reader must not over-read:
//   - Not a drawn frame. An image and a buffer holding the game's pixels and vertices are assets in
//     device memory; the pipeline, descriptors, depth and draws are the next phase.
//   - Not a byte-for-byte asset conversion yet. CreateTexture hands this layer a size and a format and
//     no pixels - the engine fills the object later, through LockRect on the TEXTURE's own vtable,
//     which this layer does not touch (see the note in the .cpp). UpdateTexture is the case where the
//     bytes do come to the device, and those are copied into the image. A vertex or index buffer is
//     sized here and filled the same way - the engine "Lock()s the result to fill it", which is the
//     next step of this phase.
//   - No decode: a format VulkanResources' texel table does not name (a BC/DXT one) is refused by name
//     and counted, not guessed at.
#pragma once

#include "VulkanDevice.hpp"
#include "VulkanResources.hpp" // the layer these resources are made through, and its Image / Buffer

#include <cstdint>
#include <vulkan/vulkan.h>

namespace VulkanAssetLoader
{
  // One resource the layer made for the engine, keyed by the D3D9 object the engine holds - so a
  // caller that knows the game's texture or buffer can find the Vulkan one beside it.
  struct Resource
  {
    void* d3d = nullptr; // the IDirect3DTexture9 / VertexBuffer9 / IndexBuffer9 the engine holds
    VulkanResources::Image image;
    VulkanResources::Buffer buffer;
    unsigned int width = 0U;
    unsigned int height = 0U;
    unsigned int d3dFormat = 0U; // the D3DFORMAT the engine asked for, kept for the report
    std::uint64_t bytes = 0ULL;  // the size the layer allocated for it
    bool isTexture = false;
    bool uploaded = false; // pixels actually reached `image` (an UpdateTexture that found the record)
  };

  // Attach to the device the native path made (see Components::IW4x32::AttachVulkanDevice). Attach
  // installs the vtable boundary on the engine's device object and refuses, with a reason, when that
  // object does not look like an IDirect3DDevice9 at all. Detach puts the object's original vtable
  // pointer back and frees what the layer made. Bound() is "a device is attached"; Installed() is
  // "the boundary is on the engine's object right now" - r_backend decides which of the two means
  // anything, Routing() answers that.
  bool Attach(const VulkanDevice::Device& device, const char** error);
  void Detach();
  bool Bound();
  bool Installed();
  void Refresh(); // re-check the cvar and the object's vtable pointer after a vid_restart / a set

  // The engine's device object died underneath the layer (vid_restart, a lost device): the resources
  // went with it, so the records drop their handles instead of handing dead ones to a destroy.
  void ForgetAll();

  // Whether an upload belongs to this layer right now: r_backend=vulkan AND Bound() AND Installed().
  // Everything else belongs to D3D9, which is the default and the untouched path.
  bool Routing();

  // The four engine calls, as the router answers them. The D3D9 object named in each is the one the
  // original call already returned: this layer never creates it and never frees it. void* because this
  // header is pulled in by the engine component and must not pull in d3d9.h.
  bool UploadTexture(void* texture, unsigned int width, unsigned int height, unsigned int mipLevels,
                     unsigned int d3dFormat, const char** error);
  bool UploadPixels(void* sourceBaseTexture, void* destinationTexture, const char** error);
  bool UploadVertexBuffer(void* vertexBuffer, unsigned int length, const char** error);
  bool UploadIndexBuffer(void* indexBuffer, unsigned int length, unsigned int d3dFormat, const char** error);

  // A check that this layer can see a bad case, run by a live test (and printing what it measured).
  // It asks for an engine texture of its own - the same CreateTexture the game's images go through -
  // and fails with a reason unless the request was counted while routing was on. The other half of
  // the proof is the default: with r_backend=d3d9 Routing() must be false, and the test says so when
  // it is not. false with a reason means the router is not wired, which is what this exists to catch.
  bool SelfTest(const char** error);

  // The numbers, for iw4x32_vkas. Both halves are counted so a run can tell "the Vulkan path got the
  // assets" from "the Vulkan path was never asked": requests is everything the engine asked the
  // renderer for (whichever backend owns it), made / uploaded is what reached a VkImage or VkBuffer.
  // A vulkan-selected run that routed 0 of 300 requests has an unwired router, and that is visible.
  std::uint32_t RequestsTotal();       // engine calls this layer saw (both backends)
  std::uint32_t TexturesRouted();      // CreateTexture calls the Vulkan path owned
  std::uint32_t TexturesMade();        // vkCreateImage through VulkanResources
  std::uint32_t PixelUploads();        // UpdateTexture bytes that reached a VkImage
  std::uint32_t GeometryBuffersMade(); // vkCreateBuffer for a vertex or index buffer
  std::uint32_t Refusals();            // a request the layer could not honour, with LastRefusal()
  std::uint64_t ResourceBytes();       // what the layer allocated for the game's assets
  const char* LastRefusal();           // one-line reason of the last refusal, "" when none yet
  std::uint32_t LiveResources();       // records still held (a teardown that ends non-zero kept one)
}
