#include "Network.hpp"

namespace Components
{
  // Packet interception
  std::unordered_map<std::string, Network::networkCallback> Network::CL_Callbacks;
  std::unordered_map<std::string, Network::networkRawCallback> Network::CL_RawCallbacks;

  Network::Address::Address()
  {
    ZeroMemory(&this->address, sizeof(Game::netadr_t));
    this->setType(Game::NA_BAD);
  }

  Network::Address::Address(const std::string& addrString)
  {
    ZeroMemory(&this->address, sizeof(Game::netadr_t));
    Game::NET_StringToAdr(addrString.data(), &this->address);
  }

  Network::Address::Address(sockaddr* addr)
  {
    ZeroMemory(&this->address, sizeof(Game::netadr_t));
    Game::SockadrToNetadr(addr, &this->address);
  }

  bool Network::Address::operator==(const Address& obj) const
  {
    return Game::NET_CompareAdr(this->address, obj.address);
  }

  void Network::Address::setPort(unsigned short port)
  {
    this->address.port = ::htons(port);
  }

  unsigned short Network::Address::getPort() const
  {
    return ntohs(this->address.port);
  }

  unsigned short Network::Address::getPortRaw() const
  {
    return this->address.port;
  }

  void Network::Address::setIP(DWORD ip)
  {
    this->address.ip.full = ip;
  }

  void Network::Address::setIP(Game::netIP_t ip)
  {
    this->address.ip = ip;
  }

  Game::netIP_t Network::Address::getIP() const
  {
    return this->address.ip;
  }

  void Network::Address::setType(Game::netadrtype_t type)
  {
    this->address.type = type;
  }

  Game::netadrtype_t Network::Address::getType() const
  {
    return this->address.type;
  }

  sockaddr Network::Address::getSockAddr()
  {
    sockaddr addr;
    this->toSockAddr(&addr);
    return addr;
  }

  void Network::Address::toSockAddr(sockaddr* addr)
  {
    if (addr)
    {
      Game::NetadrToSockadr(&this->address, addr);
    }
  }

  void Network::Address::toSockAddr(sockaddr_in* addr)
  {
    this->toSockAddr(reinterpret_cast<sockaddr*>(addr));
  }

  const Game::netadr_t* Network::Address::get() const noexcept
  {
    return &this->address;
  }

  const char* Network::Address::getCString() const
  {
    return Game::NET_AdrToString(this->address);
  }

  std::string Network::Address::getString() const
  {
    return std::string{ this->getCString() };
  }

  bool Network::Address::isLocal() const noexcept
  {
    // According to: https://en.wikipedia.org/wiki/Private_network

    // 10.X.X.X
    if (this->getIP().bytes[0] == 10) return true;

    // 192.168.X.X
    if (this->getIP().bytes[0] == 192 && this->getIP().bytes[1] == 168) return true;

    // 172.16.X.X - 172.31.X.X
    if (this->getIP().bytes[0] == 172 && (this->getIP().bytes[1] >= 16) && (this->getIP().bytes[1] < 32)) return true;

    // 127.0.0.1
    if (this->getIP().full == 0x0100007F) return true;

    // TODO: Maybe check for matching localIPs and subnet mask

    return false;
  }

  bool Network::Address::isSelf() const noexcept
  {
    if (Game::NET_IsLocalAddress(this->address)) return true; // Loopback
    if (this->getPort() != GetPort()) return false; // Port not equal

    for (int i = 0; i < *Game::numIP; ++i)
    {
      if (this->getIP().full == Game::localIP[i].full)
      {
        return true;
      }
    }

    return false;
  }

  bool Network::Address::isLoopback() const noexcept
  {
    if (this->getIP().full == 0x100007f) // 127.0.0.1
    {
      return true;
    }

    return Game::NET_IsLocalAddress(this->address);
  }

  bool Network::Address::isValid() const noexcept
  {
    return (this->getType() != Game::NA_BAD && this->getType() >= Game::NA_BOT && this->getType() <= Game::NA_IP);
  }

