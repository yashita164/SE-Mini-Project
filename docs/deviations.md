# Deviations from the SRS, SAD and STP

> Started by issue #17 (CHAT-SR-002) so the plaintext-over-TCP deviation is
> recorded. The remaining sections belong to issue #6 (PRC-06). Add rows to
> the tables rather than replacing them.

## 1. Deviations table

| Requirement | How the implementation differs or falls short | Reason | Impact | Planned sprint |
|---|---|---|---|---|
| CHAT-SR-002 (SRS 5.1.2): passwords never transmitted or stored in plaintext | **Stored:** compliant. Passwords are hashed with bcrypt and a unique per-password salt before they are written to the database. **Transmitted:** not compliant. The client sends the password to the server in plaintext inside the `REGISTER_REQUEST` / `LOGIN_REQUEST` JSON over plain TCP. | CHAT-SR-001 (TLS) is not implemented yet, so the connection is not encrypted. | Anyone who can observe the network path can read the password. The server binds to `127.0.0.1` for development, which limits exposure to the local machine. | Resolved when CHAT-SR-001 (TLS) is delivered. |
| CHAT-F-002 (SRS 4.1): retrying login on the same TCP connection is unspecified. | The server returns an invalid-credentials response and closes the socket. A client must reconnect before retrying login. | Keep authentication attempts isolated and satisfy TC-Auth-02's socket-close behavior. | A user who mistypes a password must reconnect before trying again. | Sprint 1 |
| CHAT-SR-001 (SRS 5.1.2): TLS/SSL on all socket communication | Not implemented. All traffic is plain TCP and the server binds to `127.0.0.1` only. | Out of time within the two sprints; development runs on localhost. | Credentials and messages are readable by anyone who can observe the network path. Acceptable only for local development. | Not planned |
| CHAT-F-004 (SRS 4.1) and CHAT-NF-003 (SRS 5): heartbeat and dead-connection cleanup within 30 s | Not implemented. A disconnect is detected only when the socket closes or raises an error. There is no ping/pong timeout. | Messaging, security and administration were prioritised over keep-alive handling. | A silently dropped connection stays marked online until the operating system reports it. TC-Rel-01 cannot be run as written. | Not planned |
| CHAT-SR-005 (SRS 5.1.2): per-IP rate limiting | Not implemented. A rejected login closes the connection, but a client can reconnect and retry immediately. | Medium priority and out of time. | Brute-force login attempts are not throttled. | Not planned |
| SRS 3.1: graphical chat window with contact list and file-attach button | The client is a console application with typed commands. | A console client was enough to demonstrate the protocol within the sprint. | No contact list, status indicators or attach button. | Not planned |
| CHAT-F-030 (SRS 4.4): send a file to a user or a room | Files can be sent to one online user only. An offline recipient is rejected and files cannot be sent to a room. | Chunks are relayed straight to the recipient, with no server-side file storage. | No offline or group file sharing. | Not planned |
| CHAT-F-041 (SRS 4.5): kick or ban a user from a room or the server | Moderation applies to the whole server only. There is no per-room moderation and no mute. | Rooms were added late in Sprint 2. | An administrator cannot remove a user from a single room without removing them from the server. | Not planned |
| CHAT-NF-004 (SRS 5): history retrievable for at least 90 days | All messages are kept in the database, but the history request returns only the latest 50. | A simple limit keeps the response small. | Older messages are stored but cannot be fetched through the client. | Not planned |

## 2. Protocol choices the SAD does not fix

_To be completed under issue #6._

## 3. SRS ambiguities and how the team resolved them

| Ambiguity | Resolution |
|---|---|
| bcrypt only uses the first 72 bytes of a password. The SRS sets no maximum length. | Passwords must be 8-72 UTF-8 bytes; longer passwords are rejected rather than silently truncated. |

## 4. Sprint 1 recovery

_To be completed under issue #6._
