# Working with Meta Files

This doc tells the engineer (Claude or human) how to make changes to the project's meta files. It exists so that the process for updating project-level rules is itself a project-level rule, not tribal knowledge.

## What counts as a meta file

- `CLAUDE.md` at the repo root — the entry point that points at `meta-docs/`
- Anything under `meta-docs/`:
  - `repo_goals.md` — purpose, priority order, design principles, project procedures
  - `pension_math.md` — actuarial-math reference for model work
  - `workflow.md` — this file

Add a new file under `meta-docs/` only when the content is **stable, project-level, and not coupled to current code state**. If the content is tied to specific modules or evolves with refactors, it belongs in `docs/` (project documentation), `docs/design/` (feature design rationales), or as a code comment.

## What does NOT belong in meta-docs

- Architecture descriptions of the current code (use `docs/architecture_map.md`)
- Feature design rationales (use `docs/design/`)
- Developer setup, plan structure, calibration procedure (use `docs/developer.md`)
- Session work, plans, transcripts, in-progress validation notes (use git history, GitHub issues, or PR descriptions — not files)
- Anything that "rots" as code changes

## When to update a meta file

Update meta-docs when:

- A new convention is agreed in conversation that should hold across all future work ("from now on, X")
- A pension-math insight is discovered that should shape future design decisions (closed-form opportunity, identity to preserve, approximation to flag) — add to `pension_math.md`
- A new persistent project-level rule emerges (e.g., a new label convention, a new branch-naming rule)
- An existing rule is corrected or refined

Do **not** update meta-docs for one-off task notes, bug-fix specifics, or anything that belongs in a commit message, PR description, or GitHub issue.

## How to update a meta file (process)

Meta-doc changes go on their own short-lived branch with a PR — same workflow as feature work, but separated from any code work in flight.

```bash
# 1. Sync main
git checkout main && git pull

# 2. Branch
git checkout -b meta-<short-description>
# e.g., meta-add-cola-design-pointer, meta-pension-math-cola-section

# 3. Edit
# only meta-docs/* and/or CLAUDE.md should change in this branch

# 4. Commit with a clear message; describe the rule/insight, not the diff
git add meta-docs/<file>.md CLAUDE.md
git commit -m "<subject line: what the rule/insight is>"

# 5. Push
git push -u origin meta-<short-description>

# 6. PR
gh pr create --title "<title>" --body "<body explaining the rule/insight and why>"

# 7. Merge — REQUIRES PROJECT OWNER PERMISSION
# Per repo_goals.md, never merge without explicit permission.
# If you are the project owner, self-merge via GitHub UI or `gh pr merge --squash`.

# 8. Sync and clean up
git checkout main && git pull && git branch -d meta-<short-description>
```

## Don't bundle meta-doc edits with feature work

If you realize mid-feature that a meta-doc needs updating:

```bash
git stash                        # set the feature work aside
git checkout main && git pull
git checkout -b meta-<desc>
# ... do the meta-doc edit, PR, merge as above ...
git checkout <feature-branch>
git stash pop
git merge main                   # pick up the new meta-doc on the feature branch
```

Keeping meta-doc edits on their own branch:

- Makes the rule discoverable in a focused PR, not buried in a large feature diff
- Lets the meta-doc land on `main` quickly so it applies to all in-flight branches
- Avoids tying a stable convention to a feature that might be reverted or rebased

## How feature branches see new meta-doc rules

Regularly `git merge main` (or `git rebase main`) into your in-progress feature branches. This is normal git hygiene; it caps the staleness window for meta-doc updates at one sync cycle.

## What's NOT covered by this workflow

- Project documentation in `docs/` (architecture_map, developer guide, demo, design rationales) **travels with code**. Update it on the same feature branch as the code change it describes — same PR, no separate meta-doc branch.
- Code comments and docstrings always travel with the code that contains them.

## Why this matters

The cost of a meta-doc edit is ~2–5 minutes of branch + PR overhead. The benefit is that:

- New conventions land on `main` quickly and propagate to all branches via the next sync
- Each rule has a discoverable PR that a collaborator (or future you) can find via `gh pr list --search "meta-"`
- Meta-docs never accidentally ship with feature work that gets reverted
- The "always available everywhere" property of meta-docs is real, not aspirational

The cost of getting this wrong (bundling meta-docs with features, committing meta-docs directly to main, letting rules live only in conversation) is invisible until it bites — usually months later when someone needs the rule and can't find it.
