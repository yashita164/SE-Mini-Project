# Test Case Document — Team 5 Chat Application

**Version:** 1.1 (Sprint 3)
**Backlog ID:** CHAT-TEST-001
**Related issue:** #78
**Status:** Draft

## 1. Purpose and scope

This document lists every test case for the Chat Application: the 29 cases defined in the SRS (acceptance criteria, Sections 4 and 5) and executed under the Software Test Plan (STP), plus the cases added in Sprints 2 and 3. It gives the steps, test data and expected result for each case, and points to the automated test or script that checks it. Execution results are in the [test report](test-report.md) and the requirement mapping is in the [RTM](RTM-Issue-12.md).

## 2. Environment and test data

| Item | Details |
|---|---|
| Server | `python server.py` (Python 3.13, SQLite database) |
| Automated tests | `python -m pytest -v`. Each server test starts a real `ChatServer` on a free local port with a temporary database (`tests/chat_harness.py`) and talks to it over TCP |
| Manual tests | Terminal client (`python client.py`) or desktop GUI (`python -m gui.app`) against a running server |
| Test accounts | `alice`, `bob`, `carol`, password `correct-horse` unless a case says otherwise |
| Protocol | Newline-delimited JSON over TCP. Requests other than registration and login carry the session token |

## 3. Authentication (CHAT-F-001 to CHAT-F-004)

| ID | Requirement | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-Auth-01 | CHAT-F-001 Register a unique username | 1. Register `alice`.<br>2. Register `alice` again.<br>3. Register with an empty or invalid username or password. | The first registration succeeds. The duplicate is rejected with an error. Invalid input is rejected. | `test_auth.py`: `test_auth_01_register_unique_username`, `test_auth_01_reject_duplicate_username`, `test_auth_01_reject_invalid_registration`; `test_server.py`: `test_server_register_and_login`, `test_server_rejects_duplicate_registration` |
| TC-Auth-02 | CHAT-F-002 Authenticate before access | 1. Register `alice`.<br>2. Log in with a wrong password.<br>3. Log in with the correct password. | The wrong password gets an error and the socket is closed. The correct login returns a session token. | `test_auth_02_valid_login_returns_session`, `test_auth_02_reject_invalid_password`, `test_server_rejects_invalid_login` |
| TC-Auth-03 | CHAT-F-003 Terminate session on logout | 1. Log in as `alice`.<br>2. Send a logout request. | The server closes the socket and removes `alice` from the active client list within 1 second. | `test_successful_logout_closes_connection_and_removes_active_client` |
| TC-Auth-04 | CHAT-F-004 Detect abrupt disconnection | 1. Log in as `alice`.<br>2. Close the connection without logging out. | The server removes `alice` from presence and sessions within the heartbeat timeout (heartbeat interval 10 s, timeout 30 s). | `test_silent_disconnect_is_removed_from_presence_and_session` |

## 4. Messaging (CHAT-F-010 to CHAT-F-015)

| ID | Requirement | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-Msg-01 | CHAT-F-010 Send private message | 1. Log in `alice`, `bob`, `carol`.<br>2. `alice` sends a message to `bob`. | Only `bob` receives it. `carol` receives nothing. | `test_private_message_reaches_only_recipient` |
| TC-Msg-02 | CHAT-F-011 Real-time delivery | 1. `alice` and `bob` online.<br>2. `alice` sends a message. | `bob` receives it without polling, within the 500 ms latency target. | `test_tc_msg_02_real_time_delivery_within_latency_target` |
| TC-Msg-03 | CHAT-F-012 Queue offline messages | 1. `bob` offline.<br>2. `alice` sends three messages to `bob`.<br>3. `bob` logs in. | The messages arrive in the original order after login, each exactly once. Messages sent to an online user are not queued. | `test_server.py`: `test_msg_03_offline_messages_are_stored`, `test_msg_03_queued_messages_delivered_in_order_on_login`, `test_msg_03_queued_messages_are_delivered_only_once`, `test_msg_03_live_messages_are_not_queued`; `test_database.py`: `test_msg_03_*` |
| TC-Msg-04 | CHAT-F-013 Delivery acknowledgement | 1. `alice` sends to `bob` while `bob` is online.<br>2. `bob` goes offline and `alice` sends again. | In the first case the sender gets a delivered acknowledgement and the client shows "delivered". In the second the message is reported as stored, not delivered. | `test_f013_delivery_ack.py` (4 tests) |
| TC-Msg-05 | CHAT-F-014 Typing indicator | 1. `alice` starts typing to `bob`.<br>2. `alice` stops, or goes idle for 2 s.<br>3. Repeat with no authentication or an invalid recipient. | `bob` sees the indicator appear and clear within 2 s of the state change. Unauthenticated or invalid requests are rejected. The state clears on disconnect. | `test_typing_indicator_is_sent_to_recipient_and_clears`, `test_typing_state_expires_within_two_seconds`, `test_typing_indicator_requires_authentication`, `test_typing_indicator_deduplicates_repeated_state_and_rejects_bad_recipient`, `test_typing_state_clears_on_disconnect_and_expiry` |
| TC-Msg-06 | CHAT-F-015 Persist to chat history | 1. `alice` sends several messages to `bob`.<br>2. `alice` disconnects and logs in again.<br>3. `alice` requests history.<br>4. Request history without logging in. | History returns the messages in order with sender, recipient, timestamp and content. An unauthenticated request is rejected. | `test_message_is_saved_in_history`, `test_history_survives_reconnect`, `test_history_requires_authentication` |

