// IW4x-32: what the video options screens say about the renderer that actually initialized.
//
// The player reads one read-only line - "Renderer: DX9 -> Vulkan (DXVK)" and its few alternatives - on
// the front end's Options -> Video, its advanced page, and the pause menu's equivalent. The answer comes
// from what the renderer itself proves: the device the engine is holding, what that device's own adapter
// string says, and what our native loader loaded behind d3d9.dll. The OS, the GPU vendor, the files on
// disk and every cvar are never evidence - the rules live in iw4x32/reference/renderer_status.json and
// are generated into RendererStatusTables.hpp.

#include "RendererStatus.hpp"
#include "Command.hpp"
#include "Dedicated.hpp"
#include "Dvar.hpp"
#include "Events.hpp"
#include "Logger.hpp"
#include "Renderer.hpp"
#include "Scheduler.hpp"

#include <Utils/IO.hpp>
#include <Utils/String.hpp>

#include <mutex>
#include <string>
#include <vector>

namespace Components
{
  Dvar::Var RendererStatus::ShowLine;

  namespace
  {
    // Every line this component says is said on the main thread. The console prints a message that comes
    // from another thread by queueing it for Logger::Frame, which runs on the SERVER pipeline - and a
    // plain client does not run a server, so that path is not dependable for what a run has to read.
    // Evidence: the same client printed the menu lists it said on the main thread and never printed the
    // status it said from the renderer thread (box run, 2026-11-06, in both the Wine and the native run).
    // Say queues the finished words; FlushSaid hands them to the engine's own console print, which takes
    // the line as it is - no format string, so a menu name can never be read as one.
    std::mutex g_sayMutex;
    std::vector<std::string> g_sayQueue;

    void Say(std::string line)
    {
      std::lock_guard guard(g_sayMutex);

      if (g_sayQueue.size() < 64u) // a client that never flushes must not grow without end
        g_sayQueue.push_back(std::move(line));
    }

    void FlushSaid()
    {
      auto lines = std::vector<std::string>();

      {
        std::lock_guard guard(g_sayMutex);
        lines.swap(g_sayQueue);
      }

      for (const auto& line : lines)
        Game::Com_PrintMessage(Game::CON_CHANNEL_DONT_FILTER, line.data(), 0);
    }

    // What the renderer thread last proved, published for the screens, the console line and the main
    // thread. Only the renderer thread asks the device anything.
    unsigned int g_liveEvidence = 0u;

    // The last answer printed: the status is said out loud when it changes, and at every renderer start.
    unsigned int g_saidEvidence = 0u;
    bool g_saidOnce = false;

    // Renderer starts this client has run: the first one plus every vid_restart, including the one the
    // engine asks for itself when Present says the device is gone. The engine re-creates the device there,
    // so that - not a map change - is the moment the screens have to re-read what draws.
    unsigned int g_starts = 0u;
    bool g_startHappened = false; // raised at a re-creation, spent on the renderer thread
    bool g_restartSaid = false;   // raised with it and spent by the main thread, which says it out loud

    // What the device the renderer is holding called itself, and whether the renderer start that
    // should have produced one ended without it (a failed start, or a vid_restart still in flight).
    IDirect3DDevice9* g_described = nullptr;
    bool g_deviceDxvk = false;
    bool g_deviceWine3d = false;
    bool g_startFailed = false;

    // What our loader answered. The loader never changes during a run, but the question is only worth
    // asking once the engine has a device: an answer without a device proves a loader, not a renderer.
    unsigned int g_loaderEvidence = 0u;
    bool g_loaderAsked = false;
    char g_loaderDxvk[RS_QUERY_DXVK_CHARS] = "";

    // The screen the line went over last (its own name pointer) and the font it was drawn in; both are
    // kept so a screen that stays open says its inventory once. The font name is held by value: it is
    // rebuilt from the screen's font every frame, so a pointer compare would re-register it forever.
    const char* g_drawnOn = nullptr;
    Game::Font_s* g_font = nullptr;
    std::string g_fontName;

    // Frames the line actually went over a video options screen, and the open-menu stack as it was last
    // seen - a run reads both to show the player really stood on the screen (an "open" line that never
    // changes means the navigation never reached the game).
    unsigned int g_drawnFrames = 0u;
    std::string g_openSeen;
    unsigned int g_openFrames = 0u; // frames spent standing on a video screen, for the periodic count line

    // Whether the client stands in a match, as the last reporting pass saw it. The game loads its menus
    // per UI context and a level change moves some of them, so the screens list is said again when the
    // client walks in or out of a match: a run that has to open the pause menu's video page needs to know
    // what this client really holds while it is in one, not what its front end held.
    bool g_inMatch = false;

    // The line where it was last drawn, in screen pixels: the frame capture looks in this band for the
    // line's pixels, so the picture it measures and the text the player read cannot disagree.
    float g_lineX = 0.0f, g_lineY = 0.0f, g_lineW = 0.0f, g_lineH = 0.0f;

