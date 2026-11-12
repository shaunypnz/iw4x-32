// IW4x-32: the images, buffers and staging uploads of the native renderer.
//
// PRIVATE - not for publication.
//
// What every asset conversion in phase 3 needs, in one place, in the order an upload needs it:
//
//   FindMemoryType      vkGetPhysicalDeviceMemoryProperties against the requirements the driver
//                       reported (vkGetImageMemoryRequirements / vkGetBufferMemoryRequirements):
//                       "device local" and "host visible" are property bits, and the memory type that
//                       answers for them is an index this device's own heap list has to contain.
//   CreateImage         vkCreateImage -> vkGetImageMemoryRequirements -> vkAllocateMemory ->
//                       vkBindImageMemory.
//   CreateBuffer        vkCreateBuffer -> vkGetBufferMemoryRequirements -> vkAllocateMemory ->
//                       vkBindBufferMemory.
//   Upload*             a host-visible staging buffer (vkCreateBuffer with HOST_VISIBLE|HOST_COHERENT
//                       + vkMapMemory), a transient command buffer out of a transient command pool
//                       (vkCreateCommandPool / vkAllocateCommandBuffers / vkBeginCommandBuffer), the
//                       copy itself (vkCmdCopyBuffer / vkCmdCopyBufferToImage / vkCmdCopyImage, with a
//                       vkCmdPipelineBarrier when the destination has to be in a transfer layout),
//                       vkQueueSubmit + vkWaitForFences, then the staging buffer and the pool freed.
//
// No loader is linked (the rule VulkanSurface.cpp and VulkanDevice.cpp state and this file keeps):
// every entry point comes from the device's vkGetInstanceProcAddr, and one a loader does not export
// is a failure with a reason, never a call through null.
//
// Four things that are easy to get wrong here and are checked in this file instead of by the driver:
//
//   1. A destination whose usage lacks the transfer bit the copy writes through. vkCmdCopyBuffer into
//      a buffer created without VK_BUFFER_USAGE_TRANSFER_DST_BIT is undefined behaviour the loader only
//      sometimes catches; the layer refuses it naming the usage it saw, so an "uploaded" claim cannot
//      come from a copy the driver was free to ignore.
//   2. The byte math of a VkBufferImageCopy region. One tightly packed upload spread over the mips and
//      array layers of an image needs one region per mip with the halving extent the spec gives
//      (ceil(/2), floor at 1) and a running offset; a copy that runs past the end of the staging buffer
//      reads memory the driver never gave the upload, so the loop stops at the last region that fits
//      and says so.
//   3. A layout nobody set. An image uploaded to and then sampled while still in
//      VK_IMAGE_LAYOUT_UNDEFINED is garbage on every driver; the upload barriers into
//      TRANSFER_DST_OPTIMAL, copies, and barriers to the layout the caller asked for. The layout this
//      layer believes an image is in is kept on the struct so the next barrier starts from it.
//   4. A null handle wearing VK_SUCCESS. vkCreateImage / vkCreateBuffer / vkAllocateMemory answering
//      VK_SUCCESS with no handle behind it is the same trap VulkanDevice.cpp names for the swapchain,
//      and each one is treated as a failure here.
//
// Every step prints what it asked and what it got, on stdout, under its own name, and the layer keeps
// a count of what it created and released. "The resource layer works" is a claim about vkCreateImage,
// vkAllocateMemory and vkCmdCopyBufferToImage lines in that log and about a teardown that reports
// nothing outstanding - not about a picture on the screen.

#include "VulkanResources.hpp"

#include <cstdio>
#include <cstring>
#include <vector>

namespace VulkanResources
{
  namespace
  {
    void log_line(const char* what, const char* detail)
    {
      printf("iw4x32 vulkan resources: %s %s\n", what, detail);
    }

    void log_value(const char* what)
    {
      printf("iw4x32 vulkan resources: %s\n", what);
    }

    void log_result(const char* what, const VkResult result)
    {
      printf("iw4x32 vulkan resources: %s -> %d\n", what, static_cast<int>(result));
    }

    const char* result_name(const VkResult result)
    {
      switch (result)
      {
      case VK_SUCCESS: return "VK_SUCCESS";
      case VK_ERROR_OUT_OF_DEVICE_MEMORY: return "VK_ERROR_OUT_OF_DEVICE_MEMORY";
      case VK_ERROR_OUT_OF_HOST_MEMORY: return "VK_ERROR_OUT_OF_HOST_MEMORY";
      case VK_ERROR_TOO_MANY_OBJECTS: return "VK_ERROR_TOO_MANY_OBJECTS";
      case VK_ERROR_INITIALIZATION_FAILED: return "VK_ERROR_INITIALIZATION_FAILED";
      case VK_ERROR_FEATURE_NOT_PRESENT: return "VK_ERROR_FEATURE_NOT_PRESENT";
      case VK_ERROR_VALIDATION_FAILED_EXT: return "VK_ERROR_VALIDATION_FAILED_EXT";
      case VK_ERROR_DEVICE_LOST: return "VK_ERROR_DEVICE_LOST";
      default: return "a VkResult this file does not name";
      }
    }

    // The reason a caller gets back: text this file owns, so it outlives the call.
    const char* fixed_reason(const char* reason)
    {
      return reason;
    }

    char g_Reason[256]; // for a reason that has to name numbers this file only knows at call time

    // What a memory request was asked for, in the reason that refuses it: "0x00000007" alone is a
    // number the reader has to look up; the names say "device local" / "host visible" where it is said.
    void describe_properties(const VkMemoryPropertyFlags properties, char* out, std::size_t outSize)
    {
      struct NamedBit
      {
        VkMemoryPropertyFlagBits bit;
        const char* name;
      };

      const NamedBit names[] = {
          {VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, "DEVICE_LOCAL"},
          {VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, "HOST_VISIBLE"},
          {VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, "HOST_COHERENT"},
          {VK_MEMORY_PROPERTY_HOST_CACHED_BIT, "HOST_CACHED"},
          {VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT, "LAZILY_ALLOCATED"},
      };

      out[0] = '\0';
      for (const NamedBit& entry : names)
      {
        if ((properties & entry.bit) == 0U)
          continue;
        if (out[0] != '\0')
          strncat(out, "|", outSize - strlen(out) - 1);
        strncat(out, entry.name, outSize - strlen(out) - 1);
      }

      if (out[0] == '\0')
        snprintf(out, outSize, "0x%x", static_cast<unsigned>(properties));
    }

    // Entry points come from the loader that made the device's instance; a device-level command needs
    // that instance for the lookup too, which is why VulkanDevice::Device carries it.
    template <typename T>
    T entry_point(const VulkanDevice::Device& device, const char* name)
    {
      if (device.getInstanceProcAddr == nullptr)
        return nullptr;

      return reinterpret_cast<T>(device.getInstanceProcAddr(device.instance, name));
    }

    // The layer's state. Nothing here owns the device: VulkanDevice.cpp does, and a vid_restart can
    // destroy it under these records - which is what ForgetAll is for.
    struct BufferRecord
    {
      Buffer buffer;
      void* mapped = nullptr; // the mapping a staging buffer holds for the buffer's whole life
    };

    struct Layer
    {
      const VulkanDevice::Device* device = nullptr;
      VkDevice deviceHandle = VK_NULL_HANDLE; // which device the records below were made on
      bool initialized = false;
      bool deviceLocal = false;               // this device has a heap with DEVICE_LOCAL at all
      std::vector<BufferRecord> buffers;
      std::vector<Image> images;
      std::uint64_t bytes = 0ULL;             // what vkAllocateMemory gave out and has not given back
    };

    Layer g_Layer;

