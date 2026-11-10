# Deviations from the SRS, SAD and STP

> Started by issue #17 (CHAT-SR-002) so the plaintext-over-TCP deviation is
> recorded. The remaining sections belong to issue #6 (PRC-06). Add rows to
> the tables rather than replacing them.

## 1. Deviations table

| Requirement | How the implementation differs or falls short | Reason | Impact | Planned sprint |
|---|---|---|---|---|
| CHAT-SR-002 (SRS 5.1.2): passwords never transmitted or stored in plaintext | **Stored:** compliant. Passwords are hashed with bcrypt and a unique per-password salt before they are written to the database. **Transmitted:** compliant in TLS deployment mode; encrypted JSON travels inside a TLS 1.2+ connection. Plaintext development mode is limited to localhost and is explicitly warned by the server startup output. | TLS is enabled through deployment environment variables; no certificates are bundled in the repository. | The password field remains a protocol value, but transport encryption prevents observation from the network when TLS mode is used correctly. | Sprint 2 stretch issue #40 |
| CHAT-F-002 (SRS 4.1): retrying login on the same TCP connection is unspecified. | The server returns an invalid-credentials response and closes the socket. A client must reconnect before retrying login. | Keep authentication attempts isolated and satisfy TC-Auth-02's socket-close behavior. | A user who mistypes a password must reconnect before trying again. | Sprint 1 |
| CHAT-SR-001 (SRS 5.1.2): TLS/SSL on all socket communication | Implemented when `CHAT_TLS_CERT_FILE` and `CHAT_TLS_KEY_FILE` configure the server, and `CHAT_TLS_ENABLED=1` plus `CHAT_TLS_CA_FILE` configure the client. Both sides require TLS 1.2+. Plaintext mode remains the compatibility default for localhost development and emits a server startup warning. | Deployment configuration must provide a certificate and trust chain; development still supports the repository's no-certificate setup. | Certificates and private keys are outside the repository. Untrusted or misconfigured deployments risk plaintext traffic unless TLS environment settings are applied. | Sprint 2 stretch issue #40 |
| CHAT-F-004 (SRS 4.1) and CHAT-NF-003 (SRS 5): heartbeat and dead-connection cleanup within 30 s | Implemented with 10-second server PING messages, PONG responses from the client, and a 30-second inactivity timeout. Timed-out clients are removed from active presence, their rooms are left, their sessions are invalidated, and their sockets are closed. | A bounded heartbeat prevents silently dropped clients from remaining online. | The console client replies automatically to PING; unresponsive clients are cleaned up within the 30-second requirement. | Sprint 2 |
| CHAT-SR-005 (SRS 5.1.2): per-IP rate limiting | Implemented. The server limits failed login attempts by source IP, allowing 5 failures in a rolling 60-second window before returning HTTP-style protocol code 429 for 60 seconds. Successful authentication clears the IP's failure state. Thresholds and durations are configurable with `CHAT_LOGIN_RATE_MAX_FAILURES`, `CHAT_LOGIN_RATE_WINDOW_SECONDS`, and `CHAT_LOGIN_RATE_LOCKOUT_SECONDS`. | A bounded lockout slows brute-force attempts without permanently blocking an IP. | A distributed deployment needs shared state if it runs multiple server processes behind a load balancer. | Sprint 2 issue #41 |
| SRS 3.1: graphical chat window with contact list and file-attach button | The client is a console application with typed commands. | A console client was enough to demonstrate the protocol within the sprint. | No contact list, status indicators or attach button. | Not planned |
| CHAT-F-030 (SRS 4.4): send a file to a user or a room | Files are sent to one connected user or online members of a room. Room membership is checked again when delivery begins. The client and server enforce the documented 1 MiB maximum; transfers use 8 KiB chunks and SHA-256 verification. Abandoned uploads expire after 120 seconds without a valid chunk. | Chunks are relayed directly, with no server-side file storage. | No offline file delivery. | Sprint 2 issue #30 |
| CHAT-F-041 (SRS 4.5): kick or ban a user from a room or the server | Moderation applies to the whole server only. There is no per-room moderation and no mute. | Rooms were added late in Sprint 2. | An administrator cannot remove a user from a single room without removing them from the server. | Not planned |
| CHAT-NF-004 (SRS 5): history retrievable for at least 90 days | Authenticated history queries return messages from the last 90 days and support cursor pagination in chronological order. Messages older than the query window remain stored. | Indexed timestamp/user queries keep pages bounded without deleting retained history. | History remains queryable across the full required period; records older than 90 days are not returned by the history API. | Sprint 2 issue #38 |
| CHAT-F-013 (SRS 4.2): the sender's UI shows a "delivered" tick | The console client prints `✓ Delivered` when the server confirms delivery, and `Saved, not delivered yet: recipient is offline` when the message is only stored. | The client is a console application. | The acknowledgement works as specified; there is no graphical tick. | Sprint 2 |
| CHAT-F-020 to CHAT-F-023 (SRS 4.3): chat rooms and online-user lists | Rooms are kept in memory and are lost when the server restarts. Room messages are saved under the sender only, so history shows them to the sender alone. Rooms have no owner. | Persistent rooms would need extra database tables and were out of time. | Users must recreate rooms after a server restart. | Not planned |

