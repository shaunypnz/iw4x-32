#pragma once

#include "VulkanResources.hpp" // IW4x-32: the native renderer's device and resource layer

namespace Components
{
  // IW4x-32: turns the stock iw4x.exe (sized for 18 players) into a 32-player engine at startup,
  // from inside iw4x.dll: enlarged arrays, rewritten operands, size constants, code patches and hooks.
  class IW4x32 : public Component
  {
  public:
    IW4x32();

    // True when the running exe was recognised and rewritten; false means the engine is stock 18-player.
    static bool IsPatched();

    // The enlarged copy of one of the engine arrays by name (svs_clients, level_bgs, ...), null if not patched.
    static void* GetArray(const char* name);

    // Where the UI player name / clientNum arrays live now (inside the engine's sharedUiInfo when stock).
    static char (*PlayerNames())[32];
    static int* PlayerClientNums();

    // IW4x-32: the first GSC script-variable id that is a child (field, array entry, local) rather than a
    // parent object. The stock engine says 0x9002; the grown script-variable pool moves it. Anything that
    // tells a script object id from a child id has to read it here rather than hard-code the engine's value.
    static unsigned int PoolChild0Base();

    // IW4x-32: one server frame into the frame-time histogram that iw4x32_framestats reports (Dedicated's
    // Com_ClampMsec hook sees every frame of a dedicated server).
    static void RecordFrame(int msec);

    // IW4x-32: the script arena (the 65,536 x 12-byte units MT_AllocIndex hands out) measured right now: units
    // in use, the peak since startup, the longest run of fully-free words (32 units each) and the shortest such
    // run seen. A report that ends a match has to say whether the arena was empty when it did.
    static void ScriptArena(unsigned int& used, unsigned int& peak, unsigned int& run, unsigned int& worstRun);

    // IW4x-32: the Vulkan resource layer of the native renderer (VulkanResources.cpp) attached to the
    // device the native path made, or let go of before that device is destroyed. Attaching is what
    // initializes the layer - there is no device before VulkanDevice::CreateVulkanDevice made one, and
    // the Device handed in is the proof that there is one now. Attaching also turns the asset router
    // (VulkanAssetLoader.cpp) on, which is what makes r_backend vulkan mean anything.
    static bool AttachVulkanDevice(const VulkanDevice::Device& device, const char** error);
    static void DetachVulkanDevice();

    // IW4x-32: the renderer backend this process was told to use - the r_backend cvar, "d3d9" (the
    // default, the path the game has always run on) or "vulkan" (the native renderer's path). The cvar
    // is registered here because it is the switch the whole renderer epic is selected with; who draws
    // what is asked of this, never read out of a cvar by the layers themselves.
    static int RendererBackend();       // RENDERER_BACKEND_D3D9 or RENDERER_BACKEND_VULKAN
    static const char* RendererBackendName();

    // The two r_backend values, in the order the cvar's enum lists them.
    static constexpr int RENDERER_BACKEND_D3D9 = 0;
    static constexpr int RENDERER_BACKEND_VULKAN = 1;

  private:
    static void PatchEngine();
  };
}
