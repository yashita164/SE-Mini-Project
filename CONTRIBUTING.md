# Contributing

## Branches and commits

- Create a branch from `main` named `feature/<issue-number>-<short-description>`, `bugfix/<issue-number>-<short-description>`, or `docs/<issue-number>-<short-description>`.
- Use commit messages in the format `<type>: <short imperative description>`. Common types are `feat`, `fix`, `docs`, `test`, and `chore`.
- Push your branch to the repository before opening a pull request. Do not push changes directly to `main`.

## Pull requests

- Open a pull request from your branch into `main`.
- Link the related issue in the pull request. Use `Closes #<issue-number>` when the pull request completes that issue.
- Complete the pull request checklist and provide screenshots, logs, or other evidence when applicable.
- Request an independent review from someone other than the pull request author. Do not merge until that review is complete and any requested changes are addressed.

### Pull request checklist

- [ ] Implementation is complete.
- [ ] Relevant tests pass.
- [ ] CI is green. The repository test workflow runs `python -m pytest -v` for pull requests.
- [ ] Screenshots, logs, or other evidence are attached when applicable.
- [ ] No unresolved merge conflicts remain.