    // A resource is tracked only when it belongs to the device the layer is bound to: records kept
    // across a vid_restart would be freed on a device that no longer exists.
    void track(const VulkanDevice::Device& device, const Buffer& buffer, void* mapped)
    {
      if (device.device == g_Layer.deviceHandle)
        g_Layer.buffers.push_back({buffer, mapped});
    }

    void track(const VulkanDevice::Device& device, const Image& image)
    {
      if (device.device == g_Layer.deviceHandle)
        g_Layer.images.push_back(image);
    }

    // True when a record was found and removed, so a double destroy cannot drop a count twice.
    bool untrack_buffer(const VkBuffer handle)
    {
      for (std::size_t index = 0; index < g_Layer.buffers.size(); ++index)
      {
        if (g_Layer.buffers[index].buffer.handle != handle)
          continue;

        if (g_Layer.buffers[index].buffer.memory != VK_NULL_HANDLE)
          g_Layer.bytes -= g_Layer.buffers[index].buffer.size;
        g_Layer.buffers.erase(g_Layer.buffers.begin() + static_cast<std::ptrdiff_t>(index));
        return true;
      }
      return false;
    }

    bool untrack_image(const VkImage handle)
    {
      for (std::size_t index = 0; index < g_Layer.images.size(); ++index)
      {
        if (g_Layer.images[index].handle != handle)
          continue;

        if (g_Layer.images[index].memory != VK_NULL_HANDLE)
          g_Layer.bytes -= g_Layer.images[index].size;
        g_Layer.images.erase(g_Layer.images.begin() + static_cast<std::ptrdiff_t>(index));
        return true;
      }
      return false;
    }

    // vkGetPhysicalDeviceMemoryProperties for this device - the type/heap list every memory decision
    // below reads. A null `error` is allowed: this is a question, not a call that owns a result.
    bool memory_properties(const VulkanDevice::Device& device, VkPhysicalDeviceMemoryProperties& out,
                           const char** error)
    {
      const auto get = entry_point<PFN_vkGetPhysicalDeviceMemoryProperties>(device, "vkGetPhysicalDeviceMemoryProperties");
      if (get == nullptr)
      {
        log_value("no vkGetPhysicalDeviceMemoryProperties to ask where memory can live");
        if (error != nullptr)
          *error = fixed_reason("the Vulkan loader exports no vkGetPhysicalDeviceMemoryProperties");
        return false;
      }

      get(device.physicalDevice, &out);
      if (out.memoryTypeCount == 0U)
      {
        log_value("this device reports no memory types at all");
        if (error != nullptr)
          *error = fixed_reason("the device reports no memory types: nothing can be allocated on it");
        return false;
      }
      return true;
    }

    // The aspect a format implies, for a caller that named none: a depth or stencil format is a depth
    // image, everything else is colour. A copy that names the wrong aspect copies nothing on most
    // drivers and validates on others, so the default has to at least agree with the format.
    VkImageAspectFlags default_aspect(const VkFormat format)
    {
      switch (format)
      {
      case VK_FORMAT_D16_UNORM:
      case VK_FORMAT_X8_D24_UNORM_PACK32:
      case VK_FORMAT_D32_SFLOAT:
        return VK_IMAGE_ASPECT_DEPTH_BIT;
      case VK_FORMAT_D24_UNORM_S8_UINT:
      case VK_FORMAT_D32_SFLOAT_S8_UINT:
        return static_cast<VkImageAspectFlags>(VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT);
      case VK_FORMAT_S8_UINT:
        return VK_IMAGE_ASPECT_STENCIL_BIT;
      default: return VK_IMAGE_ASPECT_COLOR_BIT;
      }
    }

    bool depth_or_stencil(const VkImageAspectFlags aspect)
    {
      return (aspect & (VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT)) != 0U;
    }

    // The mip extent the spec's halving rule gives: ceil(/2) down to a floor of 1.
    std::uint32_t mip_extent(const std::uint32_t base, const std::uint32_t level)
    {
      std::uint32_t extent = base == 0U ? 1U : base;
      for (std::uint32_t step = 0U; step < level && extent > 1U; ++step)
        extent = (extent + 1U) / 2U;
      return extent;
    }

    // The texel size of the formats this renderer converts to so far: BGRA (the swapchain format the
    // device layer picked), the RGBA/8-bit and 16/32-bit formats a UI or a mask uses, and the depth
    // formats. A format this list does not name has no size this file may claim, which is what makes
    // a mip-chain estimate refuse instead of guess - and a BC/DXT block upload is a block-format job
    // for a later task, not something to fake with a texel size.
    std::uint64_t texel_bytes(const VkFormat format)
    {
      switch (format)
      {
      case VK_FORMAT_B8G8R8A8_UNORM:
      case VK_FORMAT_R8G8B8A8_UNORM:
      case VK_FORMAT_R8G8B8A8_SRGB:
      case VK_FORMAT_B8G8R8A8_SRGB:
      case VK_FORMAT_R32G32B32A32_SFLOAT:
      case VK_FORMAT_D32_SFLOAT:
        return 4ULL;
      case VK_FORMAT_R16G16_SFLOAT:
      case VK_FORMAT_R16G16_UNORM:
      case VK_FORMAT_D16_UNORM:
        return 2ULL;
      case VK_FORMAT_R8_UNORM:
      case VK_FORMAT_R8_SRGB:
      case VK_FORMAT_S8_UINT:
        return 1ULL;
      default: return 0ULL; // unknown here: the caller's byte count is the only one this file trusts
      }
    }

    // A command buffer that exists for one submission: a TRANSIENT pool, one buffer, one fence, all
    // destroyed when the submission is waited for. An asset loader uploads one texture at a time; a
    // pool kept alive per upload is the leak this layer counts.
    struct Transient
    {
      VkCommandPool pool = VK_NULL_HANDLE;
      VkCommandBuffer commands = VK_NULL_HANDLE;
      VkFence fence = VK_NULL_HANDLE;
    };

    void transient_end(const VulkanDevice::Device& device, Transient& recorded);

    bool transient_begin(const VulkanDevice::Device& device, Transient& out, const char** error)
    {
      const auto createPool = entry_point<PFN_vkCreateCommandPool>(device, "vkCreateCommandPool");
      const auto allocate = entry_point<PFN_vkAllocateCommandBuffers>(device, "vkAllocateCommandBuffers");
      const auto begin = entry_point<PFN_vkBeginCommandBuffer>(device, "vkBeginCommandBuffer");
      const auto createFence = entry_point<PFN_vkCreateFence>(device, "vkCreateFence");

      if (createPool == nullptr || allocate == nullptr || begin == nullptr || createFence == nullptr)
      {
        log_value("the loader exports no command-buffer entry points (vkCreateCommandPool / vkAllocateCommandBuffers)");
        *error = fixed_reason("the Vulkan loader this run opened exports no command buffer commands");
        return false;
      }

      const VkCommandPoolCreateInfo poolInfo = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
                                                nullptr,
                                                VK_COMMAND_POOL_CREATE_TRANSIENT_BIT,
                                                device.queueFamily};

      const VkResult pooled = createPool(device.device, &poolInfo, nullptr, &out.pool);
      log_result("vkCreateCommandPool", pooled);
      if (pooled != VK_SUCCESS || out.pool == VK_NULL_HANDLE)
      {
        out.pool = VK_NULL_HANDLE;
        *error = result_name(pooled);
        return false;
      }

      const VkCommandBufferAllocateInfo allocateInfo = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                                        nullptr,
                                                        out.pool,
                                                        VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                                        1U};

      const VkResult allocated = allocate(device.device, &allocateInfo, &out.commands);
      log_result("vkAllocateCommandBuffers", allocated);
      if (allocated != VK_SUCCESS || out.commands == VK_NULL_HANDLE)
      {
        out.commands = VK_NULL_HANDLE;
        transient_end(device, out);
        *error = result_name(allocated);
        return false;
      }

