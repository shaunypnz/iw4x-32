// IW4x-32: the Vulkan device, the swapchain and the present - what the native renderer draws with.
//
// PRIVATE - not for publication.
//
// The three steps this file owns, in the order a renderer needs them:
//
//   CreateVulkanDevice  vkEnumeratePhysicalDevices, the first device that both offers a queue with
//                       VK_QUEUE_GRAPHICS_BIT and can present to the caller's surface
//                       (vkGetPhysicalDeviceSurfaceSupportKHR); vkEnumerateDeviceExtensionProperties
//                       to prove that device really offers VK_KHR_swapchain; then vkCreateDevice with
//                       that one family and that one extension, and vkGetDeviceQueue for its queue.
//   CreateSwapchain     vkGetPhysicalDeviceSurfaceCapabilitiesKHR + vkGetPhysicalDeviceSurfaceFormatsKHR
//                       + vkGetPhysicalDeviceSurfacePresentModesKHR, then vkCreateSwapchainKHR for
//                       VK_FORMAT_B8G8R8A8_UNORM on VK_PRESENT_MODE_FIFO_KHR, then
//                       vkGetSwapchainImagesKHR for the images behind it.
//   PresentFrame        vkAcquireNextImageKHR (AcquireNextImage) and vkQueuePresentKHR.
//
// No loader is linked (see VulkanSurface.cpp for the same rule and the reason): every entry point is
// looked up through the vkGetInstanceProcAddr of the loader that made the instance, and a command that
// a loader does not export is a failure with a reason, never a call through null.
//
// Two things this file got wrong before, in the order they cost a round each, because both read as
// "the loader exports nothing" and neither is:
//
//   1. An entry point looked up with a NULL instance. vkGetInstanceProcAddr answers for an
//      instance-level command only once it is told WHICH instance; looked up against null,
//      vkEnumeratePhysicalDevices and vkCreateDevice both come back null, and the loader is blamed.
//      device.instance therefore comes from the surface BEFORE anything is looked up.
//   2. A device made without VK_KHR_swapchain. vkCreateSwapchainKHR then still answers VK_SUCCESS from
//      the loader, with the driver's pointer NULL behind it (the loader says so on stderr: "Driver's
//      function pointer was NULL, returning VK_SUCCESS. Was the VK_KHR_swapchain extension enabled?").
//      The swapchain handle stays null and the next call into it is a segfault, not a Vulkan error.
//      So the extension is PROVEN on the device (vkEnumerateDeviceExtensionProperties) and ENABLED at
//      vkCreateDevice, and a null handle after vkCreateSwapchainKHR is a failure the caller sees.
//
// Every step prints what it asked and what it got, on stdout, under its own name. A test then tells a
// call that happened from one that was never wired up, and a device that "works" without a
// vkCreateSwapchainKHR line in the log is a device that did not produce one.

#include "VulkanDevice.hpp"

#include "Utils/SDL2/VulkanSurface.hpp"

#include <cstdio>
#include <cstring>
#include <vector>

namespace VulkanDevice
{
  namespace
  {
    void log_line(const char* what, const char* detail)
    {
      printf("iw4x32 vulkan device: %s %s\n", what, detail);
    }

    void log_value(const char* what)
    {
      printf("iw4x32 vulkan device: %s\n", what);
    }

    void log_result(const char* what, const VkResult result)
    {
      printf("iw4x32 vulkan device: %s -> %d\n", what, static_cast<int>(result));
    }

    // The VkResult as the reason a caller can print: a bare int in a log is a number the reader has to
    // look up, a name says what went wrong where it is said.
    const char* result_name(const VkResult result)
    {
      switch (result)
      {
      case VK_SUCCESS: return "VK_SUCCESS";
      case VK_NOT_READY: return "VK_NOT_READY";
      case VK_TIMEOUT: return "VK_TIMEOUT";
      case VK_ERROR_OUT_OF_DATE_KHR: return "VK_ERROR_OUT_OF_DATE_KHR";
      case VK_SUBOPTIMAL_KHR: return "VK_SUBOPTIMAL_KHR";
      case VK_ERROR_SURFACE_LOST_KHR: return "VK_ERROR_SURFACE_LOST_KHR";
      case VK_ERROR_INITIALIZATION_FAILED: return "VK_ERROR_INITIALIZATION_FAILED";
      case VK_ERROR_DEVICE_LOST: return "VK_ERROR_DEVICE_LOST";
      case VK_ERROR_OUT_OF_HOST_MEMORY: return "VK_ERROR_OUT_OF_HOST_MEMORY";
      case VK_ERROR_OUT_OF_DEVICE_MEMORY: return "VK_ERROR_OUT_OF_DEVICE_MEMORY";
      case VK_ERROR_INCOMPATIBLE_DRIVER: return "VK_ERROR_INCOMPATIBLE_DRIVER";
      case VK_ERROR_EXTENSION_NOT_PRESENT: return "VK_ERROR_EXTENSION_NOT_PRESENT";
      default: return "a VkResult this file does not name";
      }
    }