    // A frame asked for with iw4x32_rendererShot, taken off the device on the next renderer frame. One at
    // a time, and nothing happens at all until someone asks. The request rides a dvar, not a console
    // command: a "set" line of a config demonstrably reaches this component's dvars, while a command this
    // component added came back as "Unknown command" in a client that had loaded it (2026-11-06 box run),
    // and a test may not have to wonder which half of the client it is standing in.
    Dvar::Var ShotTag;  // names the file the frame goes into
    Dvar::Var ShotReq;  // bumped once per frame the run wants
    int g_shotSeen = 0;
    bool g_shotWanted = false;
    std::string g_shotName = "renderer_status";
    unsigned int g_shots = 0u;      // frames actually taken - the number in the "frame N" line
    unsigned int g_shotDraws = 0u;  // the drawn count the last picture stands for (was the line on it?)

    // The run's console, read back in: iw4x32_rendererBridge <ms> makes the client execute the commands
    // a test wrote into userraw/iw4x32_renderer_cmd.txt, one per line, and clear the file. Without it a
    // test can only hand the client a config at start-up, and cannot open the pause menu's screens after
    // it joined a match - the half of the feature it is not allowed to skip. Off by default, not saved,
    // and every line it takes is echoed to the console, so it leaves evidence of what it ran.
    Dvar::Var Bridge;
    Dvar::Var BridgeFile;
    unsigned long long g_bridgeNext = 0ull; // Sys_Milliseconds() of the next look

    // Case-insensitive whole-word test: "DXVK Device" names DXVK, "DXVKNOT" does not.
    bool NamesWord(const char* text, const char* word)
    {
      if (!text || !word || !*word)
        return false;

      const auto length = std::strlen(word);

      for (const auto* at = text; *at; ++at)
      {
        if (_strnicmp(at, word, static_cast<int>(length)) != 0)
          continue;

        const auto before = at == text ? ' ' : at[-1];
        const auto after = at[length];

        if (!isalnum(static_cast<unsigned char>(before)) && !isalnum(static_cast<unsigned char>(after)))
          return true;
      }

      return false;
    }

    // What the D3D9 implementation behind this device calls itself. Only its own words count: DXVK and
    // wined3d name themselves here, and nothing names itself on a plain Windows runtime - which is the
    // honest answer of "Direct3D 9", not a guess about what is installed.
    void DescribeDevice(IDirect3DDevice9* device)
    {
      if (!device || device == g_described)
        return;

      g_described = device;
      g_deviceDxvk = false;
      g_deviceWine3d = false;

      IDirect3D9* direct3D = nullptr;

      if (FAILED(device->GetDirect3D(&direct3D)) || !direct3D)
        return;

      D3DADAPTER_IDENTIFIER9 identifier{};

      if (SUCCEEDED(direct3D->GetAdapterIdentifier(D3DADAPTER_DEFAULT, 0, &identifier)))
      {
        g_deviceDxvk = NamesWord(identifier.Description, "DXVK") || NamesWord(identifier.Driver, "DXVK");
        // wined3d signs the adapter record it hands out; the box's Wine 10 client does not say so in the
        // description, so the driver field counts as well - whole words only, so nothing that merely
        // mentions wine can invent it
        g_deviceWine3d = NamesWord(identifier.Description, "wined3d") || NamesWord(identifier.Driver, "wined3d");
      }

      direct3D->Release();
    }

    // Forget what the old device proved and what was registered on it. A vid_restart throws the device
    // out and brings another one up - possibly through another backend - and takes the old one's fonts
    // with it: this runs at the moment a device that is not the last-described one is seen, which is what
    // keeps the screens naming the NEW renderer and keeps the draw call off a freed font.
    void ForgetDevice()
    {
      g_described = nullptr;
      g_deviceDxvk = false;
      g_deviceWine3d = false;
      g_font = nullptr;
      g_fontName.clear();
      g_drawnOn = nullptr; // the screens are re-inventoried against the new renderer, not remembered
      g_lineX = g_lineY = g_lineW = g_lineH = 0.0f;
    }

    // The word in front of the value. It is the plain English word the owner asked for and nothing else:
    // asking the localization system for MPUI_RENDERER from the render pipeline looks up an asset this
    // build does not have, and that wait cost a client 7.8 s of frozen start-up on 2026-11-06.
    const char* ScreenWord()
    {
      return "Renderer";
    }

    // A label is the player's word, so it carries no padding. The json is written by hand, and one
    // trailing space or newline in it would go out to the screen, into the console line, and into the
    // run that compares those words against the table - every one of those comparisons is exact, so a
    // hidden byte reads as a label the table may never show (box run, 2026-11-06).
    std::string Trim(const char* text)
    {
      auto value = std::string(text ? text : "");

      while (!value.empty() && isspace(static_cast<unsigned char>(value.back())))
        value.pop_back();

      while (!value.empty() && isspace(static_cast<unsigned char>(value.front())))
        value.erase(value.begin());

      return value;
    }

