#pragma once

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

    // IW4x-32: one server frame into the frame-time histogram that iw4x32_framestats reports (Dedicated's
    // Com_ClampMsec hook sees every frame of a dedicated server).
    static void RecordFrame(int msec);

  private:
    static void PatchEngine();
  };
}