    // A message this file owns, for the caller's `error` out-parameter: it has to outlive the call, so
    // it is a literal, never a buffer built on the stack.
    const char* fixed_reason(const char* reason)
    {
      return reason;
    }

    // Every entry point comes from the loader's vkGetInstanceProcAddr. Instance-level commands answer
    // only for a real instance (see the header comment); a device-level command needs the instance for
    // the same reason, which is why the device keeps the lookup itself.
    template <typename T>
    T entry_point(const Device& device, const char* name)
    {
      if (device.getInstanceProcAddr == nullptr)
        return nullptr;

      return reinterpret_cast<T>(device.getInstanceProcAddr(device.instance, name));
    }

    // A queue family this device may be built on: it draws, and it has a queue to draw with.
    bool family_offers_graphics(const VkQueueFamilyProperties& properties)
    {
      return (properties.queueFlags & VK_QUEUE_GRAPHICS_BIT) != 0U && properties.queueCount > 0U;
    }

    // Does this physical device really offer an extension? vkCreateDevice refuses a device extension
    // the driver does not list (VK_ERROR_EXTENSION_NOT_PRESENT), and a device created without it can
    // still be handed a swapchain-shaped hole - so the question is asked before the device exists.
    bool device_offers_extension(const Device& device, const char* extension)
    {
      const auto enumerate = entry_point<PFN_vkEnumerateDeviceExtensionProperties>(device,
                                                                                 "vkEnumerateDeviceExtensionProperties");
      if (enumerate == nullptr)
      {
        log_value("no vkEnumerateDeviceExtensionProperties to ask what the device offers");
        return false;
      }

      std::uint32_t count = 0U;
      VkResult result = enumerate(device.physicalDevice, nullptr, &count, nullptr);
      if (result != VK_SUCCESS || count == 0U)
      {
        log_result("vkEnumerateDeviceExtensionProperties(count)", result);
        return false;
      }

      std::vector<VkExtensionProperties> properties(count);
      result = enumerate(device.physicalDevice, nullptr, &count, properties.data());
      if (result != VK_SUCCESS && result != VK_INCOMPLETE)
      {
        log_result("vkEnumerateDeviceExtensionProperties", result);
        return false;
      }

      bool found = false;
      for (const VkExtensionProperties& candidate : properties)
        if (std::strcmp(candidate.extensionName, extension) == 0)
          found = true;

      printf("iw4x32 vulkan device: %u device extension(s), %s %s\n", count, extension,
             found ? "offered" : "NOT offered");
      return found;
    }
  } // namespace

