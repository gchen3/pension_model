# Pension Math: Reference for Model Work

A curated actuarial-math reference for the engineer working on this model. Loaded into every session via `CLAUDE.md` so the math stays in the foreground of design decisions. Where deeper formula text is needed, defer to `actuarial_calculations/winklevoss_formulas.md` (the full Winklevoss reference, ~700 lines).

## How to use this doc

When proposing a change, ask:

1. **Closed form?** Is there an exact expression that replaces a year-by-year loop or per-cohort iteration?
2. **Recursion?** Is there a backward or forward recursive relationship that lets us update rather than recompute?
3. **Approximation?** Is the current behavior an approximation? If so — what *is* the approximation, why is it there, and is the change in scope to refine it?
4. **Identity preserved?** Will the change preserve the actuarial identities the model relies on (MVA balance, AAL roll-forward, NC×payroll)?
5. **Generalization axis?** Does the change move plan-specific behavior into config/data, or does it bake new plan-specific assumptions into Python?

If a change touches actuarial logic and you can't answer these, stop and think — or ask.

## Core actuarial quantities

| Symbol | Name | Meaning |
|---|---|---|
| `B_x` | Accrued benefit at age `x` | Annual benefit earned to date by a member at age `x` |
| `FAS` | Final average salary | Average of last `N` years of salary; the multiplier base |
| `s_x` | Salary at age `x` | Projected salary given start-salary and growth |
| `a_x` | Life annuity factor at age `x` | PV of $1/year for life starting at age `x` |
| `AAL` | Actuarial accrued liability | PV of benefits earned **to date** (method-dependent) |
| `PVFB` | Present value of future benefits | PV of **all** future benefits, including future accruals |
| `PVFNC` | Present value of future normal costs | PV of NC over remaining service |
| `PVFS` | Present value of future salary | PV of remaining salary stream — denominator for NC rate |
| `NC` | Normal cost | One year's accrual cost (rate × payroll, or dollar form) |
| `UAL` | Unfunded actuarial liability | `AAL − AVA` (or `AAL − MVA`) |
| `dr` | Discount rate | Single number under US public-pension convention; conceptually three roles (see below) |

## Fundamental relationships

For a single active member under entry-age normal:

- `PVFB = AAL + PVFNC`  (the *defining* identity of EAN)
- `NC_rate = PVFB / PVFS` evaluated at entry age
- `AAL_x = PVFB_x − PVFNC_x`
- For a typical DB plan: `B_t = yos · multiplier · FAS_t`
- For an in-pay annuitant: `AAL = B · a_x` (modulo COLA, joint-life adjustments, etc.)

Projected unit credit (PUC) differs from EAN in how `AAL` and `NC` are split, but `PVFB = AAL + PVFNC` still holds.

## Cohort modeling and decrements

The model groups members by `(entry_age, yos, age)`. A member at that triple faces yearly decrements:

- `q_w(t)` — termination/withdrawal
- `q_d(t)` — disability
- `q_r(t)` — retirement
- `q_m(t)` — mortality

### Multi-decrement vs combined separation

Winklevoss treats decrements as competing risks. The probability of surviving year-by-year in active status is, per year, the joint survival across all four — typically modeled as `(1 − q_w)(1 − q_d)(1 − q_r)(1 − q_m)` with adjustments, or equivalently with the `q_i'` adjusted-decrement convention.

