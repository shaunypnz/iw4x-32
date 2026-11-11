// IW4x-32: the SDL2 window and the Vulkan surface - the first step of the native renderer.
//
// PRIVATE - not for publication.
//
// Nothing translated is used here: the only graphics libraries this file touches are SDL2 (the window)
// and the system Vulkan loader (the instance and the surface). Like the loader-side backend
// (iw4x32/native/src/backend/vk_backend.c) no loader is linked - the entry points come from
// vkGetInstanceProcAddr, taken from the Vulkan library SDL opened - so the build links nothing a
// machine may not have, and a run decides which loader answers: IW4X_VULKAN_LIB names one, SDL's own
// default (libvulkan.so.1) is the answer when it does not.
//
// Nothing is drawn. There is no device, no swapchain and no frame here: a surface made by this file is
// something a later step renders to. Every step prints what it asked and what it got, so a test can
// tell a call that happened from one that was never wired up, and a step that failed says why.
//
// The iw4x.dll build compiles the declarations only: it has no SDL2 to compile or link against, and
// the window of that build is the game's own HWND. Answering false with a reason there beats a link
// error three minutes into the build. Two builds mean no SDL2, and both refuse with their own name:
// the one here (premake5.lua's iw4x32_sdl2 says so with IW4X32_NO_SDL2) and a checkout that was configured
// with no SDL2 folder and no such define at all - the release build asks this repo and its submodules
// for dependencies, and neither the SDL2 dependency file nor an SDL2 lives in this branch.

#include "VulkanSurface.hpp"

#include <cstdio>
#include <cstdlib>
#include <vector>

// Is there an SDL2 to compile against? The build is allowed to say no (IW4X32_NO_SDL2); where nobody
// said anything, the headers answer the question. Reaching this decision without being told is what
// keeps a dependency-less checkout building. IW4X32_SDL2_PATH is this file's answer, whatever the
// route to it: iw4x32/tools/vulkan_surface_test.sh compiles the three lines below on their own (with
// -nostdinc, so no SDL2 can be in reach) and shows that answer flip.
#if defined(IW4X32_NO_SDL2)
#define IW4X32_SDL2_PATH 0
#elif defined(__has_include) && __has_include(<SDL2/SDL.h>) && __has_include(<SDL2/SDL_vulkan.h>)
#define IW4X32_SDL2_PATH 1
#else
#define IW4X32_SDL2_PATH 0
#endif

#if IW4X32_SDL2_PATH
#include <SDL2/SDL.h>
#include <SDL2/SDL_vulkan.h>
#endif

namespace Utils::SDL2
{
#if !IW4X32_SDL2_PATH

  bool CreateVulkanSurface(VulkanSurface& surface, const char*, const unsigned, const unsigned, const char** error)
  {
    if (error != nullptr)
#if defined(IW4X32_NO_SDL2)
      *error = "no SDL2 in this build (IW4X32_NO_SDL2): iw4x.dll links no SDL2, the window there is the game's own HWND";
#else
      *error = "no SDL2 headers to compile against: this build was configured without an SDL2 development folder";
#endif

    surface = VulkanSurface();
    return false;
  }

  void DestroyVulkanSurface(VulkanSurface& surface)
  {
    surface = VulkanSurface();
  }

#else

  namespace
  {
    // stdout, one line per step: the game console does not have to exist for a run to read this, and
    // the line names itself so it is never mistaken for the game's own output.
    void log_line(const char* what, const char* detail)
    {
      printf("iw4x32 vulkan surface: %s %s\n", what, detail);
    }

    void log_result(const char* what, const VkResult result)
    {
      printf("iw4x32 vulkan surface: %s -> %d\n", what, static_cast<int>(result));
    }

    // Which library the run asked for by name, or "" when it asked for SDL's default. Kept for the log
    // line: "the frame came from this loader" is the evidence a Vulkan check reads.
    const char* requested_library()
    {
      const char* fromEnv = getenv("IW4X_VULKAN_LIB");
      return (fromEnv != nullptr && *fromEnv != '\0') ? fromEnv : "";
    }

    // Open the Vulkan library SDL hands its own surface creation to. Doing it here rather than letting
    // SDL do it lazily is what makes the loader a choice of the run: instance and surface then come
    // from one and the same library, which is the one requirement Vulkan puts on a surface.
    bool open_vulkan_library(const char** error)
    {
      const char* wanted = requested_library();

      if (SDL_Vulkan_LoadLibrary(*wanted != '\0' ? wanted : nullptr) != 0)
      {
        log_line("could not open the Vulkan library:", SDL_GetError());
        *error = SDL_GetError();
        return false;
      }

      log_line("loader", *wanted != '\0' ? wanted : "SDL's default (libvulkan.so.1)");
      return true;
    }