Remark on TC-Msg-06: the SRS wording is "after restart". The automated test reconnects to the same database; messages are stored in SQLite, so they are not held in memory.

## 5. Group chat (CHAT-F-020 to CHAT-F-023)

Room names are 3 to 32 characters (letters, digits, `_`, `-`) and are case-insensitive. Rooms live in server memory, so they are cleared on server restart.

| ID | Requirement | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-Grp-01 | CHAT-F-020 Create a named room | 1. `alice` creates `general`.<br>2. Request the room list.<br>3. Create `General` again, and rooms with invalid names. | `general` appears in the directory immediately. Duplicates (any case) and invalid names are rejected. Room requests need a valid token. | `test_rooms.py`: `test_create_room_appears_in_directory_immediately`, `test_create_room_rejects_invalid_names`, `test_duplicate_room_name_rejected_case_insensitively`, `test_room_requests_need_a_valid_token` |
| TC-Grp-02 | CHAT-F-021 Join and leave | 1. `alice` creates the room, `bob` joins.<br>2. `bob` leaves.<br>3. Try to join a missing room or leave a room not joined. | Membership changes are announced to all participants. Error cases return clear errors. | `test_join_and_leave_update_membership_for_everyone`, `test_join_leave_error_cases` |
| TC-Grp-03 | CHAT-F-022 Room broadcast | 1. `alice` and `bob` in the room, `carol` outside it.<br>2. `alice` sends a room message. | `alice` and `bob` receive it within the latency target. `carol` does not. Only online members receive it. Invalid room messages are rejected. | `test_room_message_reaches_all_online_members_only`, `test_room_message_rules` |
| TC-Grp-04 | CHAT-F-023 Online user list | 1. `alice` and `bob` online, one room joined.<br>2. Request the global and the room user list.<br>3. `bob` disconnects.<br>4. A non-member requests the room list. | Global and per-room lists are correct. The lists refresh when someone connects or disconnects. A non-member cannot list a room's users. | `test_online_user_lists_global_and_per_room`, `test_disconnect_removes_user_from_rooms_and_notifies`, `test_non_member_cannot_list_room_users` |


## 6. File transfer (CHAT-F-030, CHAT-F-031)

The configured file size limit is 1 MiB (`MAX_FILE_SIZE` in `server.py`).

| ID | Requirement | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-File-01 | CHAT-F-030 Send file attachment | 1. `alice` sends a file to `bob` (online).<br>2. Repeat with an empty file and two transfers at once.<br>3. `alice` sends a file to a room with two members online and one member offline. | `bob` receives the file intact and the checksum matches. Empty files and parallel transfers work. Only the online room members receive the room file. | `test_file_transfer_preserves_bytes_and_checksum`, `test_file_transfer_supports_empty_file_and_isolated_transfer_ids`, `test_file_transfer_broadcasts_only_to_online_room_members`; `test_client.py`: `test_client_sends_file_to_room_in_bounded_chunks` |
| TC-File-02 | CHAT-F-031 Reject oversized files | 1. `alice` starts a transfer larger than 1 MiB.<br>2. Start a transfer of exactly 1 MiB.<br>3. Start transfers with an invalid size, a missing size, or an unsafe file name. | The oversized file is rejected before any chunk is accepted, with an error to the sender. A file of exactly 1 MiB is accepted and intact. Invalid sizes, missing sizes and unsafe names are rejected. The client also refuses an oversized file before sending. | `test_file_transfer_rejects_file_over_configured_limit`, `test_file_transfer_at_exact_limit_is_accepted_and_intact`, `test_file_transfer_rejects_invalid_sizes_before_accepting_chunks`, `test_file_transfer_rejects_missing_size_and_unsafe_filename`; `test_client.py`: `test_client_rejects_oversized_file_before_sending` |

