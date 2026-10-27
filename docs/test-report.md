# Test Execution Report

**Backlog ID:** PRC-10  
**Related Issue:** #10  
**Status:** Draft — pending defect summary and execution evidence

## 1. Purpose

This report documents the automated tests executed for the chat application, their results, the execution environment, and outstanding test and defect information.

## 2. Test Execution Summary

| Item | Details |
|---|---|
| Test framework | pytest 9.1.0|
| Test command | `python -m pytest -v` |
| Tests collected | 37 |
| Tests passed | 37 |
| Tests failed | 0 |
| Tests skipped | 0 |
| Execution date | 27 October 2026 |
| Environment | GitHub Actions, Linux, Python 3.13.16 |
| CI run URL | 	[Successful test job](https://github.com/yashita164/SE-Mini-Project/actions/runs/40428045153/job/121938635409?pr=48&utm_source=chatgpt.com) |

**Summary:** The available CI output reports that all 37 collected tests passed. This result applies to the tests executed in that CI run and does not, by itself, establish that every requirement or planned test case has been covered.

## 3. Test Files

The following test files were identified in the repository:

| Test file | Area |
|---|---|
| `tests/test_auth.py` | Authentication and registration |
| `tests/test_database.py` | Database operations and offline-message queue |
| `tests/test_server.py` | Server and messaging behaviour |

## 4. Test Case Results

The final report must map each existing test case ID from the Software Test Plan (STP) to its execution result.

| Test case ID | Result | Evidence / remarks |
|---|---|---|
| TC-Auth-01 |	Passed |	Registration tests in tests/test_auth.py and tests/test_server.py |
| TC-Auth-02 |	Passed |	Login tests in tests/test_auth.py and tests/test_server.py |
| TC-Msg-01	| Passed	| test_private_message_reaches_only_recipient |
| TC-Msg-03	| Passed	| Database and server offline-message queue tests |
| TC-Grp-01	| Not Executed — provisional	| No matching test identified in reviewed files |
| TC-File-01	| Passed	| test_file_transfer_preserves_bytes_and_checksum |
| TC-Admin-02	| Not Executed — provisional	| No matching test identified in reviewed files |
| TC-Perf-01	 |Pending mapping verification	| Latency test is labelled TC-Msg-02 in code |
| TC-Scale-01 |	Not Executed — provisional	| No matching test identified in reviewed files |
| TC-Rel-01 | Not Executed — provisional	| No matching test identified in reviewed files |
| TC-Sec-01	| Not Executed — provisional	| No matching test identified in reviewed files |
| TC-Sec-02 |	Passed | Password hashing and storage tests |
 
Test cases that were not executed must be listed explicitly as **Not Executed**. Do not interpret the total of 37 passing tests as proof that every STP test case passed.

## 5. Defect Summary

**Pending PRC-04 (Issue #4).**

The open and fixed defect table will be added after defect triage and resolution information is available.

| Defect ID | Summary | Severity | Owner | Status | Related PR / regression test |
|---|---|---|---|---|---|
| No confirmed defects recorded yet | Awaiting defect triage under PRC-04 (#4) | TBD | TBD | Pending triage | Pending |

This placeholder must be replaced with the actual defect information before the report is finalized.

## 6. Tests Not Executed

The test cases that were not executed have not yet been fully identified. They must be listed by their existing STP test case IDs after the test plan is compared with the CI results.

## 7. Conclusion

The available CI evidence reports 37 tests collected and 37 passed. The report remains a draft until the CI execution date, environment, run URL, test-case mapping, unexecuted tests, and PRC-04 defect summary have been verified and documented.
