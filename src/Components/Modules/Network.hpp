#pragma once

namespace Components
{
  class Network : public Component
  {
  public:
    class Address
    {
    public:
      Address();
      Address(const std::string& addrString);
      Address(sockaddr* addr);
      Address(sockaddr addr) : Address(&addr) {}
      Address(sockaddr_in addr) : Address(&addr) {}
      Address(sockaddr_in* addr) : Address(reinterpret_cast<sockaddr*>(addr)) {}
      Address(Game::netadr_t addr) : address(addr) {}
      Address(Game::netadr_t* addr) : Address(*addr) {}
      Address(const Address& obj) = default;
      bool operator!=(const Address &obj) const { return !(*this == obj); }
      bool operator==(const Address &obj) const;

      void setPort(unsigned short port);
      [[nodiscard]] unsigned short getPort() const;
      [[nodiscard]] unsigned short getPortRaw() const;

      void setIP(DWORD ip);
      void setIP(Game::netIP_t ip);
      [[nodiscard]] Game::netIP_t getIP() const;

      void setType(Game::netadrtype_t type);
      [[nodiscard]] Game::netadrtype_t getType() const;

      [[nodiscard]] sockaddr getSockAddr();
      void toSockAddr(sockaddr* addr);
      void toSockAddr(sockaddr_in* addr);
      [[nodiscard]] const Game::netadr_t* get() const noexcept;
      [[nodiscard]] const char* getCString() const;
      [[nodiscard]] std::string getString() const;

      [[nodiscard]] bool isLocal() const noexcept;
      [[nodiscard]] bool isSelf()  const noexcept;
      [[nodiscard]] bool isValid() const noexcept;
      [[nodiscard]] bool isLoopback() const noexcept;

    private:
      Game::netadr_t address;
    };

    using networkCallback = std::function<void(Address&, const std::string&)>;
    using networkRawCallback = std::function<void(Game::netadr_t*, Game::msg_t* msg)>;

    Network();

    static const char* AdrToString(const Address& a, bool port = false);

    static std::uint16_t GetPort();

    // Send quake-styled binary data
    static void Send(const Address& target, const std::string& data);
    static void Send(Game::netsrc_t type, const Address& target, const std::string& data);

    // Allows sending raw data without quake header
    static void SendRaw(const Address& target, const std::string& data);
    static void SendRaw(Game::netsrc_t type, const Address& target, const std::string& data);

    // Send quake-style command using binary data
    static void SendCommand(const Address& target, const std::string& command, const std::string& data = {});
    static void SendCommand(Game::netsrc_t type, const Address& target, const std::string& command, const std::string& data = {});

    static void Broadcast(unsigned short port, const std::string& data);
    static void BroadcastRange(unsigned int min, unsigned int max, const std::string& data);
    static void BroadcastAll(const std::string& data);

    static void OnClientPacket(const std::string& command, const networkCallback& callback);
    static void OnClientPacketRaw(const std::string& command, const networkRawCallback& callback);

    // IW4x-32: connectionless packets the engine handed to CL_HandleCommand since startup, and how many of them
    // found a handler. A crowded server that stops answering rcon while its frame loop keeps running is either
    // not reading packets or not dispatching them, and these two numbers say which. Counters only: they do not
    // change what any packet does. Read by the IW4x32 component's console stats line.
    static unsigned long long DispatchTotal();
    static unsigned long long DispatchHandled();

    // IW4x-32: the socket errors this fork silences, counted (WSAECONNRESET / WSAENETRESET are jumped past in
    // silence by PacketErrorCheck, so a socket that started failing leaves no trace in the log at all).
    static unsigned long long NetReadErrors();
    static const char* NetErrorCodes(); // "10054x7 10053x1", most seen first, up to 3 codes

    // IW4x-32: how often the engine's receive function was reached for a packet (0x4ECFF0), and how often the
    // dedicated server frame function ran its own pump (0x6271B7 and 0x6272BA) - all counted at whole 5-byte
    // call / jump sites by stubs that change nothing. This is the difference between "the server never asked",
    // "it asked and nothing was there" and "it asked, something was there, and it moved on".
    static unsigned long long NetGetCalls();
    static unsigned long long ServerPumpCalls();

    // IW4x-32: the three globals that decide whether a dedicated server collects datagrams at all (see the
    // comment at their definition): the gate the per-frame wait and the UDP read both sit behind, the byte that
    // gates the server frame function's own pump, and the loader state that makes the wait do nothing.
    //
    static const char* ReceiveGates(); // "gate;pump;loader" - once per stats window
    static const char* ReceiveGateOwner(); // what the gate global points at, printed once

    // IW4x-32: the game socket's identity - its handle, the port it is really bound to, and whether the Windows
    // UDP error report was turned off on it. A rebind (port fallback, level restart) would leave every later
    // packet going to a socket nobody talks to, and the line goes to the log only when the identity CHANGES, so a
    // rebind is dated instead of inferred. Read-only apart from the option below, and dedicated servers only.
    //
    static const char* GuardSocket(); // "fd;port;option" - call it once per stats window

    // IW4x-32: what the socket itself is holding right now - the bytes waiting in its receive queue, the first
    // waiting datagram's command word (looked at with MSG_PEEK, never taken out of the queue), and the size of
    // that queue's budget. Asked with socket calls only: no engine code is touched, because a stub inside the
    // engine's own receive path is what crashed a server round (see the report). "A getstatus sits in the queue
    // unread" and "the queue is empty" look identical from inside the engine and opposite from out here.
    //
    static const char* SocketQueue(); // "fd;port;rcvbuf;queued;peek;head;wsa" - once per stats window

  private:
    static std::unordered_map<std::string, networkCallback> CL_Callbacks;
    static std::unordered_map<std::string, networkRawCallback> CL_RawCallbacks;

    static void PacketErrorCheck();
    static void NetErrorCodeSeen(int code);
    static void NetGetCounted();
    static void ServerPumpCounted();
    static void NetGetCountStub();
    static void ServerPumpStub();
    static void ServerCatchUpPumpStub();

    static bool CL_HandleCommand(Game::netadr_t* address, const char* command, Game::msg_t* message);

    static void CL_HandleCommandStub();
  };
}

template <>
struct std::hash<Components::Network::Address>
{
  std::size_t operator()(const Components::Network::Address& x) const noexcept
  {
    return std::hash<std::uint32_t>()(*reinterpret_cast<const std::uint32_t*>(x.getIP().bytes)) ^ std::hash<std::uint16_t>()(x.getPort());
  }
};
