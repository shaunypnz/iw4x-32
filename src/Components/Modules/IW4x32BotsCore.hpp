#pragma once

// IW4x-32: the portable core of the native bot hot paths.
//
// No Win32, no MSVC-only syntax, no engine calls: this file is compiled into iw4x.dll (MSVC, /W4 /WX) and into
// the 32-bit Linux unit test (g++ -m32 -std=c++20 -Wall -Werror, iw4x32/bots/native_bots_test.cpp). It lives in
// the public tree next to the component that uses it (IW4x32Bots.cpp) so a clean checkout builds. Everything in
// it mirrors the Bot Warfare GSC it replaces; the equivalence rules are in iw4x32/bots/NATIVE_BOTS.md.

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace iw4x32
{
namespace bots
{
    // ------------------------------------------------------------------ maths

    // GSC anglestoforward( <angles> ) - roll is ignored, like the engine's AngleVectors.
    inline void AnglesToForward(const float angles[3], float out[3])
    {
        constexpr float degToRad = 3.14159265358979323846f / 180.0f;

        const float pitch = angles[0] * degToRad;
        const float yaw = angles[1] * degToRad;

        const float cosPitch = std::cos(pitch);
        const float sinPitch = std::sin(pitch);
        const float cosYaw = std::cos(yaw);
        const float sinYaw = std::sin(yaw);

        out[0] = cosPitch * cosYaw;
        out[1] = cosPitch * sinYaw;
        out[2] = -sinPitch;
    }

    inline float VectorDot(const float a[3], const float b[3])
    {
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    inline float DistanceSquared(const float a[3], const float b[3])
    {
        const float dx = a[0] - b[0];
        const float dy = a[1] - b[1];
        const float dz = a[2] - b[2];

        return dx * dx + dy * dy + dz * dz;
    }

    // GSC vectornormalize( <vector> ) - a zero length vector normalizes to (0,0,0).
    inline void VectorNormalize(const float in[3], float out[3])
    {
        const float length = std::sqrt(VectorDot(in, in));

        if (length == 0.0f)
        {
            out[0] = 0.0f;
            out[1] = 0.0f;
            out[2] = 0.0f;
            return;
        }

        const float inverse = 1.0f / length;

        out[0] = in[0] * inverse;
        out[1] = in[1] * inverse;
        out[2] = in[2] * inverse;
    }

    // GSC getConeDot( <to>, <from>, <dir> ) - how far <to> is off the front of <from>, as a dot product.
    // Pure maths: task 143 found it is the cheapest way to reject the players a bot cannot see.
    inline float GetConeDot(const float to[3], const float from[3], const float dir[3])
    {
        const float delta[3] = {to[0] - from[0], to[1] - from[1], to[2] - from[2]};

        float normalized[3];
        VectorNormalize(delta, normalized);

        float forward[3];
        AnglesToForward(dir, forward);

        return VectorDot(normalized, forward);
    }

    // ------------------------------------------------------------------ the waypoint graph

    // A flat copy of level.waypoints: origins, child index lists, and the two node types the GSC makes
    // more expensive. Nothing here is a script value, which is the point - task 143 measured the script
    // variable pool at 85.6-88.6 % of 36,865 with 32 bots, partly from one spawnstruct per expanded node.
    struct WaypointGraph
    {
        std::vector<float> origin; // 3 floats per waypoint
        std::vector<int> childStart; // count + 1 offsets into children
        std::vector<int> children;
        std::vector<unsigned char> typePenalty; // 1 when the waypoint type is "climb" or "prone"

        std::size_t Count() const
        {
            return childStart.size() >= 1 ? childStart.size() - 1 : 0;
        }

        bool Valid() const
        {
            if (childStart.size() != typePenalty.size() + 1 || origin.size() != Count() * 3)
            {
                return false;
            }

            if (childStart.front() != 0 || static_cast<std::size_t>(childStart.back()) != children.size())
            {
                return false;
            }

            for (std::size_t i = 0; i < Count(); ++i)
            {
                if (childStart[i] > childStart[i + 1])
                {
                    return false;
                }
            }

            return true;
        }

        const float* Origin(std::size_t index) const
        {
            return &origin[index * 3];
        }

        const int* ChildList(std::size_t index) const
        {
            return &children[static_cast<std::size_t>(childStart[index])];
        }

        int ChildCount(std::size_t index) const
        {
            return childStart[index + 1] - childStart[index];
        }
    };

    // Fills a WaypointGraph one waypoint at a time; the caller feeds it from GSC after the waypoints load.
    class GraphBuilder
    {
    public:
        void Add(const float origin[3], bool climbOrProneType, const int* children, int childCount)
        {
            for (int i = 0; i < 3; ++i)
            {
                graph_.origin.push_back(origin[i]);
            }

            graph_.typePenalty.push_back(climbOrProneType ? 1 : 0);

            for (int i = 0; i < childCount; ++i)
            {
                graph_.children.push_back(children[i]);
            }

            graph_.childStart.push_back(static_cast<int>(graph_.children.size()));
        }

        // Children must be in range; a bad index would read outside the graph, so the whole load is rejected.
        bool Finish()
        {
            graph_.childStart.insert(graph_.childStart.begin(), 0);

            if (!graph_.Valid())
            {
                return false;
            }

            const std::size_t count = graph_.Count();

            for (const int child : graph_.children)
            {
                if (child < 0 || static_cast<std::size_t>(child) >= count)
                {
                    return false;
                }
            }

            return true;
        }

        WaypointGraph Take()
        {
            return std::move(graph_);
        }

        // How much has been fed in so far - the caller uses these to cap the load before Finish().
        std::size_t Count() const
        {
            return graph_.typePenalty.size();
        }

        std::size_t TotalChildren() const
        {
            return graph_.children.size();
        }

    private:
        WaypointGraph graph_;
    };

    // GSC getNearestWaypoint( <pos> ): scans from the last waypoint down and keeps a strictly closer one, so a
    // tie goes to the LOWEST index. Returns -1 when the graph is empty.
    inline int NearestWaypoint(const WaypointGraph& graph, const float pos[3])
    {
        const std::size_t count = graph.Count();

        if (count == 0)
        {
            return -1;
        }

        int candidate = -1;
        float best = 2147483647.0f;

        for (std::size_t i = count; i-- > 0;)
        {
            const float current = DistanceSquared(graph.Origin(i), pos);

            if (current > best)
            {
                continue;
            }

            best = current;
            candidate = static_cast<int>(i);
        }

        return candidate;
    }

    // ------------------------------------------------------------------ route search

    struct RouteRequest
    {
        const WaypointGraph* graph;
        int startWp; // a waypoint index, as GSC's getNearestWaypoint picked it
        int goalWp;
        const int* usage; // level.waypointusage[team] as counts per waypoint, null when undefined
        bool greedyPath; // true ignores the congestion term, like the GSC flag
    };

    // Reusable scratch. One node per expanded node, plain arrays: no allocation per node, and nothing from
    // the script variable pool.
    class RouteScratch
    {
    public:
        void Reset(std::size_t nodeCount)
        {
            if (nodeCount > openNode_.size())
            {
                openNode_.resize(nodeCount);
                closedNode_.resize(nodeCount);
            }

            // The GSC's two lookup sets, openset[] and closed[], keyed by waypoint - kept apart, because a
            // waypoint can sit in both at once (a self link spawns a fresh node while the old one stays in
            // closed), and the GSC tests both of them.
            std::fill(openNode_.begin(), openNode_.begin() + static_cast<std::ptrdiff_t>(nodeCount), -1);
            std::fill(closedNode_.begin(), closedNode_.begin() + static_cast<std::ptrdiff_t>(nodeCount), -1);

            g_.clear();
            h_.clear();
            f_.clear();
            parent_.clear();
            pool_.clear();
            heap_.clear();
        }

        // One node per spawnstruct() the GSC would make - including the case where a waypoint is reached again
        // after its node left the open list, which makes the GSC allocate a fresh struct too.
        int AddNode(int wpIndex)
        {
            pool_.push_back(wpIndex);
            g_.push_back(0.0f);
            h_.push_back(0.0f);
            f_.push_back(0.0f);
            parent_.push_back(-1);

            return static_cast<int>(pool_.size()) - 1;
        }

    private:
        friend bool AStarSearch(const RouteRequest& request, RouteScratch& scratch, std::vector<int>& pathOut);

        std::vector<float> g_;
        std::vector<float> h_;
        std::vector<float> f_;
        std::vector<int> parent_;
        std::vector<int> openNode_; // waypoint index -> the node in openset, -1 when undefined
        std::vector<int> closedNode_; // waypoint index -> the node in closed, -1 when undefined
        std::vector<int> pool_; // node ids in creation order (a self loop may create a second node for one wp)
        std::vector<int> heap_; // the GSC heap array, 0 based
    };

    // A line-for-line port of AStarSearch in maps/mp/bots/_bot_utility.gsc, including the heap (its insert and
    // remove are the GSC ones, and an in-open child is updated without sifting - the GSC does that too, so the
    // pop order has to come out the same). The path comes back goal first, start last, like the GSC array.
    inline bool AStarSearch(const RouteRequest& request, RouteScratch& scratch, std::vector<int>& pathOut)
    {
        pathOut.clear();

        const WaypointGraph& graph = *request.graph;
        const std::size_t nodeCount = graph.Count();

        if (request.startWp < 0 || static_cast<std::size_t>(request.startWp) >= nodeCount ||
            request.goalWp < 0 || static_cast<std::size_t>(request.goalWp) >= nodeCount)
        {
            return false;
        }

        scratch.Reset(nodeCount);

        std::vector<int>& heap = scratch.heap_;

        // ReverseHeapAStar( item, item2 ): return item.f < item2.f;
        const auto heapLess = [&scratch](int first, int second)
        {
            return scratch.f_[first] < scratch.f_[second];
        };

        // HeapInsert( item )
        const auto heapInsert = [&scratch, &heap, &heapLess](int item)
        {
            heap.push_back(item);

            std::size_t current = heap.size(); // 1 based, like the GSC array

            while (current > 1)
            {
                const std::size_t last = current;
                current /= 2;

                if (!heapLess(item, heap[current - 1]))
                {
                    break;
                }

                heap[last - 1] = heap[current - 1];
                heap[current - 1] = item;
            }
        };

        // _HeapNextChild( node, hsize ) - 0 means "no child" (the GSC returns -1)
        const auto heapNextChild = [&scratch, &heap, &heapLess](std::size_t node, std::size_t heapSize) -> std::size_t
        {
            const std::size_t left = node * 2;
            const std::size_t right = left + 1;

            if (left > heapSize)
            {
                return 0;
            }

            if (right > heapSize)
            {
                return left;
            }

            return heapLess(heap[left - 1], heap[right - 1]) ? left : right;
        };

        // HeapRemove()
        const auto heapRemove = [&heap, &heapLess, &heapNextChild]()
        {
            std::size_t remove = heap.size();

            if (remove == 0)
            {
                return;
            }

            const int move = heap[remove - 1];
            heap[0] = move;
            heap.pop_back(); // self.data[ remove - 1 ] = undefined
            --remove;

            if (remove == 0)
            {
                return;
            }

            std::size_t last = 1;
            std::size_t next = heapNextChild(1, remove);

            while (next != 0)
            {
                if (heapLess(move, heap[next - 1]))
                {
                    break;
                }

                heap[last - 1] = heap[next - 1];
                heap[next - 1] = move;

                last = next;
                next = heapNextChild(next, remove);
            }
        };

        // spawnstruct() per node - here: the next slot in a plain int array.
        const auto newNode = [&scratch](int wpIndex) -> int { return scratch.AddNode(wpIndex); };

        const int startWp = request.startWp;
        const int goalWp = request.goalWp;

        int node = newNode(startWp);
        scratch.h_[node] = DistanceSquared(graph.Origin(startWp), graph.Origin(goalWp));
        scratch.f_[node] = scratch.h_[node]; // node.g is 0
        scratch.openNode_[static_cast<std::size_t>(startWp)] = node; // openset[ node.index ] = node
        heapInsert(node);

        while (!heap.empty())
        {
            const int bestNode = heap[0];
            heapRemove();

            const int bestWp = scratch.pool_[bestNode];
            scratch.openNode_[static_cast<std::size_t>(bestWp)] = -1; // openset[ bestNodeStr ] = undefined

            if (bestWp == goalWp)
            {
                for (int walk = bestNode; walk != -1; walk = scratch.parent_[walk])
                {
                    pathOut.push_back(scratch.pool_[walk]);
                }

                return true;
            }

            // for ( i = wp.children.size - 1; i >= 0; i-- )
            const int* childList = graph.ChildList(static_cast<std::size_t>(bestWp));
            const int childCount = graph.ChildCount(static_cast<std::size_t>(bestWp));

            for (int c = childCount; c-- > 0;)
            {
                const int child = childList[c];
                const int inOpenNode = scratch.openNode_[static_cast<std::size_t>(child)];
                const int inClosedNode = scratch.closedNode_[static_cast<std::size_t>(child)];
                const bool inOpen = inOpenNode != -1;
                const bool inClosed = inClosedNode != -1;

                int penalty = 1;

                if (!request.greedyPath && request.usage != nullptr)
                {
                    const int tempPen = request.usage[child]; // how many bots are taking this path

                    if (tempPen > 1)
                    {
                        penalty = tempPen;
                    }
                }

                if (graph.typePenalty[static_cast<std::size_t>(child)] != 0) // "climb" or "prone"
                {
                    penalty += 4;
                }

                const float newG = scratch.g_[bestNode] +
                    DistanceSquared(graph.Origin(static_cast<std::size_t>(bestWp)), graph.Origin(static_cast<std::size_t>(child))) *
                    static_cast<float>(penalty);

                if (inOpen && scratch.g_[inOpenNode] <= newG)
                {
                    continue;
                }

                if (inClosed && scratch.g_[inClosedNode] <= newG)
                {
                    continue;
                }

                if (inOpen)
                {
                    node = inOpenNode;
                }
                else if (inClosed)
                {
                    node = inClosedNode;
                }
                else
                {
                    node = newNode(child);
                }

                scratch.parent_[node] = bestNode;
                scratch.g_[node] = newG;
                scratch.h_[node] = DistanceSquared(graph.Origin(static_cast<std::size_t>(child)), graph.Origin(goalWp));
                scratch.f_[node] = scratch.g_[node] + scratch.h_[node];

                if (inClosed)
                {
                    scratch.closedNode_[static_cast<std::size_t>(child)] = -1; // closed[ childStr ] = undefined
                }

                if (!inOpen)
                {
                    heapInsert(node);
                    scratch.openNode_[static_cast<std::size_t>(child)] = node; // openset[ childStr ] = node
                }
            }

            scratch.closedNode_[static_cast<std::size_t>(bestWp)] = bestNode; // closed[ bestNodeStr ] = bestNode
        }

        return false; // unreachable goal
    }

    // ------------------------------------------------------------------ target cone

    // The GSC's target_loop reduces fov while the bot is aiming down sights:
    // myFov *= 1 - adsFovMulti * adsAmount.
    inline float AdsScaledFov(float baseFov, float adsFovFactor, float adsAmount)
    {
        return adsAmount > 0.0f ? baseFov * (1.0f - adsFovFactor * adsAmount) : baseFov;
    }
}
}
