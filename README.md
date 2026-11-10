# Chat Application — Socket Programming

A real-time multi-client chat application developed using **TCP Socket Programming** and a **client-server architecture**.

## Features

- User registration and authentication
- One-to-one private messaging
- Group chat and chat rooms
- Online/offline user presence
- Typing indicators
- Message delivery acknowledgements
- Persistent chat history
- File transfer
- Admin announcements and moderation
- Connection monitoring and reconnection handling

## Technologies

- TCP/IP Sockets
- Client-Server Architecture
- Multithreading
- JSON-based / custom socket communication
- File Handling
- Optional TLS/SSL for secure communication

## Architecture

**Client 1** ──┐  
**Client 2** ──┼──► **Chat Server**  
**Client N** ──┘  

The server handles:

- Authentication
- Message Routing
- Room Management
- File Transfer
- Administration

## Project Requirements

- Real-time message delivery using TCP sockets
- Support for multiple concurrent clients
- Persistent chat history
- Secure authentication and communication
- Reliable connection and disconnection handling

## Documentation

The complete **Software Requirements Specification (SRS)** includes:

- Functional and Non-Functional Requirements
- Security Requirements
- UML Use-Case Diagrams
- Acceptance Tests
- Requirements Traceability Matrix (RTM)

## Team

**Team 5**

| Name | SRN |
|---|---|
| Sakshi Srinivas Ghodke | PES2UG24CS914 |
| Yashita Anand | PES2UG24CS613 |
| Ujwal K | PES2UG24CS566 |
| Varun Sahu | PES2UG24CS576 |

## Project Information

**Course:** Software Engineering  
**Problem Statement:** Chat Application (Socket Programming)  
**Version:** 1.0

## Development setup

Use **Python 3.13** and a virtual environment. The commands below work from a
fresh clone. On Windows, run them in PowerShell; on macOS or Linux, use the
equivalent `python3` command and activate with `source .venv/bin/activate`.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start the server in the first terminal:

```powershell
python server.py
```

Open two more terminals, activate the same environment in each, and start a
client in each terminal:

```powershell
python client.py
```

The server listens on `127.0.0.1:5000`. In each client, use `register` to
create a distinct account and `login` to authenticate. The default database
(`chat.db`) is created beside the server code on first start.

### TLS/SSL deployment

Supply a PEM certificate and private key to enable TLS 1.2+ on the server:

```powershell
$env:CHAT_TLS_CERT_FILE = "C:\\chat\\server-cert.pem"
$env:CHAT_TLS_KEY_FILE = "C:\\chat\\server-key.pem"
python server.py
```

Start clients in TLS mode with the issuing CA certificate:

```powershell
$env:CHAT_TLS_ENABLED = "1"
$env:CHAT_TLS_CA_FILE = "C:\\chat\\server-ca.pem"
python client.py
```

Production deployments must use a certificate issued by a trusted CA. Keeping the private key outside the repository and restricting its file permissions is required. Without certificate settings, the server intentionally remains in development plaintext mode for local compatibility.

Run the automated test suite from the repository root:

```powershell
python -m pytest -v
```

### Message latency load test

Run TC-Perf-01 with 100 concurrent clients and 1,000 messages:

```powershell
python scripts/measure_message_latency.py --clients 100 --samples-per-client 10 --raw-output docs/performance/tc-perf-01-raw.csv
```

The script prints the p95 latency and exits nonzero if the p95 exceeds 500 ms. Raw samples and run metadata are written beside the requested CSV path. No defect is logged unless the measured p95 misses the target.

### Concurrent client load test

Run TC-Scale-01 with 200 authenticated clients:

```powershell
python scripts/measure_concurrent_clients.py --clients 200 --stability-seconds 5 --raw-output docs/performance/tc-scale-01-raw.csv
```

The script verifies every login session remains active after the stability period and exits nonzero if any connection drops.

### Login rate limiting

The server rejects rapid failed login attempts from the same source IP. The default limit is 5 failures in 60 seconds, followed by a 60-second lockout. A successful login clears the IP's failure state. Configuration is available through:

```powershell
$env:CHAT_LOGIN_RATE_MAX_FAILURES = "5"
$env:CHAT_LOGIN_RATE_WINDOW_SECONDS = "60"
$env:CHAT_LOGIN_RATE_LOCKOUT_SECONDS = "60"
```

Throttled connections receive `LOGIN_RESPONSE` with code `429` and are closed.

GitHub Actions runs this same command on every push and pull request using
Python 3.13.

## Tkinter desktop GUI

The GUI foundation lives in `gui/`: `app.py` owns the Tk window and navigation,
`client_core.py` is the shared TCP client, and `dashboard.py` displays online
users, rooms and connection status. Tkinter is part of the Python standard
library and adds no package to `requirements.txt`; install a Python build that
includes Tcl/Tk.

Start `server.py` in one terminal as described above, then launch the GUI from
the repository root in another terminal:

```powershell
python -m gui.app
```

