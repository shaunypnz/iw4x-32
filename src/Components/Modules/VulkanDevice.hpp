// IW4x-32: the Vulkan device, swapchain and present of the native renderer.
//
// PRIVATE - not for publication.
//
// The second step of the direct Vulkan path, after src/Utils/SDL2/VulkanSurface.hpp: choose the
// physical device that can present to that surface, make the logical device and the queue it draws
// on, make the swapchain the frames go into, and hand one frame to the screen. It owns no window and
// makes no instance - a VulkanDevice always belongs to a VulkanSurface that already exists.
//
// No Vulkan loader is linked here, exactly as in VulkanSurface.cpp: every entry point comes from the
// vkGetInstanceProcAddr the caller hands in, so a build with no Vulkan development files still
// compiles and links, and the run decides which loader answers. That pointer is kept in the struct
// because it belongs to the loader that made the instance: the caller must keep that library open
// until after DestroyVulkanDevice (SDL_Vulkan_UnloadLibrary after teardown, never before).
//
// What this is NOT: a renderer. There is no pipeline, no shader, no descriptor, no depth buffer, no
// material and no geometry here - a swapchain is a queue of images, not a frame of the game. The
// translated path keeps drawing until something else draws it.
#pragma once

#include <vulkan/vulkan.h>

#include <cstdint>
#include <vector>

namespace Utils::SDL2
{
  struct VulkanSurface; // the instance and the surface a device is picked for (VulkanSurface.hpp)
}

namespace VulkanDevice
{
  // The loader's entry point lookup, the one SDL opened for the instance (SDL_Vulkan_GetVkGetInstanceProcAddr).
  using GetInstanceProcAddr = PFN_vkGetInstanceProcAddr;

  // What CreateVulkanDevice fills and DestroyVulkanDevice empties. Every handle is null until the
  // step that made it ran and null again after teardown, so a half-built device can be destroyed as
  // easily as a finished one (a vid_restart and a failed init both do). The swapchain fields say what
  // was actually agreed with the surface capabilities - a windowed swapchain's extent comes from the
  // compositor, not from the window size, so a caller that assumes its own numbers would resize into
  // the wrong extent.
  struct Device
  {
    GetInstanceProcAddr getInstanceProcAddr = nullptr; // borrowed from the caller: never freed here

    // The instance those entry points belong to (it is the surface's, not this struct's), kept only to
    // look commands up with. Never destroyed here.
    VkInstance instance = VK_NULL_HANDLE;

    VkPhysicalDevice physicalDevice = VK_NULL_HANDLE; // selected, not created: destroying it is never ours
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE; // the one graphics-capable queue family this device was made with
    std::uint32_t queueFamily = 0;

    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
    std::uint32_t acquiredImage = 0;      // the image the frame went into (presented by PresentFrame)
    std::vector<VkImage> swapchainImages; // owned by the swapchain: destroyed with it, never separately

    VkFormat format = VK_FORMAT_UNDEFINED;             // the surface format the swapchain was made for
    VkColorSpaceKHR colorSpace = VK_COLOR_SPACE_MAX_ENUM_KHR;
    VkPresentModeKHR presentMode = VK_PRESENT_MODE_MAX_ENUM_KHR; // what the swapchain really runs on
    VkExtent2D extent = {0U, 0U};
    std::uint32_t imageCount = 0U;
    VkSurfaceTransformFlagBitsKHR preTransform = static_cast<VkSurfaceTransformFlagBitsKHR>(0U);
  };

  // The device. vkEnumeratePhysicalDevices on the surface's instance, the first device that offers a
  // queue family with VK_QUEUE_GRAPHICS_BIT AND can present to `surface` (vkGetPhysicalDeviceSurfaceSupportKHR)
  // is selected - the first one that can present, never merely the first one enumerated - and
  // vkCreateDevice is called for it with exactly that family's index and VK_KHR_swapchain enabled (the
  // swapchain belongs to the device: a device made without that extension hands every swapchain call
  // afterwards a NULL driver entry point, which the loader papers over with VK_SUCCESS and a null
  // handle). A device that does not list the extension at all (vkEnumerateDeviceExtensionProperties) is
  // refused before it is created.
  // On success returns true and fills `device`; on failure returns false, leaves `device` empty, and puts
  // a one-line reason in `error` (owned by this file, valid until the next call here - copy it out if it
  // is needed later). `getInstanceProcAddr` is the loader that made that instance; a null one is a
  // failure, not a call, and the instance is taken from `surface` before anything is looked up, because
  // vkGetInstanceProcAddr returns null for these commands when it is handed a null instance.
  bool CreateVulkanDevice(Device& device, const Utils::SDL2::VulkanSurface& surface,
                          GetInstanceProcAddr getInstanceProcAddr, const char** error);

