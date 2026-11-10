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