## 7. Administration and moderation (CHAT-F-040 to CHAT-F-042)

Administrators are the usernames listed in the `CHAT_ADMIN_USERS` environment variable. Moderation applies to the whole server; there is no per-room moderation (see [deviations](deviations.md)).

| ID | Requirement | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-Admin-01 | CHAT-F-040 Broadcast announcement | 1. Several users online.<br>2. An administrator broadcasts an announcement.<br>3. A non-administrator tries the same. | Every active client receives the announcement within the latency bound. The non-administrator is refused. | `test_tc_admin_01_announcement_reaches_all_active_clients_within_latency`, `test_tc_admin_01_non_admin_cannot_broadcast` |
| TC-Admin-02 | CHAT-F-041 Kick and ban | 1. An administrator kicks `bob`.<br>2. An administrator bans `bob`.<br>3. `bob` tries to log in again. | A kick closes `bob`'s socket. A ban disconnects `bob` and later login attempts are refused. | `test_tc_admin_02_kick_closes_target_socket`, `test_tc_admin_02_ban_disconnects_and_refuses_later_login` |
| TC-Admin-03 | CHAT-F-042 Audit log | 1. An administrator broadcasts, kicks and bans.<br>2. Inspect the audit records. | Every administrative action has an entry with the acting administrator and a timestamp. | `test_tc_admin_03_admin_actions_are_audited_with_actor_and_timestamp` |

## 8. Non-functional (CHAT-NF-001 to CHAT-NF-005)

| ID | Requirement | Steps | Expected result | Evidence |
|---|---|---|---|---|
| TC-Perf-01 | CHAT-NF-001 Latency | Run `scripts/measure_message_latency.py` with 100 concurrent clients and 1,000 private-message samples. | 95th-percentile latency is 500 ms or less. Recorded result: p95 = 23.461 ms (Pass). | `scripts/measure_message_latency.py`; raw data in `docs/performance/tc-perf-01-raw.csv` and `tc-perf-01-raw.metadata.json` |
| TC-Scale-01 | CHAT-NF-002 200 concurrent connections | Run `scripts/measure_concurrent_clients.py` with 200 authenticated clients held for 5 seconds. | All 200 sessions stay active and none are dropped. Recorded result: 200 active, 0 dropped (Pass). | `scripts/measure_concurrent_clients.py`; raw data in `docs/performance/tc-scale-01-raw.csv` and `tc-scale-01-raw.metadata.json` |
| TC-Rel-01 | CHAT-NF-003 Dead-connection cleanup | 1. Log in as `alice`.<br>2. Drop the connection without logging out.<br>3. Check presence and sessions. | The dead connection is detected and cleaned up within 30 seconds. | `test_silent_disconnect_is_removed_from_presence_and_session` |
| TC-Ops-01 | CHAT-NF-004 90-day history | 1. Store messages older than today but inside 90 days, and one near the boundary.<br>2. Request history and page through it. | Messages up to 90 days old are returned. Pages do not skip or repeat messages. | `test_database.py`: `test_history_includes_messages_through_the_90_day_boundary`, `test_history_pages_do_not_skip_or_repeat_messages`; `test_server.py`: `test_history_request_pages_messages_across_the_90_day_window` |
| TC-UX-01 | CHAT-NF-005 Non-blocking UI | 1. Simulate a slow network: the receiver waits on a partly sent server event.<br>2. Send a request from the client meanwhile. | The client can still send while the receiver is waiting, so the UI is not blocked. | `test_client.py`: `test_tc_ux_01_user_can_send_while_receiver_waits_on_slow_network` |

## 9. Security (CHAT-SR-001 to CHAT-SR-005)