    // The table's words for a backend - the label alone, without the word in front of it, which is what
    // the machine line quotes so a run can match it against RS_LABELS one-for-one.
    std::string LabelFor(const RendererBackend backend)
    {
      for (const auto& entry : RS_LABELS)
        if (entry.backend == backend)
          return Trim(entry.label);

      return std::string();
    }

    // Case-insensitive, for a name that came out of a menu file rather than out of this file.
    bool Holds(const char* text, const char* needle)
    {
      if (!text || !needle)
        return false;

      for (const auto* at = text; *at; ++at)
      {
        if (_strnicmp(at, needle, static_cast<int>(std::strlen(needle))) == 0)
          return true;
      }

      return false;
    }

    // A screen is one of the video options screens when its own name says so: the front end's
    // Options -> Video (videoOptions), its advanced page and the pause menu's equivalent all do. Their
    // names come from the game's menu files, so they are read off the loaded menus rather than
    // hard-coded here; a run prints every name that matched, per context (ListScreens).
    bool IsVideoScreen(const char* name)
    {
      return Holds(name, "video") || Holds(name, "option");
    }

    // The name of the topmost open menu in a context, "-" when none is open.
    const char* TopMenuName(const Game::UiContext* context)
    {
      if (!context || context->openMenuCount <= 0 || context->openMenuCount > 16)
        return "-";

      const auto* menu = context->menuStack[context->openMenuCount - 1];

      return menu && menu->window.name ? menu->window.name : "-";
    }

    // The topmost open menu that is a video options screen: the front end keeps its menus in
    // uiContext, the pause menu's live in the ingame context.
    const Game::menuDef_t* TopVideoScreen(Game::UiContext* context)
    {
      if (!context || context->openMenuCount <= 0)
        return nullptr;

      const auto count = context->openMenuCount < 16 ? context->openMenuCount : 16;

      for (auto i = count - 1; i >= 0; --i)
      {
        const auto* menu = context->menuStack[i];

        if (menu && IsVideoScreen(menu->window.name))
          return menu;
      }

      return nullptr;
    }

    // Whether the client is in a match: the owner asked for the line on the front end's Options -> Video
    // AND on the pause menu's equivalent, and a run has to be able to tell the two apart. This is what the
    // game itself asks before it lets a menu be a pause menu's (see Menus.cpp's openmenu), so it is the
    // answer of the running game - not of a menu name, which says nothing about where the player is.
    bool InMatch()
    {
      return Game::cl_ingame && *Game::cl_ingame && (*Game::cl_ingame)->current.enabled;
    }

    // A safe name for a frame file: it is written under the game folder, so a name from the console may
    // not carry a path.
    std::string ShotName()
    {
      auto name = g_shotName;
      auto kept = std::string();

      for (const auto c : name)
        if (isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-')
          kept += c;

      if (kept.empty())
        kept = "renderer_status";

      return "userraw/iw4x32_" + kept + ".ppm";
    }
  }

  unsigned int RendererStatus::Prove()
  {
    unsigned int evidence = 0u;

    if (const auto device = Game::dx_ptr ? *Game::dx_ptr : nullptr)
    {
      if (device != g_described) // not the device last described: a first start, a vid_restart, or the
        ForgetDevice();          // engine falling back to another backend

      evidence |= RS_EV_DEVICE;
      DescribeDevice(device);

      if (g_deviceDxvk)
        evidence |= RS_EV_DXVK;

      if (g_deviceWine3d)
        evidence |= RS_EV_WINED3D;

      // A device answered: whatever renderer start failed before this one is over, and the screens
      // show what this device is drawn through instead of the old device's label.
      g_startFailed = false;
    }
    else if (g_described)
    {
      // The renderer had a device and now has none: the engine asked for a renderer start (vid_restart,
      // a lost device) and it has not produced one. Reporting the label of the device that went away
      // would be a lie, and so would naming a backend that never came up.
      g_startFailed = true;
    }

    if (g_startFailed)
      evidence |= RS_EV_D3D9_FAILED;

    // Wine exports wine_get_version from ntdll; no other runtime does.
    if (GetProcAddress(GetModuleHandleA("ntdll.dll"), "wine_get_version") != nullptr)
      evidence |= RS_EV_WINE;

    // An OpenGL client this process actually mapped - not one that is merely installed: GetModuleHandle
    // only answers for a loaded module. Under Wine that is what wined3d draws through, and it is what
    // lets the screens say "Wine/OpenGL" instead of stopping at the honest "Wine". It says nothing on its
    // own: only the rule that also proved wined3d uses it.
    if (GetModuleHandleA("opengl32.dll") != nullptr)
      evidence |= RS_EV_GL_LOADED;

    // Our loader answers this export and nothing else does, so an answer is what says this process runs
    // on it - and it carries what the loader loaded as DXVK. It is asked only once the engine holds a
    // device: an engine that never got one has no renderer to name, whatever sits behind d3d9.dll. The
    // loader's device and frame counts come back with it for the console line; they are not evidence.
    if (!g_loaderAsked && evidence & RS_EV_DEVICE)
    {
      if (const auto query = reinterpret_cast<unsigned int(WINAPI*)(unsigned int, unsigned int, void*)>(
            GetProcAddress(GetModuleHandleA("d3d9.dll"), RS_QUERY_NAME)))
      {
        RendererBackendReport report{};

        report.size = sizeof report;

        if (query(report.size, RS_QUERY_MAGIC, &report) &&
            report.evidence & RS_EV_NATIVE_LOADER)
        {
          g_loaderEvidence = report.evidence & (RS_EV_NATIVE_LOADER | RS_EV_LOADER_DXVK_NATIVE);
          strncpy_s(g_loaderDxvk, report.dxvk, _TRUNCATE);
        }
      }

      g_loaderAsked = true; // the loader never changes: ask once, not per frame (and never again if it answered nothing)
    }

    return evidence | g_loaderEvidence;
  }

