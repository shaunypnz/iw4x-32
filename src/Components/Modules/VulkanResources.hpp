// IW4x-32: the Vulkan resources the native renderer draws with - images, buffers, and the staging
// upload that gets pixels and vertices into them.
//
// PRIVATE - not for publication.
//
// Phase 3 of the renderer epic converts the game's assets into Vulkan objects: a material needs an
// image, a mesh needs a buffer, and an asset read off disk reaches the card through a host-visible
// staging buffer. This file is the layer those conversions call instead of vkCreateImage /
// vkCreateBuffer / vkAllocateMemory, so that one place owns:
//
//   memory types   vkGetPhysicalDeviceMemoryProperties + vkGetImageMemoryRequirements /
//                  vkGetBufferMemoryRequirements: "device-local" and "host-visible" are indices into
//                  THIS device's memory heap list, and a bit combination the device does not offer is
//                  refused here with a reason, not in vkAllocateMemory's VK_ERROR_UNKNOWN.
//   lifecycle      every Image / Buffer carries its memory and what the layer believes its layout is;
//                  the destroy functions take the struct, not a bare handle, so a half-built resource
//                  is freed as safely as a finished one (a vid_restart and a failed asset load both do).
//   tracking       everything created through this layer is remembered. Shutdown() frees it and says
//                  what was outstanding, so a leak shows up as a number in the log instead of as a
//                  card that runs out of memory an hour into a match.
//
// As in VulkanDevice.cpp and VulkanSurface.cpp, no Vulkan loader is linked here: every entry point is
// looked up through the vkGetInstanceProcAddr the device carries, and a command the loader does not
// export is a failure with a reason, never a call through null.
//
// What this is NOT: a renderer, and not an allocator. There is one vkAllocateMemory per resource and
// no sub-allocation, no linear/VMA block, no dedicated allocation, no bindless, no descriptor set,
// no pipeline and no draw. A frame of the game is not assembled here - this is the plumbing the
// shader/asset work builds on.
#pragma once

#include "VulkanDevice.hpp"

#include <cstdint>
#include <vulkan/vulkan.h>

namespace VulkanResources
{
  // A buffer this layer made. `memory` is ours (vkAllocateMemory) and is destroyed with the buffer;
  // a buffer handed in from outside this layer never enters a struct like this one.
  struct Buffer
  {
    VkBuffer handle = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkDeviceSize size = 0U;
    VkBufferUsageFlags usage = 0U;
    VkMemoryPropertyFlags memoryProperties = 0U; // what was asked for, and what the type delivered
    std::uint32_t memoryType = 0U;               // index into the physical device's memoryTypes
  };

  // An image this layer made. `layout` is what this layer last left the image in - a layer-wide
  // assumption, not a fact read from the driver: a caller that transitions an image behind this
  // layer's back has to say so with SetImageLayout.
  struct Image
  {
    VkImage handle = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkDeviceSize size = 0U;
    VkExtent3D extent = {0U, 0U, 1U};
    VkFormat format = VK_FORMAT_UNDEFINED;
    VkImageType type = VK_IMAGE_TYPE_2D;
    VkImageTiling tiling = VK_IMAGE_TILING_OPTIMAL;
    VkImageUsageFlags usage = 0U;
    VkImageAspectFlags aspect = 0U; // the copy/view aspect: colour, depth, or depth+stencil
    VkImageLayout layout = VK_IMAGE_LAYOUT_UNDEFINED;
    std::uint32_t mipLevels = 1U;
    std::uint32_t arrayLayers = 1U;
    std::uint32_t memoryType = 0U;
  };

  // The layer's own state, for the component that owns it (see IW4x32.cpp): Init proves the loader the
  // device came from exports the resource commands, and reports whether this device has any
  // device-local memory at all - a renderer that then asks for device-local textures on an iGPU has
  // to be told now, not watch vkAllocateMemory fail on the hundredth material. Bind lets the layer
  // notice that a different device (a vid_restart) appeared; ForgetAll drops every record when the
  // device dies underneath it, since the driver already took the handles with it.
  //
  // The device is borrowed, exactly as everywhere else in this epic: the caller owns it, and must call
  // Shutdown() - or ForgetAll() when the device is already destroyed - before that Device object goes
  // away, because the layer keeps a pointer to it and frees its records through it.
  bool Init(const VulkanDevice::Device& device, const char** error);
  bool Init(const VulkanDevice::Device& device);
  void Shutdown();
  bool Bound();
  void Bind(const VulkanDevice::Device& device);
  void ForgetAll();