| ID | Requirement | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-Sec-01 | CHAT-SR-001 TLS | 1. Start the server with `CHAT_TLS_CERT_FILE` and `CHAT_TLS_KEY_FILE`.<br>2. Connect a client with `CHAT_TLS_ENABLED=1` and `CHAT_TLS_CA_FILE`.<br>3. Send and receive a message. | The TLS handshake succeeds and application data round-trips. TLS is optional and off by default. | `test_tls_handshake_round_trips_application_data` |
| TC-Sec-02 | CHAT-SR-002 Password hashing | 1. Register users.<br>2. Inspect the database.<br>3. Register two users with the same password.<br>4. Check the server log. | Only bcrypt hashes are stored. The same password gives different hashes. No plaintext password appears in the log. | `test_auth.py`: `test_sec_02_password_is_hashed`, `test_sec_02_same_password_produces_different_hashes`, `test_sec_02_stored_hash_has_bcrypt_format`, `test_sec_02_database_contains_only_hashed_passwords`; `test_server.py`: `test_sec_02_no_plaintext_password_in_server_logs` |
| TC-Sec-03 | CHAT-SR-003 Input validation | Send malformed JSON, wrong field types, oversized requests, control characters, NUL in a password, injection-style strings and invalid UTF-8. Then log in normally. | The server returns an error for each bad input (oversized requests get 413), does not crash, and still accepts the normal login. | `test_sr003_fuzz.py` (37 tests); `test_server.py`: `test_malformed_json_returns_error_and_connection_recovers` |
| TC-Sec-04 | CHAT-SR-004 Session token | Send protected requests (message, history, typing, room commands) with no token, a wrong token and a valid token. | Requests with a missing or invalid token are refused. A valid token is accepted. | `test_session_token_is_required_for_protected_requests`, `test_unauthenticated_message_is_rejected`, `test_missing_or_bad_token_is_refused` (fuzz file) |
| TC-Sec-05 | CHAT-SR-005 Per-IP rate limiting | 1. Send repeated failed logins from one address.<br>2. Make one successful login. | After the configured failures (default 5 in 60 s) further logins are throttled for the lockout period. A successful login clears the failure count. | `test_tc_sec_05_login_attempts_are_rate_limited_per_ip`, `test_tc_sec_05_successful_login_clears_failure_tracking` |


## 10. Test cases added after the SRS

These cases cover behaviour built in Sprints 2 and 3 that the SRS cases do not describe. The GUI cases come from the acceptance criteria of CHAT-UI-001.

### 10.1 Desktop GUI

Start the GUI with `python -m gui.app` while `python server.py` is running.

| ID | Feature | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-GUI-01 | Register and log in | 1. Register a new user.<br>2. Log in.<br>3. Try an empty field.<br>4. Try a wrong password. | Registration and login succeed and open the dashboard. Empty fields are rejected without a network request. A server error is shown on screen and the user can retry. | `test_auth_view.py` (9 tests) |
| TC-GUI-02 | Dashboard | 1. Log in with two users.<br>2. Look at the dashboard.<br>3. Click Refresh.<br>4. Click Log out. | The dashboard shows the logged-in user, the connection status, the online users and the available rooms. Refresh updates the lists. Log out returns to the login screen. | `test_gui_client_core.py`: `test_core_auth_messaging_rooms_and_history_use_server_protocol` |
| TC-GUI-03 | Private messaging | 1. Two users each open a private chat with the other.<br>2. Send a message each way.<br>3. Close one user's window and send to them. | Messages appear in the other window in real time with the local time. The status shows "Delivered" for an online user and "Saved - recipient is offline and will get it at next login" for an offline one. A typing indicator appears while the other user types. | `test_private_chat_logic.py` (8 tests) |
| TC-GUI-04 | Private chat history | 1. Exchange messages, then log out and back in.<br>2. Open the chat again.<br>3. Click "Load older messages" if it is enabled. | Earlier messages appear in order, including those sent while the user was offline. Room messages and other users' messages are not shown. Older pages load without repeating messages. | `test_private_chat_logic.py` (history filtering and formatting) |
| TC-GUI-05 | Group chat | 1. Open the group chat screen.<br>2. Create a room, join it, send a message, and leave.<br>3. Have a second user join and reply. | Rooms are listed and refresh. Room messages from other members appear. Create, join and leave show the server's result, including errors for invalid names. | `test_gui_client_core.py`: `test_core_interoperates_with_existing_server_for_chat_rooms_history_and_files` |
| TC-GUI-06 | File attachment | 1. Click Send file and pick a small file for a user.<br>2. Send a file to a room.<br>3. Pick a file larger than 1 MiB. | The file picker opens and the file is sent in chunks. The recipient receives it and the checksum is verified. A file over the limit is refused before it is sent. | `test_gui_client_core.py`: `test_core_file_transfer_uses_existing_chunk_protocol`, `test_core_receives_and_verifies_incoming_file` |
| TC-GUI-07 | Responsiveness and disconnect | 1. Use the GUI while messages and files are in transit.<br>2. Stop the server while a user is logged in. | The window stays responsive: network reads run on a background thread and events are handled on the Tk thread. When the server stops, the GUI shows a disconnected state and does not crash. | `test_gui_client_core.py`: `test_tk_event_poll_dispatches_on_calling_thread_and_reschedules`, `test_core_reports_unexpected_disconnect`, `test_disconnect_stops_and_joins_file_transfer_worker` |
| TC-GUI-08 | Terminal client independence | 1. Run `python client.py` with the GUI not running.<br>2. Register, log in, send a message, and quit.<br>3. Run the full test suite. | The terminal client works exactly as before and its tests pass. | `tests/test_client.py`; the full `python -m pytest -v` run |