  RendererBackend RendererStatus::Which(const unsigned int evidence)
  {
    for (const auto& rule : RS_RULES)
    {
      if ((evidence & rule.evidence) == rule.evidence && !(evidence & rule.forbidden))
        return rule.backend;
    }

    return RendererBackend::Unknown;
  }

  const char* RendererStatus::Label()
  {
    static std::string held; // the caller draws with it, so the string has to outlive the call

    held = StatusLineFor(g_liveEvidence);

    return held.data();
  }

  std::string RendererStatus::StatusLine()
  {
    return StatusLineFor(Prove());
  }

  std::string RendererStatus::StatusLineFor(const unsigned int evidence)
  {
    return std::string(ScreenWord()) + ": " + LabelFor(Which(evidence));
  }

  const Game::menuDef_t* RendererStatus::VideoScreen()
  {
    if (const auto* screen = TopVideoScreen(Game::cgDC))
      return screen;

    return TopVideoScreen(Game::uiContext);
  }

  void RendererStatus::Report(const unsigned int evidence, const char* reason)
  {
    if (g_saidOnce && evidence == g_saidEvidence && !reason)
      return;

    g_saidOnce = true;
    g_saidEvidence = evidence;

    // The line the player reads, word for word, in the console too: a run that cannot see the screen
    // reads the client's own words, and these are the words the screen carries. StatusLine already starts
    // with the word of the screen's line, so the print adds nothing in front of it - "Renderer: Renderer:" 
    // is not what the player is shown.
    Say(StatusLine() + "\n");
    Machine(reason);
  }

  // The same answer with the numbers behind it, for a run that has to prove what the player is shown:
  // the bits it rested on, whether a video screen is up, how many frames the line was really drawn over
  // one (a label nobody could see would say the same words - the drawn count is what says it was), and
  // how many renderer starts it has been re-read at.
  void RendererStatus::Machine(const char* reason)
  {
    const auto backend = Which(g_saidEvidence);
    const auto label = LabelFor(backend); // the table's word alone: a run compares it, byte for byte,
                                          // against RS_LABELS, so it may not carry the player's prefix

    Say(Utils::String::VA("renderer status: backend=%d label=\"%s\" evidence=0x%x devices=%d screens=%d drawn=%d "
                          "starts=%u reason=%s loader=%s\n",
                          static_cast<int>(backend), label.c_str(),
                          g_saidEvidence, g_described ? 1 : 0, VideoScreen() ? 1 : 0, g_drawnFrames, g_starts,
                          reason && *reason ? reason : "-", g_loaderDxvk[0] ? g_loaderDxvk : "-"));
  }

  // Every loaded menu of both UI contexts, once per UI init, with the context named: a run opens the
  // screens this build really has - the front end's and the ingame one's - instead of guessing at the
  // contents of the menu files. Lines are kept short because the console splits long ones anywhere.
  void RendererStatus::ListScreens()
  {
    for (const auto context : {Game::uiContext, Game::cgDC})
    {
      if (!context)
        continue;

      const auto count = context->menuCount < 0 ? 0 : (context->menuCount < 640 ? context->menuCount : 640);
      auto listed = std::string();
      auto all = 0;

      for (auto i = 0; i < count; ++i)
      {
        const auto* menu = context->Menus[i];
        const auto* name = menu ? menu->window.name : nullptr;

        if (!name)
          continue;

        ++all;

        // the screens a player can set video options on, plus the pause menu's own screens, which are
        // named by what they are rather than by the front end's prefix
        if (!IsVideoScreen(name))
          continue;

        listed = listed + " " + name; // one line per chunk: the console splits long ones anywhere

        if (listed.size() > 480u)
        {
          Say(Utils::String::VA("renderer status screens %s:%s\n",
                                context == Game::uiContext ? "front_end" : "ingame", listed.c_str()));
          listed.clear();
        }
      }

      Say(Utils::String::VA("renderer status screens %s:%s (%d/%d menus)\n",
                            context == Game::uiContext ? "front_end" : "ingame",
                            listed.empty() ? " none" : listed.c_str(), all, count));
    }
  }

