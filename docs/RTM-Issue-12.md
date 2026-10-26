# Requirements Traceability Matrix (RTM)

**Related issue:** #12 — PRC-12: Test planning  
**Source documents:** SRS and STP submitted for the Team 5 chat application  
**Evidence reviewed:** `tests/test_auth.py`, `tests/test_database.py`, and `tests/test_server.py` as supplied for review.

## Purpose

This matrix maps each SRS requirement to its existing STP test-case ID and records whether corresponding test code was found in the reviewed test files. A test being present does **not** mean it passed. The test suite has not been executed as part of this review, so execution status remains **Not Run (NR)** until a real test run is recorded.

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

| Requirement ID | Requirement (short name) | Existing STP test-case ID | Test code evidence in reviewed files | Implementation assessment | Execution status |
|---|---|---|---|---|---|
| CHAT-F-001 | Register account | TC-Auth-01 | `test_auth.py`: successful, duplicate, and invalid registration; `test_server.py`: registration integration tests | Found | NR — run not verified |
| CHAT-F-002 | Authenticate credentials | TC-Auth-02 | `test_auth.py`: valid login/session and invalid password; `test_server.py`: TCP login tests | Found | NR — run not verified |
| CHAT-F-003 | Logout / close socket | TC-Auth-03 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-004 | Detect abrupt disconnection | TC-Auth-04 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-010 | Private message | TC-Msg-01 | `test_server.py`: private message reaches intended recipient only | Found | NR — run not verified |
| CHAT-F-011 | Real-time delivery | TC-Msg-02 | `test_server.py`: delivery latency target and message acknowledgement behavior | Found | NR — run not verified |
| CHAT-F-012 | Queue offline messages | TC-Msg-03 | `test_database.py` queue/migration tests and `test_server.py` offline delivery, order, recipient-only, and once-only tests | Found | NR — run not verified |
| CHAT-F-013 | Delivery acknowledgement | TC-Msg-04 | `test_server.py` checks `MESSAGE_DELIVERED` and matching message IDs in live messaging tests | Partial / equivalent behavior found; confirm against full STP expected results | NR — run not verified |
| CHAT-F-014 | Typing indicator | TC-Msg-05 | `test_server.py`: typing start/stop events and authentication requirement | Found | NR — run not verified |
| CHAT-F-015 | Persist chat history | TC-Msg-06 | `test_server.py`: message history and history after reconnect | Found | NR — run not verified |
| CHAT-F-020 | Create room | TC-Grp-01 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-021 | Join / leave room | TC-Grp-02 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-022 | Room message broadcast | TC-Grp-03 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-023 | Display online users | TC-Grp-04 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-030 | File attachment | TC-File-01 | `test_server.py` contains `test_file_transfer_preserves_bytes_and_checksum`, but the supplied body stops after setup and has no transfer/assertions | NI / incomplete stub — finish the test so it verifies transfer and checksum | Not run; meaningful test incomplete |
| CHAT-F-031 | Reject oversized files | TC-File-02 | `test_server.py`: oversized file metadata rejected with code 413 | Found | NR — run not verified |
| CHAT-F-040 | Admin announcement | TC-Admin-01 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-041 | Kick / ban | TC-Admin-02 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-F-042 | Log admin actions | TC-Admin-03 | No dedicated test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-NF-001 | Latency ≤ 500 ms p95 | TC-Perf-01 | `test_server.py` measures a single delivery and asserts under 500 ms; it does not establish p95 latency across a sample | Partial — current test checks one delivery, not p95 | NR — run not verified |
| CHAT-NF-002 | 200 concurrent clients | TC-Scale-01 | No dedicated load/concurrency test identified | NI — add a load test for the stated target | Not run; test not identified |
| CHAT-NF-003 | Dead connection cleanup within 30 s | TC-Rel-01 | No dedicated cleanup-timing test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-NF-004 | 90-day history retention | TC-Ops-01 | No dedicated retention test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-NF-005 | Responsive UI during socket I/O | TC-UX-01 | No dedicated UI responsiveness test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-SR-001 | TLS / SSL | TC-Sec-01 | No dedicated TLS/SSL test identified | NI — add a dedicated test or document an existing equivalent | Not run; test not identified |
| CHAT-SR-002 | Password hashing | TC-Sec-02 | `test_auth.py`: bcrypt hash, salt uniqueness, format, plaintext absence; `test_server.py`: plaintext not in server logs | Found | NR — run not verified |
| CHAT-SR-003 | Input validation / sanitization | TC-Sec-03 | `test_server.py`: malformed JSON, unknown request, empty message, and unknown recipient checks | Partial — confirm sanitization coverage against the SRS requirement | NR — run not verified |
| CHAT-SR-004 | Session tokens | TC-Sec-04 | `test_auth.py` checks token issuance and database lookup; `test_server.py` checks valid/invalid-token access for messages/history/typing | Partial — confirm token-specific STP scenarios and expiry/invalidity expectations | NR — run not verified |
| CHAT-SR-005 | Per-IP rate limiting | TC-Sec-05 | No dedicated rate-limit test identified | NI — add a test that verifies per-IP limiting | Not run; test not identified |

## Test cases needing implementation or follow-up

Based on the three reviewed files, these test cases have no dedicated meaningful test identified or have an incomplete test stub:

- `TC-Auth-03` — logout / close socket
- `TC-Auth-04` — abrupt disconnection
- `TC-Grp-01` — create room
- `TC-Grp-02` — join / leave room
- `TC-Grp-03` — room message broadcast
- `TC-Grp-04` — display online users
- `TC-File-01` — finish the existing incomplete transfer/checksum test
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
- [ ] Run the test suite and record the actual result; do not mark tests `P` or `F` without execution evidence.
- [ ] Link this RTM and the test-gap list in Issue #12.
- [ ] Submit a pull request referencing Issue #12.
- [ ] Obtain review from a teammate other than the author.
- [ ] Ensure CI passes and add the CI run URL to Issue #12.
- [ ] Link evidence for each acceptance criterion in Issue #12.

## Scope note

This RTM is a draft based on the SRS/STP mappings and the three test files reviewed. “No dedicated test identified” means no corresponding test was found in those files; it does not prove the feature itself is absent. Before merge, compare the table against the current repository versions of the SRS, STP, and test suite, and get team agreement on the status legend.
