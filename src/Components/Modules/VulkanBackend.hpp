// IW4x-32: the renderer backend contract - the shape of a Vulkan renderer the client can hold.
//
// PRIVATE - not for publication.
//
// The renderer epic replaces the translated graphics path with a backend that draws the game
// through Vulkan itself. This is the boundary that work is written against: one object per
// renderer, one method per step of the lifecycle the loader-side contract counts
// (iw4x32/native/src/backend/backend.h: instance, device, surface, swapchain, present).
//
// What it does NOT promise: shaders, materials, world geometry, models, effects, depth, or
// anything else the game draws. A backend that answers this contract owns a device and a
// swapchain, not a frame of the game, and nothing may report it as one. The translated path
// keeps drawing until a backend does - Renderer::OnBackendFrame still hands out the device the
// game renders with.
//
// Vulkan headers only: `nativeWindow` is an opaque handle, so this contract does not pick a
// window system for its implementations, and it pulls in no graphics header of the old path.
#pragma once

#include <cstdint>
#include <vulkan/vulkan.h>

namespace VulkanBackend
{
  // One renderer, one lifecycle, in this order: instance, surface, device, swapchain, then
  // Present once per frame, then Shutdown. Every method returns the VkResult of the Vulkan call
  // that step made (VK_SUCCESS when the step did not reach Vulkan at all). A step that fails has
  // already released what it created on the way out, so the caller only has to start the next
  // backend - it never has to clean up a half-built one.
  class IRendererBackend
  {
  public:
    virtual ~IRendererBackend() = default;

    // The Vulkan instance of this backend, with its own app name and the apiVersion it needs.
    [[nodiscard]] virtual VkResult CreateInstance() = 0;

    // The surface to draw to: an HWND on Windows, the native loader's window on Linux. void*
    // because the window system belongs to the caller, not to the contract.
    [[nodiscard]] virtual VkResult CreateSurface(void* nativeWindow) = 0;

    // The physical device that presents to that surface, and the logical device and queue family
    // the backend renders with.
    [[nodiscard]] virtual VkResult CreateDevice() = 0;

    // The swapchain for a window of that extent; a window resize recreates it.
    [[nodiscard]] virtual VkResult CreateSwapchain(std::uint32_t width, std::uint32_t height) = 0;

    // One frame to the screen. VK_SUBOPTIMAL_KHR and VK_ERROR_OUT_OF_DATE_KHR are the caller's
    // cue to recreate the swapchain, not a dead renderer.
    [[nodiscard]] virtual VkResult Present() = 0;

    // Release everything, newest first. Safe after a partial init and safe to call twice: a
    // vid_restart and a failed init both run it, and the next backend starts from nothing.
    [[nodiscard]] virtual VkResult Shutdown() = 0;
  };

  // The backend that exists before there is a renderer: it answers the contract, logs every step
  // to stdout, and reports the step that would come next as not implemented. It never reaches a
  // Vulkan loader, so a build without one still gets the same answer, and a check can tell a call
  // that happened from one that was never wired up. The first real backend replaces it.
  class StubBackend final : public IRendererBackend
  {
  public:
    [[nodiscard]] VkResult CreateInstance() override;
    [[nodiscard]] VkResult CreateSurface(void* nativeWindow) override;
    [[nodiscard]] VkResult CreateDevice() override;
    [[nodiscard]] VkResult CreateSwapchain(std::uint32_t width, std::uint32_t height) override;
    [[nodiscard]] VkResult Present() override;
    [[nodiscard]] VkResult Shutdown() override;
  };
}
