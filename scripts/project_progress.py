"""Build the read-only GitHub Actions sprint and milestone dashboard."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _cell(value: object) -> str:
    return " ".join(str(value).replace("|", r"\|").split())


def load_sprints(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = "| Sprint | Title | Objective | Status | Evidence |"
    try:
        index = lines.index(header) + 2
    except ValueError as exc:
        raise ValueError(f"Sprint overview table not found in {path}") from exc

    sprints = []
    for line in lines[index:]:
        if not line.startswith("|"):
            break
        columns = [column.strip() for column in line.strip("|").split("|")]
        if len(columns) != 5:
            raise ValueError(f"Invalid sprint overview row: {line}")
        sprint = {
            "sprint": columns[0],
            "title": columns[1],
            "objective": columns[2],
            "status": columns[3],
            "evidence": columns[4],
        }
        if sprint["status"] not in {"Completed", "In Progress", "Pending"}:
            raise ValueError(f"Invalid status for {sprint['sprint']}: {sprint['status']}")
        sprints.append(sprint)

    if not sprints:
        raise ValueError(f"No sprint records found in {path}")
    return sprints


def fetch_github_list(token: str, repository: str, endpoint: str) -> list[dict]:
    page = 1
    results = []
    while True:
        request = Request(
            f"https://api.github.com/repos/{repository}/{endpoint}"
            f"&per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                page_results = json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"GitHub API request failed for {endpoint}: {exc}") from exc
        if not isinstance(page_results, list):
            raise RuntimeError(f"GitHub API returned an unexpected response for {endpoint}")
        results.extend(page_results)
        if len(page_results) < 100:
            return results
        page += 1


def render_report(
    *,
    repository: str,
    branch: str,
    commit_sha: str,
    sprints: list[dict[str, str]],
    milestones: list[dict],
    open_issues: list[dict],
    timestamp: str | None = None,
) -> str:
    timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    completed = sum(sprint["status"] == "Completed" for sprint in sprints)
    in_progress = sum(sprint["status"] == "In Progress" for sprint in sprints)
    pending = sum(sprint["status"] == "Pending" for sprint in sprints)
    report = [
        "# Project Progress & Sprint Milestones",
        "",
        "## Project Overview",
        "",
        "- **Project:** Python TCP Chat Application",
        f"- **Repository:** `{repository}`",
        f"- **Branch:** `{_cell(branch)}`",
        f"- **Commit:** `{_cell(commit_sha)}`",
        f"- **Workflow execution (UTC):** `{timestamp}`",
        "",
        "## Sprint Overview",
        "",
        "Sprint status is based on the documented project sprint records. "
        "It is separate from GitHub milestone issue-completion percentages.",
        "",
        "| Sprint | Title | Objective | Status | Evidence |",
        "|---|---|---|---|---|",
    ]
    for sprint in sprints:
        report.append(
            "| "
            + " | ".join(
                _cell(sprint[key])
                for key in ("sprint", "title", "objective", "status", "evidence")
            )
            + " |"
        )

    report.extend(
        [
            "",
            "## GitHub Milestone Overview",
            "",
            "| Milestone | Open Issues | Closed Issues | Total Issues | Progress | Due Date | State |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
    )
    closed_total = 0
    issue_total = 0
    for milestone in milestones:
        opened = int(milestone.get("open_issues", 0))
        closed = int(milestone.get("closed_issues", 0))
        total = opened + closed
        progress = (closed / total * 100) if total else 0.0
        closed_total += closed
        issue_total += total
        due_date = (milestone.get("due_on") or "Not set")
        if due_date != "Not set":
            due_date = due_date[:10]
        title = _cell(milestone.get("title", "Untitled milestone"))
        milestone_url = (
            f"https://github.com/{repository}/milestone/{milestone.get('number', '')}"
        )
        report.append(
            f"| [{title}]({milestone_url}) | {opened} | {closed} | {total} "
            f"| {progress:.2f}% | {_cell(due_date)} | {_cell(milestone.get('state', 'unknown'))} |"
        )

    if not milestones:
        report.extend(["", "**No GitHub milestones configured yet.**"])
        milestone_progress = "N/A — no GitHub milestones configured"
    elif issue_total:
        milestone_progress = f"{closed_total / issue_total * 100:.2f}% ({closed_total}/{issue_total} issues)"
    else:
        milestone_progress = "0.00% (0/0 issues; no issues assigned)"

    if milestones:
        report.extend(["", "### Milestone descriptions", ""])
        for milestone in milestones:
            description = _cell(milestone.get("description") or "No description provided.")
            report.append(f"- **{_cell(milestone.get('title', 'Untitled milestone'))}:** {description}")

    issues = [issue for issue in open_issues if "pull_request" not in issue]
    issues.sort(key=lambda issue: issue["number"])
    report.extend(["", "## Outstanding Tasks", ""])
    if issues:
        for issue in issues:
            milestone = issue.get("milestone")
            milestone_text = (
                f" — milestone: {_cell(milestone['title'])}"
                if milestone
                else " — no milestone"
            )
            report.append(
                f"- [#{issue['number']} {_cell(issue['title'])}]"
                f"(https://github.com/{repository}/issues/{issue['number']})"
                f"{milestone_text}"
            )
    else:
        report.append("No open GitHub issues.")

    report.extend(
        [
            "",
            "## Overall Project Progress",
            "",
            f"- **Actual sprints documented:** {len(sprints)}",
            f"- **Completed sprints:** {completed}",
            f"- **In-progress sprints:** {in_progress}",
            f"- **Pending sprints:** {pending}",
            f"- **Configured GitHub milestones:** {len(milestones)}",
            f"- **Overall milestone issue progress:** {milestone_progress}",
            "",
            "Sprint counts describe documented sprint status; milestone progress "
            "is closed issues divided by total issues assigned to configured milestones. "
            "These are distinct measures.",
        ]
    )
    return "\n".join(report) + "\n"


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    report_path = Path(os.environ["GITHUB_STEP_SUMMARY"])
    sprints = load_sprints(Path("docs/SPRINTS_AND_MILESTONES.md"))
    milestones = fetch_github_list(token, repository, "milestones?state=all")
    open_issues = fetch_github_list(token, repository, "issues?state=open")
    report = render_report(
        repository=repository,
        branch=os.environ["DASHBOARD_BRANCH"],
        commit_sha=os.environ["COMMIT_SHA"],
        sprints=sprints,
        milestones=milestones,
        open_issues=open_issues,
    )
    with report_path.open("a", encoding="utf-8") as summary:
        summary.write(report)


if __name__ == "__main__":
    main()
