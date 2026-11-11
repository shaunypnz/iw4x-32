// IW4x-32: the SDL2 window and the Vulkan surface the native renderer draws to.
//
// PRIVATE - not for publication.
//
// The native client opens its window with SDL2 and draws through Vulkan itself: no D3D9 device, no
// DXVK, nothing translated. This is the first step of that path - a windowed SDL2 window, a Vulkan
// instance carrying the instance extensions SDL says a surface needs, and the surface a swapchain is
// made for. It owns no device, no swapchain and no frame; VulkanBackend.hpp is the contract that
// describes those, and nothing here claims to be a renderer.
//
// The window system stays out of the rest of the client: SDL_Window is forward-declared, so a file
// that only holds a VulkanSurface does not need SDL2 headers to compile. The iw4x.dll build is one
// of those - it has no SDL2 to compile or link against (premake5.lua's iw4x32_sdl2 says so with
// IW4X32_NO_SDL2, and a checkout configured with no SDL2 folder at all needs no define to reach the
// same answer), and there CreateVulkanSurface answers false and says why.
#pragma once

#include <vulkan/vulkan.h>

struct SDL_Window;

namespace Utils::SDL2
{
  // What CreateVulkanSurface hands back, and what DestroyVulkanSurface takes. Every handle is null
  // until the step that made it ran, and null again after DestroyVulkanSurface, so a half-built surface
  // can be destroyed as easily as a finished one (a vid_restart and a failed init both do).
  struct VulkanSurface
  {
    VkInstance instance = VK_NULL_HANDLE;
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    SDL_Window* window = nullptr;

    // What this surface borrowed from SDL, and so what DestroyVulkanSurface gives back: the Vulkan
    // library SDL opened for this instance (never linked by us - a run can point it at one loader with
    // IW4X_VULKAN_LIB), and the video subsystem we initialised because nothing else had. Both are set
    // by the step that took them and cleared by the step that gave them back.
    bool vulkanLibrary = false;
    bool videoSubsystem = false;
  };

  // Window, instance, surface - in that order. The window is created windowed and decorated (never
  // fullscreen, never exclusive: owner 2026-10-29), the instance asks for exactly the instance
  // extensions SDL_Vulkan_GetInstanceExtensions reports plus nothing, and the surface is the one for
  // that window. On success returns true and fills `surface`; on failure returns false, leaves
  // `surface` destroyed and whole (so the caller may call DestroyVulkanSurface or nothing), and puts
  // a one-line reason in `error` - owned by this file or by SDL, good until the next SDL call, so a
  // caller that wants it later copies it out. An extension the loader does not offer is a failure, not
  // a warning: a surface made without the extension that presents on it is undefined.
  bool CreateVulkanSurface(VulkanSurface& surface, const char* title, unsigned width, unsigned height,
                           const char** error);

  // Teardown, newest first: surface, instance, SDL's Vulkan library, window, video subsystem. Safe on a
  // half-built surface, safe on a zeroed one, safe to call twice.
  void DestroyVulkanSurface(VulkanSurface& surface);
}