  const char* Network::AdrToString(const Address& a, const bool port)
  {
    if (a.getType() == Game::netadrtype_t::NA_LOOPBACK)
    {
      return "loopback";
    }

    if (a.getType() == Game::netadrtype_t::NA_BOT)
    {
      return "bot";
    }

    if (a.getType() == Game::netadrtype_t::NA_IP || a.getType() == Game::netadrtype_t::NA_BROADCAST)
    {
      if (a.getPort() && port)
      {
        return Utils::String::VA("%u.%u.%u.%u:%u", a.getIP().bytes[0], a.getIP().bytes[1], a.getIP().bytes[2], a.getIP().bytes[3], htons(a.getPortRaw()));
      }

      return Utils::String::VA("%u.%u.%u.%u", a.getIP().bytes[0], a.getIP().bytes[1], a.getIP().bytes[2], a.getIP().bytes[3]);
    }

    return "bad";
  }

  void Network::Send(Game::netsrc_t type, const Address& target, const std::string& data)
  {
    // Do not use NET_OutOfBandPrint. It only supports non-binary data!

    // Pre-reserve to avoid reallocation
    std::string rawData;
    rawData.reserve(4 + data.size());
    rawData.append("\xFF\xFF\xFF\xFF", 4);
    rawData.append(data);

    SendRaw(type, target, rawData);
  }

  void Network::Send(const Address& target, const std::string& data)
  {
    Send(Game::netsrc_t::NS_CLIENT1, target, data);
  }

  void Network::SendRaw(Game::netsrc_t type, const Address& target, const std::string& data)
  {
    if (!target.isValid()) return;

    // NET_OutOfBandData doesn't seem to work properly. Do not use it
    Game::Sys_SendPacket(type, data.size(), data.data(), *target.get());
  }

  void Network::SendRaw(const Address& target, const std::string& data)
  {
    SendRaw(Game::NS_CLIENT1, target, data);
  }

  void Network::SendCommand(Game::netsrc_t type, const Address& target, const std::string& command, const std::string& data)
  {
    // Use space as separator (possible separators are '\n', ' ').
    // Though, our handler only needs exactly 1 char as separator and doesn't care which char it is.
    // EDIT: Most 3rd party tools expect a line break, so let's use that instead!

    // Pre-reserve to avoid reallocations (4 bytes header + command + newline + data)
    std::string packet;
    packet.reserve(command.size() + 1 + data.size());
    packet.append(command);
    packet.push_back('\n');
    packet.append(data);

    Send(type, target, packet);
  }

  void Network::SendCommand(const Address& target, const std::string& command, const std::string& data)
  {
    SendCommand(Game::NS_CLIENT1, target, command, data);
  }

  void Network::Broadcast(unsigned short port, const std::string& data)
  {
    Address target;

    target.setPort(port);
    target.setIP(INADDR_BROADCAST);
    target.setType(Game::netadrtype_t::NA_BROADCAST);

    Send(Game::netsrc_t::NS_CLIENT1, target, data);
  }

  void Network::BroadcastRange(unsigned int min, unsigned int max, const std::string& data)
  {
    for (unsigned int i = min; i < max; ++i)
    {
      Broadcast(static_cast<unsigned short>(i & 0xFFFF), data);
    }
  }

  void Network::BroadcastAll(const std::string& data)
  {
    BroadcastRange(100, 65536, data);
  }

  std::uint16_t Network::GetPort()
  {
    assert((*Game::port));
    assert((*Game::port)->current.unsignedInt <= std::numeric_limits<std::uint16_t>::max());
    return static_cast<std::uint16_t>((*Game::port)->current.unsignedInt);
  }

  __declspec(naked) void Network::PacketErrorCheck()
  {
    __asm
    {
      // IW4x-32: what error the socket actually failed with, counted (see NetReadErrors). eax is the WSA code
      // and the engine answers for WSAEWOULDBLOCK ("nothing waiting") before it gets here, so every code seen is
      // a real socket error. pushad/popad keeps the engine's registers - the compares below read eax.
      //
      pushad
      push eax
      call NetErrorCodeSeen
      add esp, 4
      popad

      cmp eax, 2746h
      jz returnIgnore

      cmp eax, WSAENETRESET
      jz returnIgnore

      push 465325h
      retn

    returnIgnore:
      push 4654C6h
      retn
    }
  }

