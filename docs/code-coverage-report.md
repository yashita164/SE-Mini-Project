# Code Coverage Report – CHAT-TEST-004

## 1. Objective

Measure and report statement coverage of the SE Mini Project Chat Application. Test files are excluded from the coverage measurement to ensure that the reported figures represent application code only.

## 2. Measurement Details

| Parameter | Value |
|---|---|
| Measurement date | 11 November 2026 |
| Branch | main |
| Baseline commit | 3924fc21ec9ae4df030e61ac83c842fc8b889e74 |
| Python | Python 3.12 (verify with `python --version`) |
| pytest-cov | 7.1.0 |
| Coverage type | Statement coverage |
| Test result | 154 passed, 1 skipped |
| Execution time | 95.85 seconds |

### Command executed

```bash
python -m pytest --cov=. --cov-report=term --cov-report=html
```

### Coverage configuration

The `.coveragerc` file excludes test files:

```ini
[run]
omit =
    tests/*
    */tests/*
```

## 3. Overall Coverage Results

| Metric | Result |
|---|---:|
| Total statements | 2,195 |
| Missed statements | 746 |
| Covered statements | 1,449 |
| Overall statement coverage | 66% |

The application achieved 66% statement coverage across the measured Python application files.

## 4. Per-File Coverage

| Application file | Statements | Missed | Coverage |
|---|---:|---:|---:|
| auth.py | 40 | 4 | 90% |
| client.py | 452 | 316 | 30% |
| database.py | 91 | 3 | 97% |
| gui/__init__.py | 0 | 0 | 100% |
| gui/app.py | 140 | 94 | 33% |
| gui/client_core.py | 408 | 99 | 76% |
| gui/dashboard.py | 94 | 80 | 15% |
| server.py | 970 | 150 | 85% |
| **TOTAL** | **2,195** | **746** | **66%** |

## 5. Analysis of Low-Coverage Files

### client.py – 30%

The client contains interactive and socket-based communication functionality. Some execution paths depend on network responses, user input and connection states.

**Recommended improvement:** Introduce mock sockets and simulated server responses to exercise error handling, disconnections and alternative communication paths.

### gui/app.py – 33%

The GUI application contains window management, navigation and event-driven functionality. Some paths require interaction with Tkinter widgets and application lifecycle events.

**Recommended improvement:** Use mocked Tkinter components and event simulation to test navigation and GUI lifecycle behavior without requiring manual interaction.

### gui/dashboard.py – 15%

The dashboard contains interactive interface functionality and periodic updates. These paths are difficult to exercise through ordinary headless unit tests.

**Recommended improvement:** Add tests using mocked widgets, scheduled callbacks and simulated dashboard data.

### gui/client_core.py – 76%

The shared GUI client core has comparatively better coverage. Some asynchronous communication and connection lifecycle paths remain untested.

**Recommended improvement:** Add tests for connection failures, unexpected disconnections and asynchronous event handling.

## 6. High-Coverage Files

- `database.py` achieved 97% coverage, indicating strong test coverage of database operations.
- `auth.py` achieved 90% coverage, indicating good coverage of authentication functionality.
- `server.py` achieved 85% coverage, indicating substantial testing of server-side functionality.

These files demonstrate relatively strong statement coverage.

## 7. Coverage Gaps and Future Testing

The main testing gaps are concentrated in interactive client functionality and GUI modules.

These gaps are accepted for this measurement rather than changing application functionality solely to increase the coverage percentage.

Future testing improvements should prioritize:

1. Mock-based tests for socket communication in `client.py`.
2. Event-driven tests for GUI navigation in `gui/app.py`.
3. Mocked widget and callback tests for `gui/dashboard.py`.
4. Additional asynchronous connection tests for `gui/client_core.py`.

The 66% result is a baseline measurement, not a claim that all application behavior has been verified.

## 8. Conclusion

The application achieved 66% statement coverage across 2,195 measured statements, with 1,449 statements executed during the test run.

A total of 154 tests passed and one test was skipped.

The coverage results identify the client and GUI modules as the main opportunities for future testing improvements.

The report provides a reproducible baseline for subsequent testing and quality improvements.

## 9. Reproducibility

To reproduce the measurement:

```bash
python -m pip install -r requirements.txt
python -m pytest --cov=. --cov-report=term --cov-report=html
```

Ensure that the repository is checked out at the recorded baseline commit and that `.coveragerc` is present.

The HTML report is generated in the `htmlcov/` directory.
