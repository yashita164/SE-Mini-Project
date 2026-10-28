# Defect Log — Team 5 Chat Application

Add one row per confirmed defect. Keep reproduction steps and evidence specific enough
for another team member to verify the issue.

| Defect ID | Description | Severity | Reproduction Steps | Expected Result | Actual Result | Status | Assignee | Evidence |
|---|---|---|---|---|---|---|---|---|
| D-01 | Console client `file` command is not connected | High | Run `client.py`, log in, type `file` | The client asks for a recipient and a path and sends the file | "Unknown command". `send_file()` exists in `client.py` but `main()` never calls it | Open | Unassigned | `client.py` |
| D-02 | Every private message was printed twice | Low | Log in with two clients and send a private message | The message appears once | It appeared twice, and only the second copy carried the "received while you were offline" note | Fixed | Sakshi | PR #59 |
| D-03 | `FILE_CHUNK` with a list or object as `transferId` ended the connection's handler thread | Medium | Log in and send a `FILE_CHUNK` request whose `transferId` is `[1]` | An error reply and the connection stays usable | Unhandled TypeError, no reply, connection dropped | Fixed | Sakshi | PR #51, `test_file_chunk_with_non_string_transfer_id` |
| D-04 | Control characters accepted in messages and file names | Low | Send a message whose content contains a bell character | Rejected with code 400 | Accepted and delivered | Fixed | Sakshi | PR #51, `test_send_message_validation` |
| D-05 | NUL character accepted in passwords | Medium | Register with a password containing a NUL character | Rejected | Accepted; bcrypt treats NUL as an end-of-string marker, so characters after it may not count | Fixed | Sakshi | PR #51, fuzz case "register NUL in password" |
| D-06 | Logout does not close the socket (CHAT-F-003) | Low | Log in, send `LOGOUT_REQUEST`, keep using the connection | The server closes the socket | The session is removed but the socket stays open | Open | Unassigned | `handle_logout` in `server.py` |
| D-07 | One team member's SRN is missing an `S` in the README | Low | Read the team table in `README.md` | `PES2UG24CS566` | `PES2UG24C566` | Open | Unassigned | `README.md` |

## Triage snapshot — 2026-10-27

Reviewed the repository's open and closed issues using the `type:bug` label and
searched open issue text for "bug". No bug issues are currently logged. There
are no open defects that need severity/owner labels and no fixed bug issues to
close through a regression-test PR. Re-run this review when new defects are
reported; add a row above for every confirmed defect.
**Update, 2026-10-28:** the snapshot above only covered issues labelled `type:bug`. Seven defects were found while building and testing in Sprint 2 and are logged in the table above (four fixed, three open).