  // IW4x-32: the socket errors this fork silences. The engine reads the game socket in one place - NET_GetPacket
  // at 0x4652B0 - and PacketErrorCheck below jumps it past the error print for WSAECONNRESET and WSAENETRESET,
  // so a socket that started failing looks exactly like a server that stopped reading: frames run, nobody gets
  // an answer, and the log says nothing about either. These codes are what tell the two apart.
  //
  // Counting them here, rather than by hooking the engine's recvfrom call: a stub over that call adds a call of
  // its own in the middle of the engine's frame and it took the whole server down with it (a 63-bot run died
  // during startup, the fault one call deeper than the patched thunk). What is patched instead is whole 5-byte
  // call / jump instructions that only ever count and tail-jump (see NetGetCountStub / ServerPumpStub), and the
  // socket is asked directly about itself (see SocketQueue).
  //
  static unsigned long long g_NetErrors = 0;
  static unsigned long long g_NetGetCalls = 0;
  static unsigned long long g_ServerPumpCalls = 0;

  struct NetErrorCode
  {
    int code;
    unsigned long long seen;
  };

  static NetErrorCode g_NetCodes[6] = {};
  static unsigned long long g_NetCodeOverflow = 0;

  unsigned long long Network::NetReadErrors()
  {
    return g_NetErrors;
  }

  unsigned long long Network::NetGetCalls()
  {
    return g_NetGetCalls;
  }

  unsigned long long Network::ServerPumpCalls()
  {
    return g_ServerPumpCalls;
  }

  void Network::NetGetCounted()
  {
    g_NetGetCalls++;
  }

  void Network::ServerPumpCounted()
  {
    g_ServerPumpCalls++;
  }

  // IW4x-32: counting without changing anything. The engine's receive function (NET_GetPacket, 0x4652B0) is only
  // ever reached through the 5-byte `jmp 0x4652b0` at 0x4ECFF0 - one reference in the whole exe, so a counted
  // stub there sees every read the engine makes, whoever asked. With that number, the pump counters below and
  // SocketQueue's queue depth, a server that answers nobody while it runs frames is one of three things, and the
  // log says which: nobody came to look; someone looked and the socket held nothing; or someone looked, the
  // socket held something, and the engine walked past it.
  //
  __declspec(naked) void Network::NetGetCountStub()
  {
    __asm
    {
      pushad
      call NetGetCounted
      popad

      mov eax, 4652B0h // NET_GetPacket - the target of the jmp this stub stands in for
      jmp eax
    }
  }

  // The pump the dedicated server does for ITSELF. The engine's server frame function (0x627040) calls the pump
  // (0x458160) in two places - once per pass of its main pass (0x6271B7) and once inside the catch-up loop that
  // runs when it is behind schedule (0x6272BA) - and both are whole 5-byte `call` instructions, so a counted
  // stub can stand in either and make the call itself: push the address the engine would have returned to, then
  // jump to the target. Same stack, same registers, one number added.
  //
  // This replaces the counter that stood at 0x45827C, which was a broken instrument: that call sits on the
  // back-edge of the pump's drain loop, so a pump that reads nothing - the case worth seeing - never reaches it,
  // and it read 0 in every run. The two sites here are reached whether or not a datagram shows up.
  //
  __declspec(naked) void Network::ServerPumpStub()
  {
    __asm
    {
      pushad
      call ServerPumpCounted
      popad

      push 6271BCh
      mov eax, 458160h // Sys_ReadPacket - the pump the server frame function calls
      jmp eax
    }
  }

  __declspec(naked) void Network::ServerCatchUpPumpStub()
  {
    __asm
    {
      pushad
      call ServerPumpCounted
      popad

      push 6272BFh
      mov eax, 458160h
      jmp eax
    }
  }

