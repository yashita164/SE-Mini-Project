# Sprint and Milestone Tracking

This record is based on the repository's development evidence, sprint labels
on GitHub Issues, and the test and validation documents. The repository does
not contain a formal sprint plan with canonical sprint titles or dates.
Accordingly, the headings below retain the evidenced sprint numbering; the
descriptive titles and objectives summarize the recorded work, not new sprint
assignments. No sprint dates or team-member assignments are inferred.

## Sprint overview

The progress workflow reads this table to build the Actions summary. Keep its
header and status values (`Completed`, `In Progress`, or `Pending`) intact when
updating the sprint record.

| Sprint | Title | Objective | Status | Evidence |
|---|---|---|---|---|
| Sprint 1 | Title not recorded — initial chat prototype | Establish the initial TCP chat prototype with registration, login, private messaging, typing indicators, and project/CI setup. | Completed | [Initial prototype commit](https://github.com/yashita164/SE-Mini-Project/commit/67d98b3); [Sprint 1 recovery record](./deviations.md#4-sprint-1-recovery); [CI verification issue #1](https://github.com/yashita164/SE-Mini-Project/issues/1) |
| Sprint 2 | Title not recorded — chat features and reliability | Extend the chat application with messaging, rooms, persistence, file transfer, administration, reliability/security improvements, and verification. | Completed | [Sprint 2 feature issue](https://github.com/yashita164/SE-Mini-Project/issues/29); [final Sprint 2 test report](./test-report.md); [deviations and Sprint 1 carryover](./deviations.md) |
| Sprint 3 | Title not recorded — desktop GUI and validation | Implement the desktop GUI and complete the associated test-case, coverage, and system-validation evidence. This sprint includes application work as well as testing/documentation; it is not a testing-only sprint. | Completed | [GUI foundation issue #71](https://github.com/yashita164/SE-Mini-Project/issues/71); [GUI/file-transfer issue #74](https://github.com/yashita164/SE-Mini-Project/issues/74); [Sprint 1–3 test-case document](./test-case-document.md); [system validation report](./system-validation-report.md); [coverage reports](./code-coverage-report.md) |

Sprint 1 recovery notes identify the prototype, authentication and CI work,
and record that two documentation items were carried into Sprint 2. Sprint 2
has a final test report and the repository's issue history records its feature
and test/documentation work. Sprint 3 is evidenced by issues labelled
`sprint-3` and the GUI and validation records. The sprint labels and closed
issues support the statuses above; these statuses do not imply that every
manual test was repeated in the latest validation.

## Sprint 1 — initial chat prototype

- **Objective:** Build the initial working TCP chat flow and establish the
  project setup.
- **Features and development tasks:** The initial prototype commit records
  registration, login, private messaging, and typing indicators. The Sprint 1
  recovery notes also identify bcrypt verification, offline-message queueing,
  a latency test, defect tracking, pull-request workflow, and authentication
  and CI setup. The notes state that the remaining Sprint 1 code work was
  integrated on 26 October and that only RTM/deviation documentation was
  carried into Sprint 2.
- **Testing and quality:** Authentication and messaging tests were retained;
  CI setup and verification are evidenced by issue #1. Later test reports
  provide the final verified results and are not represented as a separate
  sprint.
- **Bug fixes and improvements:** Sprint 1 recovery work completed the
  remaining code tasks before the documented Sprint 2 carryover.
- **Acceptance criteria:** Registration/login and private chat/typing behavior
  are present in the prototype, and the test workflow is demonstrated on push
  and pull request. The CI issue records those workflow checks.
- **Acceptance evidence:** Prototype commit, CI verification issue, and
  [Sprint 1 recovery record](./deviations.md#4-sprint-1-recovery).
- **Status:** Completed, based on the recovery record and merged prototype and
  CI work.

## Sprint 2 — chat features and reliability

- **Objective:** Expand the chat product and verify its messaging, room,
  persistence, reliability, security, and operational requirements.
- **Features and development tasks:** The issue history records private and
  offline messaging, acknowledgements, history, rooms, presence, GUI/client
  responsiveness-related backend behavior, TLS, administration, and login
  rate limiting. The [deviations register](./deviations.md) documents selected
  implementation details and known limits.
- **Testing activities:** The [final test report](./test-report.md) records
  148 passing automated tests for the Sprint 2 final run and verification of
  all 29 STP cases, including separate latency and concurrency measurements.
  Defect triage and fixes are listed in that report.
- **Acceptance criteria:** The documented STP cases pass, offline/history and
  room/file behavior are verified by the suite, and the two performance
  measurements meet their documented targets. The test report records these
  results.
- **Acceptance evidence:** Closed Sprint 2 issues, test report, defect log, and
  [RTM](./RTM-Issue-12.md).
- **Status:** Completed, supported by the final Sprint 2 report and closed
  issue evidence.

## Sprint 3 — desktop GUI and validation

- **Objective:** Add the desktop user interface and record the tests and
  system-validation evidence for the Sprint 1–3 product changes.
- **Features and development tasks:** Sprint 3 issues #70–74 cover the basic
  desktop GUI, shared client layer, authentication, private chat/history,
  group chat, and file attachments. The current repository contains the GUI
  modules and associated tests.
- **Testing and quality activities:** Issues #78–82 cover the Sprint 1–3 test
  case document, unit-test report, system-validation report, code coverage,
  and branch coverage. The system-validation report records 184 automated
  tests passing and successful performance/scalability measurements.
- **Bug fixes and improvements:** The test and validation records document
  verified fixes, coverage, and known deviations from the SRS.
- **Acceptance evidence:** Closed Sprint 3 issue records, the
  [test-case document](./test-case-document.md), [system-validation report](./system-validation-report.md),
  [test report](./test-report.md), and coverage reports.
- **Acceptance criteria:** The scoped GUI issues and test/coverage documents
  have corresponding closed issue records, and the system-validation report
  records passing automated and performance checks. The report notes that the
  manual GUI checklist was not rerun during that validation.
- **Status:** Completed according to the closed Sprint 3 issue set and
  supporting reports. The test-case document is still marked Draft, and the
  system-validation report explicitly says the manual GUI checklist was not
  rerun during that validation; those caveats remain visible and are not
  claimed as newly executed acceptance tests.

## CI/CD and deployment scope

GitHub Actions test automation and CI setup are documented as Sprint 1 work.
Testing and coverage are evidenced in Sprints 2 and 3. The current
`Chat Application CI/CD` workflow also has an intentionally skipped deployment
simulation. The repository does not establish that this later simulation was
part of a separate team sprint, so it is not used to invent one. No real
deployment or external hosting is performed.

## GitHub milestone source of truth

Milestone titles, descriptions, issue counts, due dates, and state are read at
workflow runtime from the repository's GitHub Milestones API. The
`Project Progress & Sprint Milestones` workflow is read-only and never creates
or edits milestones or issues. These milestones were created using the
objectives above; due dates are unset because the original sprint dates were
not recorded:

- **Sprint 1 – Initial Prototype**
- **Sprint 2 – Chat Features and Reliability**
- **Sprint 3 – Desktop GUI and Validation**

The Iteration field on every item in the complete GitHub Projects board #1
(`SE Mini-Project — Team 5 Chat Application`) is the source of truth for
milestone membership. All 51 board items were retrieved; each links to an issue
in this repository, and no pull requests or draft items were present. Existing
issue labels were not used to override a board Iteration.

| Milestone | Assigned issues |
|---|---|
| Sprint 1 – Initial Prototype | #1–#3, #5–#6, #8–#9, #13–#14, #17, #20–#22, #25 |
| Sprint 2 – Chat Features and Reliability | #4, #7, #10–#12, #15–#16, #18–#19, #23–#24, #26–#41 |
| Sprint 3 – Desktop GUI and Validation | #70–#74 |

The board places issue #5 in Sprint 1; it is assigned to the Sprint 1
milestone despite its conflicting issue labels. Issues #78–#82 are linked to
the project board but have no Iteration value, so they are not assigned to a
sprint milestone. No board item was missing a GitHub issue link.

The progress summary calculates issue completion separately for each
milestone. Sprint completion counts and milestone issue-completion
percentages are distinct measures.