  // The menu the player is standing on in each context, and what was stood on before: the line only
  // means anything over an open Options -> Video screen, and a run drives that screen open from the
  // console (openmenu / vid_restart, no real input involved). Saying the stack only when it changed keeps
  // the console readable and still proves the navigation reached the game.
  void RendererStatus::OpenStack()
  {
    std::string seen = Utils::String::VA("%s %s %s", TopMenuName(Game::uiContext), TopMenuName(Game::cgDC),
                                         InMatch() ? "in_match" : "front_end");

    if (seen == g_openSeen)
      return;

    g_openSeen = seen;
    Say(Utils::String::VA("renderer status open:%s\n", seen.c_str()));
  }

  // The screen the player actually opened, and the controls it still has: the status line goes over
  // this menu without adding to it, so a run can read the status and the list of video controls out of
  // the same console line. Item names are the game's own, from its menu files.
  void RendererStatus::DumpScreen(const Game::menuDef_t* screen)
  {
    if (!screen)
      return;

    const auto* items = screen->items;
    const auto count = screen->itemCount < 0 ? 0 : (screen->itemCount < 512 ? screen->itemCount : 512);
    auto controls = std::string();
    auto buttons = 0;

    for (auto i = 0; i < count; ++i)
    {
      const auto* item = items[i];

      if (!item)
        continue;

      // A control the player can move to or set: anything but a line of text. The status line is not
      // one of these - it is drawn over the screen, so it is read-only by construction.
      if (item->type != Game::ITEM_TYPE_TEXT)
        ++buttons;

      if (item->window.name)
        controls = controls + " " + item->window.name;
    }

    // Which screen it is - the front end's Options -> Video or the ingame (pause menu) equivalent: the
    // owner asked for both, and a run that only ever reached one has to say so. The context a menu is
    // loaded in does not say that (this game draws its pause menu screens out of the front end's context),
    // so the game's own in-match flag decides.
    const auto ingame = InMatch();

    Say(Utils::String::VA("renderer status menu: name=%s items=%d controls=%d shown=\"%s\" context=%s\n",
                          screen->window.name ? screen->window.name : "(unnamed)", count, buttons, Label(),
                          ingame ? "ingame" : "front_end"));
    Say(Utils::String::VA("renderer status controls:%s\n", controls.c_str()));
  }

  // The frame the device is about to present. The box's display cannot give it to a test - a GL window
  // there has no readable back buffer, which is why main_menu.sh measures the native client's frame
  // inside the loader - so the picture of what the player reads is taken here, off the same device.
  // It measures the band the line was drawn in (that is the whole point of the picture) and writes the
  // frame as a PPM the run keeps as a private artefact.
  //
  // Three ways out of a D3D9 device, tried in order, because which one a runtime allows is the runtime's
  // business: the back buffer locked straight out (what a loader that serves d3d9 out of memory offers),
  // the front buffer copied into system memory (the frame that went to the screen), and the render target
  // copied into system memory (what a driver-backed device offers). The method that worked is printed
  // with the frame, next to whether the line was really on screen when the picture was asked for: one
  // bare "read back refused" named the single call that run had tried and left the next round guessing
  // what else there was (box run, 2026-11-06).
  void RendererStatus::Shot(IDirect3DDevice9* device)
  {
    const auto file = ShotName();
    const auto wanted = g_shots + 1;

    IDirect3DSurface9* backBuffer = nullptr;
    IDirect3DSurface9* systemMemory = nullptr;
    IDirect3DSurface9* readable = nullptr; // whichever surface the pixels came out of
    D3DSURFACE_DESC desc{};
    D3DLOCKED_RECT locked{};

    auto method = "none";
    auto width = 0, height = 0, step = 1, maxLuma = 0, bandMin = 255, bandMax = 0;
    unsigned long long inkSum = 0ull;
    unsigned int nonBlack = 0u, sampled = 0u, bandInk = 0u, bandSampled = 0u;

    auto why = "-";

    if (!device)
      why = "no device to read back";
    else if (FAILED(device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &backBuffer)) || !backBuffer)
      why = "no back buffer";
    else if (FAILED(backBuffer->GetDesc(&desc)) || desc.Width == 0u || desc.Height == 0u)
      why = "no back buffer size";
    else if (SUCCEEDED(backBuffer->LockRect(&locked, nullptr, D3DLOCK_READONLY)))
    {
      readable = backBuffer;
      method = "back buffer lock";
    }
    else if (SUCCEEDED(device->CreateOffscreenPlainSurface(desc.Width, desc.Height, D3DFMT_A8R8G8B8,
                                                           D3DPOOL_SYSTEMMEM, &systemMemory, nullptr)) &&
             systemMemory)
    {
      auto copied = false;

      // A plain system-memory surface is the one kind of surface the CPU may read; a swap-chain surface
      // is not, so the frame has to be copied into it first - the front buffer (what the screen got)
      // before the render target (what the device drew).
      if (SUCCEEDED(device->GetFrontBufferData(0, systemMemory)))
      {
        method = "front buffer copy";
        copied = true;
      }
      else if (SUCCEEDED(device->GetRenderTargetData(backBuffer, systemMemory)))
      {
        method = "render target copy";
        copied = true;
      }

      if (copied && SUCCEEDED(systemMemory->LockRect(&locked, nullptr, 0))) // no D3DLOCK_ flag needed here
        readable = systemMemory;
      else
        why = copied ? "no read back" : "no copy of the frame was allowed";
    }
    else
      why = "no system memory copy";