  // IW4x-32: the engine's own gates on the receive path, read as plain bytes.
  //
  // A 64-slot server that runs frames and answers nobody has stopped collecting datagrams, and the collection
  // path is not one road but three, each behind a global (every address below read off the pristine exe):
  //
  //   * the server frame function reads its socket only while the byte at 0x2089E20 is set (0x6271A9 gates both
  //     pump calls); the engine sets it after that function returns (0x62769A) and clears it inside
  //     SV_WaitServer (0x42570D), which this fork turns into a bare `ret`, so nothing in the fork clears it;
  //   * the per-frame wait - 0x4BAAAD, where this fork pumps - is only reached while the sv_running dvar says a
  //     level is running (byte at dvar + 0x10, read at 0x4BAA8F), and the UDP read inside the pump itself
  //     (0x458194) is gated by that same byte, so a server with no level running is deaf by construction;
  //   * and while the loader state word at 0x20494F8 is nonzero the wait does nothing at all (0x48B530 returns
  //     1 and the caller returns without waiting, pumping or running the level).
  //
  // Which of the three is shut decides the fix: a shut pump gate is ours to open, a shut sv_running or a stuck
  // loader means the level died upstream and pumping more will not make the match playable. Printed with the
  // counters on the same line, so one window answers both questions at once.
  //
  const char* Network::ReceiveGates()
  {
    static std::string line;

    const auto* owner = *reinterpret_cast<unsigned char* const*>(0x1AD7934);
    const auto gate = owner ? owner[0x10] : 0xFF; // no owner installed yet
    const auto pump = *reinterpret_cast<const unsigned char*>(0x2089E20);
    const auto loader = *reinterpret_cast<const unsigned char*>(0x20494F8);

    line = std::format("{};{};{}", gate, pump, loader);
    return line.c_str();
  }

  // What owns the gate global: the engine loads a pointer at 0x1AD7934 and reads a byte at offset 0x10 of what it
  // points at, and nothing in this fork knows what that object is (the upstream name for that address is a dvar,
  // and the offset does not match a dvar's value). Its first field reads as a name, so it is printed once, next
  // to the gate byte, to stop every later round guessing at it.
  //
  const char* Network::ReceiveGateOwner()
  {
    static std::string line;

    const auto* owner = *reinterpret_cast<unsigned char* const*>(0x1AD7934);

    if (owner == nullptr)
      return "none";

    const auto* name = reinterpret_cast<const char*>(owner);
    auto ok = true;

    for (auto at = 0; at < 24; at++)
      if (name[at] < 0x20 || name[at] > 0x7E)
      {
        ok = false;
        break;
      }

    line = std::format("{};gate={}", ok ? std::string(name, 24) : "<not text>", owner[0x10]);
    return line.c_str();
  }

  const char* Network::NetErrorCodes()
  {
    static std::string line;

    line.clear();
    for (auto slot = 0; slot < 3; slot++)
    {
      const auto& seen = g_NetCodes[slot];
      if (seen.code == 0)
        break;

      line += std::format("{}{}x{}", slot ? " " : "", seen.code, seen.seen);
    }

    if (g_NetCodeOverflow)
      line += std::format(" +{} more", g_NetCodeOverflow);

    return line.c_str();
  }

  void Network::NetErrorCodeSeen(const int code)
  {
    g_NetErrors++; // every code that reaches here is a real socket error: the engine answers WSAEWOULDBLOCK
                   // ("nothing waiting") before it gets to this path

    for (auto& slot : g_NetCodes)
    {
      if (slot.code == code)
      {
        slot.seen++;
        return;
      }
    }

    for (auto& slot : g_NetCodes)
    {
      if (slot.code == 0)
      {
        slot.code = code;
        slot.seen = 1;
        return;
      }
    }

    g_NetCodeOverflow++; // no slot left for a seventh distinct code: keep the total honest
  }

