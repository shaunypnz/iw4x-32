#include <Components/Modules/Sentry.hpp>
#include <Components/Modules/IW4x32.hpp> // IW4x-32: the script-variable pool this process runs on
#include "ScriptPatches.hpp"
#include "Script.hpp"
#include "ScriptError.hpp"

using namespace Utils::String;

namespace Components::GSC
{
  constexpr auto offset = 511;

  Game::game_hudelem_s* ScriptPatches::HECmd_GetHudElem(Game::scr_entref_t entref)
  {
    if (entref.classnum != 1)
    {
      Game::Scr_ObjectError("not a hud element");
      return nullptr;
    }

    assert(entref.entnum < 1024);
    return &Game::g_hudelems[entref.entnum];
  }

  void ScriptPatches::Scr_TableLookupIStringByRow_Hk()
  {
    if (Game::Scr_GetNumParam() < 3)
    {
      Game::Scr_Error("USAGE: tableLookupIStringByRow( filename, rowNum, returnValueColumnNum )");
      return;
    }

    const auto* fileName = Game::Scr_GetString(0);
    const auto rowNum = Game::Scr_GetInt(1);
    const auto returnValueColumnNum = Game::Scr_GetInt(2);

    const auto* table = Game::DB_FindXAssetHeader(Game::ASSET_TYPE_STRINGTABLE, fileName).stringTable;

    if (!table)
    {
      Game::Scr_ParamError(0, Utils::String::VA("%s does not exist", fileName));
      return;
    }

    const auto* value = Game::StringTable_GetColumnValueForRow(table, rowNum, returnValueColumnNum);
    Game::Scr_AddIString(value);
  }

  // Return the frames of the running thread, innermost first, as the script
  // functions they are in. See ScriptError::DescribeCodePos() for details.
  //
  std::string ScriptPatches::DescribeFrames ()
  {
    const auto& fs (*reinterpret_cast<Game::function_stack_t*> (0x2040CD4));

    std::string r (ScriptError::DescribeCodePos (fs.pos));
    for (int i (Game::scrVmPub->function_count - 1); i > 0; --i)
    {
      r += ", ";
      r += ScriptError::DescribeCodePos (Game::scrVmPub->function_frame_start[i].fs.pos);
    }

    return r;
  }

  // Log and report that the script state is corrupt and end the match.
  //
  void ScriptPatches::ReportCorruptState (const std::string& logger, const std::string& details)
  {
    Logger::PrintError (Game::CON_CHANNEL_ERROR, "{}\n", details);

    if (auto* r = Sentry::Runtime ())
      r->capture (SENTRY_LEVEL_ERROR, logger, details);

    Logger::Error (Game::ERR_DROP,
                   "Script error: the game's script state is corrupt, so "
                   "the match had to end.");
  }

  // Make sure the stack of a thread that is about to wait is sane before the
  // game archives it.
  //
  // When a thread waits, the game copies what its frame has on the stack,
  // that is, from the start of the frame to the top. We've seen the top end
  // up below the start (with Bot Warfare in a private match), at which point
  // the copy runs off the bottom of the stack and crashes. Something corrupts
  // the VM before that and we don't know what yet. So instead of crashing we
  // end the match with an error and offer to report what we know about the
  // stack, which is hopefully enough to find the culprit.
  //
  // Note that we don't try to recover: by now the stack can't be trusted and
  // carrying on would only move the crash somewhere else.
  //
  unsigned int ScriptPatches::VM_ArchiveStack_Hk()
  {
    const auto& fs (*reinterpret_cast<Game::function_stack_t*> (0x2040CD4));

    if (fs.top < fs.startTop)
    {
      // A thread that waits copies its frame into the script arena (MT_AllocIndex, 65,536 units of 12 bytes,
      // free map at 0x1dc0100), and it asks for values * 5 + 11 bytes, which the allocator rounds up to a
      // power-of-two run of 32-unit words. When no such run is free the engine prints
      // "MT_AllocIndex: failed memory allocation of %d bytes for script usage", dumps every script thread, and
      // returns unit 0 - so the frame lands on top of somebody else's block and the VM walks off it. Naming the
      // arena in this report is what separates that cause from a plain corrupt frame; it costs one scan of
      // 2,048 words at a point where the match is over anyway.
      //
      unsigned int mtUsed (0), mtPeak (0), mtRun (0), mtWorst (0);
      IW4x32::ScriptArena (mtUsed, mtPeak, mtRun, mtWorst);

      const auto details (
        std::format ("script stack is corrupt: top is {} values below the "
                     "start of the frame (frames {}: {}; fs_game '{}', script memory "
                     "{}/{} units, peak {}, free run {} words, worst {})",
                     fs.startTop - fs.top,
                     Game::scrVmPub->function_count,
                     DescribeFrames (),
                     (*Game::fs_gameDirVar)->current.string,
                     mtUsed,
                     65536u,
                     mtPeak,
                     mtRun,
                     mtWorst));

      ReportCorruptState ("script_stack", details);
    }

    return Utils::Hook::Call<unsigned int ()> (0x61DB70) ();
  }

