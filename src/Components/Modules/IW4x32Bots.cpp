// IW4x-32: native Bot Warfare hot paths. GSC builtins that answer what target_loop and AStarSearch spend
// their time on - visible-target acquisition and route finding - as native code on the game thread.
// Pure query: they read engine state and a native copy of the waypoint graph, they never write script state.
// The algorithm core is portable (src/Components/Modules/IW4x32BotsCore.hpp, also built and tested on Linux as
// 32-bit); this file is only the engine glue. Signatures and equivalence rules: iw4x32/bots/NATIVE_BOTS.md.

#include "IW4x32Bots.hpp"

#include "Events.hpp"
#include "GSC/Script.hpp"

#include "IW4x32BotsCore.hpp"

#include <algorithm>
#include <cctype>
#include <string>
#include <vector>

namespace Components
{
  namespace
  {
    // The stock iw4x.exe runs the GSC trace builtins through the three calls below - found in the exe's
    // builtin tables (the dword after a builtin's name is its function): bullettrace is 0x5F0990,
    // bullettracepassed is 0x5F0BC0, sighttracepassed is 0x5F0C50. Calling the engine's own trace code,
    // with the masks the builtins pass, is what makes our answers match what the GSC gets today.
    //
    //   sighttracepassed( a, b, false, undefined ) -> 0x4F5FE0(&r, a, b, 0x7FF, 0x00801803), passed = (r == 0)
    //   bullettrace(      a, b, false, undefined ) -> 0x406440(&t, a, b, 0x7FF, 0x00806831, 0)
    //   bullettracepassed(a, b, false, undefined ) -> 0x4C2A50(a, b, 0x7FF, 0x7FF, 0x00806831, 0), truthy = passed
    using TraceLine_t = void(*)(Game::trace_t* results, const float* start, const float* end,
      int passEntityNum, int contentMask, int extra);
    using SightTrace_t = int(*)(int* result, const float* start, const float* end,
      int passEntityNum, int contentMask);
    using TracePassed_t = int(*)(const float* start, const float* end,
      int passEntityNum, int passEntityNum2, int contentMask, int extra);

    const TraceLine_t TraceLine = reinterpret_cast<TraceLine_t>(0x406440);
    const SightTrace_t SightTrace = reinterpret_cast<SightTrace_t>(0x4F5FE0);
    const TracePassed_t TracePassed = reinterpret_cast<TracePassed_t>(0x4C2A50);

    constexpr int CONTENT_MASK_BULLET = 0x00806831;
    constexpr int CONTENT_MASK_SIGHT = 0x00801803;
    constexpr int NO_ENTITY = 0x7FF; // ENTITYNUM_NONE, what the builtins use when no entity is ignored

    // gettagorigin is the builtin at 0x5F4780; it calls 0x501120( ent, tagStringIndex, scratch, 1, 0 ) with
    // the engine's scratch buffer at 0x1A860C0 and then pushes the vector at scratch + 0x30. The callee
    // writes a cache stamp at +0x00, the entity number at +0x04, a string ref at +0x08, the tag matrix at
    // +0x0C, and the solved origin at +0x30 - so a caller supplies 0x3C bytes and reads the origin there.
    //
    // The 4th argument is "raise a Com_Error if this entity has no such tag": 0x501120 asks 0x44FBB0 for the
    // tag, and when that says "no such tag" it either errors (0x42EF40, the builtin's path with a 1) or
    // returns 0 (with a 0). We pass 0 and treat 0 as "this bone is not here": a bot aiming at a player that
    // lost its model for a frame must age the target, not end the level. The GSC's checkTraceForBone is
    // written the same way (if ( !isdefined( boneLoc ) ) return false) even though its builtin would error.
    using TagOrigin_t = int(*)(const Game::gentity_s* ent, unsigned int tagStringIndex,
      void* out, int errorIfMissing, int unused);

    const TagOrigin_t TagOrigin = reinterpret_cast<TagOrigin_t>(0x501120);
    constexpr int TAG_ERROR_IF_MISSING = 0;