  // IW4x-32: the socket's own identity, and one Windows switch on it.
  //
  // The identity half: the receive counters can say "nothing arrived", but they cannot say "nothing arrived at
  // THIS socket". A rebind - the port taken and the engine falling back to the next one, or a level restart that
  // runs the net setup again - leaves the probes talking to a port nobody owns any more while the server reads its
  // own socket in peace. Handle + bound port, printed only when they CHANGE, dates that instead of guessing it.
  //
  // The switch half: Windows reports an ICMP "port unreachable" that the socket itself provoked as a recvfrom
  // failure (WSAECONNRESET), and keeps reporting it for a while. This fork silences exactly that code (see
  // PacketErrorCheck), so a socket stuck in that report looks identical to a server that stopped reading: frames
  // run, nothing arrives, the log says nothing. SIO_UDP_CONNRESET is the documented Windows way to stop the
  // report; it is applied once per socket and its result is printed, because a Wine that does not know the option
  // has to show that rather than be assumed to honour it.
  //
  // SIO_UDP_CONNRESET is _WSAIOW(IOC_VENDOR, 12) = IOC_IN | IOC_VENDOR | 12 = 0x9000000C. MSVC's winsock2.h does
  // not define it (WinPcap's does, with the same arithmetic), so it is spelled out here - and the spelling is
  // worth stating, because the number that sat here before (-1073741444) was not this option.
  //
  constexpr DWORD SIO_UDP_CONNRESET = 0x9000000c; // IOC_IN 0x80000000 | IOC_VENDOR 0x10000000 | 12

  static SOCKET g_GuardedSocket (INVALID_SOCKET);

  const char* Network::GuardSocket()
  {
    const auto s (*Game::ip_socket);

    if (s == g_GuardedSocket)
      return nullptr; // the same socket as the last window: nothing new to say, and nothing to re-apply

    g_GuardedSocket = s;

    auto option = "none";
    auto port = -1;

    if (s != INVALID_SOCKET)
    {
      const BOOL reportReset = FALSE;
      auto bytes = 0UL;
      option = ::WSAIoctl(s, SIO_UDP_CONNRESET, const_cast<BOOL*>(&reportReset), sizeof(reportReset), nullptr, 0,
                          &bytes, nullptr, nullptr)
                 ? Utils::String::VA("err%d", ::WSAGetLastError())
                 : "off";

      sockaddr_in name{};
      auto len = static_cast<int>(sizeof(name));
      if (::getsockname(s, reinterpret_cast<sockaddr*>(&name), &len) != SOCKET_ERROR)
        port = ntohs(name.sin_port);
    }

    static std::string line;
    line = std::format("{};{};{}", static_cast<unsigned long long>(s), port, option);
    return line.c_str();
  }

  // IW4x-32: ask the socket what it is holding, once per stats window, with socket calls only.
  //
  // FIONREAD is the byte count the kernel has queued for us. MSG_PEEK then looks at the first waiting datagram
  // without taking it out of the queue: the four-byte sequence number comes first, then the command word, and
  // only that command word is printed - it stops at the first space or unprintable byte, so nothing else a
  // packet carries (a client's address, its userinfo) can reach the log. SO_RCVBUF is the budget that queue is
  // capped at, because a kernel drops what does not fit and tells nobody.
  //
  // Those three answer the question the in-engine counters cannot: a getstatus sitting unread in the queue means
  // the engine stopped coming to look, an empty queue means the datagrams never reached this socket, and a queue
  // at SO_RCVBUF with datagrams missing means the server was overrun. Nothing here consumes or alters a packet.
  //
  const char* Network::SocketQueue()
  {
    static std::string line;

    const auto s (*Game::ip_socket);

    if (s == INVALID_SOCKET)
    {
      line = "nosocket";
      return line.c_str();
    }

    auto port = -1;
    sockaddr_in name{};
    auto nameLen = static_cast<int>(sizeof(name));
    if (::getsockname(s, reinterpret_cast<sockaddr*>(&name), &nameLen) != SOCKET_ERROR)
      port = ntohs(name.sin_port);

    auto rcvbuf = -1;
    auto bufLen = static_cast<int>(sizeof(rcvbuf));
    if (::getsockopt(s, SOL_SOCKET, SO_RCVBUF, reinterpret_cast<char*>(&rcvbuf), &bufLen) == SOCKET_ERROR)
      rcvbuf = -1;

    auto queued = -1;
    auto peek = -1;
    auto wsa = 0;
    char head[16] = "";

    if (::ioctlsocket(s, FIONREAD, reinterpret_cast<u_long*>(&queued)) == SOCKET_ERROR)
    {
      wsa = ::WSAGetLastError();
    }
    else if (queued > 0)
    {
      char probe[64];
      peek = ::recv(s, probe, static_cast<int>(sizeof(probe)), MSG_PEEK);

      if (peek == SOCKET_ERROR)
        wsa = ::WSAGetLastError();
      else
      {
        auto out = 0;
        for (auto at = 4; at < peek && out < 15; at++)
        {
          const auto c = static_cast<unsigned char>(probe[at]);
          if (c <= 0x20 || c > 0x7E)
            break;

          head[out++] = static_cast<char>(c);
        }

        head[out] = '\0';
      }
    }

    line = std::format("{};{};{};{};{};{};{}", static_cast<unsigned long long>(s), port, rcvbuf, queued, peek,
                       head, wsa);
    return line.c_str();
  }

