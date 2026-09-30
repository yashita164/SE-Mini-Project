

````markdown
# Chat Application — Socket Programming

A real-time multi-client chat application built using **TCP socket programming** and a **client-server architecture**.

The system is designed to support private and group communication, user authentication, presence tracking, file transfer, message persistence, delivery acknowledgements, and basic administration/moderation.

---

## 📌 Project Overview

The application follows a centralized client-server model:

- A **multi-threaded server** listens on a configurable TCP port.
- Multiple clients can connect concurrently.
- Clients maintain persistent TCP socket connections with the server.
- The server authenticates users and routes messages to the intended recipients or chat rooms.
- Chat history and other persistent data can be stored using a local file system or database.
- Heartbeat messages are used to detect dropped connections and support reconnection handling.

---

## ✨ Key Features

### 🔐 Authentication & Session Management

- User registration with unique usernames
- Username/password authentication
- Secure session management
- Clean logout and socket termination
- Online/offline presence tracking
- Detection of abrupt client disconnections

### 💬 Private Messaging

- One-to-one messaging between connected users
- Real-time message delivery without polling or refresh
- Offline message queuing
- Delivery acknowledgements
- Typing indicators
- Persistent chat history

### 👥 Group Chat / Chat Rooms

- Create named chat rooms
- Join and leave existing rooms
- Broadcast messages to room members
- Display online users globally and within rooms

### 📁 File Transfer

- Send file attachments to individual users or rooms
- Configurable maximum file size
- Chunked/buffered file transfer
- File integrity verification using checksums
- Rejection of oversized files

### 🛡️ Administration & Moderation

- System-wide announcements
- Kick users from rooms or the server
- Ban users from the server
- Logging of administrative actions with timestamps and administrator IDs

### ⚡ Reliability & Performance

- Persistent TCP connections
- Heartbeat/ping-pong mechanism
- Automatic detection and cleanup of dead connections
- Client reconnection handling
- Target of **≤500 ms** end-to-end message latency for at least **95% of messages** under normal conditions
- Designed to support up to **200 concurrent client connections**

---

## 🏗️ System Architecture

```text
                    +----------------------+
                    |      Chat Server     |
                    |----------------------|
                    | Authentication       |
                    | Session Management   |
                    | Message Router       |
                    | Room Manager         |
                    | File Transfer        |
                    | Admin/Moderation     |
                    | Persistence          |
                    +----------+-----------+
                               |
                 TCP Socket Connections
              +----------------+----------------+
              |                |                |
        +-----+-----+    +-----+-----+    +-----+-----+
        |  Client 1 |    |  Client 2 |    |  Client N |
        +-----------+    +-----------+    +-----------+

---

## 🌐 Communication

The application uses:

* **TCP/IP sockets** for client-server communication
* Configurable server port, with **5000** as the default
* A custom application-layer message protocol using **JSON or delimited text**
* Persistent socket connections
* Heartbeat/ping-pong messages for connection monitoring
* Optional TLS/SSL for encrypted communication

---

## 🔒 Security

The system includes security requirements for:

* TLS/SSL communication when deployed over untrusted networks
* Secure password hashing with a unique salt per password
* Validation and sanitization of incoming message payloads
* Session-token based authentication
* Rate limiting of connection attempts to reduce brute-force and denial-of-service attempts
* Role-based authorization for administrative operations

---

## 📊 Non-Functional Requirements

| Requirement             | Target                                                       |
| ----------------------- | ------------------------------------------------------------ |
| Message latency         | ≤500 ms for at least 95% of messages under normal conditions |
| Concurrent clients      | At least 200                                                 |
| Dead connection cleanup | Within 30 seconds                                            |
| Chat history retention  | At least 90 days                                             |
| Client responsiveness   | Socket I/O should not block the UI                           |

---

## 📂 Project Structure

The exact implementation structure may vary depending on the final codebase.

```text
chat-application/
│
├── server/
│   ├── server
│   ├── authentication
│   ├── message_router
│   ├── room_manager
│   ├── connection_manager
│   └── persistence
│
├── client/
│   ├── client
│   ├── ui
│   └── networking
│
├── tests/
│   ├── authentication
│   ├── messaging
│   ├── groups
│   ├── file_transfer
│   ├── security
│   └── performance
│
├── docs/
│   └── SRS.pdf
│
└── README.md
```

> **Note:** Update this structure to match the actual source-code organization of the final project.

---

## 🚀 Getting Started

### Prerequisites

Install the dependencies required by the final implementation of the project.

The application requires:

* A system capable of running TCP socket applications
* Network connectivity between server and clients
* Appropriate runtime/compiler dependencies used by the implementation

### Running the Server

Start the chat server on the configured host and port.

```bash
# Example
./server
```

The default port specified in the SRS is:

```text
5000
```

### Running a Client

Start a client and provide the server's host/IP address and port.

```bash
# Example
./client
```

Multiple clients can connect to the same server and communicate in real time.

> **Note:** Replace the example commands above with the exact commands used by the final implementation.

---

## 🧪 Testing

The SRS defines acceptance test suites covering:

* Authentication
* Private messaging
* Group chat
* File transfer
* Administration and moderation
* Performance and load
* Security
* Reliability and reconnection

### Test Case Categories

```text
TC-Auth-01 ... TC-Auth-04

TC-Msg-01 ... TC-Msg-06

TC-Grp-01 ... TC-Grp-04

TC-File-01 ... TC-File-02

TC-Admin-01 ... TC-Admin-03

TC-Perf-01

TC-Scale-01

TC-Rel-01

TC-Ops-01

TC-UX-01

TC-Sec-01 ... TC-Sec-05
```

---

## 🔗 Requirements Traceability

The project maintains a **Requirements Traceability Matrix (RTM)** linking requirements to:

* System modules
* Test cases
* Requirement sections
* Implementation status

The RTM helps verify that the functional, non-functional, and security requirements are covered by the project and its tests.

---

## 📚 Documentation

The Software Requirements Specification contains:

1. **Introduction**
2. **Overall Description**
3. **External Interface Requirements**
4. **Detailed System Features**
5. **Non-Functional Requirements**
6. **Quality Attributes & Acceptance Tests**
7. **UML Use-Case Diagrams**
8. **Requirements Traceability Matrix**

---

## 👨‍💻 Team

**Team Number:** 5

| Name                   | SRN           |
| ---------------------- | ------------- |
| Sakshi Srinivas Ghodke | PES2UG24CS914 |
| Yashita Anand          | PES2UG24CS613 |
| Ujwal K                | PES2UG24C566  |
| Varun Sahu             | PES2UG24CS576 |

---

## 📌 Project Information

**Project:** Chat Application (Socket Programming)

**Course:** Software Engineering

**Version:** 1.0

---

## 📄 License

This project was developed as an academic Software Engineering project.

```

### One thing before you paste it

The only section I **wouldn't blindly keep as-is** is `Project Structure` and `Getting Started`, because those need to match your **actual code**.

Once you show me the files that are actually in your GitHub repo, I can make those two sections **100% accurate** instead of having the generic examples.
```
````
