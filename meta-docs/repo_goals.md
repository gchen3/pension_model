# Model Goals

## Purpose

A Python pension simulation model for **policy research** that projects pension costs, funded status, and employer contributions under baseline and alternative assumptions over a long-term horizon. The model is designed to generalize across U.S. public retirement systems — defined-benefit, defined-contribution, cash-balance, and hybrid plans, including supplemental features such as DROP — with configuration and data alone, and no plan-specific code.

## Primary Goals

- **Project long-term funded status** — model AAL, UAL, assets, and funded ratios year-by-year for each plan.
- **Estimate employer contributions** — compute normal cost and amortization payments under actuarial or statutory contribution policies.
- **Support scenario analysis** — allow overrides to economic assumptions, COLA rules, funding parameters, actuarial tables, and model horizon without code changes.
- **Generalize across plans and plan types** — support any number of plans through JSON configuration and CSV data alone, with zero Python changes required to add a new plan. Plan-specific behavior lives in configuration, not in special-case code for a particular plan. The same engine handles DB, DC, cash-balance, and hybrid (DB + DC or DB + CB) designs, as well as optional features such as DROP, variable COLAs, and employee-choice tiers.
- **Normalize heterogeneous source data** — public plans publish inputs in wildly different formats (PDFs, Excel, varying layouts). The model should provide an ingestion layer that lands everything in consistent internal formats (long CSVs, single-year bins, identifier columns).
- **Exploit actuarial math** — use closed-form solutions, recursive relationships, and commutation-function shortcuts from **Winklevoss** (book and notes) where they eliminate unnecessary computation. Don't brute-force what the math can simplify.
- **Full actuarial coverage of common plan features (long-term goal)** — over time, the model must be able to handle the full range of features commonly found in U.S. public retirement systems in an actuarially sound manner, not just the subset exercised by today's reference plans. This includes (non-exhaustive): multiple benefit tiers and membership classes; graded vesting; service-based and age-based eligibility; early-retirement reduction factors; final-average-salary and career-average formulas; cash-balance interest crediting (fixed, indexed, or floor-and-cap); DROP in its common variants (forward, backward, partial-lump-sum, with and without interest credits); purchase-of-service credit; variable and conditional COLAs; employee-choice between DB and DC; hybrid DB + DC and DB + CB stacks; disability and survivor benefits; refund-of-contributions options; and supplemental/13th-check benefits. Current implementations are intentionally limited to what the reference R models exercise. In particular, FRS DROP is today handled as a simplified adjustment to the active cohort rather than a full sub-cohort model of DROP participants — adequate for reproducing the R baseline, but a known limitation. Richer treatments are added as new plans require them, each with its own validation story.

## Validation Strategy: Match R First

