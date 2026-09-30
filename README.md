````markdown
# Chat Application — Socket Programming

A real-time multi-client chat application developed using **TCP Socket Programming** and a **client-server architecture**.

## Features

- User registration and authentication
- One-to-one private messaging
- Group chat and chat rooms
- Online/offline user presence
- Typing indicators
- Message delivery acknowledgements
- Chat history
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

```text
       +----------------+
       |     Server     |
       |----------------|
       | Authentication |
       | Message Router |
       | Room Manager   |
       | File Transfer  |
       | Admin Module   |
       +-------+--------+
               |
        TCP Socket Connection
        /        |        \
       /         |         \
+---------+ +---------+ +---------+
| Client 1| | Client 2| | Client N|
+---------+ +---------+ +---------+
```

## Project Requirements

* Real-time message delivery using TCP sockets
* Support for multiple concurrent clients
* Persistent chat history
* Secure authentication and communication
* Reliable connection and disconnection handling

## Documentation

The complete Software Requirements Specification (SRS) includes:

* Functional & Non-Functional Requirements
* Security Requirements
* UML Use-Case Diagrams
* Acceptance Tests
* Requirements Traceability Matrix (RTM)

## Team

**Team 5**

* Sakshi Srinivas Ghodke — PES2UG24CS914
* Yashita Anand — PES2UG24CS613
* Ujwal K — PES2UG24C566
* Varun Sahu — PES2UG24CS576

## Project

**Course:** Software Engineering
**Problem Statement:** Chat Application (Socket Programming)
**Version:** 1.0