    constexpr std::size_t TAG_BUFFER_SIZE = 0x3C;
    constexpr std::size_t TAG_ORIGIN_OFFSET = 0x30;

    // The surface type of a trace hit lives in bits 20-24 of surfaceFlags (the bullettrace builtin does the
    // same >> 0x14 & 0x1F before naming it). The engine's surface-type table puts "glass" at 9 and
    // "opaqueglass" at 31 - the GSC counts only glass as visible, so the comparison is against 9 exactly.
    constexpr int SURFACE_TYPE_SHIFT = 20;
    constexpr int SURFACE_TYPE_MASK = 0x1F;
    constexpr int SURFACE_TYPE_GLASS = 9;

    constexpr std::size_t MAX_BONES = 8;
    constexpr std::size_t MAX_GRAPH_WAYPOINTS = 8192;
    constexpr std::size_t MAX_GRAPH_CHILDREN = 65536;

    const Game::dvar_t* NativeBotsDvar = nullptr;

    // The native copy of level.waypoints, rebuilt once per map by the GSC feeding it in.
    iw4x32::bots::WaypointGraph Graph;
    iw4x32::bots::GraphBuilder GraphBuilder;
    bool GraphBuilding = false;

    // level.waypointusage[team] as a flat per-waypoint count. The GSC owns it and pushes every change through
    // iw4x32_bots_usage_set; the builtin only reads it.
    std::vector<int> Usage;

    iw4x32::bots::RouteScratch RouteScratch;
    std::vector<int> RoutePath;

    // bone name (lowercase) -> the VM const string the tag lookup wants
    std::vector<std::pair<std::string, unsigned int>> TagStrings;

    unsigned int TagStringForName(const std::string& name)
    {
      for (const auto& entry : TagStrings)
      {
        if (entry.first == name)
        {
          return entry.second;
        }
      }

      const unsigned int index = Game::SL_GetString(name.c_str(), 0);

      if (TagStrings.size() < 32)
      {
        TagStrings.emplace_back(name, index);
      }

      return index;
    }

    // "12,13,14" -> {12, 13, 14}; an empty string is an empty list.
    std::vector<int> ParseIntList(const char* text)
    {
      std::vector<int> out;

      if (text == nullptr)
      {
        return out;
      }

      std::size_t i = 0;

      while (text[i] != '\0')
      {
        std::size_t start = i;
        int value = 0;
        bool any = false;

        while (text[i] != '\0' && text[i] != ',')
        {
          if (text[i] >= '0' && text[i] <= '9')
          {
            value = value * 10 + (text[i] - '0');
            any = true;
          }

          ++i;
        }

        if (any)
        {
          out.push_back(value);
        }
        else if (start == i)
        {
          ++i; // a stray comma
        }

        if (text[i] == ',')
        {
          ++i;
        }
      }

      return out;
    }

    std::vector<std::string> ParseNameList(const char* text)
    {
      std::vector<std::string> out;

      if (text == nullptr)
      {
        return out;
      }

      std::string current;

      for (std::size_t i = 0;; ++i)
      {
        const char c = text[i];

        if (c == '\0' || c == ',')
        {
          if (!current.empty())
          {
            out.push_back(current);
          }

          current.clear();

          if (c == '\0')
          {
            break;
          }

          continue;
        }

        current += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
      }

      return out;
    }

    void ResetGraphState()
    {
      Graph = iw4x32::bots::WaypointGraph();
      GraphBuilder = iw4x32::bots::GraphBuilder();
      GraphBuilding = false;
      Usage.clear();
      RoutePath.clear();
    }

    // The GSC's per-player filter in engine state: in the game and with health. The mod's isreallyalive()
    // is not in the stock exe and not in this repo, so part B still runs it on the (few) candidates this
    // returns if it wants byte-for-byte parity - see iw4x32/bots/NATIVE_BOTS.md.
    bool InPlay(const Game::gentity_s* ent)
    {
      return ent->client != nullptr &&
        ent->client->sess.sessionState == Game::SESS_STATE_PLAYING &&
        ent->health > 0;
    }