  bool CreateVulkanDevice(Device& device, const Utils::SDL2::VulkanSurface& surface,
                          const GetInstanceProcAddr getInstanceProcAddr, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    // Only the fields this step owns: a device that is being rebuilt keeps nothing of the old one, and
    // a device that is being filled for the first time starts empty either way.
    device.device = VK_NULL_HANDLE;
    device.queue = VK_NULL_HANDLE;
    device.physicalDevice = VK_NULL_HANDLE;
    device.queueFamily = 0U;
    device.getInstanceProcAddr = getInstanceProcAddr;

    if (getInstanceProcAddr == nullptr)
    {
      log_value("no vkGetInstanceProcAddr to take entry points from");
      *fail = fixed_reason("no vkGetInstanceProcAddr given: this build links no Vulkan loader");
      return false;
    }

    if (surface.instance == VK_NULL_HANDLE || surface.surface == VK_NULL_HANDLE)
    {
      log_value("no instance or surface to pick a device for");
      *fail = fixed_reason("the surface has no instance or no surface: make it before the device");
      return false;
    }

    // Borrowed from the surface, and set before the first lookup: every entry point below is an
    // instance-level or device-level command, and vkGetInstanceProcAddr returns null for all of those
    // when it is handed a null instance.
    device.instance = surface.instance;

    const auto vkEnumeratePhysicalDevices = entry_point<PFN_vkEnumeratePhysicalDevices>(device, "vkEnumeratePhysicalDevices");
    const auto vkGetPhysicalDeviceQueueFamilyProperties =
        entry_point<PFN_vkGetPhysicalDeviceQueueFamilyProperties>(device, "vkGetPhysicalDeviceQueueFamilyProperties");
    const auto vkGetPhysicalDeviceSurfaceSupportKHR =
        entry_point<PFN_vkGetPhysicalDeviceSurfaceSupportKHR>(device, "vkGetPhysicalDeviceSurfaceSupportKHR");
    const auto vkGetPhysicalDeviceProperties =
        entry_point<PFN_vkGetPhysicalDeviceProperties>(device, "vkGetPhysicalDeviceProperties");
    const auto vkCreateDevice = entry_point<PFN_vkCreateDevice>(device, "vkCreateDevice");
    const auto vkGetDeviceQueue = entry_point<PFN_vkGetDeviceQueue>(device, "vkGetDeviceQueue");

    if (vkEnumeratePhysicalDevices == nullptr || vkGetPhysicalDeviceQueueFamilyProperties == nullptr ||
        vkGetPhysicalDeviceSurfaceSupportKHR == nullptr || vkCreateDevice == nullptr || vkGetDeviceQueue == nullptr)
    {
      log_value("the Vulkan loader exports none of the device commands (no vkEnumeratePhysicalDevices / vkCreateDevice)");
      *fail = fixed_reason("the Vulkan loader this run opened exports no device entry points");
      return false;
    }

    // How many physical devices this instance sees, then all of them. A driver that reports zero is a
    // machine with no Vulkan device at all (or no ICD in reach), which is a reason, not a crash.
    std::uint32_t count = 0U;
    VkResult result = vkEnumeratePhysicalDevices(surface.instance, &count, nullptr);
    log_result("vkEnumeratePhysicalDevices(count)", result);
    if (result != VK_SUCCESS || count == 0U)
    {
      *fail = result == VK_SUCCESS ? fixed_reason("this Vulkan instance sees no physical device")
                                   : fixed_reason("vkEnumeratePhysicalDevices failed to count the devices");
      return false;
    }

    std::vector<VkPhysicalDevice> physical(count, VK_NULL_HANDLE);
    result = vkEnumeratePhysicalDevices(surface.instance, &count, physical.data());
    log_result("vkEnumeratePhysicalDevices", result);
    if (result != VK_SUCCESS && result != VK_INCOMPLETE)
    {
      *fail = fixed_reason("vkEnumeratePhysicalDevices gave no devices");
      return false;
    }

    // The first device that can draw AND present. A box with more than one card enumerates them in an
    // order nobody promised, and a device that cannot present to this surface can never show a frame,
    // so presenting is part of the selection and not an assumption made after it.
    std::uint32_t selected = count; // count means "none of them"
    std::uint32_t selectedFamily = 0U;
    for (std::uint32_t index = 0U; index < count; ++index)
    {
      std::uint32_t families = 0U;
      vkGetPhysicalDeviceQueueFamilyProperties(physical[index], &families, nullptr);
      if (families == 0U)
        continue;

      std::vector<VkQueueFamilyProperties> properties(families);
      vkGetPhysicalDeviceQueueFamilyProperties(physical[index], &families, properties.data());

      for (std::uint32_t family = 0U; family < families; ++family)
      {
        if (!family_offers_graphics(properties[family]))
          continue;

        VkBool32 presents = VK_FALSE;
        const VkResult support = vkGetPhysicalDeviceSurfaceSupportKHR(physical[index], family, surface.surface, &presents);
        if (support == VK_SUCCESS && presents == VK_TRUE)
        {
          selected = index;
          selectedFamily = family;
          break;
        }
      }

      if (selected < count)
        break;
    }

    if (selected == count)
    {
      printf("iw4x32 vulkan device: no device of the %u this instance sees presents to this surface with a graphics queue\n",
             count);
      *fail = fixed_reason("no Vulkan device offers a graphics queue that presents to this surface");
      return false;
    }

    device.physicalDevice = physical[selected];

    if (vkGetPhysicalDeviceProperties != nullptr)
    {
      VkPhysicalDeviceProperties properties{};
      vkGetPhysicalDeviceProperties(device.physicalDevice, &properties);
      printf("iw4x32 vulkan device: selected device %u of %u \"%s\" type %u api %u.%u\n", selected, count,
             properties.deviceName, static_cast<unsigned>(properties.deviceType),
             VK_API_VERSION_MAJOR(properties.apiVersion), VK_API_VERSION_MINOR(properties.apiVersion));
    }
    else
    {
      printf("iw4x32 vulkan device: selected device %u of %u (this loader exports no vkGetPhysicalDeviceProperties)\n",
             selected, count);
    }

    // The swapchain comes from the device, not from the instance: VK_KHR_swapchain has to be one of the
    // extensions this device is created with, or every swapchain call after it runs against a driver
    // entry point that was never wired up. Ask the device first, so a driver without it is refused here
    // with its name in the reason, not in a crash two steps later.
    if (!device_offers_extension(device, VK_KHR_SWAPCHAIN_EXTENSION_NAME))
    {
      *fail = fixed_reason("the selected device does not offer VK_KHR_swapchain: no swapchain is possible");
      return false;
    }

    // One queue family, the one that was proven above: no second queue, no transfer-only family, no
    // family the caller did not ask for. The index is kept because PresentFrame and every future draw
    // run on that queue.
    device.queueFamily = selectedFamily;
    const float queuePriority = 1.0f;

    const VkDeviceQueueCreateInfo queueInfo = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                              nullptr,
                                              0U,
                                              device.queueFamily,
                                              1U,
                                              &queuePriority};

