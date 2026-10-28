# Requirements Traceability Matrix (RTM)

**Related issues:** #12 (map issues to test case IDs and define the RTM status legend) and #7 (update the RTM from verified results)  
**Source documents:** SRS, SAD and STP submitted for the Team 5 chat application  
**Evidence:** `python -m pytest -v` on `main` after all Sprint 2 pull requests were merged: 115 tests collected, 115 passed, 0 failed. CI run: https://github.com/yashita164/SE-Mini-Project/actions/runs/40567424923

## Purpose

This matrix maps each SRS requirement to its STP test-case ID, names the automated tests that provide the evidence, and records the verified result. A passing test shows that the behaviour the test checks works. Where a test checks less than the requirement says (for example a single latency sample against a 95th-percentile target), the row is marked accordingly instead of passed.

## Status definitions

The SRS sample RTM used `N` without defining it. It is treated here as "not yet verified" and replaced by the codes below.

| Code | Meaning | When to use |
|---|---|---|
| P | Passed | The relevant test was executed and met its expected result. |
| F | Failed | The relevant test was executed and did not meet its expected result. |
| NR | Not Run | A test exists but does not fully cover the requirement, or its result has not been recorded. |
| NI | Not Implemented | No meaningful test (or no implementation) exists yet for the planned test case. |
| B | Blocked | The test cannot be executed because of a documented dependency or blocker. |

## RTM

| Requirement ID | Requirement (short name) | STP test case | Test evidence (current `main`) | Status |
|---|---|---|---|---|
| CHAT-F-001 | Register account | TC-Auth-01 | `test_auth.py` (`test_auth_01_*`), `test_server.py` registration tests | P |
| CHAT-F-002 | Authenticate credentials | TC-Auth-02 | `test_auth.py` (`test_auth_02_*`), `test_server_rejects_invalid_login` | P |
| CHAT-F-003 | Logout / close socket | TC-Auth-03 | No dedicated test; logout leaves the socket open (defect D-06) | NI |
| CHAT-F-004 | Detect abrupt disconnection | TC-Auth-04 | `test_silent_disconnect_is_removed_from_presence_and_session` | I |
| CHAT-F-010 | Private message | TC-Msg-01 | `test_private_message_reaches_only_recipient` | P |
| CHAT-F-011 | Real-time delivery | TC-Msg-02 | `test_tc_msg_02_real_time_delivery_within_latency_target` | P |
| CHAT-F-012 | Queue offline messages | TC-Msg-03 | `test_msg_03_*` in `test_server.py` and `test_database.py` | P |
| CHAT-F-013 | Delivery acknowledgement | TC-Msg-04 | `test_f013_delivery_ack.py` (4 tests) | P |
| CHAT-F-014 | Typing indicator | TC-Msg-05 | `test_typing_indicator_*` | P |
| CHAT-F-015 | Persist chat history | TC-Msg-06 | `test_message_is_saved_in_history`, `test_history_survives_reconnect` | P |
| CHAT-F-020 | Create room | TC-Grp-01 | `test_rooms.py` (create, invalid and duplicate names) | P |
| CHAT-F-021 | Join / leave room | TC-Grp-02 | `test_rooms.py` (join, leave, error cases) | P |
| CHAT-F-022 | Room message broadcast | TC-Grp-03 | `test_rooms.py` (broadcast, non-member rules) | P |
| CHAT-F-023 | Display online users | TC-Grp-04 | `test_rooms.py` (global and per-room lists) | P |
| CHAT-F-030 | File attachment | TC-File-01 | `test_file_transfer_preserves_bytes_and_checksum` | P |
| CHAT-F-031 | Reject oversized files | TC-File-02 | `test_file_transfer_rejects_file_over_configured_limit` | P |
| CHAT-F-040 | Admin announcement | TC-Admin-01 | `test_tc_admin_01_*` | P |
| CHAT-F-041 | Kick / ban | TC-Admin-02 | `test_tc_admin_02_*` (server-wide only, see deviations) | P |
| CHAT-F-042 | Log admin actions | TC-Admin-03 | `test_tc_admin_03_*` | P |
| CHAT-NF-001 | Latency ≤ 500 ms at p95 | TC-Perf-01 | One delivery is checked against 500 ms; p95 over a sample is not measured | NR |
| CHAT-NF-002 | 200 concurrent clients | TC-Scale-01 | No load test | NI |
| CHAT-NF-003 | Dead-connection cleanup within 30 s | TC-Rel-01 | `test_silent_disconnect_is_removed_from_presence_and_session` | I |
| CHAT-NF-004 | 90-day history retention | TC-Ops-01 | No retention test; history request returns the latest 50 | NI |
| CHAT-NF-005 | Responsive UI during socket I/O | TC-UX-01 | `test_tc_ux_01_user_can_send_while_receiver_waits_on_slow_network` | P |
| CHAT-SR-001 | TLS / SSL | TC-Sec-01 | Not implemented (see deviations) | NI |
| CHAT-SR-002 | Password hashing | TC-Sec-02 | `test_sec_02_*` in `test_auth.py` and `test_server.py` | P |
| CHAT-SR-003 | Input validation | TC-Sec-03 | `test_sr003_fuzz.py` (37 tests) and `test_malformed_json_returns_error_and_connection_recovers` | P |
| CHAT-SR-004 | Session tokens | TC-Sec-04 | `test_session_token_is_required_for_protected_requests`, token tests in `test_sr003_fuzz.py` | P |
| CHAT-SR-005 | Per-IP rate limiting | TC-Sec-05 | Not implemented | NI |

**Totals:** 29 requirements: 21 P, 1 NR, 7 NI, 0 F, 0 B.

## Test cases still open

- `TC-Auth-03` logout closing the socket: not implemented (defect D-06).
- `TC-Scale-01` 200 concurrent clients: no load test written.
- `TC-Ops-01` 90-day retention: messages are kept but only the latest 50 are returned; no retention test.
- `TC-Sec-01` TLS and `TC-Sec-05` rate limiting: not implemented (recorded in docs/deviations.md).
- `TC-Perf-01` latency: the current test checks one delivery against 500 ms; the 95th-percentile target over a sample is not measured (status NR).

## Evidence and completion checklist (issues #12 and #7)

- [x] Every SRS requirement is mapped to its STP test-case ID.
- [x] Status legend defined and the undefined `N` value replaced.
- [x] Test suite run on `main`: 115 tests, all passed. CI run: https://github.com/yashita164/SE-Mini-Project/actions/runs/40567424923
- [x] Statuses updated from the verified results (#7).
- [x] Open test cases listed with reasons.
- [ ] Pull request referencing #12 and #7.
- [ ] Review from a teammate other than the author.
- [ ] CI run URL added to issues #12 and #7.

## Scope note

A status of `P` means the named automated test passed in the run linked above. It does not claim coverage beyond what the test asserts; rows where the test is narrower than the requirement are marked NR.