  // True when this device can give out VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT memory at all.
  bool HasDeviceLocalMemory();

  // What this layer still holds: how many images and buffers it made and never destroyed, and how
  // many bytes of memory it allocated. A teardown that reports a non-zero count found a leak.
  std::uint32_t LiveImages();
  std::uint32_t LiveBuffers();
  std::uint64_t AllocatedBytes();

  // The memory type index for a set of property bits, the way the spec says to find it:
  // vkGetImageMemoryRequirements / vkGetBufferMemoryRequirements gives the allowed TYPE BITS, and the
  // first memory type whose index is in those bits and whose properties contain every bit of
  // `properties` wins. There is no such index as "device local" on a device that has no such heap, so
  // a failure here comes back with a reason naming what was asked for, and `outType` untouched.
  bool FindMemoryType(const VulkanDevice::Device& device, std::uint32_t allowedTypeBits,
                      VkMemoryPropertyFlags properties, std::uint32_t& outType, const char** error);

  // vkCreateImage, then vkAllocateMemory for exactly what that image needs
  // (vkGetImageMemoryRequirements), then vkBindImageMemory. The image is created in
  // VK_IMAGE_LAYOUT_UNDEFINED - the only layout a brand new image may start in - and `out.layout`
  // says so. `memoryProperties` is what the image's memory must offer (device-local for a texture,
  // host-visible for a staging image).
  // On success returns true and fills `out`, and the image is tracked for Shutdown. On failure
  // returns false, has destroyed anything it made, leaves `out` empty, and puts a one-line reason in
  // `error` (owned by this file, good until the next call here).
  bool CreateImage(const VulkanDevice::Device& device, const VkImageCreateInfo& info,
                   VkMemoryPropertyFlags memoryProperties, Image& out, const char** error);

  // Convenience for the one shape the renderer makes most: a 2D image of that size and format,
  // VK_IMAGE_TILING_OPTIMAL, one sample, VK_SHARING_MODE_EXCLUSIVE, VK_IMAGE_LAYOUT_UNDEFINED to start,
  // memory asked for DEVICE_LOCAL, and `mipLevels` of 0 meaning one. Nothing about `usage` is widened -
  // an image that cannot be a copy destination stays that way, and UploadBufferToImage refuses it.
  // `aspect` of 0 takes what the format implies (colour, depth, stencil, or depth+stencil).
  bool CreateImage2D(const VulkanDevice::Device& device, std::uint32_t width, std::uint32_t height, VkFormat format,
                     VkImageUsageFlags usage, VkImageAspectFlags aspect, std::uint32_t mipLevels, Image& out,
                     const char** error);

  // vkCreateBuffer, vkAllocateMemory (vkGetBufferMemoryRequirements), vkBindBufferMemory. `usage` is
  // used exactly as given; a size of 0 is refused before it reaches the driver, which would answer
  // VK_ERROR_VALIDATION_FAILED_EXT at best and an oversized allocation at worst.
  bool CreateBuffer(const VulkanDevice::Device& device, VkDeviceSize size, VkBufferUsageFlags usage,
                    VkMemoryPropertyFlags memoryProperties, Buffer& out, const char** error);

  // A buffer in memory the CPU may write: VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, plus HOST_COHERENT when
  // this device offers it (without that bit a mapped write has to be flushed with
  // vkFlushMappedMemoryRanges before the queue reads it). `out.data` is the mapped pointer, held for
  // the buffer's whole life - mapped once here, unmapped by DestroyStagingBuffer - because the asset
  // converters fill a vertex or texture upload in place instead of copying twice. A device that offers
  // no host-visible memory at all is a failure with a reason.
  struct StagingBuffer
  {
    Buffer buffer;
    void* data = nullptr; // the mapping, valid until DestroyStagingBuffer
  };

  bool CreateStagingBuffer(const VulkanDevice::Device& device, VkDeviceSize size, StagingBuffer& out,
                           const char** error);

