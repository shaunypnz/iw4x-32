#pragma once

namespace Components
{
  // IW4x-32: GSC builtins that run the Bot Warfare hot paths (target acquisition and route finding) as native
  // code on the game thread. Pure query: they read engine state and a native copy of the waypoint graph, they
  // never write script state. Everything is behind the iw4x32_native_bots dvar - with 0 nothing changes.
  class IW4x32Bots : public Component
  {
  public:
    IW4x32Bots();

    // The iw4x32_native_bots dvar (default 0). GSC reads it to pick the path.
    static bool Enabled();

  private:
    static void RegisterDvars();
    static void AddScriptFunctions();
  };
}
