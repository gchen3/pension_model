# Model Goals

## Purpose

A Python pension simulation model for **policy research** that projects pension costs, funded status, and employer contributions under baseline and alternative assumptions over a long-term horizon. The model is designed to generalize across U.S. public retirement systems — defined-benefit, defined-contribution, cash-balance, and hybrid plans, including supplemental features such as DROP — with configuration and data alone, and no plan-specific code.

## Primary Goals

- **Project long-term funded status** — model AAL, UAL, assets, and funded ratios year-by-year for each plan.
- **Estimate employer contributions** — compute normal cost and amortization payments under actuarial or statutory contribution policies.
- **Support scenario analysis** — allow overrides to economic assumptions, COLA rules, funding parameters, actuarial tables, and model horizon without code changes.
- **Generalize across plans and plan types** — support any number of plans through JSON configuration and CSV data alone, with zero Python changes required to add a new plan. Plan-specific behavior lives in configuration, not in `if plan == ...` branches. The same engine handles DB, DC, cash-balance, and hybrid (DB + DC or DB + CB) designs, as well as optional features such as DROP, variable COLAs, and employee-choice tiers.
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

1. **Match R** — reproduce baselines numerically.
2. **Generalize** — remove plan-specific code paths; move behavior into config.
3. **Optimize** — profile and speed up the stage-3-to-results solve path (the only path where runtime matters for policy work).
4. **Extend** — add new plans (CalPERS, NYSLRS, etc.) by configuration alone.

Each step validates the previous one.

## Design Principles

- **Data-driven** — plan rules live in config files and lookup tables, not code branches. Benefit factors use inequality joins against rule tables, not if/else ladders.
- **State-based cohort modeling** — actuarially distinct member states (active, DROP participant, disability retiree, deferred vested, service retiree, survivor/beneficiary) should be represented as their own sub-cohorts with explicit transitions, decrements, and cash flows, rather than folded into aggregate adjustments on the active population. The current model approximates several of these states (DROP in particular); full state-based treatment is a long-term goal and is the natural vehicle for the "full actuarial coverage" goal above.
- **Calibrated, not reconstructed** — small adjustment factors align output with published actuarial valuations rather than modeling every detail from first principles.
- **Clean architecture** — modular design, explicit state passing, no global state, typed dataclasses where they help. The code should read as if designed from scratch to meet these goals, not as a port that retains vestiges of the R model.
- **Self-documenting code** — prefer clear names, small focused functions, and explicit types over comments. Add comments only where intent is not obvious from the code (non-obvious invariants, actuarial provenance, intentional workarounds). Keep longer-form explanation in `docs/` rather than in code.
- **Fast where it matters** — the stage-3-to-results solve is the only runtime-sensitive path. Data prep, ingestion, and tests do not need to be fast. On the hot path, prefer vectorized NumPy/pandas over Python loops.
- **Memory-efficient on the hot path** — projection arrays can grow quickly with horizon × cohorts × states × plans. Prefer in-place updates and typed NumPy arrays over wide, duplicated DataFrames on the solve path; avoid retaining large intermediates beyond the stage that needs them. As with speed, this applies to the solve path — not to data prep or tests.
- **Uniform output** — all plans produce the same columns in the same order; inapplicable values are NA. No plan-specific output paths or formats.
- **Well tested** — R-baseline regression tests, actuarial identity checks (e.g., MVA balance identity), and year-by-year reasonableness checks. Tests require explicit plan names; no silent defaults.

## Current Scope

- Two reference plans: **Florida Retirement System** (FRS, 7 membership classes, with DROP) and **Texas TRS** (1 class).
- Benefit types exercised today: defined benefit (DB), defined contribution (DC), and cash balance (CB); FRS exercises DROP.
- Target scope includes hybrid designs (e.g., DB + DC stacked tiers, DB + CB) and additional supplemental features as new plans are added.
- Cohort-level projection (entry age × years of service), not individual member records.

## Non-Goals

- Not a replacement for an actuarial valuation.
- Not a drop-in replacement for the R models — a clean redesign that matches them numerically, not a line-by-line port.
- Does not model individual member records.
- Does not optimize contribution policy (evaluates policies; does not search for optimal ones).

## Project Procedures

- **Feature-branch workflow** — always work on a feature branch. Never commit directly to `main`.
- **No merge without permission** — never merge a feature branch into `main` without explicit permission from the project owner.
- **No push to origin/main without permission** — never push `main` to the remote without explicit permission.
- **Verify before merge** — before requesting a merge, inspect actual output numbers (not just test pass/fail): R-baseline diffs, identity checks, and year-by-year reasonableness. A green test suite is necessary but not sufficient.
- **File issues, don't silently fix** — when R appears wrong or a cleaner design is obvious, open a GitHub issue and keep R-matching behavior in the current branch. Improvements land on their own branches with their own validation.
