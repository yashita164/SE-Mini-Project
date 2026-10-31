# Test Report — Team 5 Chat Application

**Backlog ID:** PRC-10  
**Related issue:** #10  
**Status:** Final (Sprint 2)

## 1. Summary

| Item | Details |
|---|---|
| Test framework | pytest 9.1.0 |
| Command | `python -m pytest -v` |
| Tests collected | 148 |
| Passed | 148 |
| Failed | 0 |
| Skipped | 0 |
| Execution date | 31 October 2026 |
| Environment | GitHub Actions (ubuntu-latest), Python 3.13; also run locally on Python 3.13 |
| CI run | [https://github.com/yashita164/SE-Mini-Project/actions/runs/40567424923](https://github.com/yashita164/SE-Mini-Project/actions/runs/41162261396) |

All 148 automated tests pass on `main`. Every one of the 29 STP test cases has an executed test or measurement (section 4). TC-Perf-01 and TC-Scale-01 are verified by the measurement scripts in `scripts/`, not by pytest.

## 2. Test files

| File | Tests | Area |
|---|---|---|
| `tests/test_auth.py` | 9 | Registration, login, password hashing |
| `tests/test_client.py` | 4 | Client responsiveness during socket I/O |
| `tests/test_database.py` | 6 | Offline-message queue and database migration |
| `tests/test_f013_delivery_ack.py` | 4 | Delivery acknowledgement |
| `tests/test_rooms.py` | 23 | Chat rooms, room broadcast, online-user lists |
| `tests/test_server.py` | 65 | Server integration: messaging, history, typing, files, sessions, administration |
| `tests/test_sr003_fuzz.py` | 37 | Malformed-payload fuzzing and input validation |

## 3. Method notes

- Server tests start a real server on a free local port with a temporary database, and talk to it over TCP.
- **TC-UX-01** uses a socket pair: the test sends only part of an incoming server event, leaves the client receiver blocked waiting for the rest, and checks that a client request can still be sent while the simulated slow response is in progress.
- **TC-Sec-03** sends malformed JSON, wrong types, injection-style strings, invalid UTF-8, oversized requests and bad tokens, then checks that the server still accepts a normal login.

## 4. Results by STP test case

| Test case | Requirement | Result | Evidence / remarks |
|---|---|---|---|
| TC-Auth-01 | CHAT-F-001 | Passed | `test_auth.py` (`test_auth_01_*`) and server registration tests |
| TC-Auth-02 | CHAT-F-002 | Passed | `test_auth_02_*`, `test_server_rejects_invalid_login` |
| TC-Auth-03 | CHAT-F-003 | Passed | `test_successful_logout_closes_connection_and_removes_active_client` |
| TC-Auth-04 | CHAT-F-004 | Passed | `test_silent_disconnect_is_removed_from_presence_and_session` |
| TC-Msg-01 | CHAT-F-010 | Passed | `test_private_message_reaches_only_recipient` |
| TC-Msg-02 | CHAT-F-011 | Passed | `test_tc_msg_02_real_time_delivery_within_latency_target` |
| TC-Msg-03 | CHAT-F-012 | Passed | `test_msg_03_*` in `test_server.py` and `test_database.py` |
| TC-Msg-04 | CHAT-F-013 | Passed | `test_f013_delivery_ack.py` |
| TC-Msg-05 | CHAT-F-014 | Passed | `test_typing_indicator_*` |
| TC-Msg-06 | CHAT-F-015 | Passed | `test_message_is_saved_in_history`, `test_history_survives_reconnect` |
| TC-Grp-01 | CHAT-F-020 | Passed | `test_rooms.py` |
| TC-Grp-02 | CHAT-F-021 | Passed | `test_rooms.py` |
| TC-Grp-03 | CHAT-F-022 | Passed | `test_rooms.py` |
| TC-Grp-04 | CHAT-F-023 | Passed | `test_rooms.py` |
| TC-File-01 | CHAT-F-030 | Passed | `test_file_transfer_preserves_bytes_and_checksum` |
| TC-File-02 | CHAT-F-031 | Passed | `test_file_transfer_rejects_file_over_configured_limit` |
| TC-Admin-01 | CHAT-F-040 | Passed | `test_tc_admin_01_*` |
| TC-Admin-02 | CHAT-F-041 | Passed | `test_tc_admin_02_*` (server-wide only) |
| TC-Admin-03 | CHAT-F-042 | Passed | `test_tc_admin_03_*` |
| TC-Perf-01 | CHAT-NF-001 | Passed | `scripts/measure_message_latency.py` ran 100 concurrent clients and 1,000 private-message samples; raw results are in `docs/performance/tc-perf-01-raw.csv` and metadata in `docs/performance/tc-perf-01-raw.metadata.json` |
| TC-Scale-01 | CHAT-NF-002 | Passed | `scripts/measure_concurrent_clients.py` verified 200 authenticated clients remained active with zero dropped sessions |
| TC-Rel-01 | CHAT-NF-003 | Passed | `test_silent_disconnect_is_removed_from_presence_and_session` verifies cleanup within the 30-second requirement |
| TC-Ops-01 | CHAT-NF-004 | Passed | `test_history_includes_messages_through_the_90_day_boundary`, `test_history_request_pages_messages_across_the_90_day_window` |
| TC-UX-01 | CHAT-NF-005 | Passed | `tests/test_client.py` |
| TC-Sec-01 | CHAT-SR-001 | Passed | `test_tls_handshake_round_trips_application_data` |
| TC-Sec-02 | CHAT-SR-002 | Passed | `test_sec_02_*` |
| TC-Sec-03 | CHAT-SR-003 | Passed | `test_sr003_fuzz.py` and `test_malformed_json_returns_error_and_connection_recovers` |
| TC-Sec-04 | CHAT-SR-004 | Passed | `test_session_token_is_required_for_protected_requests`, token tests in `test_sr003_fuzz.py` |
| TC-Sec-05 | CHAT-SR-005 | Passed | `test_tc_sec_05_login_attempts_are_rate_limited_per_ip` and `test_tc_sec_05_successful_login_clears_failure_tracking` |

**Totals:** 29 STP test cases: 29 passed, 0 partly covered, 0 not executed.

## 5. Test cases not executed

None. All 29 STP test cases have an executed test or measurement. TC-Perf-01 (100 clients, 1,000 latency samples) and TC-Scale-01 (200 concurrent clients) are verified by `scripts/measure_message_latency.py` and `scripts/measure_concurrent_clients.py`; their raw results are in `docs/performance/`.

## 6. Defect summary

Seven defects were logged in the [defect log](defect-log.md): 1 High, 2 Medium and 4 Low. All seven are fixed. No Critical defects were found.

| ID | Summary | Severity | Owner | Status | Fix / evidence |
|---|---|---|---|---|---|
| D-01 | Client `file` command was not connected, so files could not be sent from the console client | High | Yashita Anand | Fixed | PR #67 (the `file` command now sends to a user or a `#room`) |
| D-02 | Every private message was printed twice | Low | Sakshi | Fixed | PR #59 |
| D-03 | `FILE_CHUNK` with a non-string transfer ID ended the connection's handler thread | Medium | Sakshi | Fixed | PR #51; `test_file_chunk_with_non_string_transfer_id` |
| D-04 | Control characters accepted in messages and file names | Low | Sakshi | Fixed | PR #51; `test_send_message_validation` |
| D-05 | NUL character accepted in passwords | Medium | Sakshi | Fixed | PR #51; fuzz case "register NUL in password" |
| D-06 | Logout did not close the socket (CHAT-F-003) | Low | Ujwal K | Fixed | PR #61; `test_successful_logout_closes_connection_and_removes_active_client` |
| D-07 | One team member's SRN was missing an `S` in the README | Low | Sakshi | Fixed | This documentation PR (README team table) |

## 7. Conclusion

All 148 automated tests pass on `main`, and all 29 STP test cases have been executed and passed: 27 by automated tests and two (TC-Perf-01 and TC-Scale-01) by measurement scripts. All seven logged defects are fixed.