### 10.2 Additional server behaviour

| ID | Related requirement | Steps | Expected result | Automated test |
|---|---|---|---|---|
| TC-Grp-05 | CHAT-F-014, CHAT-F-022 Typing in rooms | 1. A member types in a room.<br>2. The member leaves the room.<br>3. Send typing for a room that does not exist or was not joined. | Only room members see the indicator. It clears when the member leaves. Invalid or unjoined rooms are rejected. | `test_typing_indicator_is_limited_to_room_members_and_clears_on_leave`, `test_typing_indicator_rejects_invalid_or_unjoined_rooms` |
| TC-File-03 | CHAT-F-030 Transfer robustness | 1. Drop the sender during an upload.<br>2. Disconnect the recipient during an upload.<br>3. Leave a transfer idle.<br>4. A room member leaves during a room upload. | Interrupted and abandoned transfers are cleaned up. A recipient disconnect gives the sender an error and releases the transfer state. The idle timeout resets after each valid chunk. A member who leaves is skipped. | `test_file_transfer_cleans_up_interrupted_upload`, `test_file_transfer_rejects_recipient_disconnect_and_releases_state`, `test_file_transfer_expires_abandoned_state`, `test_file_transfer_idle_timeout_resets_after_valid_chunk`, `test_room_file_transfer_skips_member_who_leaves_during_upload` |

## 11. Execution status of the added cases

| Case | Automated | Manual |
|---|---|---|
| TC-GUI-01 to TC-GUI-04 | Passing in CI | Done 10 November 2026 on Windows with two clients and a local server (screenshots in the PR for issue #73) |
| TC-GUI-05 to TC-GUI-07 | Passing in CI | To be executed and recorded in the System Validation Report (CHAT-TEST-003) |
| TC-GUI-08 | Passing in CI | To be recorded in CHAT-TEST-003 |
| TC-Grp-05, TC-File-03 | Passing in CI | Not needed |

## 12. Changes to the Test Plan since v1.0

The Test Plan (STP, dated 16 September 2026) has not been re-issued. These are the differences between it and what was done.

| Area | In the STP (v1.0) | What was done |
|---|---|---|
| Implementation | Java ServerSocket or Python asyncio and threading | Python 3.13 with `socketserver.ThreadingTCPServer`, SQLite and bcrypt |
| Chat client UI | Contact/room list, message pane, file-attach control | A terminal client plus a Tkinter desktop GUI (login, dashboard, private chat, group chat, file attachments) |
| Test tools | JUnit/pytest, JMeter, Wireshark, OWASP ZAP | pytest, a custom socket harness (`tests/chat_harness.py`), custom load scripts (`scripts/measure_*.py`) and custom fuzz tests. TLS is verified by an automated handshake test; no packet capture is stored in the repository |
| Defect tracking | Jira or Trello | GitHub Issues, plus the [defect log](defect-log.md) |
| Test automation | Git/GitHub CI | GitHub Actions runs `python -m pytest -v` on every push and pull request |
| Reconnection | Heartbeat and client reconnection | Dead-connection detection is implemented and tested (TC-Auth-04, TC-Rel-01). Automatic client reconnection is not implemented. After a failed login the client reconnects before retrying |
| Moderation | Kick/ban from a room or the server | Moderation applies to the whole server (see [deviations](deviations.md)) |
| Schedule | Test design 18 Sep to UAT 1–3 Oct 2026 | Testing ran through Sprints 2 and 3. The full automated run on final `main` was on 30 October 2026 and the GUI was tested in November 2026 |
| Document details | SRN for Ujwal K printed as `PES2UG24C566` | Correct SRN is `PES2UG24CS566` (defect D-07) |