The shared client speaks the server's newline-delimited UTF-8 JSON protocol.
It reads responses on a background thread and places protocol events in a
`queue.Queue`; the Tk application drains that queue with `root.after()` and
updates widgets only on the main thread. The same client layer supports
registration/login, private and room messaging, room/user lists, paginated
history, typing indicators and both directions of the existing file-transfer
protocol. Received files are size/checksum verified and saved under
`received_files/`. It honors the existing `CHAT_TLS_ENABLED` and
`CHAT_TLS_CA_FILE` client settings.

The GUI is being integrated in modules by the team. `gui.auth_view.AuthView`
and the private-chat, room-chat and file screens are extension points and may
not yet be present. Until those modules are integrated, the app shows an
authentication placeholder and chat-screen placeholders; the dashboard and
shared client API are available for their implementation. The backend has no
push notification for changes to the global online-user list, so the dashboard
refreshes it periodically. Unexpected disconnections are reported; automatic
reconnection is not implemented. The server closes a connection after failed
login, so the authentication view must reconnect before another attempt.

`ClientCore` is the integration surface for screens:

- `connect()` starts connecting in the background. Read `connection_state`,
  `is_connected`, `is_authenticated` and `username` for current state.
- `register(username, password)` and `login(username, password)` send the
  existing authentication requests.
- `send_private_message(recipient, content)` and
  `send_room_message(room, content)` use the existing `SEND_MESSAGE` format.
- `create_room(room)`, `join_room(room)`, `leave_room(room)`, `list_rooms()`
  and `list_users(room=None)` expose the backend's room and presence requests.
- `request_history(limit=50, before_id=None)` requests one history page;
  `nextBeforeId` in the `HISTORY_RESPONSE` is the cursor for the next older
  page.
- `send_typing(destination, is_typing, room=False)` and
  `send_file(destination, filepath)` expose the existing typing and transfer
  protocols. File sends run in a worker; received files are verified and
  reported through a `file_transfer` event with the saved path.
- `logout()` requests logout and `close()` shuts down the connection. Consume
  server responses and local lifecycle/error events from `client.events`.

Server messages are queued unchanged as dictionaries with a `type`.
Client-generated events use `_event`: `connection`, `client_error` or
`file_transfer`. Screens should implement `handle_event(event)` and let the app
deliver queued events; they must not read the socket or update Tk widgets from
worker threads.

The app loads optional teammate views using these contracts: `gui.auth_view`
exports `AuthView(parent=..., client=..., on_authenticated=...)`;
`gui.private_chat` exports `PrivateChatView(parent=..., client=..., target=...,
on_back=...)`; `gui.room_chat` exports `RoomChatView` with the same feature-view
arguments; and `gui.files` may export `FilesView` with those arguments.
Factories can also be passed directly to `ChatApplication`.

## Administrator announcements

Administrators are identified by their exact registered usernames in the
server's `CHAT_ADMIN_USERS` environment variable. Set one or more comma-separated
usernames before starting the server; an empty or unset value grants no
administrator privileges. For example, in PowerShell:

```powershell
$env:CHAT_ADMIN_USERS = "site_admin,moderator1"
python server.py
```

An authenticated administrator can use the `announce` client command to send
a system-wide announcement. Other authenticated users may see the command but
the server rejects their request. The server sends the announcement to all
currently connected clients.

## Server-wide moderation

Moderation applies to the entire server; there is no per-room moderation. An
administrator can use `kick` to disconnect an online
user or `ban` to persist a server-wide ban and disconnect that user if online.
Banned users are refused at their next login, including after the server
restarts. Both commands accept an optional reason.

Successful administrator announcements, kicks, and bans are recorded in the
SQLite `admin_audit_log` table with the administrator username, UTC timestamp,
action, target when applicable, and announcement text or moderation reason.

## Chat rooms

Clients can create and join named rooms and exchange messages with the other
members who are online. Room commands in the client:

| Command | What it does |
|---|---|
| `create` | Prompts for a room name, creates the room and joins it |
| `join` | Prompts for a room name and joins an existing room |
| `leave` | Prompts for a room name and leaves it |
| `rooms` | Lists existing rooms |
| `users` | Lists everyone online; enter a room name at the prompt to list that room's members (you must be a member) |
| `room` | Prompts for a room name and a message, then sends it to every online member |

Room names are 3–32 characters (letters, digits, `_` and `-`) and are
case-insensitive. Rooms are held in server memory, so they are cleared when the
server restarts, and room messages are delivered only to members who are
online. A file can be sent to a room with `file` using `#room` as the target
(for example `#general`) instead of a username.

## File transfers

After logging in, use `file` and enter a recipient username or `#room`, followed
by the local file path. Files are limited to 1 MiB; both client and server
enforce this limit. Recipients receive files in `received_files/` after the
SHA-256 checksum is verified. Room transfers reach online room members only,
with membership checked again when delivery begins. Uploads expire after 120
seconds without a valid chunk.