  // The upload, end to end: a host-visible staging buffer holding `size` bytes of `data`,
  // vkCmdCopyBuffer from it into `destination` (which this call does NOT create - its usage has to
  // carry VK_BUFFER_USAGE_TRANSFER_DST_BIT, and that is checked here rather than handed to the
  // driver), the copy submitted on the device's queue and waited for, then the staging buffer
  // destroyed. The command buffer is a transient one from a command pool this call makes and frees:
  // an asset loader uploads one image at a time, and a pool per upload is the difference between a
  // loader that works on a box with 512 MB and one that does not.
  //
  // `destination` must already exist; it is left exactly as it was found except for its contents. A
  // null `data` or a size of 0 is a failure, not a no-op: a zero-size vkCmdCopyBuffer is a validation
  // error, and an asset that converted to zero bytes is a bug the caller must see.
  bool UploadStagingBuffer(const VulkanDevice::Device& device, const void* data, VkDeviceSize size, Buffer& destination,
                           const char** error);

  // The same staging cycle into an image: the bytes go into a staging buffer, then
  // vkCmdCopyBufferToImage with one VkBufferImageCopy per mip level of `image` - the extents halved by
  // the spec's rule (ceil(/2), floor at 1), tightly packed (bufferRowLength / bufferImageHeight of 0),
  // all array layers of that level in one region, with a running offset. A region that would run past
  // the end of the upload is not recorded: the copy stops at the last mip that fits and says how far it
  // got, because a copy past a staging buffer reads memory the upload never had.
  //
  // The image is transitioned to VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL with vkCmdPipelineBarrier in the
  // same command buffer that holds the copy, copied into, and left in `finalLayout` - the layout the
  // renderer needs it in (VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL for a sampled texture,
  // VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL for a render target); `image.layout` follows that barrier,
  // because this layer is what tracks layouts. A finalLayout of UNDEFINED or TRANSFER_DST_OPTIMAL is a
  // refusal: an uploaded image has to end somewhere the next pass can read.
  //
  // The image must already exist and must carry VK_IMAGE_USAGE_TRANSFER_DST_BIT. The byte count of a
  // mip chain is computed from this file's texel-size table (the BGRA/8/16/32-bit and depth formats
  // this renderer converts to today); a format that table does not name - a block-compressed one, a
  // packed 10-bit one - uploads the bytes given as mip 0 and refuses to guess a mip chain, which is
  // what a BC/DXT conversion in a later task has to answer for itself.
  bool UploadBufferToImage(const VulkanDevice::Device& device, const void* data, VkDeviceSize size, Image& image,
                           VkImageLayout finalLayout, const char** error);

  // vkCmdCopyImage between two images, each transitioned into the layout the copy requires with
  // vkCmdPipelineBarrier in the command buffer that holds the copy, submitted on the device's queue and
  // waited for. `aspect` of 0 takes the source's aspect; both images must carry the transfer usage bit
  // the copy reads or writes through. The copy is the whole of mip 0 and the smaller of the two
  // extents - a resample is a vkCmdBlitImage job for the formats that allow filtering, not something
  // this fakes. The images come in by const reference, so what this call left them in is printed and
  // NOT recorded on the structs: transition them (TransitionImageLayout) before the next pass uses one.
  bool CopyImage(const VulkanDevice::Device& device, const Image& source, const Image& destination,
                 VkImageAspectFlags aspect, const char** error);

  // vkCmdPipelineBarrier for one image: undefined/optimal -> what a step needs, optimal -> present,
  // and everything between. `sourceLayout` is the layout the layer believes the image is in; the
  // result is stored in `image.layout`. A barrier is not optional around a swapchain image a check
  // reads back, and it is not free, so it stays a call of its own rather than something CreateImage
  // sneaks in.
  bool TransitionImageLayout(const VulkanDevice::Device& device, Image& image, VkImageLayout sourceLayout,
                             VkImageLayout destinationLayout, const char** error);

  // Teardown for one resource: vkDestroyBuffer / vkDestroyImage, then vkFreeMemory (and vkUnmapMemory
  // first for a staging buffer). Safe on a half-built struct (a refusal inside CreateImage / CreateBuffer
  // runs this path), safe on an empty one, safe to call twice; the struct comes back empty either way,
  // and the layer stops counting it.
  void DestroyBuffer(const VulkanDevice::Device& device, Buffer& buffer);
  void DestroyStagingBuffer(const VulkanDevice::Device& device, StagingBuffer& staging);
  void DestroyImage(const VulkanDevice::Device& device, Image& image);
}