    // An instance-level entry point of that library: vkGetInstanceProcAddr with a null instance answers
    // for every instance-level command, including the ones used before an instance exists. A null here
    // means that loader does not export the command - a reason, never a call through null.
    template <typename T>
    T instance_entry_point(const char* name)
    {
      const auto gipa = reinterpret_cast<PFN_vkGetInstanceProcAddr>(SDL_Vulkan_GetVkGetInstanceProcAddr());
      if (gipa == nullptr)
        return nullptr;

      return reinterpret_cast<T>(gipa(VK_NULL_HANDLE, name));
    }

    // Same, once an instance exists: a device-level command needs the instance to find its dispatch.
    template <typename T>
    T instance_entry_point(VkInstance instance, const char* name)
    {
      const auto gipa = reinterpret_cast<PFN_vkGetInstanceProcAddr>(SDL_Vulkan_GetVkGetInstanceProcAddr());
      if (gipa == nullptr)
        return nullptr;

      return reinterpret_cast<T>(gipa(instance, name));
    }
  } // namespace

  bool CreateVulkanSurface(VulkanSurface& surface, const char* title, const unsigned width, const unsigned height,
                           const char** error)
  {
    const char* reason = nullptr;
    const char** fail = error != nullptr ? error : &reason;

    surface = VulkanSurface();

    // The window first: both the extension list and the surface belong to a window, so a machine that
    // cannot open one fails before a Vulkan object exists.
    //
    // SDL_WINDOW_VULKAN and nothing that asks for a context - no SDL_WINDOW_OPENGL, no GL attribute:
    // a GL context would put a second graphics stack in front of the surface this feeds. The flags are
    // one named expression (windowFlags below): decorated and windowed, never fullscreen and never
    // exclusive (owner 2026-10-29).
    if (SDL_WasInit(SDL_INIT_VIDEO) == 0)
    {
      if (SDL_InitSubSystem(SDL_INIT_VIDEO) != 0)
      {
        log_line("SDL could not start its video subsystem:", SDL_GetError());
        *fail = SDL_GetError();
        return false;
      }
      surface.videoSubsystem = true;
    }

    const Uint32 windowFlags = SDL_WINDOW_VULKAN | SDL_WINDOW_ALLOW_HIGHDPI;
    surface.window = SDL_CreateWindow(title != nullptr ? title : "IW4x", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED,
                                      static_cast<int>(width), static_cast<int>(height), windowFlags);
    if (surface.window == nullptr)
    {
      log_line("SDL_CreateWindow failed:", SDL_GetError());
      *fail = SDL_GetError();
      DestroyVulkanSurface(surface);
      return false;
    }

    // What the window really is, read back from SDL rather than assumed: a decorated window of the size
    // it was asked for. A window manager that overrode the request is worth seeing in the log - and a
    // FULLSCREEN in that line is a run that broke the windowed rule, whatever the caller passed.
    int windowWidth = 0, windowHeight = 0;
    SDL_GetWindowSize(surface.window, &windowWidth, &windowHeight);
    const Uint32 flags = SDL_GetWindowFlags(surface.window);
    printf("iw4x32 vulkan surface: window %dx%d flags 0x%08x%s\n", windowWidth, windowHeight,
           static_cast<unsigned>(flags), (flags & SDL_WINDOW_FULLSCREEN) ? " FULLSCREEN" : "");

    // The instance extensions SDL needs for a surface on this window system - on X11 that is
    // VK_KHR_surface plus VK_KHR_xlib_surface; a surface made without them is invalid, so an empty list
    // or a second call that dropped them fails here rather than at present time.
    unsigned int extensionCount = 0;
    if (SDL_Vulkan_GetInstanceExtensions(surface.window, &extensionCount, nullptr) == SDL_FALSE || extensionCount == 0)
    {
      log_line("SDL_Vulkan_GetInstanceExtensions reported no extensions for this window", "(no extension list, no surface)");
      *fail = "SDL reported no Vulkan instance extensions for this window";
      DestroyVulkanSurface(surface);
      return false;
    }

    std::vector<const char*> extensions(extensionCount, nullptr);
    if (SDL_Vulkan_GetInstanceExtensions(surface.window, &extensionCount, extensions.data()) == SDL_FALSE)
    {
      log_line("SDL_Vulkan_GetInstanceExtensions failed:", SDL_GetError());
      *fail = SDL_GetError();
      DestroyVulkanSurface(surface);
      return false;
    }

    printf("iw4x32 vulkan surface: %u instance extension(s)", extensionCount);
    for (const char* extension : extensions)
      printf(" %s", extension != nullptr ? extension : "(null)");
    printf("\n");

    if (!open_vulkan_library(fail))
    {
      DestroyVulkanSurface(surface);
      return false;
    }
    surface.vulkanLibrary = true;

    const auto vkCreateInstance = instance_entry_point<PFN_vkCreateInstance>("vkCreateInstance");
    if (vkCreateInstance == nullptr)
    {
      log_line("the Vulkan library exports no vkCreateInstance", "(no instance, no surface)");
      *fail = "the Vulkan library SDL opened exports no vkCreateInstance";
      DestroyVulkanSurface(surface);
      return false;
    }

    // The instance: this app, the apiVersion this code is written against, and exactly the extensions
    // SDL asked for - no layers, no device extension, nothing else layered on. The extension list in the
    // line above is the evidence of that.
    const VkApplicationInfo appInfo = {VK_STRUCTURE_TYPE_APPLICATION_INFO,
                                       nullptr,
                                       "IW4x-32",
                                       VK_MAKE_API_VERSION(0, 1, 0, 0),
                                       "IW4x-32 native Vulkan",
                                       VK_MAKE_API_VERSION(0, 1, 0, 0),
                                       VK_API_VERSION_1_1};

    const VkInstanceCreateInfo createInfo = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
                                             nullptr,
                                             0,
                                             &appInfo,
                                             0,
                                             nullptr,
                                             extensionCount,
                                             extensions.data()};