  void Network::OnClientPacket(const std::string& command, const networkCallback& callback)
  {
    CL_Callbacks[Utils::String::ToLower(command)] = callback;
  }

  void Network::OnClientPacketRaw(const std::string& command, const networkRawCallback& callback)
  {
    CL_RawCallbacks[Utils::String::ToLower(command)] = callback;
  }

  // IW4x-32: the two counters iw4x32's console stats line prints (see Network.hpp). Game thread only.
  static unsigned long long g_DispatchTotal = 0;
  static unsigned long long g_DispatchHandled = 0;

  unsigned long long Network::DispatchTotal()
  {
    return g_DispatchTotal;
  }

  unsigned long long Network::DispatchHandled()
  {
    return g_DispatchHandled;
  }

  bool Network::CL_HandleCommand(Game::netadr_t* address, const char* command, Game::msg_t* message)
  {
    const auto command_ = Utils::String::ToLower(command);

    g_DispatchTotal++;

    const auto offset = command_.size() + 5;
    if (static_cast<std::size_t>(message->cursize) < offset)
    {
      return false;
    }

    if (const auto rawHandler = CL_RawCallbacks.find(command_); rawHandler != CL_RawCallbacks.end())
    {
      g_DispatchHandled++;
      rawHandler->second(address, message);
      return true;
    }

    const auto handler = CL_Callbacks.find(command_);
    if (handler == CL_Callbacks.end())
    {
      // Normal handler was not found, return
      return false;
    }

    g_DispatchHandled++;

    const std::string data{ reinterpret_cast<char*>(message->data) + offset, message->cursize - offset };

    auto target = Address{ address };
    handler->second(target, data);
    return true;
  }

  __declspec(naked) void Network::CL_HandleCommandStub()
  {
    __asm
    {
      lea eax, [esp + 0xC54] // address

      pushad

      push ebp // msg_t
      push edi // command name
      push eax // netadr_t pointer
      call CL_HandleCommand
      add esp, 0xC

      test al, al

      popad

      jz unhandled

      // Exit CL_DispatchConnectionlessPacket
      push 0x5A9E0E
      retn

    unhandled:
      // Proceed
      push 0x5AA719
      retn
    }
  }

