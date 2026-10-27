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
| Ujwal K | PES2UG24C566 |
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

Run the automated test suite from the repository root:

```powershell
python -m pytest -v
```

GitHub Actions runs this same command on every push and pull request using
Python 3.13.

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

This version does not implement chat rooms, so moderation currently applies to
the entire server. An administrator can use `kick` to disconnect an online
user or `ban` to persist a server-wide ban and disconnect that user if online.
Banned users are refused at their next login, including after the server
restarts. Both commands accept an optional reason.
