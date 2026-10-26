# Deviations from the SRS, SAD and STP

> Started by issue #17 (CHAT-SR-002) so the plaintext-over-TCP deviation is
> recorded. The remaining sections belong to issue #6 (PRC-06). Add rows to
> the tables rather than replacing them.

## 1. Deviations table

| Requirement | How the implementation differs or falls short | Reason | Impact | Planned sprint |
|---|---|---|---|---|
| CHAT-SR-002 (SRS 5.1.2): passwords never transmitted or stored in plaintext | **Stored:** compliant. Passwords are hashed with bcrypt and a unique per-password salt before they are written to the database. **Transmitted:** not compliant. The client sends the password to the server in plaintext inside the `REGISTER_REQUEST` / `LOGIN_REQUEST` JSON over plain TCP. | CHAT-SR-001 (TLS) is not implemented yet, so the connection is not encrypted. | Anyone who can observe the network path can read the password. The server binds to `127.0.0.1` for development, which limits exposure to the local machine. | Resolved when CHAT-SR-001 (TLS) is delivered. |

## 2. Protocol choices the SAD does not fix

_To be completed under issue #6._

## 3. SRS ambiguities and how the team resolved them

| Ambiguity | Resolution |
|---|---|
| bcrypt only uses the first 72 bytes of a password. The SRS sets no maximum length. | Passwords must be 8-72 UTF-8 bytes; longer passwords are rejected rather than silently truncated. |

## 4. Sprint 1 recovery

_To be completed under issue #6._
