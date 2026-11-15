from pathlib import Path

from scripts.project_progress import load_sprints, render_report


def test_sprint_overview_uses_existing_evidence_based_sprints():
    sprint_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "SPRINTS_AND_MILESTONES.md"
    )

    sprints = load_sprints(sprint_path)

    assert [sprint["sprint"] for sprint in sprints] == [
        "Sprint 1",
        "Sprint 2",
        "Sprint 3",
    ]
    assert {sprint["status"] for sprint in sprints} == {"Completed"}


def test_report_handles_no_milestones_and_open_tasks():
    report = render_report(
        repository="yashita164/SE-Mini-Project",
        branch="main",
        commit_sha="abc123",
        sprints=[],
        milestones=[],
        open_issues=[
            {
                "number": 123,
                "title": "Document future work",
                "state": "open",
                "milestone": None,
            }
        ],
        timestamp="2026-11-15T00:00:00Z",
    )

    assert "**No GitHub milestones configured yet.**" in report
    assert "N/A — no GitHub milestones configured" in report
    assert "[#123 Document future work]" in report


def test_report_handles_milestone_with_zero_issues():
    report = render_report(
        repository="yashita164/SE-Mini-Project",
        branch="main",
        commit_sha="abc123",
        sprints=[],
        milestones=[
            {
                "number": 1,
                "title": "Empty milestone",
                "description": "No issues assigned",
                "state": "open",
                "due_on": None,
                "open_issues": 0,
                "closed_issues": 0,
            }
        ],
        open_issues=[],
        timestamp="2026-11-15T00:00:00Z",
    )

    assert "| 0 | 0 | 0 | 0.00% | Not set | open |" in report
    assert "0.00% (0/0 issues; no issues assigned)" in report
    assert "No open GitHub issues." in report


def test_milestone_progress_uses_closed_over_total_issue_counts():
    report = render_report(
        repository="yashita164/SE-Mini-Project",
        branch="main",
        commit_sha="abc123",
        sprints=[],
        milestones=[
            {
                "number": 1,
                "title": "Tracked milestone",
                "description": "Progress is based on issues",
                "state": "closed",
                "due_on": "2026-12-01T00:00:00Z",
                "open_issues": 1,
                "closed_issues": 3,
            }
        ],
        open_issues=[],
        timestamp="2026-11-15T00:00:00Z",
    )

    assert "| 1 | 3 | 4 | 75.00% | 2026-12-01 | closed |" in report
    assert "75.00% (3/4 issues)" in report