      // A fence rather than vkDeviceWaitIdle: the upload waits for its own copy, not for everything
      // else the queue happens to hold, so a loader that uploads a hundred textures stays responsive.
      const VkFenceCreateInfo fenceInfo = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, nullptr, 0U};
      const VkResult fenced = createFence(device.device, &fenceInfo, nullptr, &out.fence);
      log_result("vkCreateFence", fenced);
      if (fenced != VK_SUCCESS || out.fence == VK_NULL_HANDLE)
      {
        out.fence = VK_NULL_HANDLE;
        transient_end(device, out);
        *error = result_name(fenced);
        return false;
      }

      const VkCommandBufferBeginInfo beginInfo = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                                                  nullptr,
                                                  VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
                                                  nullptr};

      const VkResult begun = begin(out.commands, &beginInfo);
      log_result("vkBeginCommandBuffer", begun);
      if (begun != VK_SUCCESS)
      {
        transient_end(device, out);
        *error = result_name(begun);
        return false;
      }

      return true;
    }

    // The submission and the wait: the copy is finished when this returns true, which is what lets the
    // caller destroy the staging buffer straight afterwards without racing the queue.
    bool transient_submit(const VulkanDevice::Device& device, Transient& recorded, const char** error)
    {
      const auto end = entry_point<PFN_vkEndCommandBuffer>(device, "vkEndCommandBuffer");
      const auto submit = entry_point<PFN_vkQueueSubmit>(device, "vkQueueSubmit");
      const auto wait = entry_point<PFN_vkWaitForFences>(device, "vkWaitForFences");

      if (end == nullptr || submit == nullptr || wait == nullptr)
      {
        log_value("the loader exports no vkEndCommandBuffer / vkQueueSubmit / vkWaitForFences");
        *error = fixed_reason("the Vulkan loader this run opened exports no submit entry points");
        return false;
      }

      VkResult result = end(recorded.commands);
      log_result("vkEndCommandBuffer", result);
      if (result != VK_SUCCESS)
      {
        *error = result_name(result);
        return false;
      }

      // The command buffer is the payload (commandBufferCount 1, pCommandBuffers), not a semaphore
      // list: a swap of those two fields is a compile error against the header, and the fence below is
      // what says when the copy is really finished.
      const VkSubmitInfo submitInfo = {VK_STRUCTURE_TYPE_SUBMIT_INFO,
                                       nullptr,
                                       0U,
                                       nullptr,
                                       nullptr,
                                       1U,
                                       &recorded.commands,
                                       0U,
                                       nullptr};

      result = submit(device.queue, 1U, &submitInfo, recorded.fence);
      log_result("vkQueueSubmit(staging copy)", result);
      if (result != VK_SUCCESS)
      {
        *error = result_name(result);
        return false;
      }

      result = wait(device.device, 1U, &recorded.fence, VK_TRUE, ~0ULL);
      log_result("vkWaitForFences", result);
      if (result != VK_SUCCESS)
      {
        *error = result_name(result);
        return false;
      }

      return true;
    }

    void transient_end(const VulkanDevice::Device& device, Transient& recorded)
    {
      // Newest first, and everything skipped rather than guessed at when the loader does not export
      // it: a half-built transient tears down as far as it was built.
      if (recorded.fence != VK_NULL_HANDLE && device.device != VK_NULL_HANDLE)
      {
        const auto destroyFence = entry_point<PFN_vkDestroyFence>(device, "vkDestroyFence");
        if (destroyFence != nullptr)
          destroyFence(device.device, recorded.fence, nullptr);
      }
      recorded.fence = VK_NULL_HANDLE;

      // vkDestroyCommandPool frees every buffer it handed out, so freeing the buffer first would be a
      // call into a pool that is on its way out for no reason.
      if (recorded.pool != VK_NULL_HANDLE && device.device != VK_NULL_HANDLE)
      {
        const auto destroyPool = entry_point<PFN_vkDestroyCommandPool>(device, "vkDestroyCommandPool");
        if (destroyPool != nullptr)
          destroyPool(device.device, recorded.pool, nullptr);
      }
      recorded.pool = VK_NULL_HANDLE;
      recorded.commands = VK_NULL_HANDLE;
    }

    // The barrier that puts one image where a copy or a draw can reach it, recorded into `commands`.
    // This records only - it does not submit - so an upload's barriers and its copy land in one
    // command buffer and stay in one order.
    bool record_barrier(const VulkanDevice::Device& device, const VkCommandBuffer commands, const VkImage image,
                        const VkImageAspectFlags aspect, const VkImageLayout from, const VkImageLayout to,
                        const char** error)
    {
      const auto barrier = entry_point<PFN_vkCmdPipelineBarrier>(device, "vkCmdPipelineBarrier");
      if (barrier == nullptr)
      {
        log_value("no vkCmdPipelineBarrier to put an image where a copy can reach it");
        *error = fixed_reason("the Vulkan loader exports no vkCmdPipelineBarrier");
        return false;
      }

      const bool depth = depth_or_stencil(aspect);

      // srcAccessMask 0 because the only layouts this starts from are UNDEFINED (nothing happened to
      // the image yet) and TRANSFER_DST_OPTIMAL (the copy that filled it is earlier in this same
      // command buffer, so the submission orders it).
      const VkImageMemoryBarrier imageBarrier = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                                                 nullptr,
                                                 static_cast<VkAccessFlags>(0U), // no source access to wait for
                                                 static_cast<VkAccessFlags>(
                                                     depth ? VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT |
                                                                 VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT
                                                           : VK_ACCESS_SHADER_READ_BIT |
                                                                 VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT),
                                                 from,
                                                 to,
                                                 VK_QUEUE_FAMILY_IGNORED,
                                                 VK_QUEUE_FAMILY_IGNORED,
                                                 image,
                                                 {aspect, 0U, 1U, 0U, 1U}};

      // dependencyFlags, then three (count, array) pairs: no memory barriers, no buffer barriers,
      // one image barrier. Seven arguments after the two stage masks - a pair left out is a call the
      // header refuses, and a barrier that silently records nothing is a frame of garbage.
      barrier(commands,
              static_cast<VkPipelineStageFlags>(from == VK_IMAGE_LAYOUT_UNDEFINED ? VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT
                                                                                  : VK_PIPELINE_STAGE_ALL_COMMANDS_BIT),
              static_cast<VkPipelineStageFlags>(
                  depth ? VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT
                        : VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT | VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT),
              0U, 0U, nullptr, 0U, nullptr, 1U, &imageBarrier);

      printf("iw4x32 vulkan resources: barrier aspect 0x%x layout %u -> %u\n", static_cast<unsigned>(aspect),
             static_cast<unsigned>(from), static_cast<unsigned>(to));
      return true;
    }

    // A staging buffer with the bytes already in it, filled in place through the mapping the layer
    // keeps. HOST_VISIBLE|HOST_COHERENT first; a device whose visible heap is not coherent still
    // uploads, with a vkFlushMappedMemoryRanges, rather than failing over one bit.
    bool staging_filled(const VulkanDevice::Device& device, const void* data, const VkDeviceSize size,
                        StagingBuffer& out, const char** error)
    {
      char asked[128];
      describe_properties(static_cast<VkMemoryPropertyFlags>(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                                                            VK_MEMORY_PROPERTY_HOST_COHERENT_BIT),
                          asked, sizeof(asked));
      log_line("staging upload", asked);

      if (!CreateStagingBuffer(device, size, out, error))
        return false;

      std::memcpy(out.data, data, static_cast<std::size_t>(size));

      // A coherent mapping needs no flush; a non-coherent one has to be flushed before the queue reads
      // it, or the copy moves whatever the driver had left in cache instead of these bytes.
      if ((out.buffer.memoryProperties & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) == 0U)
      {
        const auto flush = entry_point<PFN_vkFlushMappedMemoryRanges>(device, "vkFlushMappedMemoryRanges");
        if (flush == nullptr)
        {
          log_value("this staging memory is not host-coherent and the loader exports no vkFlushMappedMemoryRanges");
          DestroyStagingBuffer(device, out);
          *error = fixed_reason("staging memory is not host-coherent and vkFlushMappedMemoryRanges is not available");
          return false;
        }

        const VkMappedMemoryRange range = {VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE, nullptr, out.buffer.memory, 0ULL,
                                           out.buffer.size};
        const VkResult flushed = flush(device.device, 1U, &range);
        log_result("vkFlushMappedMemoryRanges", flushed);
        if (flushed != VK_SUCCESS)
        {
          DestroyStagingBuffer(device, out);
          *error = result_name(flushed);
          return false;
        }
        log_value("staging memory is host-visible but not coherent - flushed the mapping");
      }

      return true;
    }
  } // namespace

  bool Init(const VulkanDevice::Device& device, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    if (g_Layer.initialized)
    {
      if (g_Layer.deviceHandle == device.device)
      {
        log_value("already initialized on this device");
        return true;
      }
      // A different device underneath the same layer: the records of the old one died with it.
      ForgetAll();
    }

    g_Layer.initialized = false;
    g_Layer.device = &device;
    g_Layer.deviceHandle = device.device;
    g_Layer.deviceLocal = false;

    if (device.device == VK_NULL_HANDLE || device.physicalDevice == VK_NULL_HANDLE)
    {
      log_value("no device to make resources on");
      *fail = fixed_reason("no Vulkan device yet: the resource layer has nothing to allocate on");
      return false;
    }

    // The commands this layer needs, asked for once at init so that a loader without them is reported
    // here and not at the first texture upload: a device that boots, makes a swapchain and presents,
    // and then cannot vkCreateImage, would otherwise look healthy for a whole match.
    static const char* const required[] = {
        "vkCreateImage",            "vkDestroyImage",     "vkCreateBuffer",   "vkDestroyBuffer",
        "vkAllocateMemory",         "vkFreeMemory",       "vkBindImageMemory", "vkBindBufferMemory",
        "vkGetImageMemoryRequirements", "vkGetBufferMemoryRequirements", "vkGetPhysicalDeviceMemoryProperties",
        "vkMapMemory",              "vkUnmapMemory",      "vkCmdCopyBuffer",  "vkCmdCopyBufferToImage",
        "vkCmdCopyImage",           "vkCmdPipelineBarrier", "vkCreateCommandPool", "vkDestroyCommandPool",
        "vkAllocateCommandBuffers", "vkFreeCommandBuffers", "vkBeginCommandBuffer", "vkEndCommandBuffer",
        "vkQueueSubmit",            "vkCreateFence",      "vkDestroyFence",   "vkWaitForFences",
    };

    std::uint32_t missing = 0U;
    for (const char* name : required)
    {
      if (entry_point<PFN_vkVoidFunction>(device, name) != nullptr)
        continue;
      if (missing < 4U)
        printf("iw4x32 vulkan resources: the loader exports no %s\n", name);
      ++missing;
    }

    const auto total = static_cast<std::uint32_t>(sizeof(required) / sizeof(required[0]));
    if (missing != 0U)
    {
      printf("iw4x32 vulkan resources: %u of %u resource entry points missing from this loader\n", missing, total);
      *fail = fixed_reason("the Vulkan loader this run opened exports no Vulkan resource commands");
      return false;
    }

    VkPhysicalDeviceMemoryProperties properties{};
    if (!memory_properties(device, properties, fail))
      return false;

    for (std::uint32_t index = 0U; index < properties.memoryTypeCount; ++index)
    {
      if ((properties.memoryTypes[index].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) != 0U)
      {
        g_Layer.deviceLocal = true;
        break;
      }
    }

    printf("iw4x32 vulkan resources: initialized on a device - %u memory type(s), device-local memory %s, "
           "%u/%u resource entry points\n",
           properties.memoryTypeCount, g_Layer.deviceLocal ? "present" : "ABSENT (device-local requests will be refused)",
           total - missing, total);

    g_Layer.initialized = true;
    return true;
  }

  bool Init(const VulkanDevice::Device& device)
  {
    return Init(device, nullptr);
  }

  bool Bound()
  {
    return g_Layer.initialized;
  }

  void Bind(const VulkanDevice::Device& device)
  {
    if (g_Layer.deviceHandle != device.device)
      ForgetAll();
    g_Layer.device = &device;
    g_Layer.deviceHandle = device.device;
  }

  void ForgetAll()
  {
    if (!g_Layer.images.empty() || !g_Layer.buffers.empty())
      printf("iw4x32 vulkan resources: dropping %u image(s) and %u buffer(s) of a device that is gone - the "
             "driver took them with it, nothing here can free them\n",
             static_cast<unsigned>(g_Layer.images.size()), static_cast<unsigned>(g_Layer.buffers.size()));

    g_Layer.images.clear();
    g_Layer.buffers.clear();
    g_Layer.bytes = 0ULL;
    g_Layer.device = nullptr;
    g_Layer.deviceHandle = VK_NULL_HANDLE;
    g_Layer.initialized = false;
    g_Layer.deviceLocal = false;
  }

  bool HasDeviceLocalMemory()
  {
    return g_Layer.deviceLocal;
  }

  std::uint32_t LiveImages()
  {
    return static_cast<std::uint32_t>(g_Layer.images.size());
  }

  std::uint32_t LiveBuffers()
  {
    return static_cast<std::uint32_t>(g_Layer.buffers.size());
  }

  std::uint64_t AllocatedBytes()
  {
    return g_Layer.bytes;
  }

  bool FindMemoryType(const VulkanDevice::Device& device, const std::uint32_t allowedTypeBits,
                      const VkMemoryPropertyFlags properties, std::uint32_t& outType, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    VkPhysicalDeviceMemoryProperties memory{};
    if (!memory_properties(device, memory, fail))
      return false;

    for (std::uint32_t index = 0U; index < memory.memoryTypeCount; ++index)
    {
      if ((allowedTypeBits & (1U << index)) == 0U)
        continue;
      if ((memory.memoryTypes[index].propertyFlags & properties) != properties)
        continue;

      outType = index;
      printf("iw4x32 vulkan resources: memory type %u for 0x%x (the resource allowed 0x%x, heap %u)\n", index,
             static_cast<unsigned>(properties), allowedTypeBits, memory.memoryTypes[index].heapIndex);
      return true;
    }

    char asked[128];
    describe_properties(properties, asked, sizeof(asked));
    printf("iw4x32 vulkan resources: no memory type in 0x%x offers %s - this device has %u type(s)\n", allowedTypeBits,
           asked, memory.memoryTypeCount);

    snprintf(g_Reason, sizeof(g_Reason), "this device offers no memory type %s (the resource allowed 0x%x)", asked,
             allowedTypeBits);
    *fail = fixed_reason(g_Reason);
    return false;
  }

  bool CreateImage(const VulkanDevice::Device& device, const VkImageCreateInfo& info,
                   const VkMemoryPropertyFlags memoryProperties, Image& out, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    out = Image{};

    if (device.device == VK_NULL_HANDLE || device.physicalDevice == VK_NULL_HANDLE)
    {
      log_value("no device to create an image on");
      *fail = fixed_reason("no Vulkan device: an image has nothing to be created on");
      return false;
    }

    // Refused before the driver sees them: a zero extent, no mip level or no layer is a validation
    // error on some drivers and an allocation of nothing on others, and an image with no texels is an
    // asset conversion bug either way.
    if (info.extent.width == 0U || info.extent.height == 0U || info.extent.depth == 0U || info.mipLevels == 0U ||
        info.arrayLayers == 0U || info.format == VK_FORMAT_UNDEFINED)
    {
      printf("iw4x32 vulkan resources: refusing an image %ux%ux%u format %u, %u mip(s), %u layer(s)\n",
             info.extent.width, info.extent.height, info.extent.depth, static_cast<unsigned>(info.format),
             info.mipLevels, info.arrayLayers);
      *fail = fixed_reason("the image has no pixels, no format, no mip level or no layer");
      return false;
    }

    const auto create = entry_point<PFN_vkCreateImage>(device, "vkCreateImage");
    const auto requirements = entry_point<PFN_vkGetImageMemoryRequirements>(device, "vkGetImageMemoryRequirements");
    const auto allocate = entry_point<PFN_vkAllocateMemory>(device, "vkAllocateMemory");
    const auto bind = entry_point<PFN_vkBindImageMemory>(device, "vkBindImageMemory");

    if (create == nullptr || requirements == nullptr || allocate == nullptr || bind == nullptr)
    {
      log_value("the loader exports no vkCreateImage / vkAllocateMemory / vkBindImageMemory");
      *fail = fixed_reason("the Vulkan loader this run opened exports no image commands");
      return false;
    }

    const auto destroyImage = [&device](const VkImage image)
    {
      if (image == VK_NULL_HANDLE)
        return;
      const auto destroy = entry_point<PFN_vkDestroyImage>(device, "vkDestroyImage");
      if (destroy != nullptr)
        destroy(device.device, image, nullptr);
    };

    VkResult result = create(device.device, &info, nullptr, &out.handle);
    log_result("vkCreateImage", result);
    if (result != VK_SUCCESS || out.handle == VK_NULL_HANDLE)
    {
      // A refusal that still filled the handle belongs to the image that was refused.
      destroyImage(out.handle);
      out.handle = VK_NULL_HANDLE;
      *fail = result == VK_SUCCESS ? fixed_reason("vkCreateImage said VK_SUCCESS and gave no image") : result_name(result);
      return false;
    }

    // vkGetImageMemoryRequirements is asked of the DEVICE, not of the physical device: a handle is
    // dispatchable, a physical device is not, and passing one where the other belongs is a compile
    // error against the header rather than a call into the wrong table.
    VkMemoryRequirements needed{};
    requirements(device.device, out.handle, &needed);
    printf("iw4x32 vulkan resources: image %ux%ux%u format %u needs %llu byte(s), type bits 0x%x, alignment %llu\n",
           info.extent.width, info.extent.height, info.extent.depth, static_cast<unsigned>(info.format),
           static_cast<unsigned long long>(needed.size), needed.memoryTypeBits,
           static_cast<unsigned long long>(needed.alignment));

    std::uint32_t memoryType = 0U;
    if (!FindMemoryType(device, needed.memoryTypeBits, memoryProperties, memoryType, fail))
    {
      destroyImage(out.handle);
      out.handle = VK_NULL_HANDLE;
      return false;
    }

    const VkMemoryAllocateInfo allocateInfo = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, nullptr, needed.size, memoryType};
    result = allocate(device.device, &allocateInfo, nullptr, &out.memory);
    log_result("vkAllocateMemory(image)", result);
    if (result != VK_SUCCESS || out.memory == VK_NULL_HANDLE)
    {
      destroyImage(out.handle);
      out.handle = VK_NULL_HANDLE;
      out.memory = VK_NULL_HANDLE;
      *fail = result == VK_SUCCESS ? fixed_reason("vkAllocateMemory said VK_SUCCESS and gave no memory") : result_name(result);
      return false;
    }

    result = bind(device.device, out.handle, out.memory, 0ULL);
    log_result("vkBindImageMemory", result);
    if (result != VK_SUCCESS)
    {
      const auto free = entry_point<PFN_vkFreeMemory>(device, "vkFreeMemory");
      if (free != nullptr)
        free(device.device, out.memory, nullptr);
      destroyImage(out.handle);
      out.handle = VK_NULL_HANDLE;
      out.memory = VK_NULL_HANDLE;
      *fail = result_name(result);
      return false;
    }

    out.size = needed.size;
    out.extent = info.extent;
    out.format = info.format;
    out.type = info.imageType;
    out.tiling = info.tiling;
    out.usage = info.usage;
    out.aspect = default_aspect(info.format);
    out.mipLevels = info.mipLevels;
    out.arrayLayers = info.arrayLayers;
    out.layout = info.initialLayout; // what the driver really starts the image in
    out.memoryType = memoryType;

    g_Layer.bytes += out.size;
    track(device, out);

    printf("iw4x32 vulkan resources: vkCreateImage + vkAllocateMemory + vkBindImageMemory done - %ux%ux%u "
           "format %u usage 0x%x, %llu byte(s) in memory type %u\n",
           out.extent.width, out.extent.height, out.extent.depth, static_cast<unsigned>(out.format),
           static_cast<unsigned>(out.usage), static_cast<unsigned long long>(out.size), out.memoryType);
    return true;
  }

  bool CreateImage2D(const VulkanDevice::Device& device, const std::uint32_t width, const std::uint32_t height,
                     const VkFormat format, const VkImageUsageFlags usage, VkImageAspectFlags aspect,
                     const std::uint32_t mipLevels, Image& out, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    const VkImageCreateInfo info = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
                                    nullptr,
                                    0U,
                                    VK_IMAGE_TYPE_2D,
                                    format,
                                    {width, height, 1U},
                                    1U,
                                    mipLevels == 0U ? 1U : mipLevels,
                                    VK_SAMPLE_COUNT_1_BIT,
                                    VK_IMAGE_TILING_OPTIMAL,
                                    usage,
                                    VK_SHARING_MODE_EXCLUSIVE,
                                    0U,
                                    nullptr,
                                    VK_IMAGE_LAYOUT_UNDEFINED};

    if (!CreateImage(device, info, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, out, fail))
      return false;

    // A caller that named no aspect keeps what the format implies (CreateImage set that); the copy and
    // view code that follows an image with a mismatched aspect copies or views nothing.
    if (aspect != 0U)
      out.aspect = aspect;

    return true;
  }

  bool CreateBuffer(const VulkanDevice::Device& device, const VkDeviceSize size, const VkBufferUsageFlags usage,
                    const VkMemoryPropertyFlags memoryProperties, Buffer& out, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    out = Buffer{};

    if (device.device == VK_NULL_HANDLE || device.physicalDevice == VK_NULL_HANDLE)
    {
      log_value("no device to create a buffer on");
      *fail = fixed_reason("no Vulkan device: a buffer has nothing to be created on");
      return false;
    }

    if (size == 0ULL)
    {
      log_value("refusing a buffer of 0 bytes (an asset that converted to nothing)");
      *fail = fixed_reason("the buffer is empty: nothing to allocate");
      return false;
    }

    const auto create = entry_point<PFN_vkCreateBuffer>(device, "vkCreateBuffer");
    const auto requirements = entry_point<PFN_vkGetBufferMemoryRequirements>(device, "vkGetBufferMemoryRequirements");
    const auto allocate = entry_point<PFN_vkAllocateMemory>(device, "vkAllocateMemory");
    const auto bind = entry_point<PFN_vkBindBufferMemory>(device, "vkBindBufferMemory");

    if (create == nullptr || requirements == nullptr || allocate == nullptr || bind == nullptr)
    {
      log_value("the loader exports no vkCreateBuffer / vkAllocateMemory / vkBindBufferMemory");
      *fail = fixed_reason("the Vulkan loader this run opened exports no buffer commands");
      return false;
    }

    const auto destroyBuffer = [&device](const VkBuffer buffer)
    {
      if (buffer == VK_NULL_HANDLE)
        return;
      const auto destroy = entry_point<PFN_vkDestroyBuffer>(device, "vkDestroyBuffer");
      if (destroy != nullptr)
        destroy(device.device, buffer, nullptr);
    };

    const VkBufferCreateInfo createInfo = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                           nullptr,
                                           0U,
                                           size,
                                           usage,
                                           VK_SHARING_MODE_EXCLUSIVE,
                                           0U,
                                           nullptr};

    VkResult result = create(device.device, &createInfo, nullptr, &out.handle);
    log_result("vkCreateBuffer", result);
    if (result != VK_SUCCESS || out.handle == VK_NULL_HANDLE)
    {
      destroyBuffer(out.handle);
      out.handle = VK_NULL_HANDLE;
      *fail = result == VK_SUCCESS ? fixed_reason("vkCreateBuffer said VK_SUCCESS and gave no buffer") : result_name(result);
      return false;
    }

    VkMemoryRequirements needed{};
    requirements(device.device, out.handle, &needed); // the device, as vkGetImageMemoryRequirements above

    std::uint32_t memoryType = 0U;
    if (!FindMemoryType(device, needed.memoryTypeBits, memoryProperties, memoryType, fail))
    {
      destroyBuffer(out.handle);
      out.handle = VK_NULL_HANDLE;
      return false;
    }

    const VkMemoryAllocateInfo allocateInfo = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, nullptr, needed.size, memoryType};
    result = allocate(device.device, &allocateInfo, nullptr, &out.memory);
    log_result("vkAllocateMemory(buffer)", result);
    if (result != VK_SUCCESS || out.memory == VK_NULL_HANDLE)
    {
      destroyBuffer(out.handle);
      out.handle = VK_NULL_HANDLE;
      out.memory = VK_NULL_HANDLE;
      *fail = result == VK_SUCCESS ? fixed_reason("vkAllocateMemory said VK_SUCCESS and gave no memory") : result_name(result);
      return false;
    }

    result = bind(device.device, out.handle, out.memory, 0ULL);
    log_result("vkBindBufferMemory", result);
    if (result != VK_SUCCESS)
    {
      const auto free = entry_point<PFN_vkFreeMemory>(device, "vkFreeMemory");
      if (free != nullptr)
        free(device.device, out.memory, nullptr);
      destroyBuffer(out.handle);
      out.handle = VK_NULL_HANDLE;
      out.memory = VK_NULL_HANDLE;
      *fail = result_name(result);
      return false;
    }

    out.size = size;
    out.usage = usage;
    out.memoryType = memoryType;

    // What the type delivered, not only what was asked for: a staging buffer that turned out not to be
    // host-coherent has to be flushed by whoever fills it, and that is what this field is for.
    VkPhysicalDeviceMemoryProperties properties{};
    if (memory_properties(device, properties, nullptr) && memoryType < properties.memoryTypeCount)
      out.memoryProperties = properties.memoryTypes[memoryType].propertyFlags;

    g_Layer.bytes += out.size;
    track(device, out, nullptr);

    printf("iw4x32 vulkan resources: vkCreateBuffer + vkAllocateMemory + vkBindBufferMemory done - %llu byte(s) "
           "usage 0x%x in a type with properties 0x%x (%u)\n",
           static_cast<unsigned long long>(out.size), static_cast<unsigned>(out.usage),
           static_cast<unsigned>(out.memoryProperties), out.memoryType);
    return true;
  }

  bool CreateStagingBuffer(const VulkanDevice::Device& device, const VkDeviceSize size, StagingBuffer& out,
                           const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    out = StagingBuffer{};

    if (size == 0ULL)
    {
      *fail = fixed_reason("the staging buffer is empty: nothing to allocate");
      return false;
    }

    VkMemoryPropertyFlags wanted = static_cast<VkMemoryPropertyFlags>(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                                                                     VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (!CreateBuffer(device, size, VK_BUFFER_USAGE_TRANSFER_SRC_BIT, wanted, out.buffer, fail))
    {
      printf("iw4x32 vulkan resources: no HOST_VISIBLE|HOST_COHERENT memory type here - asking HOST_VISIBLE alone\n");
      wanted = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT;
      if (!CreateBuffer(device, size, VK_BUFFER_USAGE_TRANSFER_SRC_BIT, wanted, out.buffer, fail))
        return false;
    }

    const auto map = entry_point<PFN_vkMapMemory>(device, "vkMapMemory");
    if (map == nullptr)
    {
      log_value("no vkMapMemory to write a staging buffer");
      DestroyBuffer(device, out.buffer);
      *fail = fixed_reason("the Vulkan loader exports no vkMapMemory");
      return false;
    }

    void* mapped = nullptr;
    const VkResult result = map(device.device, out.buffer.memory, 0ULL, out.buffer.size, 0U, &mapped);
    log_result("vkMapMemory(staging)", result);
    if (result != VK_SUCCESS || mapped == nullptr)
    {
      DestroyBuffer(device, out.buffer);
      *fail = result == VK_SUCCESS ? fixed_reason("vkMapMemory said VK_SUCCESS and gave no pointer") : result_name(result);
      return false;
    }

    // The mapping is held for the buffer's whole life - the converters write into it in place, and
    // DestroyStagingBuffer unmaps it. A staging buffer whose mapping is dropped and taken again per
    // row is a loader that spends its time in vkMapMemory.
    out.data = mapped;
    return true;
  }

  bool UploadStagingBuffer(const VulkanDevice::Device& device, const void* data, const VkDeviceSize size,
                           Buffer& destination, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    if (device.device == VK_NULL_HANDLE || device.queue == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no device or queue to copy through");
      return false;
    }

    if (data == nullptr || size == 0ULL)
    {
      log_value("refusing an upload of no bytes (a zero-byte asset is a conversion bug, not a no-op)");
      *fail = fixed_reason("the upload has no data or no size");
      return false;
    }

    if (destination.handle == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("the destination buffer does not exist yet: create it, then upload into it");
      return false;
    }

    // The usage bit the copy writes through. vkCmdCopyBuffer into a buffer that was created without it
    // is undefined: some drivers validate it, some write into memory they never promised to map for it.
    if ((destination.usage & VK_BUFFER_USAGE_TRANSFER_DST_BIT) == 0U)
    {
      printf("iw4x32 vulkan resources: refusing a buffer upload into usage 0x%x (no TRANSFER_DST)\n",
             static_cast<unsigned>(destination.usage));
      *fail = fixed_reason("the destination buffer was not created with VK_BUFFER_USAGE_TRANSFER_DST_BIT");
      return false;
    }

    if (size > destination.size)
    {
      printf("iw4x32 vulkan resources: refusing a %llu byte upload into a %llu byte buffer\n",
             static_cast<unsigned long long>(size), static_cast<unsigned long long>(destination.size));
      *fail = fixed_reason("the upload is larger than the destination buffer");
      return false;
    }

    const auto copy = entry_point<PFN_vkCmdCopyBuffer>(device, "vkCmdCopyBuffer");
    if (copy == nullptr)
    {
      log_value("no vkCmdCopyBuffer to copy with");
      *fail = fixed_reason("the Vulkan loader exports no vkCmdCopyBuffer");
      return false;
    }

    StagingBuffer staging;
    if (!staging_filled(device, data, size, staging, fail))
      return false;

    Transient transient;
    if (!transient_begin(device, transient, fail))
    {
      DestroyStagingBuffer(device, staging);
      return false;
    }

    const VkBufferCopy region = {0ULL, 0ULL, size};
    copy(transient.commands, staging.buffer.handle, destination.handle, 1U, &region);
    printf("iw4x32 vulkan resources: vkCmdCopyBuffer staging -> buffer, %llu byte(s)\n",
           static_cast<unsigned long long>(size));

    bool ok = transient_submit(device, transient, fail);

    transient_end(device, transient);
    DestroyStagingBuffer(device, staging); // the copy is waited for, so these bytes are dead

    if (!ok)
      return false;

    printf("iw4x32 vulkan resources: staging upload done - staging buffer made, copied from, and freed\n");
    return true;
  }

  bool UploadBufferToImage(const VulkanDevice::Device& device, const void* data, const VkDeviceSize size, Image& image,
                           const VkImageLayout finalLayout, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    if (device.device == VK_NULL_HANDLE || device.queue == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no device or queue to copy through");
      return false;
    }

    if (data == nullptr || size == 0ULL)
    {
      *fail = fixed_reason("the image upload has no data or no size");
      return false;
    }

    if (image.handle == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("the destination image does not exist yet: create it, then upload into it");
      return false;
    }

    if ((image.usage & VK_IMAGE_USAGE_TRANSFER_DST_BIT) == 0U)
    {
      printf("iw4x32 vulkan resources: refusing an image upload into usage 0x%x (no TRANSFER_DST)\n",
             static_cast<unsigned>(image.usage));
      *fail = fixed_reason("the destination image was not created with VK_IMAGE_USAGE_TRANSFER_DST_BIT");
      return false;
    }

    if (finalLayout == VK_IMAGE_LAYOUT_UNDEFINED || finalLayout == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL)
    {
      // An uploaded image left in UNDEFINED is garbage to whatever samples it; left in
      // TRANSFER_DST_OPTIMAL it is an error in the pass that samples it. Either is a bug here.
      *fail = fixed_reason("an upload has to leave the image in a layout the renderer can use");
      return false;
    }

    const auto copyToImage = entry_point<PFN_vkCmdCopyBufferToImage>(device, "vkCmdCopyBufferToImage");
    if (copyToImage == nullptr)
    {
      log_value("no vkCmdCopyBufferToImage to copy with");
      *fail = fixed_reason("the Vulkan loader exports no vkCmdCopyBufferToImage");
      return false;
    }

    // One region per mip level: the extents halved by the spec's rule, tightly packed (a
    // bufferRowLength / bufferImageHeight of 0 says exactly that), with a running offset. Every region
    // has to fit in the staging buffer - a copy that reads past it reads memory the upload never had.
    const std::uint64_t bytesPerPixel = texel_bytes(image.format);
    std::vector<VkBufferImageCopy> regions;
    std::uint64_t offset = 0ULL;

    for (std::uint32_t level = 0U; level < image.mipLevels; ++level)
    {
      const std::uint64_t width = mip_extent(image.extent.width, level);
      const std::uint64_t height = mip_extent(image.extent.height, level);
      const std::uint64_t depth = mip_extent(image.extent.depth, level);

      std::uint64_t levelBytes = 0ULL;
      if (bytesPerPixel != 0ULL)
        levelBytes = width * height * depth * bytesPerPixel * image.arrayLayers;
      else if (level == 0U)
        // A format this file has no texel size for (a block-compressed one, a packed 10-bit one): the
        // whole byte count goes to the level the caller described. A mip chain of such a format is
        // uploaded one level per call - saying so beats inventing a texel size.
        levelBytes = size;
      else
        break;

      if (offset + levelBytes > size)
      {
        printf("iw4x32 vulkan resources: mip %u of this image wants %llu byte(s) at offset %llu and the upload "
               "is %llu byte(s) - %u region(s) recorded\n",
               level, static_cast<unsigned long long>(levelBytes), static_cast<unsigned long long>(offset),
               static_cast<unsigned long long>(size), static_cast<unsigned>(regions.size()));
        break;
      }

      const VkBufferImageCopy region = {offset,
                                        0U,
                                        0U,
                                        {image.aspect, level, 0U, image.arrayLayers},
                                        {0, 0, 0},
                                        {static_cast<std::uint32_t>(width), static_cast<std::uint32_t>(height),
                                         static_cast<std::uint32_t>(depth)}};
      regions.push_back(region);
      offset += levelBytes;
    }

    if (regions.empty())
    {
      printf("iw4x32 vulkan resources: %llu byte(s) is not enough for mip 0 of a %ux%u format %u image\n",
             static_cast<unsigned long long>(size), image.extent.width, image.extent.height,
             static_cast<unsigned>(image.format));
      *fail = fixed_reason("the upload is too small for even the first mip of this image");
      return false;
    }

    StagingBuffer staging;
    if (!staging_filled(device, data, size, staging, fail))
      return false;

    Transient transient;
    if (!transient_begin(device, transient, fail))
    {
      DestroyStagingBuffer(device, staging);
      return false;
    }

    // Where the image came from -> TRANSFER_DST_OPTIMAL: a copy destination has to be in a transfer
    // layout, and the previous contents of a brand new image are whatever the driver left there.
    bool ok = record_barrier(device, transient.commands, image.handle, image.aspect, image.layout,
                             VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, fail);

    if (ok)
    {
      copyToImage(transient.commands, staging.buffer.handle, image.handle, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                  static_cast<std::uint32_t>(regions.size()), regions.data());
      printf("iw4x32 vulkan resources: vkCmdCopyBufferToImage staging -> image, %u region(s), %llu byte(s)\n",
             static_cast<unsigned>(regions.size()), static_cast<unsigned long long>(size));
    }

    // ... and out again, into the layout the renderer asked for, in the same command buffer so the
    // order barrier / copy / barrier is the submission's order.
    if (ok)
      ok = record_barrier(device, transient.commands, image.handle, image.aspect, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                          finalLayout, fail);

    if (ok)
      ok = transient_submit(device, transient, fail);

    transient_end(device, transient);
    DestroyStagingBuffer(device, staging);

    if (!ok)
    {
      // The barriers may have run before the submission failed: the layout this layer records is the
      // one the image was left in only when the whole command buffer ran.
      log_value("the upload did not submit - the image layout on the record is the one before this call");
      return false;
    }

    image.layout = finalLayout;
    printf("iw4x32 vulkan resources: image upload done, %llu byte(s) into a %ux%u image, left in layout %u\n",
           static_cast<unsigned long long>(size), image.extent.width, image.extent.height,
           static_cast<unsigned>(finalLayout));
    return true;
  }

  bool CopyImage(const VulkanDevice::Device& device, const Image& source, const Image& destination,
                 const VkImageAspectFlags aspect, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    if (device.device == VK_NULL_HANDLE || device.queue == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no device or queue to copy through");
      return false;
    }

    if (source.handle == VK_NULL_HANDLE || destination.handle == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("one of the images of this copy does not exist");
      return false;
    }

    // Both usage bits, or the copy is undefined. The layouts are this call's business too, which is
    // why the transitions below are part of it and not left to the caller.
    if ((source.usage & VK_IMAGE_USAGE_TRANSFER_SRC_BIT) == 0U ||
        (destination.usage & VK_IMAGE_USAGE_TRANSFER_DST_BIT) == 0U)
    {
      printf("iw4x32 vulkan resources: refusing an image copy of source usage 0x%x -> destination usage 0x%x\n",
             static_cast<unsigned>(source.usage), static_cast<unsigned>(destination.usage));
      *fail = fixed_reason("the source image lacks TRANSFER_SRC or the destination lacks TRANSFER_DST");
      return false;
    }

    const auto copy = entry_point<PFN_vkCmdCopyImage>(device, "vkCmdCopyImage");
    if (copy == nullptr)
    {
      log_value("no vkCmdCopyImage to copy with");
      *fail = fixed_reason("the Vulkan loader exports no vkCmdCopyImage");
      return false;
    }

    Transient transient;
    if (!transient_begin(device, transient, fail))
      return false;

    const VkImageAspectFlags chosenAspect = aspect == 0U ? source.aspect : aspect;
    const std::uint32_t width = source.extent.width < destination.extent.width ? source.extent.width
                                                                              : destination.extent.width;
    const std::uint32_t height = source.extent.height < destination.extent.height ? source.extent.height
                                                                                 : destination.extent.height;
    const std::uint32_t depth = source.extent.depth < destination.extent.depth ? source.extent.depth
                                                                              : destination.extent.depth;

    bool ok = record_barrier(device, transient.commands, source.handle, chosenAspect, source.layout,
                             VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, fail);
    if (ok)
      ok = record_barrier(device, transient.commands, destination.handle, chosenAspect, destination.layout,
                          VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, fail);

    if (ok)
    {
      // The whole of mip 0, as many layers as the source has, into the same place in the destination:
      // a copy between two differently sized images is a resample, and a resample is a vkCmdBlitImage
      // written for the formats that allow filtering - not something to fake here.
      const VkImageCopy region = {{chosenAspect, 0U, 0U, source.arrayLayers},
                                  {0, 0, 0},
                                  {chosenAspect, 0U, 0U, destination.arrayLayers},
                                  {0, 0, 0},
                                  {width, height, depth}};

      copy(transient.commands, source.handle, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, destination.handle,
           VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1U, &region);
      printf("iw4x32 vulkan resources: vkCmdCopyImage %ux%ux%u aspect 0x%x\n", width, height, depth,
             static_cast<unsigned>(chosenAspect));
    }

    if (ok)
      ok = transient_submit(device, transient, fail);

    transient_end(device, transient);

    if (!ok)
      return false;

    // The structs came in const: what this call left the images in cannot be recorded on them, so it
    // is said out loud instead of assumed. A caller that wants the layer to track the layouts takes the
    // images by value from the layer's own records (DestroyImage / TransitionImageLayout do that).
    printf("iw4x32 vulkan resources: image copy done - both images are in their transfer layouts now, and "
           "the next pass that reads or writes one has to transition it\n");
    return true;
  }

  bool TransitionImageLayout(const VulkanDevice::Device& device, Image& image, const VkImageLayout sourceLayout,
                             const VkImageLayout destinationLayout, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    if (device.device == VK_NULL_HANDLE || device.queue == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no device or queue to record a barrier on");
      return false;
    }

    if (image.handle == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no image to transition");
      return false;
    }

    Transient transient;
    if (!transient_begin(device, transient, fail))
      return false;

    const bool ok = record_barrier(device, transient.commands, image.handle, image.aspect, sourceLayout,
                                   destinationLayout, fail) &&
                    transient_submit(device, transient, fail);

    transient_end(device, transient);

    if (!ok)
      return false;

    image.layout = destinationLayout;
    return true;
  }

  void DestroyBuffer(const VulkanDevice::Device& device, Buffer& buffer)
  {
    if (buffer.handle == VK_NULL_HANDLE && buffer.memory == VK_NULL_HANDLE)
      return; // already empty: destroying twice is allowed, and it is not a second vkFreeMemory

    // Newest first, everything skipped rather than guessed at when the loader does not export it, and
    // the struct emptied either way: a half-built resource tears down as far as it was built.
    if (buffer.handle != VK_NULL_HANDLE && device.device != VK_NULL_HANDLE)
    {
      const auto destroy = entry_point<PFN_vkDestroyBuffer>(device, "vkDestroyBuffer");
      if (destroy != nullptr)
        destroy(device.device, buffer.handle, nullptr);
      else
        log_value("no vkDestroyBuffer - a buffer is being let go undestroyed");
    }

    if (buffer.memory != VK_NULL_HANDLE && device.device != VK_NULL_HANDLE)
    {
      const auto free = entry_point<PFN_vkFreeMemory>(device, "vkFreeMemory");
      if (free != nullptr)
        free(device.device, buffer.memory, nullptr);
    }

    untrack_buffer(buffer.handle);
    buffer = Buffer{};
  }

  void DestroyStagingBuffer(const VulkanDevice::Device& device, StagingBuffer& staging)
  {
    // The unmap goes first: a mapping that outlives its memory is a page the driver cannot take back.
    if (staging.data != nullptr && staging.buffer.memory != VK_NULL_HANDLE && device.device != VK_NULL_HANDLE)
    {
      const auto unmap = entry_point<PFN_vkUnmapMemory>(device, "vkUnmapMemory");
      if (unmap != nullptr)
        unmap(device.device, staging.buffer.memory);
      else
        log_value("no vkUnmapMemory - a staging mapping is being let go");
    }

    staging.data = nullptr;
    DestroyBuffer(device, staging.buffer);
  }

  void DestroyImage(const VulkanDevice::Device& device, Image& image)
  {
    if (image.handle == VK_NULL_HANDLE && image.memory == VK_NULL_HANDLE)
      return;

    if (image.handle != VK_NULL_HANDLE && device.device != VK_NULL_HANDLE)
    {
      const auto destroy = entry_point<PFN_vkDestroyImage>(device, "vkDestroyImage");
      if (destroy != nullptr)
        destroy(device.device, image.handle, nullptr);
      else
        log_value("no vkDestroyImage - an image is being let go undestroyed");
    }

    if (image.memory != VK_NULL_HANDLE && device.device != VK_NULL_HANDLE)
    {
      const auto free = entry_point<PFN_vkFreeMemory>(device, "vkFreeMemory");
      if (free != nullptr)
        free(device.device, image.memory, nullptr);
    }

    untrack_image(image.handle);
    image = Image{};
  }

  void Shutdown()
  {
    if (g_Layer.device == nullptr)
    {
      if (!g_Layer.images.empty() || !g_Layer.buffers.empty())
      {
        printf("iw4x32 vulkan resources: %u image(s) and %u buffer(s) with no device bound that could free them\n",
               static_cast<unsigned>(g_Layer.images.size()), static_cast<unsigned>(g_Layer.buffers.size()));
        ForgetAll();
      }
      g_Layer.initialized = false;
      log_value("nothing bound - nothing to shut down");
      return;
    }

    const VulkanDevice::Device& device = *g_Layer.device;
    const std::uint64_t before = g_Layer.bytes;

    // The records are moved out before anything is destroyed: DestroyBuffer / DestroyImage untrack as
    // they go, and a destroy that erased the record being iterated would skip the next one.
    std::vector<BufferRecord> outstandingBuffers;
    outstandingBuffers.swap(g_Layer.buffers);
    for (BufferRecord& record : outstandingBuffers)
    {
      // A record that carries a mapping goes through the staging path - a mapping that outlives its
      // memory is a page the driver cannot take back.
      StagingBuffer staging;
      staging.buffer = record.buffer;
      staging.data = record.mapped;
      if (staging.data != nullptr)
        DestroyStagingBuffer(device, staging);
      else
        DestroyBuffer(device, staging.buffer);
    }

    std::vector<Image> outstandingImages;
    outstandingImages.swap(g_Layer.images);
    for (Image& image : outstandingImages)
      DestroyImage(device, image);

    // Every record is gone, so the count goes with it: a teardown that reports non-zero in the line
    // above was not this call, it was the caller letting a resource die without destroying it.
    printf("iw4x32 vulkan resources: shutdown - %u buffer(s) and %u image(s) destroyed, %llu byte(s) released\n",
           static_cast<unsigned>(outstandingBuffers.size()), static_cast<unsigned>(outstandingImages.size()),
           static_cast<unsigned long long>(before));

    g_Layer.bytes = 0ULL;
    g_Layer.device = nullptr;
    g_Layer.deviceHandle = VK_NULL_HANDLE;
    g_Layer.initialized = false;
  }
}
