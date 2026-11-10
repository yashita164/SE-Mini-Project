# Unit Test Report — Team 5 Chat Application

## A. Report Information

| Item | Result |
|---|---|
| Project | Team 5 Chat Application |
| Issue | #79 — CHAT-TEST-002: Unit Test Report |
| Testing date | 2026-11-10 |
| Tested `main` commit | `a6fc49e45f2b27cf4cdf51f7346f270138311eb3` |
| Python | 3.13.7 |
| Pytest | 9.1.1 |
| Operating system | Windows 11 (10.0.26200), AMD64 |
| Test command | `python -m pytest -v` |

The working branch was created from the exact `origin/main` commit shown above.
The suite was run with the repository virtual environment's Python on `PATH`.
A second full run added `--junitxml` to obtain reliable per-file counts; its
aggregate result was the same.

## B. Testing Objective

Unit testing validates individual modules and functions to check that their
expected behaviour is correct. The repository suite also includes integration
tests that exercise the TCP server, client, database, and GUI client layer.

## C. Testing Environment

| Component | Actual environment |
|---|---|
| Python environment | Repository `.venv` |
| Python | 3.13.7 |
| Pytest installed | 9.1.1 |
| bcrypt installed | 5.0.0 |
| Declared dependencies | `bcrypt==5.0.0`, `pytest==9.1.0` in `requirements.txt` |
| Test configuration | No `pytest.ini`, `pyproject.toml`, `setup.cfg`, or `tox.ini` found |
| CI platform | GitHub Actions, Ubuntu 26.04, Python 3.13.18, pytest 9.1.0 |

The local installed pytest patch version differs from the version pinned in
`requirements.txt`; the actual version used for local results is recorded
above. CI installed the pinned version.

## D. Test Execution Summary

The required verbose command completed successfully on the tested commit.

An initial invocation with the system Python did not collect tests because
that interpreter lacked `bcrypt` (`ModuleNotFoundError`). No test cases ran in
that attempt. The command was rerun with the repository virtual environment
on `PATH`; the results below are from that successful run.

| Metric | Actual result |
|---|---:|
| Total tests collected | 172 |
| Passed | 171 |
| Failed | 0 |
| Skipped | 1 |
| Errors | 0 |
| Execution time | 103.64 seconds |

A subsequent full run with JUnit output for per-file reconciliation also
reported **171 passed, 1 skipped** (113.73 seconds). Its per-file counts are
shown below; those counts sum to 172.

## E. Module-wise Test Results

| Test file | Module/functionality | Executed | Passed | Failed | Skipped | Coverage summary |
|---|---|---:|---:|---:|---:|---|
| `tests/test_auth.py` | Authentication and password storage | 9 | 9 | 0 | 0 | Registration, login, password validation, and bcrypt hashing. |
| `tests/test_auth_view.py` | GUI authentication view | 9 | 9 | 0 | 0 | Login/registration submissions, feedback, validation, reconnection, and callback compatibility. |
| `tests/test_client.py` | Terminal client responsiveness and file/history behavior | 4 | 4 | 0 | 0 | Nonblocking UI behavior during socket reads, file limits/chunking, and large history responses. |
| `tests/test_database.py` | Database and message history | 6 | 6 | 0 | 0 | Offline-message ordering/delivery, migration, and 90-day history retention/pagination boundaries. |
| `tests/test_f013_delivery_ack.py` | Private-message delivery acknowledgements | 4 | 4 | 0 | 0 | Online delivery acknowledgements and offline stored-message behavior in server/client flow. |
| `tests/test_gui_client_core.py` | GUI shared client protocol layer | 7 | 7 | 0 | 0 | Authentication, messaging, rooms, history, file transfer, disconnect/thread handling, and live-server interoperability. |
| `tests/test_private_chat_logic.py` | Private chat presentation logic | 8 | 8 | 0 | 0 | Conversation filtering, message/typing display, history rows, and acknowledgement/time formatting. |
| `tests/test_rooms.py` | Room messaging and presence | 23 | 23 | 0 | 0 | Room lifecycle, membership, broadcasts, user lists, and typing behavior. |
| `tests/test_server.py` | TCP server integration | 65 | 64 | 0 | 1 | Authentication/session enforcement, messages, history, files, moderation, TLS, and performance/scaling checks. |
| `tests/test_sr003_fuzz.py` | Malformed input and protocol validation | 37 | 37 | 0 | 0 | Malformed/oversized payloads, invalid fields/tokens, and server recovery. |
| **Total** |  | **172** | **171** | **0** | **1** |  |

## F. Failed and Skipped Tests

No failures or test errors were observed in the local test execution. No
failure requires a defect-log reference.

| Test | Result | Reason |
|---|---|---|
| `tests/test_server.py::test_tls_handshake_round_trips_application_data` | Skipped | The test checks for the `openssl` executable and skips with the message “OpenSSL executable is required for the TLS handshake test” when it is unavailable in the local environment. |

This is an environment-dependent skip, not a logged application defect. The
same test passed in the corresponding GitHub Actions run on Ubuntu.

## G. CI Verification

| Item | CI result |
|---|---|
| Workflow | Chat Application Tests (`.github/workflows/tests.yaml`) |
| Run status | Completed — success |
| Tested commit | `a6fc49e45f2b27cf4cdf51f7346f270138311eb3` |
| CI test summary | 172 passed in 56.56 seconds, no skips |
| Run URL | [GitHub Actions run 42811096482](https://github.com/yashita164/SE-Mini-Project/actions/runs/42811096482) |

The CI job ran `python -m pytest -v` with Python 3.13.18 and pytest 9.1.0.
Its log reports 172 passed. The local run had one fewer pass and one skip
because OpenSSL was unavailable locally; the TLS test passed in CI. The log
also contains GitHub Actions runner deprecation warnings for Node.js 20
actions, which did not affect the Python test job or its successful result.

This run verifies the exact `main` commit tested for this report. CI for the
documentation pull request itself remains pending until the PR is opened.

## H. Conclusion

The complete local pytest suite finished successfully on `main` commit
`a6fc49e45f2b27cf4cdf51f7346f270138311eb3`: 171 passed, no failures or errors,
and one environment-dependent TLS test skipped. GitHub Actions verified the
same commit with all 172 tests passing. The test execution, per-file results,
environment, commit, and corresponding CI evidence required by CHAT-TEST-002
are recorded. The report still requires review and merge before it exists on
`main`; independent review of the pull request also remains outstanding.
