# Issue tracker: GitHub

Issues and specs live in the private GitHub repository `wei0210-bit/managing-long-task-context`.

Use the `gh` CLI for issue operations.

- Create: `gh issue create`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open`
- Comment: `gh issue comment <number>`
- Label: `gh issue edit <number> --add-label "..."`
- Close: `gh issue close <number> --comment "..."`

Infer the repository from the local `origin` remote.

## Pull requests as a triage surface

PRs as a request surface: no.

## Skill conventions

- “Publish to the issue tracker” means create a GitHub issue.
- “Fetch the relevant ticket” means read the issue body, labels, and comments.
- Issues are the canonical planning surface; implementation evidence remains in commits, tests, and linked artifacts.

## Wayfinding operations

- A map is one issue labelled `wayfinder:map`; child tickets link back to it.
- Prefer GitHub sub-issues and native issue dependencies when available.
- When those features are unavailable, use task-list links and a `Blocked by: #<n>` line.
- Claim work with `gh issue edit <n> --add-assignee @me` before implementation.
- Resolve work by posting the result and evidence, then closing the issue.