    if (!readable && *why == '-')
      why = "nothing read back";

    // The line the picture is supposed to prove: the draw counts frames it put the line over an open
    // video screen, so a picture that stands for drawing after the last picture really does carry it -
    // and the band to look in is the band that draw used. Nothing here asks the UI what is open: the
    // screen belongs to the main thread (see Frame), and this runs on the thread that presents.
    const auto onScreen = g_drawnFrames > g_shotDraws;
    auto bandTop = 0, bandBottom = 0, bandLeft = 0, bandRight = 0;

    if (readable)
    {
      width = static_cast<int>(desc.Width);
      height = static_cast<int>(desc.Height);

      // A frame of the screen: at most ~256 across, so the picture a run keeps is small enough to read.
      step = width / 256;
      if (step < 1)
        step = 1;

      if (onScreen)
      {
        bandTop = static_cast<int>(g_lineY - g_lineH);
        bandBottom = static_cast<int>(g_lineY + g_lineH / 2.0f);
        bandLeft = static_cast<int>(g_lineX);
        bandRight = static_cast<int>(g_lineX + g_lineW);

        if (bandBottom < bandTop || bandRight < bandLeft)
          bandTop = bandBottom = bandLeft = bandRight = 0; // a band of nothing is measured as nothing
      }

      auto picture = std::string();
      const auto rowWidth = (width + step - 1) / step;

      picture.reserve(static_cast<std::size_t>(rowWidth) * static_cast<std::size_t>((height + step - 1) / step) * 3u +
                      32u);
      picture = Utils::String::VA("P6\n%d %d\n255\n", rowWidth, (height + step - 1) / step);

      for (auto y = 0; y < height; y += step)
      {
        const auto* row = static_cast<const unsigned char*>(locked.pBits) + static_cast<std::size_t>(y) * locked.Pitch;

        for (auto x = 0; x < width; x += step)
        {
          const auto* pixel = row + static_cast<std::size_t>(x) * 4u; // A8R8G8B8, little endian
          const auto red = pixel[2], green = pixel[1], blue = pixel[0];
          const auto luma = (red > green ? (red > blue ? red : blue) : (green > blue ? green : blue));

          picture.push_back(static_cast<char>(luma));
          picture.push_back(static_cast<char>(luma));
          picture.push_back(static_cast<char>(luma));

          ++sampled;
          if (luma > maxLuma)
            maxLuma = luma;
          if (luma > 24u)
            ++nonBlack;

          if (onScreen && y >= bandTop && y <= bandBottom && x >= bandLeft && x <= bandRight)
          {
            ++bandSampled;
            inkSum += luma;
            if (luma > bandMax)
              bandMax = luma;
            if (luma < bandMin)
              bandMin = luma;
          }
        }
      }

      // The line is white on the screen's own background: it is there when the band holds both a dark
      // background and light pixels, and how many light pixels it holds says how much of the line the
      // frame really carries.
      if (bandSampled)
      {
        const auto bandMean = static_cast<int>(inkSum / bandSampled);

        for (auto y = bandTop; y <= bandBottom && y < height; y += step)
        {
          const auto* row = static_cast<const unsigned char*>(locked.pBits) + static_cast<std::size_t>(y) * locked.Pitch;

          for (auto x = bandLeft; x <= bandRight && x < width; x += step)
          {
            const auto* pixel = row + static_cast<std::size_t>(x) * 4u;
            const auto luma = (pixel[2] > pixel[1] ? (pixel[2] > pixel[0] ? pixel[2] : pixel[0])
                                                   : (pixel[1] > pixel[0] ? pixel[1] : pixel[0]));

            if (luma > bandMean + 32)
              ++bandInk;
          }
        }
      }

      readable->UnlockRect();
      readable = nullptr; // unlocked: the release below is all that is left of it

      if (Utils::IO::WriteFile(file, picture))
      {
        why = "-";
        g_shots = wanted;
        g_shotDraws = g_drawnFrames; // this picture stands for the drawing up to here
      }
      else
        why = "write refused";
    }

    if (systemMemory)
      systemMemory->Release();
    if (backBuffer)
      backBuffer->Release();