    const VkResult instanceResult = vkCreateInstance(&createInfo, nullptr, &surface.instance);
    log_result("vkCreateInstance", instanceResult);
    if (instanceResult != VK_SUCCESS || surface.instance == VK_NULL_HANDLE)
    {
      surface.instance = VK_NULL_HANDLE;
      *fail = instanceResult == VK_ERROR_INITIALIZATION_FAILED ? "vkCreateInstance refused: no Vulkan driver, or an extension the loader does not offer"
                                                              : "vkCreateInstance did not give an instance";
      DestroyVulkanSurface(surface);
      return false;
    }

    // The surface, through SDL - which is the point of the extensions above: the window system's surface
    // creation belongs to the loader that made the instance, and both are the library SDL opened.
    if (SDL_Vulkan_CreateSurface(surface.window, surface.instance, &surface.surface) == SDL_FALSE)
    {
      log_line("SDL_Vulkan_CreateSurface failed:", SDL_GetError());
      *fail = SDL_GetError();
      surface.surface = VK_NULL_HANDLE;
      DestroyVulkanSurface(surface);
      return false;
    }

    // A non-dispatchable handle is a 64-bit integer on every platform (a pointer on some), so it is
    // printed as a number: the value is only there to tell one surface from another in a run.
    printf("iw4x32 vulkan surface: surface 0x%016llx over %u extension(s)\n",
           static_cast<unsigned long long>(surface.surface), extensionCount);
    return true;
  }

  void DestroyVulkanSurface(VulkanSurface& surface)
  {
    // Newest first, each step through the library that made it, and each step skipped rather than
    // guessed at when that library does not export it: leaking a handle on a teardown path is
    // survivable, jumping through a null one is not.
    if (surface.vulkanLibrary)
    {
      if (surface.instance != VK_NULL_HANDLE && surface.surface != VK_NULL_HANDLE)
      {
        const auto vkDestroySurfaceKHR = instance_entry_point<PFN_vkDestroySurfaceKHR>(surface.instance, "vkDestroySurfaceKHR");
        if (vkDestroySurfaceKHR != nullptr)
          vkDestroySurfaceKHR(surface.instance, surface.surface, nullptr);
      }
      surface.surface = VK_NULL_HANDLE;

      if (surface.instance != VK_NULL_HANDLE)
      {
        const auto vkDestroyInstance = instance_entry_point<PFN_vkDestroyInstance>("vkDestroyInstance");
        if (vkDestroyInstance != nullptr)
          vkDestroyInstance(surface.instance, nullptr);
      }
      surface.instance = VK_NULL_HANDLE;

      SDL_Vulkan_UnloadLibrary();
      surface.vulkanLibrary = false;
    }

    if (surface.window != nullptr)
    {
      SDL_DestroyWindow(surface.window);
      surface.window = nullptr;
    }

    if (surface.videoSubsystem)
    {
      SDL_QuitSubSystem(SDL_INIT_VIDEO);
      surface.videoSubsystem = false;
    }
  }

#endif
}