  // The swapchain for a window of that size: VK_FORMAT_B8G8R8A8_UNORM (the first of the formats
  // vkGetPhysicalDeviceSurfaceFormatsKHR offers when it offers that one, and a refusal when it does
  // not - the render pass and every material the renderer will write are written for BGRA),
  // VK_PRESENT_MODE_FIFO_KHR (the mode Vulkan guarantees exists, and the vsynced mode the box's tests
  // measure), VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR unless the compositor says otherwise,
  // VK_SHARING_MODE_EXCLUSIVE, and the image count the surface asks for (clamped into
  // minImageCount..maxImageCount; 0 means "as many as we can get").
  //
  // The swapchain is made in VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
  // VK_IMAGE_USAGE_TRANSFER_DST_BIT: a renderer draws into the image, and a check reads one back. A
  // swapchain without TRANSFER_SRC_BIT cannot be read at all, which is how a "green frame" claim could
  // only ever be assumed.
  //
  // `oldSwapchain` recreates on a resize or a vid_restart (VK_NULL_HANDLE the first time; it is not
  // destroyed here - the caller does that once the new one works). VK_SUBOPTIMAL_KHR counts as made:
  // the swapchain works but no longer matches the surface, and recreating it is the caller's job. A
  // VK_SUCCESS that came back with a null handle is a failure, not a swapchain.
  // Returns true and fills the swapchain fields; returns false with a reason in `error` and no swapchain.
  bool CreateSwapchain(Device& device, VkSurfaceKHR surface, std::uint32_t width, std::uint32_t height,
                       VkSwapchainKHR oldSwapchain, const char** error);

  // One image of this swapchain, ready to draw into: vkAcquireNextImageKHR. `semaphore` and `fence` are
  // the caller's (VK_NULL_HANDLE for neither of them is not an option the driver likes: pass at least
  // one, or the caller has no way to know the image is actually its own). VK_ERROR_OUT_OF_DATE_KHR and
  // VK_SUBOPTIMAL_KHR mean "recreate the swapchain", which the caller owns: they come back as false
  // with `error` naming the result, never as a working frame.
  bool AcquireNextImage(Device& device, VkSemaphore semaphore, VkFence fence, std::uint32_t& outImage,
                        const char** error);

  // The frame, as the engine will want it: the image to present and its format and extent, for a
  // command buffer recorded by the caller. `image` is the one AcquireNextImage gave, or the current
  // one when nothing was acquired.
  const std::vector<VkImage>& SwapchainImages(const Device& device);
  VkExtent2D SwapchainExtent(const Device& device);
  VkFormat SwapchainFormat(const Device& device);

  // vkQueuePresentKHR for the queue this device was created with, presenting `image`. A present of an
  // image this swapchain never had is refused before it reaches Vulkan: an out-of-range index is a
  // memory error on the driver's side, not a Vulkan error. VK_SUCCESS, VK_SUBOPTIMAL_KHR and
  // VK_ERROR_OUT_OF_DATE_KHR all return true with `stale` set for the last two - the caller recreates
  // the swapchain instead of blaming the renderer. Anything else returns false with the result in
  // `error` as text.
  bool PresentFrame(Device& device, std::uint32_t image, bool& stale, const char** error);
  bool PresentFrame(Device& device, std::uint32_t image, const char** error);

  // vkDeviceWaitIdle on this device's queue: a check that reads a frame back, and a teardown that
  // destroys what the queue may still be holding, both wait here first.
  bool WaitIdle(Device& device, const char** error);

  // Teardown, newest first: swapchain (and with it its images), device. The physical device and the
  // queue are not destroyed - they belong to the instance and its loader. Safe on a half-built
  // device, safe on an empty one, safe to call twice.
  void DestroyVulkanDevice(Device& device);
}