    // The engine's scratch buffer for one tag solve - the builtin uses one static buffer too, and the
    // builtin chain never re-enters it, so one buffer per call site is enough.
    alignas(16) unsigned char TagBuffer[TAG_BUFFER_SIZE];

    // checkTraceForBone( myEye, bone ): sight trace first (it is the same segment and is ANDed with the bullet
    // trace), bullet trace only if the sight trace passed, glass counts as visible.
    bool BoneVisible(const float* eye, const float* boneLoc)
    {
      int sightResult = 1;
      SightTrace(&sightResult, eye, boneLoc, NO_ENTITY, CONTENT_MASK_SIGHT);

      if (sightResult != 0)
      {
        return false;
      }

      Game::trace_t trace{};
      TraceLine(&trace, eye, boneLoc, NO_ENTITY, CONTENT_MASK_BULLET, 0);

      return trace.fraction >= 1.0f ||
        ((trace.surfaceFlags >> SURFACE_TYPE_SHIFT) & SURFACE_TYPE_MASK) == SURFACE_TYPE_GLASS;
    }

    // bullettracepassed( a, b, false, undefined ) - what AStarSearch uses for its start/goal sanity check.
    bool LineClear(const float* a, const float* b)
    {
      return TracePassed(a, b, NO_ENTITY, NO_ENTITY, CONTENT_MASK_BULLET, 0) != 0;
    }

    // getNearestWaypointWithSight( pos ): the nearest waypoint that also has a clear line to pos. Same scan
    // order as the GSC (last waypoint first, a <= match wins), so ties go to the lowest index.
    int NearestWaypointWithSight(const float* pos)
    {
      const std::size_t count = Graph.Count();

      if (count == 0)
      {
        return -1;
      }

      const float raised[3] = {pos[0], pos[1], pos[2] + 15.0f};

      int candidate = -1;
      float best = 2147483647.0f;

      for (std::size_t i = count; i-- > 0;)
      {
        const float* origin = Graph.Origin(i);
        const float raisedOrigin[3] = {origin[0], origin[1], origin[2] + 15.0f};

        if (!LineClear(raised, raisedOrigin))
        {
          continue;
        }

        const float current = iw4x32::bots::DistanceSquared(origin, pos);

        if (current > best)
        {
          continue;
        }

        best = current;
        candidate = static_cast<int>(i);
      }

      return candidate;
    }

    // AStarSearch's start/goal prologue: nearest waypoint, and the sight fallback when the straight line to
    // it is blocked. Returns false when the graph has no waypoints (the GSC returns an empty array there).
    bool RouteEnds(const float* start, const float* goal, int& startWp, int& goalWp)
    {
      startWp = iw4x32::bots::NearestWaypoint(Graph, start);

      if (startWp < 0)
      {
        return false;
      }

      const float raisedStart[3] = {start[0], start[1], start[2] + 15.0f};
      const float* startOrigin = Graph.Origin(static_cast<std::size_t>(startWp));
      const float raisedStartOrigin[3] = {startOrigin[0], startOrigin[1], startOrigin[2] + 15.0f};

      if (!LineClear(raisedStart, raisedStartOrigin))
      {
        const int withSight = NearestWaypointWithSight(start);

        if (withSight >= 0)
        {
          startWp = withSight;
        }
      }

      goalWp = iw4x32::bots::NearestWaypoint(Graph, goal);

      if (goalWp < 0)
      {
        return false;
      }

      const float raisedGoal[3] = {goal[0], goal[1], goal[2] + 15.0f};
      const float* goalOrigin = Graph.Origin(static_cast<std::size_t>(goalWp));
      const float raisedGoalOrigin[3] = {goalOrigin[0], goalOrigin[1], goalOrigin[2] + 15.0f};

      if (!LineClear(raisedGoal, raisedGoalOrigin))
      {
        const int withSight = NearestWaypointWithSight(goal);

        if (withSight >= 0)
        {
          goalWp = withSight;
        }
      }

      return true;
    }