  // Report the id passed to RemoveRefToObject() that can't be an object and
  // end the match. See RemoveRefToObject_Stub() for details.
  //
  // We've seen RemoveRefToObject() crash on such an id in a private match
  // without mods. This is most likely the same corruption that
  // VM_ArchiveStack_Hk() detects, only noticed before any thread waits, so we
  // handle it the same way. Note that the caller is what we are after: it is
  // where the bad id comes from (or at least passes through). If a script is
  // running, we also describe its frames, which is where to look next.
  //
  void ScriptPatches::RemoveRefToObject_Bad (unsigned int id, unsigned int caller)
  {
    const auto frames (Game::scrVmPub->function_count > 0
                       ? DescribeFrames ()
                       : std::string ("none"));

    ReportCorruptState (
      "script_object",
      std::format ("script object id {:#x} is out of range (called from "
                   "{:#x}, frames {}: {}; fs_game '{}')",
                   id,
                   caller,
                   Game::scrVmPub->function_count,
                   frames,
                   (*Game::fs_gameDirVar)->current.string));
  }

  // Make sure the id passed to RemoveRefToObject() is an object, that is, it
  // is in the parent part of the variable list (child ids start at the pool's
  // first child base). Otherwise the function decrements a reference count
  // somewhere in memory and, if we are lucky, crashes.
  //
  // IW4x-32: that base is one of the script-variable pool geometry constants
  // our component can move (0x9002 for the stock pool, 0xe001 for the grown
  // one), so it comes from IW4x32 rather than the literal upstream compares
  // against. On the stock pool the two are the same value.
  //
  bool ScriptPatches::RemoveRefToObject_IsChild (unsigned int id)
  {
    return id >= IW4x32::PoolChild0Base ();
  }

  __declspec(naked) void ScriptPatches::RemoveRefToObject_Stub ()
  {
    __asm
    {
      push dword ptr [esp + 0x4] // the id
      call RemoveRefToObject_IsChild
      add esp, 0x4

      test al, al
      jnz bad

      // The code our jump replaces.
      //
      push esi
      push edi
      mov edi, [esp + 0xC]

      push 0x437196
      ret

    bad:
      push dword ptr [esp + 0x4] // the id
      push dword ptr [esp + 0x4] // the caller, which is where the bad id came from
      call RemoveRefToObject_Bad

      // Shouldn't get here but if we do, skip the call rather than crash.
      //
      add esp, 0x8
      ret
    }
  }

  ScriptPatches::ScriptPatches()
  {
    // Give the script compiler more room. Scr_BeginLoadScripts() makes it a
    // 1.5MB hunk, which holds the source of every script until they are all
    // compiled, and a mod with a lot of scripts runs out of it ("out of
    // memory for 'Scr_BeginLoadScripts'"). Note that the hunk only reserves
    // the address space and commits what it uses, so this costs us nothing
    // unless a mod actually needs it.
    //
    Utils::Hook::Set<DWORD>(0x4E1EDA, 0x1000000);

    // Fix format string in Scr_RandomFloatRange
    Utils::Hook::Set<const char*>(0x5F10C6, "Scr_RandomFloatRange parms: %f %f ");

    Utils::Hook (0x6206C8, VM_ArchiveStack_Hk, HOOK_CALL).install ()->quick (); // VM_Execute: wait.
    Utils::Hook (0x62080B, VM_ArchiveStack_Hk, HOOK_CALL).install ()->quick (); // VM_Execute: waittillframeend.
    Utils::Hook (0x62101C, VM_ArchiveStack_Hk, HOOK_CALL).install ()->quick (); // VM_Execute: waittill.

    Utils::Hook (0x437190, RemoveRefToObject_Stub, HOOK_JUMP).install ()->quick ();
    Utils::Hook::Nop (0x437195, 1);

    // Correct builtin function pointer
    Utils::Hook::Set<Game::BuiltinFunction>(0x79A90C, Scr_TableLookupIStringByRow_Hk);

    Script::AddMethod("ClearHudText", [](Game::scr_entref_t entref) -> void
    {
      auto* hud = HECmd_GetHudElem(entref);

      // Frees config string up
      if ((hud->elem).text)
      {
        Game::SV_SetConfigstring((hud->elem).text + offset, nullptr);
      }
    });
  }
}