The current model uses combined separation rates in some paths (issue #25). Replacing with explicit multi-decrement is a generalization step that makes status-by-status modeling natural.

## Discount rate: three conceptual roles

US public-pension convention uses one number, but it plays three distinct roles:

1. **Valuation rate** — discounts projected benefit cashflows to today's PV. Drives `AAL`, `PVFB`, `NC_rate`.
2. **Cashflow estimation rate** — sizes synthetic payment streams when only the PV is published (e.g., current term-vested members where the input is `pvfb_term_current`, a published-rate quantity). Anchored to the rate the input was *published at*, not the scenario rate. See `docs/design/discount_rate_scenarios.md` for why.
3. **Asset return assumption** — projects assets forward. Equal to the valuation rate by convention; conceptually independent.

A "high-discount-rate scenario" can move (1) and (3) together (the US convention) or independently. The model currently overrides only `dr_current`, `dr_new`, and `model_return`; (2) is anchored at `baseline_dr_current`, snapshotted at config-load.

## Identities the model relies on

The Python model's correctness rests on these holding to floating-point precision:

- **MVA balance identity:** `mva_eoy = mva_boy + er_cont + ee_cont − benefits − refunds − admin + invest_income`
- **AAL roll-forward (single discount rate, no gain/loss):** `aal_eoy ≈ (aal_boy + nc_boy) · (1 + dr) − benefits_during_year`
- **NC dollar identity:** `nc_dollar = nc_rate · payroll`
- **Funded ratio:** `fr_mva = mva / aal`, `fr_ava = ava / aal`

Every roll-forward step that violates one of these identities is a bug. The truth-table tests check identities along with R-baseline matching; new code must not break them.

## Closed-form shortcuts to keep in mind

The big wins for a simulation model:

### Commutation functions

`D_x = v^x · l_x`, `N_x = Σ_{t≥x} D_t`, `M_x = Σ_{t≥x} v^{t+1} · d_t`.

With these:
- Annuity factor: `a_x = N_x / D_x`
- AAL for a single retiree: `B_x · N_x / D_x`
- Many other PVs collapse into ratios of pre-built sums.

In code: build `D_x`, `N_x`, `M_x` once, vectorized over ages, and every per-cohort annuity-factor calc becomes an array lookup. No per-cohort loop.

### Recursive PV relationships

`a_x = 1 + v · p_x · a_{x+1}` — annuity factor at age `x` in terms of next year's. Same pattern applies to many actuarial PVs. Collapses term-by-term sums into a single backward sweep over ages.

### Salary cumprod

Salary at age `x` given start at entry age `ea`: `s_x = s_ea · Π_{i=ea}^{x−1} (1 + g_i)`. Always express as `cumprod` over ages, never as a loop.

### Vectorized accrued benefit

`B_(ea, yos, age) = yos · multiplier(age, tier) · FAS(ea, yos, age)` is a 3-axis tensor where every axis is a known grid. Build it once across `(ea × yos × age)` rather than per-cohort.

## Approximations currently in the model

Each of these is a known approximation with a tracked issue. Don't blindly "fix" — but keep them in mind as the model generalizes.

| Approximation | Where | Issue | Notes |
|---|---|---|---|
| Bell-curve termination cashflow shape | Synthetic stream for current term-vested PVFB sizing | #64 | Current shape preserves R; refinement is post-R-match |
| 50-year amortization placeholder | Sizing the synthetic term-vested stream | #66 | Move construction to input-loading stage |
| Single-scalar calibration plug | One residual per class to match published AAL | #65, #46, #48 | Replace with component-by-component calibration; or with explicit current-term-vested liability model |
| Combined separation rates | Some decrement paths | #25 | Winklevoss multi-decrement is the generalization |
| DROP as adjusted active cohort | FRS DROP handling | (covered in `repo_goals.md`) | Will need full sub-cohort treatment for richer DROP designs |
| Hardcoded retiree mortality (5% flat) | R model behavior preserved | #1 | Phase-post-r — change R behavior |
| Hardcoded retiree COLA (3% flat) | R model behavior preserved | #2 | Phase-post-r |

## Generalization axes — what "general" means

A truly general public-pension model handles, on the same engine:

- **Member statuses**: active, deferred-vested, retiree, beneficiary, DROP, disability, refund-pending. Each with its own decrements and cashflow logic.
- **Multiple tiers and grandfathering**: different formulas, multipliers, COLA rules, ER reductions per tier; rules selected by entry-date or other criteria.
- **Plan types**: DB, DC, CB, hybrid (DB+DC, DB+CB).
- **Optional features**: DROP variants, conditional/variable COLAs, variable interest credits (CB), employee DB-vs-DC choice, purchase-of-service credit.
- **Decrements**: gender-specific mortality with improvement scales (MP-2021 etc.), table-based or formula-based termination, age- or YOS-driven retirement, select-and-ultimate patterns.

Each of these wants to live in **config + data**, not in Python branches. When you see plan-specific code, ask: could this be a config field plus a generic engine path?

## Performance — where it actually matters

Per `meta-docs/repo_goals.md`, performance only matters in the **core projection** (year-by-year solve from stage-3 inputs through final results). Data prep, loading, and tests can be slow.

Inside the core projection:

- Vectorize across `(entry_age × yos × age)` — never loop cohort-by-cohort
- Use commutation functions / closed forms wherever they collapse a per-year sum into a ratio of pre-built arrays
- Update arrays in place; don't keep large working data around after the step that needs it
- Use inequality joins (or numpy `searchsorted`) for tier/range lookups; not Python `if`/`elif` chains
- Watch out for memory blowups from `(years × cohorts × statuses × plans)` outer products — collapse axes as early as possible

## Pointers

- **Full formula reference (deep dive):** [`actuarial_calculations/winklevoss_formulas.md`](../actuarial_calculations/winklevoss_formulas.md) — Winklevoss "Pension Mathematics" 2nd ed., key formulas extracted by chapter
- **Discount rate primer:** [`docs/design/discount_rate_scenarios.md`](../docs/design/discount_rate_scenarios.md)
- **Termination rates:** [`docs/design/termination_rate_design.md`](../docs/design/termination_rate_design.md)
- **Early retirement reduction:** [`docs/design/early_retirement_reduction_design.md`](../docs/design/early_retirement_reduction_design.md)
- **Project goals and procedures:** [`repo_goals.md`](repo_goals.md)
- **Architecture map:** [`docs/architecture_map.md`](../docs/architecture_map.md)