    const char* const extensions[] = {VK_KHR_SWAPCHAIN_EXTENSION_NAME};

    const VkDeviceCreateInfo createInfo = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                                           nullptr,
                                           0U,
                                           1U,
                                           &queueInfo,
                                           0U,
                                           nullptr,
                                           1U,
                                           extensions,
                                           nullptr};

    result = vkCreateDevice(device.physicalDevice, &createInfo, nullptr, &device.device);
    log_result("vkCreateDevice", result);
    if (result != VK_SUCCESS || device.device == VK_NULL_HANDLE)
    {
      device.device = VK_NULL_HANDLE;
      *fail = result == VK_ERROR_EXTENSION_NOT_PRESENT
                  ? fixed_reason("vkCreateDevice refused VK_KHR_swapchain: the device does not carry it")
                  : fixed_reason("vkCreateDevice gave no device");
      return false;
    }

    vkGetDeviceQueue(device.device, device.queueFamily, 0U, &device.queue);
    if (device.queue == VK_NULL_HANDLE)
    {
      log_value("vkGetDeviceQueue returned no queue");
      *fail = fixed_reason("the device was created but handed out no queue");
      const auto vkDestroyDevice = entry_point<PFN_vkDestroyDevice>(device, "vkDestroyDevice");
      if (vkDestroyDevice != nullptr)
        vkDestroyDevice(device.device, nullptr);
      device.device = VK_NULL_HANDLE;
      return false;
    }

    printf("iw4x32 vulkan device: queue family %u graphics 1 device_extension 1 VK_KHR_swapchain\n", device.queueFamily);
    return true;
  }

  bool CreateSwapchain(Device& device, const VkSurfaceKHR surface, const std::uint32_t width, const std::uint32_t height,
                       const VkSwapchainKHR oldSwapchain, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    device.swapchain = VK_NULL_HANDLE;
    device.swapchainImages.clear();
    device.acquiredImage = 0U;
    device.imageCount = 0U;
    device.format = VK_FORMAT_UNDEFINED;
    device.extent = {0U, 0U};

    if (device.device == VK_NULL_HANDLE || device.physicalDevice == VK_NULL_HANDLE || surface == VK_NULL_HANDLE)
    {
      log_value("no device or no surface to make a swapchain for");
      *fail = fixed_reason("no device (or no surface): the swapchain has nothing to present to");
      return false;
    }

    const auto vkGetPhysicalDeviceSurfaceCapabilitiesKHR =
        entry_point<PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR>(device, "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
    const auto vkGetPhysicalDeviceSurfaceFormatsKHR =
        entry_point<PFN_vkGetPhysicalDeviceSurfaceFormatsKHR>(device, "vkGetPhysicalDeviceSurfaceFormatsKHR");
    const auto vkGetPhysicalDeviceSurfacePresentModesKHR =
        entry_point<PFN_vkGetPhysicalDeviceSurfacePresentModesKHR>(device, "vkGetPhysicalDeviceSurfacePresentModesKHR");
    const auto vkCreateSwapchainKHR = entry_point<PFN_vkCreateSwapchainKHR>(device, "vkCreateSwapchainKHR");
    const auto vkGetSwapchainImagesKHR = entry_point<PFN_vkGetSwapchainImagesKHR>(device, "vkGetSwapchainImagesKHR");

    if (vkGetPhysicalDeviceSurfaceCapabilitiesKHR == nullptr || vkGetPhysicalDeviceSurfaceFormatsKHR == nullptr ||
        vkGetPhysicalDeviceSurfacePresentModesKHR == nullptr || vkCreateSwapchainKHR == nullptr ||
        vkGetSwapchainImagesKHR == nullptr)
    {
      log_value("the Vulkan loader exports no swapchain commands (vkCreateSwapchainKHR / vkGetSwapchainImagesKHR)");
      *fail = fixed_reason("the Vulkan loader this run opened exports no swapchain entry points");
      return false;
    }

    VkSurfaceCapabilitiesKHR capabilities{};
    VkResult result = vkGetPhysicalDeviceSurfaceCapabilitiesKHR(device.physicalDevice, surface, &capabilities);
    log_result("vkGetPhysicalDeviceSurfaceCapabilitiesKHR", result);
    if (result != VK_SUCCESS)
    {
      *fail = result_name(result);
      return false;
    }

    std::uint32_t formatCount = 0U;
    result = vkGetPhysicalDeviceSurfaceFormatsKHR(device.physicalDevice, surface, &formatCount, nullptr);
    if (result != VK_SUCCESS || formatCount == 0U)
    {
      log_result("vkGetPhysicalDeviceSurfaceFormatsKHR(count)", result);
      *fail = fixed_reason("this surface offers no format at all - a window with no pixels");
      return false;
    }
    std::vector<VkSurfaceFormatKHR> formats(formatCount);
    result = vkGetPhysicalDeviceSurfaceFormatsKHR(device.physicalDevice, surface, &formatCount, formats.data());
    log_result("vkGetPhysicalDeviceSurfaceFormatsKHR", result);
    if (result != VK_SUCCESS && result != VK_INCOMPLETE)
    {
      *fail = fixed_reason("vkGetPhysicalDeviceSurfaceFormatsKHR gave no formats");
      return false;
    }

    // VK_FORMAT_B8G8R8A8_UNORM, the format the renderer is written for: the first entry that names it.
    // A surface that does not offer BGRA at all is a refusal rather than a silent substitute - a
    // renderer that writes BGRA into an R8G8B8A8 swapchain draws the game in the wrong colours, and a
    // check that reads the frame back would read those colours as correct.
    bool haveBgra = false;
    for (const VkSurfaceFormatKHR& candidate : formats)
      if (candidate.format == VK_FORMAT_B8G8R8A8_UNORM)
        haveBgra = true;
    if (!haveBgra)
    {
      printf("iw4x32 vulkan device: this surface offers no VK_FORMAT_B8G8R8A8_UNORM (%u format(s))\n", formatCount);
      *fail = fixed_reason("the surface offers no VK_FORMAT_B8G8R8A8_UNORM: this renderer is written for BGRA");
      return false;
    }
    for (const VkSurfaceFormatKHR& candidate : formats)
    {
      if (candidate.format == VK_FORMAT_B8G8R8A8_UNORM)
      {
        device.format = candidate.format;
        device.colorSpace = candidate.colorSpace;
        break;
      }
    }

    std::uint32_t modeCount = 0U;
    result = vkGetPhysicalDeviceSurfacePresentModesKHR(device.physicalDevice, surface, &modeCount, nullptr);
    if (result != VK_SUCCESS || modeCount == 0U)
    {
      log_result("vkGetPhysicalDeviceSurfacePresentModesKHR(count)", result);
      *fail = fixed_reason("this surface offers no present mode");
      return false;
    }
    std::vector<VkPresentModeKHR> modes(modeCount);
    result = vkGetPhysicalDeviceSurfacePresentModesKHR(device.physicalDevice, surface, &modeCount, modes.data());
    log_result("vkGetPhysicalDeviceSurfacePresentModesKHR", result);
    if (result != VK_SUCCESS && result != VK_INCOMPLETE)
    {
      *fail = fixed_reason("vkGetPhysicalDeviceSurfacePresentModesKHR gave no modes");
      return false;
    }

    // VK_PRESENT_MODE_FIFO_KHR is the one mode the specification guarantees every implementation
    // supports, and it is vsynced: no tearing in a recorded run, and the frame rate of a windowed test
    // stays bounded by the display instead of by how fast the card can spin.
    bool haveFifo = false;
    for (const VkPresentModeKHR mode : modes)
      if (mode == VK_PRESENT_MODE_FIFO_KHR)
        haveFifo = true;
    if (!haveFifo)
    {
      printf("iw4x32 vulkan device: this surface offers no VK_PRESENT_MODE_FIFO_KHR (%u mode(s))\n", modeCount);
      *fail = fixed_reason("the surface offers no VK_PRESENT_MODE_FIFO_KHR");
      return false;
    }
    device.presentMode = VK_PRESENT_MODE_FIFO_KHR;

    // The extent the compositor actually wants. currentExtent is what a windowed surface is showing
    // (0x0 or UINT32_MAX only for a surface that has no size yet, where the caller's size is used);
    // clamping into minImageExtent/maxImageExtent is what a resize into a weird window size costs - an
    // out-of-range extent is a validation error, not a smaller swapchain.
    VkExtent2D extent = capabilities.currentExtent;
    if (extent.width == 0U || extent.height == 0U || extent.width == 0xFFFFFFFFU)
    {
      extent.width = width;
      extent.height = height;
    }
    if (extent.width < capabilities.minImageExtent.width)
      extent.width = capabilities.minImageExtent.width;
    if (extent.height < capabilities.minImageExtent.height)
      extent.height = capabilities.minImageExtent.height;
    if (capabilities.maxImageExtent.width != 0U && extent.width > capabilities.maxImageExtent.width)
      extent.width = capabilities.maxImageExtent.width;
    if (capabilities.maxImageExtent.height != 0U && extent.height > capabilities.maxImageExtent.height)
      extent.height = capabilities.maxImageExtent.height;
    if (extent.width == 0U || extent.height == 0U)
    {
      log_value("the surface wants a swapchain of zero extent (an iconified or zero-size window)");
      *fail = fixed_reason("the surface asked for a swapchain with no pixels");
      return false;
    }
    device.extent = extent;

    // The transform: identity when the surface is upright (the normal windowed case); otherwise the
    // compositor's own, which the caller has to match in its render pass. Only a transform the surface
    // supports is asked for - an unsupported one is a validation error.
    if ((capabilities.supportedTransforms & capabilities.currentTransform) != 0U)
      device.preTransform = capabilities.currentTransform;
    else if ((capabilities.supportedTransforms & VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR) != 0U)
      device.preTransform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
    else
    {
      device.preTransform = static_cast<VkSurfaceTransformFlagBitsKHR>(capabilities.supportedTransforms &
                                                                      (~capabilities.supportedTransforms + 1U));
      printf("iw4x32 vulkan device: the surface wants no transform it supports (taking 0x%x)\n",
             static_cast<unsigned>(device.preTransform));
    }

    // Image count: what the surface asks for, clamped into what it allows. maxImageCount of 0 means
    // "no maximum", so the requested count stands.
    std::uint32_t imageCount = capabilities.minImageCount + 1U;
    if (capabilities.maxImageCount > 0U && imageCount > capabilities.maxImageCount)
      imageCount = capabilities.maxImageCount;
    if (imageCount < capabilities.minImageCount)
      imageCount = capabilities.minImageCount;
    if (imageCount == 0U)
      imageCount = 1U;

    const VkSwapchainCreateInfoKHR createInfo = {VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
                                                 nullptr,
                                                 0U,
                                                 surface,
                                                 imageCount,
                                                 device.format,
                                                 device.colorSpace,
                                                 extent,
                                                 1U,
                                                 VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                                                     VK_IMAGE_USAGE_TRANSFER_DST_BIT,
                                                 VK_SHARING_MODE_EXCLUSIVE,
                                                 0U,
                                                 nullptr,
                                                 device.preTransform,
                                                 VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
                                                 device.presentMode,
                                                 VK_TRUE,
                                                 oldSwapchain};

    result = vkCreateSwapchainKHR(device.device, &createInfo, nullptr, &device.swapchain);
    log_result("vkCreateSwapchainKHR", result);

    // VK_SUBOPTIMAL_KHR is a swapchain that works but no longer matches the surface (a rotated
    // compositor, a window that changed shape): the caller recreates it, it is not a failed run.
    const bool created = result == VK_SUCCESS || result == VK_SUBOPTIMAL_KHR;
    if (created && result == VK_SUBOPTIMAL_KHR)
      log_line("swapchain suboptimal", result_name(result));

    // The handle, not only the result: a loader whose device was built without VK_KHR_swapchain answers
    // VK_SUCCESS with a null swapchain and a NULL driver pointer behind it. Nothing below may run on it.
    if (device.swapchain == VK_NULL_HANDLE)
    {
      *fail = result == VK_SUCCESS
                  ? fixed_reason("vkCreateSwapchainKHR said VK_SUCCESS but gave no swapchain: VK_KHR_swapchain is not enabled on this device")
                  : fixed_reason(result == VK_ERROR_OUT_OF_DATE_KHR ? "vkCreateSwapchainKHR: the surface changed underneath us"
                                                                    : "vkCreateSwapchainKHR gave no swapchain");
      return false;
    }
    if (!created)
    {
      // A refusal that still filled the handle: it belongs to the swapchain that was refused.
      const auto vkDestroySwapchainKHR = entry_point<PFN_vkDestroySwapchainKHR>(device, "vkDestroySwapchainKHR");
      if (vkDestroySwapchainKHR != nullptr)
        vkDestroySwapchainKHR(device.device, device.swapchain, nullptr);
      device.swapchain = VK_NULL_HANDLE;
      *fail = result_name(result);
      return false;
    }

    std::uint32_t imageCount2 = 0U;
    result = vkGetSwapchainImagesKHR(device.device, device.swapchain, &imageCount2, nullptr);
    if (result != VK_SUCCESS || imageCount2 == 0U)
    {
      log_result("vkGetSwapchainImagesKHR(count)", result);
      *fail = fixed_reason("the swapchain handed out no images");
      const auto vkDestroySwapchainKHR = entry_point<PFN_vkDestroySwapchainKHR>(device, "vkDestroySwapchainKHR");
      if (vkDestroySwapchainKHR != nullptr)
        vkDestroySwapchainKHR(device.device, device.swapchain, nullptr);
      device.swapchain = VK_NULL_HANDLE;
      return false;
    }
    device.swapchainImages.resize(imageCount2, VK_NULL_HANDLE);
    result = vkGetSwapchainImagesKHR(device.device, device.swapchain, &imageCount2, device.swapchainImages.data());
    log_result("vkGetSwapchainImagesKHR", result);
    device.imageCount = imageCount2;

    printf("iw4x32 vulkan device: swapchain %u image(s) %ux%u format %u present_mode %u transform %u old %s\n",
           imageCount2, extent.width, extent.height, static_cast<unsigned>(device.format),
           static_cast<unsigned>(device.presentMode), static_cast<unsigned>(device.preTransform),
           oldSwapchain == VK_NULL_HANDLE ? "none" : "replaced");
    return true;
  }

  bool AcquireNextImage(Device& device, const VkSemaphore semaphore, const VkFence fence, std::uint32_t& outImage,
                        const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    if (device.device == VK_NULL_HANDLE || device.swapchain == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no swapchain to take an image from");
      return false;
    }

    const auto vkAcquireNextImageKHR = entry_point<PFN_vkAcquireNextImageKHR>(device, "vkAcquireNextImageKHR");
    if (vkAcquireNextImageKHR == nullptr)
    {
      *fail = fixed_reason("the Vulkan loader exports no vkAcquireNextImageKHR");
      return false;
    }

    std::uint32_t image = 0U;
    const VkResult result = vkAcquireNextImageKHR(device.device, device.swapchain, ~0ULL, semaphore, fence, &image);
    log_result("vkAcquireNextImageKHR", result);
    if (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR)
    {
      *fail = result == VK_ERROR_OUT_OF_DATE_KHR ? fixed_reason("vkAcquireNextImageKHR: VK_ERROR_OUT_OF_DATE_KHR - recreate the swapchain")
                                                 : fixed_reason("vkAcquireNextImageKHR gave no image");
      return false;
    }

    // An image the swapchain never listed cannot be drawn into or presented: the driver indexes its own
    // array with this number.
    if (image >= device.imageCount)
    {
      printf("iw4x32 vulkan device: vkAcquireNextImageKHR handed image %u of %u\n", image, device.imageCount);
      *fail = fixed_reason("vkAcquireNextImageKHR gave an image past the end of this swapchain");
      return false;
    }

    outImage = image;
    device.acquiredImage = image;
    return true;
  }

  const std::vector<VkImage>& SwapchainImages(const Device& device)
  {
    return device.swapchainImages;
  }

  VkExtent2D SwapchainExtent(const Device& device)
  {
    return device.extent;
  }

  VkFormat SwapchainFormat(const Device& device)
  {
    return device.format;
  }

  bool PresentFrame(Device& device, const std::uint32_t image, bool& stale, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    stale = false;

    if (device.device == VK_NULL_HANDLE || device.queue == VK_NULL_HANDLE || device.swapchain == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no device, queue or swapchain to present through");
      return false;
    }

    // An index the swapchain never handed out is a driver-side memory error, not a Vulkan error: the
    // count comes from vkGetSwapchainImagesKHR, so it is known here.
    if (image >= device.imageCount)
    {
      printf("iw4x32 vulkan device: refusing to present image %u of %u\n", image, device.imageCount);
      *fail = fixed_reason("the image index is past the end of this swapchain");
      return false;
    }

    const auto vkQueuePresentKHR = entry_point<PFN_vkQueuePresentKHR>(device, "vkQueuePresentKHR");
    if (vkQueuePresentKHR == nullptr)
    {
      *fail = fixed_reason("the Vulkan loader exports no vkQueuePresentKHR");
      return false;
    }

    const VkPresentInfoKHR presentInfo = {VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
                                          nullptr,
                                          0U,
                                          nullptr,
                                          1U,
                                          &device.swapchain,
                                          &image,
                                          nullptr};

    const VkResult result = vkQueuePresentKHR(device.queue, &presentInfo);
    log_result("vkQueuePresentKHR", result);

    // A present of an out-of-date or suboptimal swapchain did happen - the frame went away, the
    // swapchain is the thing to rebuild. Telling those two apart from a dead renderer is the caller's
    // job, so they come back as true + stale.
    if (result == VK_SUCCESS)
      return true;
    if (result == VK_SUBOPTIMAL_KHR || result == VK_ERROR_OUT_OF_DATE_KHR)
    {
      stale = true;
      *fail = result_name(result);
      log_line("stale swapchain", result_name(result));
      return true;
    }

    *fail = result_name(result);
    return false;
  }

  bool PresentFrame(Device& device, const std::uint32_t image, const char** error)
  {
    bool stale = false;
    return PresentFrame(device, image, stale, error);
  }

  bool WaitIdle(Device& device, const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    if (device.device == VK_NULL_HANDLE)
    {
      *fail = fixed_reason("no device to wait for");
      return false;
    }

    const auto vkDeviceWaitIdle = entry_point<PFN_vkDeviceWaitIdle>(device, "vkDeviceWaitIdle");
    if (vkDeviceWaitIdle == nullptr)
    {
      *fail = fixed_reason("the Vulkan loader exports no vkDeviceWaitIdle");
      return false;
    }

    const VkResult result = vkDeviceWaitIdle(device.device);
    log_result("vkDeviceWaitIdle", result);
    if (result != VK_SUCCESS)
    {
      *fail = result_name(result);
      return false;
    }
    return true;
  }

  void DestroyVulkanDevice(Device& device)
  {
    // Newest first. A command that the loader does not export is skipped rather than guessed at - a
    // half-built device tears down as far as it was built, and nothing here is ever called through null.
    if (device.device != VK_NULL_HANDLE && device.swapchain != VK_NULL_HANDLE)
    {
      const auto vkDestroySwapchainKHR = entry_point<PFN_vkDestroySwapchainKHR>(device, "vkDestroySwapchainKHR");
      if (vkDestroySwapchainKHR != nullptr)
        vkDestroySwapchainKHR(device.device, device.swapchain, nullptr);
    }
    device.swapchain = VK_NULL_HANDLE;
    device.swapchainImages.clear();
    device.imageCount = 0U;
    device.acquiredImage = 0U;

    if (device.device != VK_NULL_HANDLE)
    {
      const auto vkDestroyDevice = entry_point<PFN_vkDestroyDevice>(device, "vkDestroyDevice");
      if (vkDestroyDevice != nullptr)
        vkDestroyDevice(device.device, nullptr);
    }
    device.device = VK_NULL_HANDLE;
    device.queue = VK_NULL_HANDLE;

    // The physical device and the instance belong above this file (to the device's physical device and
    // to the surface), so this file lets go of the handles without destroying anything.
    device.physicalDevice = VK_NULL_HANDLE;
    device.instance = VK_NULL_HANDLE;
    device.format = VK_FORMAT_UNDEFINED;
    device.extent = {0U, 0U};
    device.getInstanceProcAddr = nullptr;
  }
}