## 2. Protocol choices the SAD does not fix

- **Framing:** each request and response is one JSON object on one line, UTF-8 encoded, ending with a newline. A request line may be at most 16 KiB; longer input gets error 413 and the connection is closed.
- **Sessions:** a successful login returns a random session token. Every later request must carry that token, and the server checks it on each request. A connection holds one session; logging in again from another connection closes the older one.
- **Errors:** failures use HTTP-style numeric codes in the response (400 bad request, 401 not authenticated, 404 not found, 409 conflict, 413 too large, 500 internal error).
- **Messages:** private messages are limited to 4,000 characters. The sender gets `MESSAGE_DELIVERED` when the message was written to the recipient's connection, or `MESSAGE_STORED` when the recipient is offline. Stored messages are replayed in order at the recipient's next login.
- **Typing indicator:** sent to the named online user or online members of the selected room. Explicit start/stop changes are forwarded immediately and deduplicated; disconnects clear the indicator, and stale states expire within two seconds.
- **File transfer:** the sender announces the file (name, size, SHA-256 checksum), then sends 8 KiB base64 chunks. The server checks metadata, size, and checksum before forwarding to the online user or room members; recipients verify the checksum again. The size limit is 1 MiB.
- **File-transfer timeout:** an upload is discarded after 120 seconds without a valid chunk; each valid non-final chunk resets the idle timeout.
- **Administration:** administrators are the usernames listed in the `CHAT_ADMIN_USERS` environment variable of the server. Announcements, kicks and bans are written to an audit table with a timestamp and the administrator's name.
- **Timestamps:** ISO 8601 in UTC.

## 3. SRS ambiguities and how the team resolved them

| Ambiguity | Resolution |
|---|---|
| bcrypt only uses the first 72 bytes of a password. The SRS sets no maximum length. | Passwords must be 8-72 UTF-8 bytes; longer passwords are rejected rather than silently truncated. |
| The SRS sets no maximum message size. | Messages are limited to 4,000 characters, inside a 16 KiB request line. Larger input is rejected with code 413. |
| The SRS says "configured size limit" for files but gives no value. | The limit is 1 MiB per file, set as a constant in `server.py` and `client.py`. |
| The SRS does not say how usernames are written. | Usernames are 3 to 24 letters, digits or underscores, and are not case-sensitive. |
| The SRS does not say who an administrator is. | The server operator lists administrator usernames in the `CHAT_ADMIN_USERS` environment variable. |

## 4. Sprint 1 recovery

Sprint 1 was planned for 19–23 October. The first working prototype (registration, login, private messaging and typing indicators) and the Sprint 1 demo video were committed on 25 October, and the remaining Sprint 1 items (bcrypt verification, offline message queue, latency test, defect log, PR workflow, and authentication and CI setup) were merged on 26 October, so Sprint 1 finished about three days after its planned end.

Items still open at the end of Sprint 1 were labelled `carried-from-sprint-1` and moved into Sprint 2, including the RTM update (#7) and this deviations document (#6).

Recovery: the delay came from completing and integrating the remaining Sprint 1 functionality, tests and the CI and pull-request workflow after the initial prototype was committed on 25 October. The team finished these through follow-up pull requests merged on 26 October, with automated tests running in CI on every push and pull request. Only the documentation items (#6 and #7) were carried into Sprint 2, and all code work for Sprint 2 followed the same pull-request workflow.
