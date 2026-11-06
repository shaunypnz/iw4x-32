// IW4x-32: the stub Vulkan backend - the contract of VulkanBackend.hpp, answered with a log line.
//
// PRIVATE - not for publication.
//
// Nothing here draws. Each step says what it was asked and what it answered, so a run shows
// whether the renderer path actually walks the lifecycle - a backend that is never called and a
// backend that is called in the wrong order look different in the log. The steps report
// VK_INCOMPLETE rather than VK_SUCCESS: an unimplemented step that claimed success would make a
// check that looks for a working Vulkan path believe this one.
//
// VK_INCOMPLETE is also the value the Vulkan loader itself answers with when a step needs
// something it cannot give (a surface for a window type the loader does not support), so the
// caller already has to treat it as "no renderer, start the next one" - which is exactly what a
// stub is for.

#include "VulkanBackend.hpp"

#include <cstdio>

namespace VulkanBackend
{
  namespace
  {
    // stdout, one line per step: the game console does not have to exist yet for a test run to
    // read this, and the line names itself so it cannot be confused with the game's own output.
    void log_step(const char* step, VkResult result)
    {
      printf("iw4x32 vulkan backend: %s -> %d\n", step, static_cast<int>(result));
    }
  } // namespace

  VkResult StubBackend::CreateInstance()
  {
    log_step("create instance", VK_INCOMPLETE);
    return VK_INCOMPLETE;
  }

  VkResult StubBackend::CreateSurface(void* nativeWindow)
  {
    printf("iw4x32 vulkan backend: create surface window %p\n", nativeWindow);
    log_step("create surface", VK_INCOMPLETE);
    return VK_INCOMPLETE;
  }

  VkResult StubBackend::CreateDevice()
  {
    log_step("create device", VK_INCOMPLETE);
    return VK_INCOMPLETE;
  }

  VkResult StubBackend::CreateSwapchain(std::uint32_t width, std::uint32_t height)
  {
    printf("iw4x32 vulkan backend: create swapchain %ux%u\n", width, height);
    log_step("create swapchain", VK_INCOMPLETE);
    return VK_INCOMPLETE;
  }

  VkResult StubBackend::Present()
  {
    log_step("present", VK_INCOMPLETE);
    return VK_INCOMPLETE;
  }

  VkResult StubBackend::Shutdown()
  {
    log_step("shutdown", VK_SUCCESS); // nothing was ever built: teardown really does succeed
    return VK_SUCCESS;
  }
}
