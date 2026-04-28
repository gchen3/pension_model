# Discount Rate Scenarios: A Primer

## What this primer is for

You're about to read code and config that runs "discount rate" scenarios — most prominently a high_discount scenario that pushes the rate from ~6.7% to 7.5%. This document explains:

- What rate-like assumptions actually exist in the model (just three).
- Two genuine ways to read a "high discount rate" scenario, and how they differ.
- What the FRS and TXTRS R reference models do under high_discount.
- Why current term-vested members need slightly different handling than retirees and actives, and why that handling is *not* a third discount rate role.
- How the scenario JSON files express intent.

Read this when you want the *concept*. The code is the implementation.

## The setup

A pension plan owes future benefit payments to its members. To know whether the plan has enough assets to pay them, the actuary:

1. **Projects future benefit payments** for each member cohort — actives, retirees, term-vested (people who left the workforce but haven't yet started collecting), DROP participants, etc.
2. **Discounts those projected payments** back to today's dollars. The result is the AAL and related quantities.
3. **Projects assets forward** at an assumed return.
4. **Compares projected assets to the AAL** to compute the funded ratio and required employer contributions.

Steps 2 and 3 each depend on a rate assumption. By US public-pension convention, both rates are normally the same number — but conceptually they are two distinct uses of the assumption, and a "discount rate scenario" can move them together or separately.

## Acronyms

- **PVFB** — *Present Value of Future Benefits*. The PV of *all* future benefit payments to current members, including benefits that will be earned through future service.
- **PVFNC** — *Present Value of Future Normal Cost*. The PV of contributions the actuary expects will accumulate for service members have not yet rendered.
- **AAL** — *Actuarial Accrued Liability*. The portion of PVFB attributable to *past* service.
- **PVFS** — *Present Value of Future Salaries*. Used in cost-method calculations that allocate liability based on salary (e.g., Entry Age Normal).
- **NC** — *Normal Cost*. The per-year version of PVFNC.

The fundamental identity:

```
PVFB = AAL + PVFNC
```

Concrete example. A 30-year-old active with 5 years of service who will retire at 60 with 35 years:

- PVFB ≈ \$500,000
- AAL ≈ 5/35 × \$500,000 ≈ \$71,000 (under projected unit credit)
- PVFNC ≈ \$429,000
- Sum back to PVFB ✓

For different member statuses, the AAL/PVFB relationship differs:

| Status | AAL vs PVFB | Reason |
|---|---|---|
| Active | AAL \< PVFB | Future service accrual still ahead |
| DROP | varies | Typically not accruing further DB; DROP balance is separate |
| Retiree | AAL = PVFB | No future service; benefit stream is locked |
| Term-vested | AAL = PVFB | No future service; benefit was frozen at termination |

For retirees and term-vested members, AAL = PVFB so the model can take a single PVFB and treat it as the year-1 AAL. For actives, the model must project PVFB, PVFS, and NC separately at each year and derive AAL.

## The three rate assumptions

The model has exactly three rate-like inputs that show up in scenarios:

- **`dr_current`** — discount rate for liabilities of *current* members (current actives, current retirees, current term-vested).
- **`dr_new`** — discount rate for liabilities of *future hires*. For FRS and TXTRS this equals `dr_current`. The split exists in case a plan ever wants to value a new tier at a different rate. Today, two names for one number.
- **`model_return`** — assumed investment return on plan assets. Drives asset projections.

By US public-pension convention, all three normally equal each other. A scenario file changes one or more of them.

There is no fourth "cashflow discount rate." When you see that phrase elsewhere in the codebase or in older drafts of this document, read it as a clumsy name for "the rate the input `PVFB_term_current` was published at" — which is just the baseline `dr_current` from before any scenario override. It is not a separate scenario assumption; it is a fixed property of the input data file.

## Two ways to read "high discount rate scenario"

Crystallized: the difference between Reading A and Reading B is **whether `model_return` moves with `dr_current` or stays put**. Everything else follows from that.

### Reading A: Valuation sensitivity (GASB style)

> "Hold investment assumptions constant. Just rediscount the same benefit stream at a different rate."

This is what GASB 67/68 requires plans to disclose annually: AAL at the discount rate, AAL at +1%, AAL at -1%. A measurement exercise.

In scenario terms: **change `dr_current`/`dr_new`. Leave `model_return` alone.**

What follows:
- Future benefit payments do not change (plan rules are plan rules).
- Liability discount factors and annuity factors recompute at the new rate. AAL, PVFB, PVFNC, NC all move.
- Asset projections continue to roll at the original `model_return`.
- Funded ratio moves only from the liability side.

### Reading B: Consistent assumption change

> "Suppose the actuary had assumed a higher long-term return all along. What would the valuation look like?"

In scenario terms: **change `dr_current`/`dr_new` AND `model_return`.**

What follows:
- Future benefit payments do not change.
- Liability side moves the same way as in Reading A.
- Asset projections also roll at the new rate (so the projected asset trajectory is steeper).
- Required contributions adjust (lower NC and lower amortization payment because liabilities discount harder; asset side rolls faster).
- Funded ratio moves from both sides.

### Why the distinction matters

The same input ("set the rate to 7.5%") produces different funded-ratio trajectories depending on which reading you intend. Reading A moves only the liability side. Reading B also moves the asset side. A scenario file should declare which it wants by overriding the appropriate subset of the three rate assumptions.

## How the FRS and TXTRS R reference models read high_discount

R sets `dr_current = dr_new = model_return = 0.075` — that is **Reading B**. Liability discounting, annuity factors, and asset projection all move to 7.5%.

| Component | What R does under high_discount |
|---|---|
| Active members | Re-derives PVFB, PVFS, NC at 7.5%; annuity factors recompute |
| Retirees | Recomputes PV of projected benefit stream at 7.5%; annuity factors recompute |
| Current term-vested | Sizes synthetic 50-year payment stream against input PVFB at 6.7%, then PVs that stream at 7.5% |
| Asset side | Projects asset growth at 7.5% |

The first two rows and the last row are unsurprising — change the rate, recompute the math. The third row is where this primer earns its keep.

## Why current term-vested looks different (it isn't)

For active members and retirees, the model has cohort-level data:

- Actives: each (entry age × YOS) cohort has its own salary, decrement rates, accrual schedule.
- Retirees: each age cohort has its own count, average benefit, mortality, and COLA. (`plans/{plan}/data/demographics/retiree_distribution.csv`.)

Given cohort-level data, the engine can build the actual benefit cashflow stream from plan rules. The discount rate enters only when those cashflows are PV'd. Change the rate → recompute discount factors and annuity factors → get a new PV. Cashflows are unchanged. This is true under both Reading A and Reading B.

For the *current term-vested* cohort (Component 1 below) the input is different. The published actuarial valuation gives us a single number — `PVFB_term_current` — defined as "the PV of future benefit payments to currently term-vested members, computed at the actuarial valuation's discount rate (6.7%)." There is no underlying breakdown by age, deferral period, or accrued benefit. So the engine has nothing to PV directly — there is no cashflow on file.

The engine *estimates* one. The estimate is a 50-year smooth amortization payment schedule, sized so that its NPV at 6.7% equals `PVFB_term_current`. The 6.7% sizing rate isn't a modeling choice — it's dictated by what the input number means. `PVFB_term_current` is "this many dollars of PV at 6.7%"; the synthetic stream is calibrated to honor that statement. If you sized the stream at any other rate, you would be asserting something different about what the input represents.

Once the synthetic stream exists, it is treated as the model's best estimate of the cohort's actual benefit cashflow, and it gets discounted at the scenario `dr_current` exactly the same way retiree and active cashflows do.

So R's current term-vested treatment is not a different *reading* of the scenario. It's the same Reading B as everywhere else, applied to an *estimated* cashflow rather than a built-from-rules cashflow. The "two rates" — 6.7% to size, 7.5% to discount — are not a third rate role. They are:

- The **baseline rate** anchored to the meaning of the input data (always 6.7% here, never moves under any scenario).
- The **scenario `dr_current`** (7.5% under high_discount).

The engine just needs to know to use the baseline rate when sizing and the scenario rate when discounting. No extra config knob is required.

## The two slices of term-vested liability

The term-vested cohort is not static in our open-group projection. Every year, some active members terminate vested and become new term-vested members; some current term-vested members start collecting benefits or die. The R and Python models split term-vested liability into two distinct components:

**Component 1: Current term-vested cohort** (the year-1 snapshot only)
- Members already term-vested AS OF the valuation date.
- Input: a single rolled-up `PVFB_term_current`.
- Amortized over a long period (50 years for FRS and TXTRS) via the synthetic stream described above.
- Yields `aal_term_current_est` (R) / equivalent in Python.
- **This is the only component where any cashflow estimation happens.**
- As years pass, this component declines monotonically as the original cohort collects benefits and dies.

**Component 2: Newly-vested terminations from active service**
- Each year, the active-member model applies vested-termination decrement rates and produces, for each (entry age × YOS) cohort, a number of new term-vested members and the PV of their resulting deferred annuity (via full annuity factors and cumulative mortality).
- Aggregated into separate components like `aal_term_db_legacy_est` (vested terms from current actives) and `aal_term_db_new_est` (vested terms from future hires).
- Cashflows are built from cohort-level data; rates enter only via discounting and annuity factors.
- **No estimation needed.**

So the in-flow (actives → term-vested) is built from cohort data via the active model, and the out-flow (term-vested → retirees, deaths) is handled because the Component-1 synthetic stream naturally declines over the amortization horizon. The cashflow-shape concern below applies *only* to Component 1. Component 1's share of total term-vested liability shrinks year by year as the original cohort amortizes down and Component 2 grows.

### A note on naming: `_current_` vs `_legacy_` vs `_new_`

The R model uses three suffixes that answer different questions:

- **`_current_`** — members ALREADY in this destination status as of year 1. So `aal_retire_current_est` is liability for already-retired members; `aal_term_current_est` is liability for already-term-vested members (Component 1).
- **`_legacy_`** — liability that originates from the year-1 ACTIVE cohort and flows into destination statuses over the projection. `aal_term_db_legacy_est` is term-vested liability from those who terminate vested during the projection.
- **`_new_`** — same idea as `_legacy_` but for actives HIRED during the projection.

Both `_current_` and `_legacy_` reference year-1 things, but they're not synonyms: `_current_` says **where members are now**, `_legacy_` says **where members started**. This primer follows the R convention. The names are inherited from R; renaming them in Python is tracked in #63 and gated on the R-matching phase ending.

## How accurate is the synthetic-cashflow estimate

The Component-1 estimate is exactly right at 6.7% by construction. Under a rate scenario, the question becomes: how much does the PV of the *true* term-vested cashflow change vs. the PV of the *synthetic* cashflow?

PV-rate sensitivity is governed by **duration** — roughly, the dollar-weighted average year payments occur. Two streams with the same baseline-rate NPV but different shapes have different durations and therefore different rate sensitivities.

- The true Component-1 cashflow is **back-loaded**: each term-vested member starts collecting only when she hits retirement age (often 5-15+ years away) and then runs to death. Long deferral, then an annuity — high duration.
- The 50-year smooth amortization stream is more level — payments start in year 1 and grow gradually. Shorter duration.

So when the synthetic stream is rediscounted at 7.5%, its PV falls *less* than the true cashflow's PV would. R's Component-1 AAL response under a high-rate scenario is **in the right direction but smaller in magnitude than a true cohort-level revaluation would give**.

This is a cashflow-shape estimation issue, not a reading-of-the-scenario issue. The bias is bounded: Component 1 is a small share of total AAL (a few percent for FRS and TXTRS) and shrinks each year.

Two realistic future improvements (tracked in #64), both opt-in via plan config and neither requiring scenario-file changes:

1. **Shape-aware synthetic stream.** Replace smooth-50-year with a deferral-then-annuity shape parametrized per plan. Same input data, better duration, more accurate rate sensitivity.
2. **Duration-based scaling.** Skip the synthetic stream entirely. Declare a Macaulay duration `D` per plan and scale `PVFB_term_current` directly under a rate stress as `PVFB × (1 - D × Δr)`.

Cohort-level term-vested data (frozen accrued benefit, age, deferral period) would let us build the actual stream and skip estimation entirely. We don't have that data for FRS or TXTRS and likely won't get it.

## A second concern: the calibration plug

There is a second source of approximation under scenarios that is *not* about the synthetic stream's shape — it is about how we calibrate to the published valuation.

Our retiree calc (and our active calc) computes PVFB from cohort-level data using our mortality table, our COLA implementation, and our annuity-factor calculation. Those internals will not exactly match the published actuary's. So:

- Our model's retiree PVFB will not exactly equal the AV's published retiree PVFB.
- Our model's active AAL will not exactly equal the AV's published active AAL.

We do not bridge these gaps with per-component calibration factors. Instead, the global mismatch is absorbed into a single per-class plug. The calibration code (`src/pension_model/core/calibration.py:66`) literally does:

```python
pvfb_term_current = val_aal - model_aal
```

i.e., "whatever AAL is missing after our retiree, active, and Component-2 calcs, dump it into the term-vested input." `plans/frs/config/calibration.json` confirms this — the `admin` class has a *negative* `pvfb_term_current` (-2.1M), which a real PVFB cannot be. The values in this file are residuals, not the AV's published term-vested PVFB.

This calibration plug has two consequences for scenario behavior:

1. **At baseline**, total AAL matches the AV per class by construction. No problem.
2. **Under a discount-rate scenario**, the plug carries the synthetic-stream rate sensitivity (the smooth-50-year duration discussed above). But the residual it represents may include retiree-mortality mismatches, active-projection mismatches, etc. Each of those cohorts has its own correct duration. Routing all of them through the synthetic-stream duration contaminates the AAL's rate sensitivity in a way that is hard to reason about.

For FRS the scale is meaningful: ~\$10B of `pvfb_term_current` across classes, an unknown fraction of which represents real term-vested members vs residuals from other components. Under high_discount, all of it moves at synthetic-stream duration regardless.

A "proper" model would calibrate component-by-component (one factor per cohort) so each component carries its own correct rate sensitivity. This is tracked in #65 and naturally pairs with #64 — better Component-1 cashflow shape only matters if `pvfb_term_current` actually represents term-vested members. Both are gated on the R-matching phase ending.

## What our Python model does

Two rules:

1. **Match R first.** Per `meta-docs/repo_goals.md`, exact reproduction of R is a hard constraint on the matching branch. We do not change actuarial behavior to "improve" on R while we are still in matching mode; we file issues for improvements and tackle them later on their own branches.
2. **Keep the data anchor in code, not config.** The "use baseline `dr_current` to size the Component-1 synthetic stream" rule is an engineering invariant tied to what the input data means. It lives in `compute_current_term_vested_liability` (`src/pension_model/core/pipeline_current.py`), not as a config knob.

Concretely, the engine snapshots the baseline `dr_current` at config-load time (before any scenario override is merged in). When `compute_current_term_vested_liability` runs:

- It uses the **baseline `dr_current`** to size the synthetic payment stream against `PVFB_term_current`.
- It uses the **scenario `dr_current`** (whatever the loaded config now reports) to PV that stream.

In baseline runs the two are equal and nothing special happens. In a scenario run, the two differ by exactly the rate stress.

For every other component (actives, retirees, Component 2 of term-vested), only the scenario `dr_current` / `dr_new` is used. There is no special handling.

## How the scenario JSON expresses intent

Scenarios use the existing flat `economic` shape and override only the three real assumptions:

### Reading B: high discount, consistent assumption change (matches R high_discount)

```json
{
  "name": "high_discount",
  "description": "Reading B: 7.5% discount AND 7.5% investment return",
  "overrides": {
    "economic": { "dr_current": 0.075, "dr_new": 0.075, "model_return": 0.075 }
  }
}
```

### Reading A: pure GASB-style sensitivity

```json
{
  "name": "valuation_only_high",
  "description": "Reading A: liability rediscount only; assets unchanged",
  "overrides": {
    "economic": { "dr_current": 0.075, "dr_new": 0.075 }
  }
}
```

(Omitting `model_return` leaves it at the baseline value.)

### Investment-only stress

```json
{
  "name": "low_return",
  "description": "Pessimistic investment return; discount rate unchanged",
  "overrides": {
    "economic": { "model_return": 0.05, "return_scen": "model" }
  }
}
```

This is a what-if about asset performance only — the discount rate stays at baseline so liabilities don't move. (The `return_scen` switch tells the funding model to use the model-return column rather than the assumption column.)

No role-namespaced override blocks. No `valuation` / `cashflow_projection` / `asset_return` keys. The three real assumptions are what the actuarial model has, and the scenario file overrides them directly.

## Summary

- The model has three rate-like assumptions: `dr_current`, `dr_new`, `model_return`. A scenario overrides one or more.
- Reading A vs Reading B is a single decision: does `model_return` move with `dr_current`, or stay put? Reading A leaves it; Reading B moves it. Everything else follows.
- The R reference models do Reading B for high_discount.
- For active members and retirees, scenarios just rediscount cashflows built from cohort data. No estimation step.
- For current term-vested (Component 1), the input is a single rolled-up PVFB with no underlying cohort data. The engine estimates a cashflow by sizing a synthetic stream against the input using the baseline `dr_current`, then PVs that stream at the scenario `dr_current`. The baseline rate here is fixed by the meaning of the input data, not by a config choice. There is no third "cashflow discount rate" assumption.
- The Component-1 estimate is exact at the baseline rate by construction. Under a rate stress, its PV moves in the right direction but understates the true cohort-level revaluation because the synthetic stream's level shape has shorter duration than real back-loaded term-vested cashflows. Bias is bounded; Component 1 is a small share of total AAL.
- A separate concern: `pvfb_term_current` in our calibration files is not the published term-vested PVFB. It is a per-class plug that absorbs *all* model-vs-AV residuals (retiree, active, term-vested) into one number. At baseline this guarantees total AAL matches the AV; under a scenario, the plug carries synthetic-stream rate sensitivity for residuals that originate in other cohorts, which contaminates AAL rate sensitivity in ways that are hard to reason about.
- Future improvements: better Component-1 cashflow shape (#64) and component-by-component calibration (#65) — both opt-in, both gated on the R-matching phase ending. They naturally pair: better cashflow shape only matters once `pvfb_term_current` actually represents term-vested members.
