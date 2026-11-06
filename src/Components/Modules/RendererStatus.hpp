#pragma once

#include "RendererStatusTables.hpp"

namespace Components
{
  // IW4x-32: the renderer that actually initialized, shown as read-only text on the video options
  // screens (the front end's Options -> Video, its advanced page, and the pause menu's equivalent)
  // and printed to the console when it changes.
  //
  // The answer comes from what the renderer itself proves - the device it created, what answers
  // d3d9.dll, what our loader loaded behind d3d9.dll - through the rules
  // iw4x32/reference/renderer_status.json generates into RendererStatusTables.hpp. The OS, the GPU
  // vendor and any cvar are never evidence.
  class RendererStatus : public Component
  {
  public:
    RendererStatus();

    // What the screens show: the label of the backend that is drawing right now.
    static const char* Label();

    // The label plus what proved it, for the console and for a test to read.
    static std::string StatusLine();

    // The same words for evidence that was proved a moment ago - the renderer thread publishes what it
    // proved, and the screens, the console line and the main thread all say that, so nothing but the
    // renderer thread ever asks a device what it is.
    static std::string StatusLineFor(unsigned int evidence);

    // The status line over the open video options screen, or nothing when no such screen is open.
    static void Draw();

    // Say what is true right now: the renderer thread's answer, the screen the player stands on and what
    // it still holds, the open-menu stack. This runs on the main thread, which is where the game's UI
    // state lives and the only thread whose console lines reach the log of a client that runs no server.
    static void Frame();

  private:
    static Dvar::Var ShowLine;

    // RS_EV_* bits this process can prove about its renderer at this moment.
    static unsigned int Prove();

    // Which backend a set of bits says is drawing.
    static RendererBackend Which(unsigned int evidence);

    // The video options menu the player is looking at (front end or ingame), NULL when none is open.
    static const Game::menuDef_t* VideoScreen();

    // Say which menu the player stands on in each context, only when that changed.
    static void OpenStack();

    // Say the answer out loud: the line the player reads, and the machine line under it. It repeats when
    // what proved it changed, and at every renderer start (first one, vid_restart, fallback), so the
    // answer on screen always belongs to the renderer that is up now.
    static void Report(unsigned int evidence, const char* reason);

    // The answer with the numbers behind it (evidence bits, open screen, frames drawn, the loader).
    static void Machine(const char* reason);

    // Every loaded menu of each UI context, once per UI init, labelled front end or ingame - so a run
    // opens the screens this build really has instead of guessing at menu-file contents.
    static void ListScreens();

    // The screen the player opened: its own name and the controls it kept, so a run can show the
    // status line went over a real Options -> Video screen and that nothing was taken off it.
    static void DumpScreen(const Game::menuDef_t* screen);

    // The frame the device is about to present, read back out of it (the back buffer locked out, or the
    // front buffer / render target copied into system memory - whichever this runtime allows, printed with
    // the frame), written next to the client's own logs, and measured: the band the status line was drawn
    // in has to carry the line's pixels. Asked for by iw4x32_rendererShot, so it costs nothing until a run
    // or a player asks for it.
    static void Shot(IDirect3DDevice9* device);
  };
}