Two reference R models (Reason Foundation's FRS and TX TRS) serve as the validation anchor. They are believed to be largely numerically correct, but each is a one-off build tied to its specific plan — not structured for reuse, not intended as a general modeling framework, and in places harder to read or extend than a purpose-built general model should be.

- **Reproduce R results exactly** before making any improvements. Tight numerical tolerances, not approximate agreement.
- When R appears wrong or suboptimal, **preserve R behavior** and open a GitHub issue. Fix later on its own branch, with its own validation story, ONLY AFTER THE MODEL IS GENERALIZED AND READY FOR NEW PLANS.
- Divergence from R is a bug until proven otherwise — never attributed to "inherent R vs. Python differences."
- Once a plan matches R, the R model is no longer load-bearing: the Python model stands on its own tests and identities.

## Priority Order

1.  **Match R** — reproduce baselines numerically.
2.  **Generalize** — remove any code that only works for one specific plan; move that behavior into configuration files instead.
3.  **Optimize** — profile and speed up the **core projection code** (the year-by-year solve that runs from the stage-3 inputs through the final results). That is the only place where runtime matters for policy work; data prep and tests can be slow.
4.  **Extend** — add new plans (CalPERS, NYSLRS, etc.) by configuration alone.

Each step validates the previous one.

## Design Principles

- **Explicit over implicit** — commands and tests must be told which plan and scenario to run; the model never guesses or falls back to a default plan. Configuration is read and checked up front, not pieced together as the run progresses.
- **Separate the math from the plumbing** — the core projection code takes inputs, returns outputs, and does nothing else: no reading files, no writing files, no printing messages to the screen. Reading and writing files, logging, and saving results happen in wrapper code that calls the math. This keeps the math easy to test and cheap to re-run.
- **Check inputs once, at the door** — validate plan configuration and input data when they are first loaded, with clear error messages. Once inside the year-by-year projection, trust that the data is well-formed; do not repeat the same checks deep inside the code, because that makes bugs harder to find and slows down the core projection.
- **No workarounds without a paper trail** — if R behavior has to be preserved despite looking wrong, or a clean design has to wait, leave a comment pointing at a GitHub issue. No quiet hacks.
- **Type hints on public functions** — functions that other modules call, dataclasses, and config loaders carry Python type hints. Small internal helpers can skip them when types add noise without catching anything.
- **Single source of truth** — plan parameters live in one config file; assumptions live in one scenario file; no duplicated constants between Python and data files.
- **Data-driven** — plan rules live in configuration files and lookup tables, not inside if/else code. Benefit factors are read from rule tables using table lookups, not long chains of if/else conditions.
- **Member-status cohort modeling** — group members by their status in the pension system (active worker, DROP participant, disability retiree, deferred vested, service retiree, survivor/beneficiary) and model each status as its own sub-group with its own transitions, decrements, and cash flows, rather than lumping everything into adjustments on the active workforce. The current model approximates several of these statuses (DROP in particular); full status-by-status treatment is a long-term goal and is the natural vehicle for the "full actuarial coverage" goal above.
- **Calibrated, not reconstructed** — small adjustment factors align output with published actuarial valuations rather than modeling every detail from first principles.
- **Clean architecture** — the code is broken into self-contained pieces; data flows through function arguments rather than through hidden shared variables; typed data structures are used where they help. The code should read as if designed from scratch to meet these goals, not as a port that retains vestiges of the R model.
- **Self-documenting code** — prefer clear names, small focused functions, and explicit types over comments. Add comments only where intent is not obvious from the code (non-obvious rules that must hold true, actuarial provenance, intentional workarounds). Keep longer-form explanation in `docs/` rather than in code.
- **Fast where it matters** — the core projection code (year-by-year solve from stage 3 through results) is the only place where runtime matters. Data prep, data loading, and tests do not need to be fast. Inside the core projection, prefer array-at-a-time NumPy/pandas operations over row-by-row Python loops.
- **Memory-efficient in the core projection** — projection arrays can grow quickly with (years × cohorts × member statuses × plans). Inside the core projection, prefer updating arrays in place and using compact NumPy arrays over wide, duplicated tables; do not keep large working data around after the step that needs it. As with speed, this applies only to the core projection — not to data prep or tests.
- **Uniform output** — all plans produce the same columns in the same order; inapplicable values are NA. No plan-specific output paths or formats.
- **Well tested** — automated tests compare each plan's output against the R baseline; actuarial identity checks (e.g., the MVA balance identity) verify that accounting relationships hold; year-by-year reasonableness checks catch obviously wrong numbers. Tests require an explicit plan name; no silent defaults.

## Current Repo Boundary

This repository owns the canonical pension-model runtime:

- typed plan configuration and rule resolution
- canonical CSV/JSON input loading
- liability projection
- funding projection
- calibration
- validation against R baselines and internal identities

This repository does **not** aim to own every upstream data-extraction step from source PDFs, spreadsheets, or bespoke actuarial workbooks. Those sources should be normalized into the plan-specific `plans/{plan}/data/` layout before they enter the runtime model.

The current runtime boundary is:

```text
plan config + canonical input tables
  -> config validation / rule resolution
  -> liability pipeline
  -> funding pipeline
  -> uniform outputs + validation
```

`docs/architecture_map.md` is the current map of that runtime structure. As code is refactored, the documentation should prefer these stage boundaries and stable public entry points over fragile function-by-function implementation detail.

## Current Scope

- Two reference plans: **Florida Retirement System** (FRS, 7 membership classes, with DROP) and **Texas TRS** (1 class).
- Benefit types exercised today: defined benefit (DB), defined contribution (DC), and cash balance (CB); FRS exercises DROP.
- Target scope includes hybrid designs (e.g., DB + DC stacked tiers, DB + CB) and additional supplemental features as new plans are added.
- Cohort-level projection (entry age × years of service), not individual member records.

## The Following are Not Goals

- Not a replacement for an actuarial valuation.
- Not a drop-in replacement for the R models — a clean redesign that matches them numerically, not a line-by-line port.
- Does not model individual member records.
- Does not optimize contribution policy (evaluates policies; does not search for optimal ones).

## Project Procedures

- **Feature-branch workflow** — always work on a feature branch. Never commit directly to `main`.
- **No merge without permission** — never merge a feature branch into `main` without explicit permission from the project owner.
- **No push to origin/main without permission** — never push `main` to the remote without explicit permission.
- **Verify before merge** — before requesting a merge, inspect actual output numbers (not just test pass/fail): R-baseline diffs, identity checks, and year-by-year reasonableness. A green test suite is necessary but not sufficient.
- **File issues, don't silently fix** — when R appears wrong or a cleaner design is obvious, open a GitHub issue and keep R-matching behavior in the current branch. Potential improvements will be worked on on their own branches with their own validation.
- **Phase-label every open issue** — every open issue carries exactly one phase label, applied when it is filed. `phase-r-is-truth` (green) is for work that fits the current Match-R phase: bug fixes, tests, documentation, or investigation that preserves R behavior. `phase-post-r` (purple) is for work that should wait until R-matching is done — typically because it would change R behavior or depends on later cleanup. `phase-anytime` (blue) is for work that is orthogonal to the phase ordering, such as upstream data-prep and provenance reviews that live outside the runtime boundary. An untagged open issue means it still needs to be triaged.

## Questions for Reason

1.  What policy options are crucial for modeling?

2.  What is the next plan you'd like to have incorporated into the model?
