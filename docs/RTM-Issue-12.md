# Requirements Traceability Matrix (RTM)

**Related issue:** #12 — PRC-12: Test planning  
**Source documents:** SRS and STP submitted for the Team 5 chat application  
**Evidence reviewed:** `tests/test_auth.py`, `tests/test_database.py`, and `tests/test_server.py` as supplied for review.

## Purpose

This matrix maps each SRS requirement to its existing STP test-case ID and records the test code found in the reviewed files. GitHub Actions executed `python -m pytest -v`, collecting and passing 37 tests with no failures. However, a passing test suite does not automatically prove that every requirement is fully covered. Individual RTM assessments must be based on the relevant test assertions and the expected results defined in the STP.

## Proposed RTM status definitions — pending team agreement

| Code | Proposed meaning | When to use |
|---|---|---|
| P | Passed | The relevant test was executed and met its expected result. |
| F | Failed | The relevant test was executed and did not meet its expected result. |
| NR | Not Run | A meaningful test exists, but its execution result has not been recorded. |
| NI | Not Implemented | No meaningful test implementation exists yet for the planned test case. |
| B | Blocked | The test cannot currently be executed because of a documented dependency or blocker. |

**Team decision required:** the SRS sample RTM currently uses `N`, but the SRS does not define it. Agree what `N` means before changing existing rows. If the team adopts this proposal, replace `N` with `NR` only when the test exists but has not been run; use `NI` when no meaningful test implementation exists.

## RTM

“Test code evidence” describes the supplied files only. “Implementation assessment” is preliminary and is not a test pass/fail result.

| Requirement ID | Requirement (short name) | STP test case | Test evidence (current `main`) | Status |
|---|---|---|---|---|
| CHAT-F-001 | Register account | TC-Auth-01 | `test_auth.py` (`test_auth_01_*`), `test_server.py` registration tests | P |
| CHAT-F-002 | Authenticate credentials | TC-Auth-02 | `test_auth.py` (`test_auth_02_*`), `test_server_rejects_invalid_login` | P |
| CHAT-F-003 | Logout / close socket | TC-Auth-03 | No dedicated test; logout leaves the socket open (defect D-06) | NI |
| CHAT-F-004 | Detect abrupt disconnection | TC-Auth-04 | No heartbeat or timeout test (see deviations) | NI |
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
| CHAT-NF-003 | Dead-connection cleanup within 30 s | TC-Rel-01 | No heartbeat, no test | NI |
| CHAT-NF-004 | 90-day history retention | TC-Ops-01 | No retention test; history request returns the latest 50 | NI |
| CHAT-NF-005 | Responsive UI during socket I/O | TC-UX-01 | `test_tc_ux_01_user_can_send_while_receiver_waits_on_slow_network` | P |
| CHAT-SR-001 | TLS / SSL | TC-Sec-01 | Not implemented (see deviations) | NI |
| CHAT-SR-002 | Password hashing | TC-Sec-02 | `test_sec_02_*` in `test_auth.py` and `test_server.py` | P |
| CHAT-SR-003 | Input validation | TC-Sec-03 | `test_sr003_fuzz.py` (35 tests) and `test_malformed_json_returns_error_and_connection_recovers` | P |
| CHAT-SR-004 | Session tokens | TC-Sec-04 | `test_session_token_is_required_for_protected_requests`, token tests in `test_sr003_fuzz.py` | P |
| CHAT-SR-005 | Per-IP rate limiting | TC-Sec-05 | Not implemented | NI |

## Test cases needing implementation or follow-up

Based on the three reviewed files, these test cases have no dedicated meaningful test identified or have an incomplete test stub:

- `TC-Auth-03` — logout / close socket
- `TC-Auth-04` — abrupt disconnection
- `TC-Grp-01` — create room
- `TC-Grp-02` — join / leave room
- `TC-Grp-03` — room message broadcast
- `TC-Grp-04` — display online users
- `TC-Admin-01` — admin announcement
- `TC-Admin-02` — kick / ban
- `TC-Admin-03` — admin action logging
- `TC-Scale-01` — 200 concurrent clients
- `TC-Rel-01` — dead connection cleanup within 30 seconds
- `TC-Ops-01` — 90-day history retention
- `TC-UX-01` — UI responsiveness during socket I/O
- `TC-Sec-01` — TLS / SSL
- `TC-Sec-05` — per-IP rate limiting

Additional follow-up / coverage confirmation:

- `TC-Msg-04`: existing acknowledgement assertions appear in live messaging tests; confirm they meet the STP's full expected results and add a dedicated test if needed.
- `TC-Perf-01`: the current integration test checks one message's latency, not the p95 requirement across a defined sample.
- `TC-Sec-03` and `TC-Sec-04`: related tests exist, but compare their assertions with the complete STP test steps before marking full coverage.

## Evidence and completion checklist for Issue #12

- [x] Every SRS requirement listed above is mapped to its existing STP test-case ID.
- [x] Preliminary test-code gaps are listed from the reviewed files.
- [ ] Team agrees on RTM status definitions and clarifies the existing `N` value.
- [x] Run the test suite: GitHub Actions collected 37 tests and all 37 passed.
- [ ] Link this RTM and the test-gap list in Issue #12.
- [ ] Submit a pull request referencing Issue #12.
- [ ] Obtain review from a teammate other than the author.
- [ ] Ensure CI passes and add the CI run URL to Issue #12.
- [ ] Link evidence for each acceptance criterion in Issue #12.

## Scope note

This RTM is a draft based on the SRS/STP mappings and the three test files reviewed. “No dedicated test identified” means no corresponding test was found in those files; it does not prove the feature itself is absent. Before merge, compare the table against the current repository versions of the SRS, STP, and test suite, and get team agreement on the status legend.
