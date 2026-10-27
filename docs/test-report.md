# Test Report — Team 5 Chat Application

## TC-UX-01: Client responsiveness during socket I/O

- **Requirement:** CHAT-NF-005
- **Result:** PASS locally on 2026-10-27
- **Evidence:** `tests/test_client.py::test_tc_ux_01_user_can_send_while_receiver_waits_on_slow_network`
- **Method:** A socket-pair test sends only part of an incoming server event and leaves the client receiver blocked waiting for the rest. While the simulated slow response is in progress, the test sends a client request and verifies that the peer receives it before the server completes its event.
- **Command:** `python -m pytest -q --basetemp=.pytest-tmp`
- **Suite result:** 38 passed in 66.60 seconds.
- **CI:** Pending the pull request workflow run.