    Say(Utils::String::VA("renderer status frame %u: file=%s screen=%dx%d band=%dx%d maxluma=%d nonblack=%u/%u "
                          "bandink=%u/%u bandluma=%d-%d written=%d method=%s line=%d\n",
                          wanted, file.c_str(), width, height, bandRight - bandLeft, bandBottom - bandTop,
                          maxLuma, nonBlack, sampled, bandInk, bandSampled, bandSampled ? bandMin : 0, bandMax,
                          *why == '-' ? 1 : 0, method, onScreen ? 1 : 0));

    if (*why != '-')
      Say(Utils::String::VA("renderer status frame %u: %s\n", wanted, why));
  }

  // Everything this component says, said here: what the renderer thread proved (g_liveEvidence) and what
  // the game's UI says the player is standing on, both read on the main thread, whose console lines reach
  // the log of a client that runs no server (see Say / FlushSaid above).
  void RendererStatus::Frame()
  {
    auto reason = static_cast<const char*>(nullptr);

    if (g_restartSaid)
    {
      g_restartSaid = false;
      reason = "renderer restart"; // said again at every renderer start, even when the words repeat
    }

    Report(g_liveEvidence, reason);

    // A video options screen just came up: say what it is and what it still holds, once. While the player
    // stays on one the count line comes back every couple of seconds, and when the screen closes the last
    // one says how many frames really carried the line.
    const auto* screen = VideoScreen();

    if (screen && screen->window.name != g_drawnOn)
    {
      g_drawnOn = screen->window.name;
      g_openFrames = 0u;
      DumpScreen(screen);
    }
    else if (!screen && g_drawnOn)
    {
      g_drawnOn = nullptr;
      Machine(nullptr);
    }
    else if (screen && ++g_openFrames % 10u == 0u) // this pass runs five times a second
      Machine("screen open");

    if (const auto inMatch = InMatch(); inMatch != g_inMatch)
    {
      g_inMatch = inMatch;
      Say(Utils::String::VA("renderer status match: %d\n", inMatch ? 1 : 0));
      ListScreens(); // which screens exist NOW, per context - the match's are not the front end's
    }

    OpenStack();
  }

  // The run's requests, read back in: the frame it wants (a dvar bumped, see above) and the commands it
  // wrote into its own file (see Bridge). This runs on the main thread, where commands belong; the frame
  // itself is taken on the renderer thread, which is the one that drew the line.
  void BridgePoll();

  void Poll()
  {
    if (const auto want = ShotReq.get<int>(); want != g_shotSeen)
    {
      g_shotName = ShotTag.get<std::string>();
      g_shotWanted = true;
      g_shotSeen = want == 0 ? 1 : 0;
      ShotReq.set(g_shotSeen); // spend the request: the dvar goes back to the other value, so the run's
                               // next "set ... 1" reads as a change again and gets a frame of its own
                               // (two screens asked for in one config used to yield one frame)
    }

    BridgePoll();
    RendererStatus::Frame(); // the status and the screens, said on the main thread
    FlushSaid();
  }

  // The run's console, read back in (see Bridge). Lines are taken from the file, echoed to the client's
  // console so the run can see what the client agreed to run, and queued into the client's own command
  // buffer, which is where the game's own config exec puts them - so a screen opens exactly as if the
  // player had typed it. The file is cleared afterwards, so nothing runs twice.
  void BridgePoll()
  {
    const auto every = Bridge.get<int>();

    if (every <= 0)
      return;

    const auto now = static_cast<unsigned long long>(Game::Sys_Milliseconds());

    if (now < g_bridgeNext)
      return;

    g_bridgeNext = now + static_cast<unsigned long long>(every);

    const auto file = BridgeFile.get<std::string>();

    if (file.empty())
      return;

    const auto text = Utils::IO::ReadFile(file);

    if (text.empty())
      return;

    auto taken = 0;
    auto line = std::string();

    for (const auto character : text)
    {
      if (character == '\r')
        continue;

      if (character != '\n')
      {
        if (line.size() < 256u)
          line += character;
        continue;
      }

      if (!line.empty())
      {
        Say(Utils::String::VA("renderer status cmd: %s\n", line.c_str()));
        Command::Execute(line, false); // the client's own command buffer, as a config exec would
        ++taken;
      }

      line.clear();

      if (taken >= 16) // a file that never got cleared must not run the client in circles
        break;
    }

    if (taken)
      Utils::IO::WriteFile(file, "");
  }

