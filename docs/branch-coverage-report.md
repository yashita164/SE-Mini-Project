# Branch Coverage Report

**Project:** SE Mini Project – Team 5 Chat Application
**Issue:** #82 – CHAT-TEST-005
**Date:** 11 November 2026
**Baseline branch:** main
**Baseline commit:** e5ec64c1afeeb6b9785bec5c69043cc3730f3f10

## Reproduction

Coverage command:

`python -m pytest --cov=. --cov-branch --cov-report=term-missing`

JSON export:

`python -m coverage json -o branch-coverage.json`

## Overall Results

| Metric | Result |
|---|---:|
| Statements | 3,189 |
| Covered statements | 1,761 |
| Missing statements | 1,428 |
| Statement coverage | 55.22% |
| Total branches | 1,084 |
| Covered branches | 536 |
| Missing branches | 548 |
| Branch coverage | 49.45% |
| Partial branches | 184 |
| Tests passed | 183 |
| Tests skipped | 1 |

## Per-File Branch Coverage

| File | Total | Covered | Missing | Partial | Coverage |
|---|---:|---:|---:|---:|---:|
| auth.py | 20 | 18 | 2 | 2 | 90.00% |
| client.py | 186 | 51 | 135 | 27 | 27.42% |
| database.py | 10 | 7 | 3 | 3 | 70.00% |
| gui/app.py | 42 | 10 | 32 | 10 | 23.81% |
| gui/auth_view.py | 32 | 21 | 11 | 9 | 65.63% |
| gui/client_core.py | 124 | 71 | 53 | 39 | 57.26% |
| gui/dashboard.py | 30 | 10 | 20 | 6 | 33.33% |
| gui/files.py | 46 | 15 | 31 | 11 | 32.61% |
| gui/private_chat.py | 48 | 0 | 48 | 0 | 0.00% |
| gui/private_chat_logic.py | 10 | 10 | 0 | 0 | 100.00% |
| gui/room_chat.py | 168 | 21 | 147 | 15 | 12.50% |
| server.py | 368 | 302 | 66 | 62 | 82.07% |

`gui/__init__.py` has no measurable branches.

## Main Untested Branches and Decisions

**client.py — 27.42%:** Socket disconnections, malformed JSON, unexpected response types, file metadata validation, Base64 decoding, size limits, checksum failures, write errors and timeouts.
**Decision:** Add automated tests using mocked sockets.

**gui/room_chat.py — 12.50%:** Unauthenticated operations, room creation/joining failures, empty room lists, membership handling, message/file errors and server events.
**Decision:** Add mocked controller and event-handler tests.

**gui/private_chat.py — 0.00%:** History pagination, deduplication, message sending failures, connection failures, typing indicators, incoming messages and callback cleanup.
**Decision:** Add mocked Tkinter and ClientCore tests.

**gui/app.py — 23.81%:** Authentication fallback, navigation, missing view factories, login/logout, connection errors and shutdown.
**Decision:** Add tests with mocked dependencies.

**server.py — 82.07%:** File-transfer validation, moderation, broadcasts, session edge cases, typing expiration and cleanup.
**Decision:** Add targeted security and session tests.

**Other files:** Add targeted tests for database errors, authentication failures, dashboard navigation, file operations, authentication view transitions and client-core connection handling.

## Accepted Gaps

Native Tkinter rendering and OS-specific event-loop behaviour may require manual smoke testing where headless CI cannot reproduce the desktop environment. Underlying business logic, callbacks, validation and error handling should still be automated wherever practical.

## Recommendations

1. Prioritize private chat, room chat, application navigation and client networking.
2. Add tests for network failures and file-transfer validation.
3. Use mocks to test GUI logic.
4. Add regression tests for fixed branches.
5. Rerun coverage and compare results.

## Conclusion

Baseline branch coverage is 49.45% (536 of 1,084 branches). Statement coverage is 55.22%. The largest gaps are in private chat, room chat, application navigation and client networking. These areas require additional automated tests. This report records the baseline and does not claim that the identified gaps have already been fixed.