    void AddRouteArray(const iw4x32::bots::RouteRequest& request)
    {
      Game::Scr_MakeArray();

      if (iw4x32::bots::AStarSearch(request, RouteScratch, RoutePath))
      {
        for (const int waypoint : RoutePath)
        {
          Game::Scr_AddInt(waypoint);
        }
      }

      Game::Scr_AddArray();
    }
  }

  bool IW4x32Bots::Enabled()
  {
    return NativeBotsDvar != nullptr && NativeBotsDvar->current.integer != 0;
  }

  void IW4x32Bots::RegisterDvars()
  {
    NativeBotsDvar = Game::Dvar_RegisterInt("iw4x32_native_bots", 0, 0, 1,
      Game::DVAR_NONE, "Run the Bot Warfare target and route hot paths as native code (0 = stock GSC)");
  }

  void IW4x32Bots::AddScriptFunctions()
  {
    // gsc: iw4x32_bots_reset()
    // Drops the native graph and usage mirror. Call it before loading a map's waypoints.
    GSC::Script::AddFunction("iw4x32_bots_reset", []
    {
      ResetGraphState();
      Game::Scr_AddInt(1);
    });

    // gsc: iw4x32_bots_graph_add( <origin vector>, <type penalty 0/1>, <children "1,2,3"> )
    // One call per waypoint, right after load_waypoints(): the GSC walks level.waypoints once per map and the
    // native side keeps a flat copy. type penalty is 1 when the waypoint type is "climb" or "prone".
    GSC::Script::AddFunction("iw4x32_bots_graph_add", []
    {
      if (!GraphBuilding)
      {
        GraphBuilding = true;
        GraphBuilder = iw4x32::bots::GraphBuilder();
      }

      float origin[3]{};
      Game::Scr_GetVector(0, origin);

      const bool typePenalty = Game::Scr_GetInt(1) != 0;
      const auto children = ParseIntList(Game::Scr_GetString(2));

      if (GraphBuilder.Count() >= MAX_GRAPH_WAYPOINTS ||
        GraphBuilder.TotalChildren() + children.size() > MAX_GRAPH_CHILDREN)
      {
        Game::Scr_Error("iw4x32_bots_graph_add: too many waypoints");
        return;
      }

      GraphBuilder.Add(origin, typePenalty, children.data(), static_cast<int>(children.size()));

      Game::Scr_AddInt(1);
    });

    // gsc: iw4x32_bots_graph_finish() -> the waypoint count when the graph is usable, 0 when it was rejected
    GSC::Script::AddFunction("iw4x32_bots_graph_finish", []
    {
      if (!GraphBuilder.Finish())
      {
        Graph = iw4x32::bots::WaypointGraph();
        GraphBuilding = false;
        Usage.clear();
        Game::Scr_AddInt(0);
        return;
      }

      Graph = GraphBuilder.Take();
      GraphBuilding = false;
      Usage.assign(Graph.Count(), 0);

      Game::Scr_AddInt(static_cast<int>(Graph.Count()));
    });

    // gsc: iw4x32_bots_graph_count() -> the number of waypoints the native side holds
    GSC::Script::AddFunction("iw4x32_bots_graph_count", []
    {
      Game::Scr_AddInt(static_cast<int>(Graph.Count()));
    });

    // gsc: iw4x32_bots_nearest_waypoint( <pos> ) -> waypoint index, or -1
    // The linear scan of getNearestWaypoint, over the native graph. Ties go to the lowest index, like the GSC.
    GSC::Script::AddFunction("iw4x32_bots_nearest_waypoint", []
    {
      if (Graph.Count() == 0)
      {
        Game::Scr_Error("iw4x32_bots_nearest_waypoint: the waypoint graph is not loaded");
        return;
      }

      float pos[3]{};
      Game::Scr_GetVector(0, pos);

      Game::Scr_AddInt(iw4x32::bots::NearestWaypoint(Graph, pos));
    });

    // gsc: iw4x32_bots_nearest_waypoint_sight( <pos> ) -> waypoint index, or -1
    // getNearestWaypointWithSight: the nearest waypoint with a clear bullet line (both ends raised 15).
    GSC::Script::AddFunction("iw4x32_bots_nearest_waypoint_sight", []
    {
      if (Graph.Count() == 0)
      {
        Game::Scr_Error("iw4x32_bots_nearest_waypoint_sight: the waypoint graph is not loaded");
        return;
      }

      float pos[3]{};
      Game::Scr_GetVector(0, pos);

      Game::Scr_AddInt(NearestWaypointWithSight(pos));
    });

    // gsc: iw4x32_bots_trace_passed( <start>, <end> ) -> 1 when bullettracepassed( start, end, false, undefined )
    GSC::Script::AddFunction("iw4x32_bots_trace_passed", []
    {
      float start[3]{};
      float end[3]{};
      Game::Scr_GetVector(0, start);
      Game::Scr_GetVector(1, end);

      Game::Scr_AddInt(LineClear(start, end) ? 1 : 0);
    });

    // gsc: iw4x32_bots_usage_set( <waypoint>, <count> ) / iw4x32_bots_usage_get( <waypoint> )
    // The mirror of level.waypointusage[team]. The GSC applies usage; the builtin only reads it.
    GSC::Script::AddFunction("iw4x32_bots_usage_set", []
    {
      const int waypoint = Game::Scr_GetInt(0);

      if (waypoint < 0 || static_cast<std::size_t>(waypoint) >= Usage.size())
      {
        Game::Scr_ParamError(0, "iw4x32_bots_usage_set: waypoint out of range");
        return;
      }

      Usage[static_cast<std::size_t>(waypoint)] = Game::Scr_GetInt(1);

      Game::Scr_AddInt(1);
    });

    GSC::Script::AddFunction("iw4x32_bots_usage_get", []
    {
      const int waypoint = Game::Scr_GetInt(0);

      if (waypoint < 0 || static_cast<std::size_t>(waypoint) >= Usage.size())
      {
        Game::Scr_ParamError(0, "iw4x32_bots_usage_get: waypoint out of range");
        return;
      }

      Game::Scr_AddInt(Usage[static_cast<std::size_t>(waypoint)]);
    });

    // gsc: iw4x32_bots_route( <start>, <goal>, <greedy 0/1>, <use usage 0/1> ) -> waypoint indices, goal first
    // AStarSearch end to end: the nearest-waypoint prologue with its sight fallback, then the search.
    // Empty array when there is no path, like the GSC. No spawnstruct per node - that is one of the two wins.
    GSC::Script::AddFunction("iw4x32_bots_route", []
    {
      if (Graph.Count() == 0)
      {
        Game::Scr_Error("iw4x32_bots_route: the waypoint graph is not loaded");
        return;
      }

      float start[3]{};
      float goal[3]{};
      Game::Scr_GetVector(0, start);
      Game::Scr_GetVector(1, goal);

      int startWp = -1;
      int goalWp = -1;

      if (!RouteEnds(start, goal, startWp, goalWp))
      {
        Game::Scr_MakeArray();
        Game::Scr_AddArray();
        return;
      }

      const iw4x32::bots::RouteRequest request
      {
        &Graph,
        startWp,
        goalWp,
        Game::Scr_GetInt(3) != 0 ? Usage.data() : nullptr,
        Game::Scr_GetInt(2) != 0
      };

      AddRouteArray(request);
    });

    // gsc: iw4x32_bots_route_wp( <startWp>, <goalWp>, <greedy 0/1>, <use usage 0/1> ) -> same, no prologue
    // For callers that already picked the end waypoints.
    GSC::Script::AddFunction("iw4x32_bots_route_wp", []
    {
      if (Graph.Count() == 0)
      {
        Game::Scr_Error("iw4x32_bots_route_wp: the waypoint graph is not loaded");
        return;
      }

      const iw4x32::bots::RouteRequest request
      {
        &Graph,
        Game::Scr_GetInt(0),
        Game::Scr_GetInt(1),
        Game::Scr_GetInt(3) != 0 ? Usage.data() : nullptr,
        Game::Scr_GetInt(2) != 0
      };

      AddRouteArray(request);
    });

    // gsc: self iw4x32_bots_visible_targets( <eye>, <fov>, <team based 0/1>, <bones "j_head,j_ankle_le">,
    //                                        <force "12,7"> )
    // What target_loop's per-player loop spends its time on: the team / in-play filter, the cone test, and
    // checkTraceForBone for the bones asked for. Returns a flat array, five values per player that passes the
    // team / in-play filter: the player entity, its entity number, distance squared, in cone (1 = the cone dot
    // cleared fov), and the bone slot + 1 into <bones> for the first bone that is visible (0 = none of them).
    // A player the filter drops is simply absent - that is the GSC's "untarget and continue" case.
    // <force> (optional) names entity numbers to trace even out of the cone: the ( isObjDef && obj.trace_time )
    // half of the GSC's inCone, which is script state the builtin must not read.
    // It writes nothing to script state - self.bot.targets, humanize, smoke, remember times and script targets
    // stay in GSC.
    GSC::Script::AddMethod("iw4x32_bots_visible_targets", [](const Game::scr_entref_t entref)
    {
      const auto* self = GSC::Script::Scr_GetPlayerEntity(entref);

      if (self == nullptr || self->client == nullptr)
      {
        Game::Scr_MakeArray();
        Game::Scr_AddArray();
        return;
      }

      float eye[3]{};
      Game::Scr_GetVector(0, eye);

      const float fov = Game::Scr_GetFloat(1);
      const bool teamBased = Game::Scr_GetInt(2) != 0;

      const auto bones = ParseNameList(Game::Scr_GetString(3));
      const std::vector<int> forced =
        Game::Scr_GetNumParam() > 4 ? ParseIntList(Game::Scr_GetString(4)) : std::vector<int>();

      unsigned int boneStrings[MAX_BONES]{};
      const std::size_t boneCount = std::min(bones.size(), MAX_BONES);

      for (std::size_t bone = 0; bone < boneCount; ++bone)
      {
        boneStrings[bone] = TagStringForName(bones[bone]);
      }

      Game::Scr_MakeArray();

      // level.players is a script array; walking g_entities and keeping the ones with a client is the same
      // set without touching script state.
      for (std::size_t i = 0; i < Game::MAX_GENTITIES; ++i)
      {
        const auto& player = Game::g_entities[i];

        if (&player == self || !player.r.isInUse || !InPlay(&player))
        {
          continue;
        }

        if (teamBased && self->team == player.team)
        {
          continue;
        }

        const float origin[3] =
        {
          player.r.currentOrigin[0],
          player.r.currentOrigin[1],
          player.r.currentOrigin[2]
        };

        const float coneDot = iw4x32::bots::GetConeDot(origin, self->r.currentOrigin, self->client->ps.viewangles);
        const bool inCone = coneDot >= fov;

        int visibleBone = 0;

        // The GSC traces only when inCone is true, and it stops at the first bone that is visible.
        if (inCone || std::find(forced.begin(), forced.end(), static_cast<int>(i)) != forced.end())
        {
          for (std::size_t bone = 0; bone < boneCount; ++bone)
          {
            if (TagOrigin(&player, boneStrings[bone], TagBuffer, TAG_ERROR_IF_MISSING, 0) == 0)
            {
              continue; // no such bone on this entity
            }

            if (BoneVisible(eye, reinterpret_cast<const float*>(TagBuffer + TAG_ORIGIN_OFFSET)))
            {
              visibleBone = static_cast<int>(bone) + 1;
              break;
            }
          }
        }

        Game::Scr_AddEntity(&player);
        Game::Scr_AddInt(static_cast<int>(player.s.number));
        Game::Scr_AddFloat(iw4x32::bots::DistanceSquared(origin, self->r.currentOrigin));
        Game::Scr_AddInt(inCone ? 1 : 0);
        Game::Scr_AddInt(visibleBone);
      }

      Game::Scr_AddArray();
    });
  }

  IW4x32Bots::IW4x32Bots()
  {
    RegisterDvars();
    AddScriptFunctions();

    Events::OnVMShutdown([]
    {
      ResetGraphState();
      TagStrings.clear();
    });
  }
}