  void RendererStatus::Draw()
  {
    if (!ShowLine.get<bool>())
      return;

    const auto* screen = VideoScreen();

    if (!screen)
      return;

    const auto width = Renderer::Width();
    const auto height = Renderer::Height();

    if (width <= 0 || height <= 0)
      return;

    // One line of the screen's own font at this height: the scale follows the video mode, so the line -
    // and the band a test looks in - is one line tall in every mode.
    const auto scale = static_cast<float>(height) / 480.0f;
    const auto line = height / 12;
    const auto top = static_cast<float>(height - line * 3 / 2);

    const auto* fontName = screen->font ? Utils::String::VA("fonts/%s", screen->font) : "fonts/smallFont";

    if (!g_font || g_fontName != fontName)
    {
      g_font = Game::R_RegisterFont(fontName, 0);
      g_fontName = fontName;
    }

    if (!g_font)
      return;

    const auto text = StatusLineFor(g_liveEvidence);
    ++g_drawnFrames; // counted when the line was asked for over an open screen: a run compares it across
                     // a vid_restart to see that the drawing path came back up, not just the label
    const auto textWidth = Game::R_TextWidth(text.data(), static_cast<int>(text.size()), g_font);

    if (textWidth <= 0)
      return;

    const auto left = (static_cast<float>(width) - static_cast<float>(textWidth) * scale) / 2.0f;
    float color[4] = {1.0f, 1.0f, 1.0f, 0.95f};

    Game::R_AddCmdDrawText(text.data(), static_cast<int>(text.size()), g_font, left, top, scale, scale, 0.0f, color,
                           Game::ITEM_TEXTSTYLE_NORMAL);

    g_lineX = left;
    g_lineY = top;
    g_lineW = static_cast<float>(textWidth) * scale;
    g_lineH = static_cast<float>(height) / 20.0f; // the height of a line of this font at this scale
  }

  RendererStatus::RendererStatus()
  {
    if (Dedicated::IsEnabled())
      return;

    Events::OnDvarInit([]
    {
      // Whether the line is drawn. It never changes what the status IS - hiding it does not make a DXVK
      // renderer a Vulkan one - and it is not saved, so it cannot outlive the run it described.
      RendererStatus::ShowLine = Dvar::Register("iw4x32_rendererStatus", true, Game::DVAR_NONE,
                                                "Show which renderer the game initialized on the video options screens");

      // Test hooks, off by default and never saved: how often to read the run's command file (0 = never)
      // and which file. They let a test drive the client's own menus after it joined a match; they do not
      // touch what the renderer status is, and every command they take is printed to the console.
      Bridge = Dvar::Register<int>("iw4x32_rendererBridge", 0, 0, 60000, Game::DVAR_NONE,
                                   "Milliseconds between reads of the test command file (0 = off)");
      BridgeFile = Dvar::Register("iw4x32_rendererBridgeFile", "userraw/iw4x32_renderer_cmd.txt", Game::DVAR_NONE,
                                  "File of client commands a test feeds this client, read and cleared");

      // Ask for the next frame the renderer presents: bump iw4x32_rendererShot once and the frame goes
      // into userraw/iw4x32_<iw4x32_rendererShotTag>.ppm. The picture is taken on the renderer thread,
      // where the line was drawn, so the band it measures is the band that was filled. Neither dvar is
      // saved, and neither says anything about the renderer itself.
      ShotTag = Dvar::Register("iw4x32_rendererShotTag", "renderer_status", Game::DVAR_NONE,
                               "Name of the frame file iw4x32_rendererShot writes");
      ShotReq = Dvar::Register<int>("iw4x32_rendererShot", 0, 0, 1000000, Game::DVAR_NONE,
                                    "Bump to capture the next frame over the video options screens");
    });

    Scheduler::Loop([]
    {
      // The engine re-created its renderer (a vid_restart, or the one the engine asked for after Present
      // said the device is gone): the screens have to say what the NEW device is drawn through, and a
      // run has to see that they did - so the answer is said out loud again at every start, even when it
      // is the same words as the device before it.
      if (g_startHappened)
      {
        g_startHappened = false;
        ForgetDevice();
        g_restartSaid = true; // the main thread says what the NEW device is drawn through
      }

      g_liveEvidence = RendererStatus::Prove(); // the only thread that asks a device anything

      if (g_shotWanted)
      {
        g_shotWanted = false;
        RendererStatus::Shot(Game::dx_ptr ? *Game::dx_ptr : nullptr);
      }

      RendererStatus::Draw(); // the line goes over the screen this thread presents
    }, Scheduler::Pipeline::RENDERER);

    // The run's frame request and command file, on the main thread, where commands belong.
    Scheduler::Loop(Poll, Scheduler::Pipeline::MAIN, std::chrono::milliseconds(200));

    Events::AfterUIInit(RendererStatus::ListScreens);

    // The engine's renderer re-creation: vid_restart, and the restart the fork runs when the device the
    // driver gave up on has to be replaced. Both throw the device out and bring another one up, possibly
    // through another backend. The flag is spent on the renderer thread, which is the one that draws the
    // screens and holds the fonts - taking the old device's font down here would be a freed pointer in
    // the middle of a frame.
    Renderer::OnDeviceRecoveryBegin([]
      {
        ++g_starts;
        g_startHappened = true;
      });

    Renderer::OnDeviceRecoveryEnd([]
      {
        ++g_starts;
        g_startHappened = true;
      });
  }
}
