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

  private:
    static void PatchEngine();
  };
}