  Network::Network()
  {
    AssertSize(Game::netadr_t, 20);

    // Maximum size in NET_OutOfBandPrint
    Utils::Hook::Set<std::uint32_t>(0x4AEF08, 0x1FFFC);
    Utils::Hook::Set<std::uint32_t>(0x4AEFA3, 0x1FFFC);

    // Increase max port binding attempts from 10 to 100
    Utils::Hook::Set<std::uint8_t>(0x4FD48A, 100);

    // Increase cl_maxpackets dvar limit
    Utils::Hook::Set<std::uint8_t>(0x4050A1, 125);

    // Increase snaps (disabled for unknown reasons)
    //Utils::Hook::Set<BYTE>(0x405357, 40);

    // Set default value of snaps and cl_maxpackets dvar
    Utils::Hook::Set<std::uint8_t>(0x40535B, 30);
    Utils::Hook::Set<std::uint8_t>(0x4050A5, 125);

    // Parse port as short in Net_AddrToString
    Utils::Hook::Set<const char*>(0x4698E3, "%u.%u.%u.%u:%hu");

    // Prevent recvfrom error spam
    Utils::Hook(0x46531A, PacketErrorCheck, HOOK_JUMP).install()->quick();

    // IW4x-32: count the pump without changing it (see NetGetCountStub). Dedicated servers only.
    //
    if (Dedicated::IsEnabled())
    {
      Utils::Hook(0x4ECFF0, NetGetCountStub, HOOK_JUMP).install()->quick();
      Utils::Hook(0x6271B7, ServerPumpStub, HOOK_JUMP).install()->quick();
      Utils::Hook(0x6272BA, ServerCatchUpPumpStub, HOOK_JUMP).install()->quick();
    }

    // Handle client packets
    Utils::Hook(0x5AA703, CL_HandleCommandStub, HOOK_JUMP).install()->quick();

    // Disable unused OOB packets handlers just to be sure
    Utils::Hook::Set<std::uint8_t>(0x5AA5B6, 0xEB); // CL_SteamServerAuth
    Utils::Hook::Set<std::uint8_t>(0x5AA69F, 0xEB); // echo
    Utils::Hook::Set<std::uint8_t>(0x5AAA82, 0xEB); // SP
    Utils::Hook::Set<std::uint8_t>(0x5A9F77, 0xEB); // CL_WeNowCantHearSomeone
    Utils::Hook::Set<std::uint8_t>(0x5A9F18, 0xEB); // CL_VoiceConnectionTestPacket
    Utils::Hook::Set<std::uint8_t>(0x5A9FF3, 0xEB); // CL_HandleRelayPacket

    // For security reasons check the sender of the 'print' OOB
    Utils::Hook::Set<std::uint8_t>(0x5AA729, 0xEB);

    // Com_GetProtocol
    Utils::Hook::Set<std::uint32_t>(0x4FB501, PROTOCOL);

    // Set the default, min and max of the protocol dvar
    Utils::Hook::Set<std::uint32_t>(0x4D36A9, PROTOCOL);
    Utils::Hook::Set<std::uint32_t>(0x4D36AE, PROTOCOL);
    Utils::Hook::Set<std::uint32_t>(0x4D36B3, PROTOCOL);

    // Internal version is 99, most servers should accept it
    Utils::Hook::Set<std::uint32_t>(0x463C61, 208); // getBuildNumberAsInt

    // LSP disabled
    Utils::Hook::Set<std::uint8_t>(0x435950, 0xC3); // LSP HELLO
    Utils::Hook::Set<std::uint8_t>(0x49C220, 0xC3); // We wanted to send a logging packet, but we haven't connected to LSP!
    Utils::Hook::Set<std::uint8_t>(0x4BD900, 0xC3); // main LSP response func
    Utils::Hook::Set<std::uint8_t>(0x682170, 0xC3); // Telling LSP that we're playing a private match
    Utils::Hook::Nop(0x4FD448, 5); // Don't create lsp_socket

    // Do not run UPNP stuff at all
    Utils::Hook::Set<std::uint8_t>(0x48A135, 0xC3);
    Utils::Hook::Nop(0x48A135 + 1, 4);

    Utils::Hook::Set<std::uint8_t>(0x48A151, 0xC3);
    Utils::Hook::Nop(0x48A151 + 1, 4);

    // Don't spam the console
    Utils::Hook(0x684080, Game::Com_DPrintf, HOOK_CALL).install()->quick();

    // Disable the IWNet IP detection (default 'got ipdetect' flag to 1)
    Utils::Hook::Set<std::uint8_t>(0x649D6F0, 1);

    OnClientPacket("resolveAddress", []([[maybe_unused]] const Address& address, [[maybe_unused]] const std::string& data)
    {
      SendRaw(address, address.getString());
    });

    OnClientPacketRaw("print", [](Game::netadr_t* address, Game::msg_t* msg)
    {
      auto* clc = Game::CL_GetLocalClientConnection(0);
      if (!Game::NET_CompareBaseAdr(clc->serverAddress, *address))
      {
        Logger::Debug("Ignoring stray 'print' network message from '{}'", Game::NET_AdrToString(*address));
        return;
      }

      char printBuf[2048]{};

      const auto* s = Game::MSG_ReadBigString(msg);
      Game::I_strncpyz(clc->serverMessage, s, sizeof(clc->serverMessage));
      Game::Com_sprintf(printBuf, sizeof(printBuf), "%s", s);
      Game::Com_PrintMessage(Game::CON_CHANNEL_CLIENT, printBuf, false);
    });
  }
}
