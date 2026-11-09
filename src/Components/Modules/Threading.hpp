#pragma once

namespace Components
{
  // IW4x-32: the dedicated server's packet pump counts itself (see Threading.cpp). The totals are read by the
  // server console's IW4X32_CPU stats line (IW4x32::RecordFrame), which is what makes "the server stopped
  // reading packets" a measured statement instead of a guess.
  namespace FrameTime
  {
    unsigned long long WaitSelects();
    unsigned long long WaitActivity();
    unsigned long long WaitSelectFails();
    unsigned long long WaitPumps();
  }

  class Threading : public Component
  {
  public:
    Threading();

  private:
    static void FrameEpilogueStub();
    static void PacketEventStub();
  };
}
