# Project Conventions for Claude

This is a Python pension simulation model. Three project-level reference docs apply to every session — read them before doing substantial work:

- **[`meta-docs/repo_goals.md`](meta-docs/repo_goals.md)** — purpose, priority order (Match R → Generalize → Optimize → Extend), design principles, project procedures (feature-branch workflow, no merge without permission, file issues don't silently fix, phase-label every issue).
- **[`meta-docs/pension_math.md`](meta-docs/pension_math.md)** — actuarial math reference. Many model operations have closed-form or recursive shortcuts (commutation functions, annuity factors); many current implementations are approximations with known limits and tracked issues. When proposing a change, ask whether the math can simplify or accelerate it before reaching for ad-hoc code.
- **[`meta-docs/workflow.md`](meta-docs/workflow.md)** — how to update these meta files. Meta-doc edits go on their own short-lived branch with a PR, never bundled with feature work, never directly to main. Same workflow as feature work but separated.

## Quick rules

- We are in the **Match-R phase**. R behavior is preserved. When R appears wrong or a cleaner design is obvious, **file an issue and keep R-matching behavior on the current branch**. Do not silently "fix" anything.
- Every open issue must carry exactly one phase label: `phase-r-is-truth` (R-phase work), `phase-post-r` (deferred), or `phase-anytime` (orthogonal — data-prep, provenance, docs, tooling).
- The core projection (year-by-year solve from stage-3 inputs through final results) is the only place runtime matters. Data prep, loading, and tests can be slow.
- Validation against R baselines must hold to floating-point precision (~1e-15 relative). "Inherent R-vs-Python differences" is not an acceptable explanation for divergence.

## Writing style

In docs, PR descriptions, comments, and any prose the user reads or shares with collaborators, **default to plain English, not actuarial/quant/programming jargon**. Reserve technical terms for code-level references (function names, config keys, column names). For prose, paraphrase: "synthetic payment stream" → "estimated stream of future payments"; "PV the cashflows" → "compute today's value of the cashflows"; "anchored to data meaning" → describe the actual constraint plainly. When in doubt, ask: would a smart engineer who hasn't touched actuarial work understand this sentence in isolation?

## Other docs

- [`docs/architecture_map.md`](docs/architecture_map.md) — current runtime structure
- [`docs/developer.md`](docs/developer.md) — developer guide
- [`docs/design/`](docs/design/) — feature-specific design rationales (discount rate scenarios, termination rates, early retirement reduction)
- [`actuarial_calculations/winklevoss_formulas.md`](actuarial_calculations/winklevoss_formulas.md) — full Winklevoss formula reference (697 lines; deep dive when needed)
