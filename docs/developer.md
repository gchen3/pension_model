# Developer Guide

## Table of Contents

- [Goals](#goals)
- [Architecture Overview](#architecture-overview)
- [How a Model Run Works](#how-a-model-run-works)
- [Plan Data Structure](#plan-data-structure)
- [Calibration](#calibration)
- [How to Add a New Plan](#how-to-add-a-new-plan)
- [Scenarios](#scenarios)
- [Testing](#testing)
- [Design Deep Dives](#design-deep-dives)

---

## Goals

This project is a Python pension simulation model for **policy research**. It projects pension costs, funded status, and employer contributions under baseline and alternative assumptions over a 30-year horizon.

**Origin.** The model began as a port of the Reason Foundation's R model of the Florida Retirement System (FRS). It has since been generalized to support multiple plans with no plan-specific Python code — all plan differences are expressed through JSON configuration and CSV data files.

**Design principles:**

- **Data-driven.** Plan rules (tiers, eligibility, benefit multipliers, early retirement reductions) live in `plan_config.json`, not in code branches. Adding a plan means adding data, not writing new Python.
- **Reproduce first, then extend.** Exact reproduction of current R-backed baselines remains a hard constraint. Improvements are made one at a time with measured impact.
- **Calibrated.** Small adjustment factors align model output with actuarial valuation (AV) reports rather than trying to match every detail from first principles.
- **Fast.** Benefit tables are built in a single stacked pass across all membership classes. Workforce projection uses NumPy matrix operations. Only the stage-3-to-results solve time matters — data prep and tests can be slower.
- **Well tested.** The test suite verifies R baseline match, actuarial identities, and year-by-year reasonableness.

**Current scope.** Two reference plans are implemented: FRS (7 membership classes, DB/DC) and Texas TRS (1 class, DB/CB/DC). The model supports defined benefit, defined contribution, and cash balance benefit types.

**Non-goals.** This is not a replacement for an actuarial valuation. It does not model individual member records and does not optimize contribution policy.

---

## Architecture Overview

### Package Map

```
src/
  pension_model/
    cli.py                    CLI entry point and output writing
    plan_config.py            Stable public config API / compatibility surface
    config_*.py               Config schema, loading, validation, helpers, resolvers
    truth_table.py            R-vs-Python comparison helpers
    core/
      data_loader.py          Canonical input loading and normalization
      pipeline.py             Liability orchestration
      benefit_tables.py       Benefit-table builders
      workforce.py            Workforce projection
      pipeline_current.py     Current retiree / current term-vested liability pieces
      pipeline_projected.py   Projected active / term / retire / refund liability pieces
      funding_model.py        Public funding entry point
      _funding_*.py           Funding implementation split by concern
      calibration.py          Calibration computation and diagnostics
plans/                        Per-plan config and data (not a Python package)
  frs/                        Florida Retirement System
  txtrs/                      Texas Teachers Retirement System
R_model/                      Local legacy reference R models used for comparison
  R_model_frs/                FRS reference model workspace
  R_model_txtrs/              TXTRS reference model workspace
scenarios/                    Scenario override files (JSON)
tests/                        Test suite
docs/                         Documentation
```

`plans/` is pure plan data — no Python code. The repo boundary is intentionally
centered on canonical runtime inputs under `plans/{plan}/`; extracting those
inputs from source PDFs or workbooks is upstream prep work, not part of the
runtime architecture.

The repository also currently includes local copies of the legacy reference R
models under `R_model/R_model_frs/` and `R_model/R_model_txtrs/`. Those
directories are developer reference material for tracing legacy behavior and
checking R-side actuarial logic when needed; they are not part of the Python
runtime boundary.

### Pipeline Data Flow

```
plan_config.json + calibration.json
        |
        v
  load_plan_config()  ──────────────────>  PlanConfig dataclass
        |
        v
  load_plan_inputs()  ──────────────────>  per-class CSV data dicts
        |
        v
  build_plan_benefit_tables()
    salary_headcount
      -> salary_benefit
      -> separation_rate
      -> ann_factor
      -> benefit
      -> final_benefit
      -> benefit_val
        |
        v
  For each class:
    project_workforce()  ───────────────>  active / term / retire / refund
      -> compute liability components   ->  yearly AAL, NC, payroll
        |
        v
  load_funding_inputs()  ───────────────>  init_funding, return_scenarios
        |
        v
  run_funding_model()  ─────────────────>  year-by-year funding projection
        |
        v
  build_plan_summary()  ────────────────>  summary.csv, liability_stacked.csv
```

### Key Design Decisions

- **Stacked DataFrames.** Benefit tables are built for all classes in one pass, with `class_name` as a categorical column. This avoids 7x loops and enables vectorized operations across classes.
- **Config-driven tiers.** Tier assignment, benefit multipliers, and early retirement reductions are resolved from JSON lookup tables at runtime — no if/else chains for plan-specific rules.
- **Separate calibration.** Calibration factors are computed once at baseline and stored in `calibration.json`. Scenario runs reuse them without recalibrating.

---

## How a Model Run Works

This section traces `pension-model run frs --no-test` through the code.

### 1. Plan Discovery and Config Loading

The CLI entry point is `main()` in `src/pension_model/cli.py`.

- **`discover_plans()`** scans `plans/*/config/plan_config.json` and returns a dict mapping plan names to config paths. Plans are auto-discovered — no registry to maintain.
- **`load_plan_config()`** (`config_loading.py`) reads `plan_config.json` into a frozen `PlanConfig` dataclass. It also loads `calibration.json` (per-class `nc_cal` and `pvfb_term_current`). If `--scenario` is provided, the scenario's overrides are deep-merged into the config before constructing `PlanConfig`.

`PlanConfig` is the single source of truth for the run. It replaces the old `ModelConstants` + `tier_logic.py` modules with table-driven lookups.

### 2. Data Loading

**`load_plan_inputs()`** (`core/data_loader.py`) calls `load_plan_data()` for each class in `constants.classes`.

Per-class files follow a naming convention: `{class}_salary.csv`, `{class}_headcount.csv`, `{class}_termination_rates.csv`, `{class}_retirement_rates.csv`. Shared files (mortality, salary growth, retiree distribution) have no class prefix. If a per-class file isn't found, the loader falls back to an unprefixed version.

Each class gets a dict containing salary/headcount DataFrames, decrement tables, a `CompactMortality` object (built from `base_rates.csv` + `improvement_scale.csv`), and annuity factor inputs.

### 3. Benefit Table Construction

**`build_plan_benefit_tables()`** (`core/pipeline.py`) orchestrates the stacked benefit-table chain:

| Step | Builder | What It Produces |
|------|---------|-----------------|
| 1 | `build_salary_headcount_table()` | Entry age, entry year, projected salary, headcount for each (age, yos) cell |
| 2 | `build_salary_benefit_table()` | Salary, FAS, DB employee balance, tier assignment, retirement status for each cohort trajectory |
| 3 | `build_separation_rate_table()` | Combined termination + retirement rates by (entry_age, age, yos, tier) |
| 4 | `build_ann_factor_table()` | Annuity factors, mortality-discount matrices, distribution ages |
| 5 | `build_benefit_table()` + `build_final_benefit_table()` | Benefit streams and retirement-selection adjustments |
| 6 | `build_benefit_val_table()` | PVFB, PVFS, normal cost for each cohort — the inputs to liability calculation |

Steps 1-3 are built per class (class-specific inputs), then stacked. Steps 4-6 operate on the stacked result. All builders are in `core/benefit_tables.py`.

### 4. Workforce Projection and Liability

**`project_workforce()`** (`core/workforce.py`) runs a matrix-based year-by-year projection for each class. Starting from the initial active population, it applies separation rates to move members from active to terminated, then to retired or refunded. New entrants are added each year based on the entrant profile.

The function returns four DataFrames: `wf_active`, `wf_term`, `wf_retire`, `wf_refund` — each with (entry_age, age, year, count).

`run_plan_pipeline()` in `core/pipeline.py` combines workforce output with the stacked benefit-value tables and the current-liability helpers from `pipeline_current.py` / `pipeline_projected.py` to compute liability components (active AAL, term AAL, retire AAL, refund AAL, normal cost, benefit payments). These are aggregated by year into a single liability DataFrame per class.

### 5. Funding Projection

**`load_funding_inputs()`** (`core/funding_model.py`) reads `init_funding.csv` (initial assets and liabilities), `return_scenarios.csv` (investment returns by year), and `amort_layers.csv` (existing UAL amortization schedules).

**`run_funding_model()`** (`core/funding_model.py`) is the public entry point. It is a thin wrapper over the unified `_compute_funding()` driver in `core/_funding_core.py`. Setup/context resolution lives in `_funding_setup.py`, year-loop phases live in `_funding_phases.py`, strategy objects live in `_funding_strategies.py`, and low-level helpers live in `_funding_helpers.py`. For each year the funding model:

1. Get payroll, benefits, AAL from liability output
2. Apply calibration: `nc_rate = nc_rate_est * nc_cal`; `aal = aal_est + pvfb_term_current`
3. Project MVA: `(mva + contributions - benefits) * (1 + return)`
4. Smooth AVA via the configured smoothing strategy
5. Compute UAL = AAL - AVA, amortize by layer
6. Calculate employer contribution: NC + amortization + admin + DC

`run_funding_model` always returns a dict shaped `{class_name: DataFrame, plan_name: aggregate_DataFrame, ...}`. For single-class plans the aggregate frame is a distinct copy of the class frame (no DataFrame aliasing). For multi-class plans the aggregate is built by accumulating each class's results year by year, and plans with DROP may also carry an explicit `"drop"` frame.

### 6. Output

**`build_plan_summary()`** consumes the uniform `run_funding_model` dict shape directly. The CLI prints a parameters block and a year-1/year-30 comparison table, then writes:

- `output/{plan}/summary.csv` — year-by-year funding summary
- `output/{plan}/liability_stacked.csv` — detailed liability components by class and year

If `--truth-table` is passed, it also writes an R-vs-Python comparison table.

---

## Plan Data Structure

### Directory Layout

```
plans/{plan}/
  config/
    plan_config.json        All plan parameters (see sections below)
    calibration.json        Per-class calibration factors (nc_cal, pvfb_term_current)
  data/
    demographics/
      {class}_salary.csv         Salary by age and YOS (wide or long format)
      {class}_headcount.csv      Headcount by age and YOS
      salary_growth.csv          Salary growth rates (shared, or per-class with prefix)
      entrant_profile.csv        New hire age/salary distribution (optional)
      retiree_distribution.csv   Current retiree age/benefit distribution
    decrements/
      {class}_termination_rates.csv   Termination rates by lookup_type (yos or years_from_nr)
      {class}_retirement_rates.csv    Retirement rates by age, tier, and eligibility type
      reduction_*.csv                 Early retirement reduction tables (optional)
    mortality/
      base_rates.csv             Base mortality rates by age, gender, and status
      improvement_scale.csv      Mortality improvement factors by age, gender, and year
    funding/
      init_funding.csv           Initial assets, liabilities, contribution rates
      return_scenarios.csv       Investment return paths by year and scenario
      amort_layers.csv           Existing UAL amortization layers (optional)
  baselines/
    *.csv                        Reference outputs for validation tests (optional)
```

**Naming convention.** Files prefixed with `{class}_` are loaded per class; unprefixed files are shared across all classes. For single-class plans like TRS (class name `"all"`), use `all_salary.csv` etc., or unprefixed files as a fallback.

### plan_config.json Sections

The FRS config (`plans/frs/config/plan_config.json`) is the canonical reference. Key sections:

- **`economic`** — discount rates (`dr_current`, `dr_new`), payroll growth, inflation, model return, `return_scen` (which return column funding uses)
- **`benefit`** — employee contribution rates, `cal_factor` (global benefit calibration, typically ~0.9-1.0), FAS years, benefit types (`["db", "dc"]` or `["db", "cb", "dc"]`), COLA parameters
- **`funding`** — funding model (`"frs"` or `"trs"`), amortization method/period, asset smoothing parameters (corridor or gain-loss method)
- **`ranges`** — min/max age, start year, `new_year` (plan design cutoff for legacy vs new hires), model period (typically 30)
- **`classes`** — list of membership class names (e.g., `["regular", "special", "admin", ...]`)
- **`class_groups`** — grouping of classes for shared tier eligibility rules
- **`tiers`** — array of tier definitions, each with `entry_year_min`/`entry_year_max`, eligibility rules (age/YOS conditions for normal and early retirement), and early retirement reduction parameters
- **`benefit_multipliers`** — per-class, per-tier benefit formulas (flat rate or graded by YOS/age)
- **`plan_design`** — DB/DC allocation ratios by hire cohort (before/after cutoff year)
- **`valuation_inputs`** — per-class actuarial valuation targets: `val_norm_cost`, `val_aal`, `val_payroll`, `outflow`, `total_active_member`

### calibration.json

Generated by `pension-model calibrate {plan} --write`. Structure:

```json
{
  "cal_factor": 0.9,
  "classes": {
    "regular": { "nc_cal": 0.985, "pvfb_term_current": 6591924964 },
    "special": { "nc_cal": 0.985, "pvfb_term_current": 3237800000 }
  }
}
```

---

## Calibration

Calibration adjusts the model so its baseline output matches the actuarial valuation (AV) report. It accounts for structural gaps between what the model computes from first principles and what the actuary reports. Ideally calibration factors are small — large factors indicate model or data problems worth investigating.

### Architecture

Calibration is computed **once** against the baseline AV and stored in `plans/{plan}/config/calibration.json`. Policy analysis runs (different discount rate, mortality table, etc.) reuse the same calibration factors — they do not recalibrate. The calibration captures structural model gaps, not assumption sensitivity.

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  AV targets      │     │  Uncalibrated     │     │  calibration.json   │
│  (valuation_     │────>│  pipeline run     │────>│  (cal_factor,       │
│   inputs in      │     │  (nc_cal=1.0,     │     │   nc_cal per class, │
│   plan_config)   │     │   pvfb_term=0)    │     │   pvfb_term_current │
└─────────────────┘     └──────────────────┘     │   per class)        │
                                                   └────────┬────────────┘
                                                            │
                                                            v
                                                   ┌─────────────────────┐
                                                   │  Policy/scenario    │
                                                   │  runs load fixed    │
                                                   │  calibration from   │
                                                   │  JSON               │
                                                   └─────────────────────┘
```

### The Three Calibration Factors

**1. `cal_factor` (global, typically ~0.9-1.0)**

Multiplied into every DB benefit calculation in `core/benefit_tables.py` and `core/cohort_calculator.py`. Formula: `db_benefit = yos * ben_mult * fas * reduce_factor * cal_factor`. This is a first-pass calibration that reduces all computed benefits by a uniform amount.

**2. `nc_cal` (per class)**

Fine-tunes each class's normal cost rate in the funding model: `nc_cal = AV_NC / model_NC`. Applied during funding-frame setup in `core/_funding_setup.py` via helpers in `core/_funding_helpers.py`. Values near 1.0 mean the model is accurate for that class; values far from 1.0 indicate the model is structurally off.

| Class | nc_cal | Interpretation |
|-------|--------|----------------|
| regular | 0.985 | 1.5% too high — excellent |
| special | 0.985 | 1.5% too high — excellent |
| senior_management | 0.961 | 4% too high — good |
| eso | 0.940 | 6% too high — acceptable |
| judges | 0.917 | 8% too high — investigate |
| eco | 0.828 | 17% too high — investigate |
| admin | 1.396 | 40% too low — investigate |

*(FRS values shown. See GH #12-15 for investigation of admin and eco outliers.)*

**3. `pvfb_term_current` (per class)**

Closes the AAL gap: `pvfb_term_current = AV_AAL - model_AAL`. This liability component is amortized as a growing payment stream over 50 years. Applied in `core/pipeline_current.py`.

### When to Recalibrate

- **Yes:** after changing benefit formulas, salary scales, decrement tables, or AV targets.
- **No:** after changing policy/scenario assumptions (discount rate, COLA, investment return). Scenarios reuse baseline calibration.

### Running Calibration

```bash
pension-model calibrate frs              # compute and print diagnostics (no write)
make calibrate plan=frs                  # write calibration.json AND rebuild that
                                         # plan's term-vested cashflow CSV in one
                                         # step (preferred — see note below)
pension-model run frs                    # verify output and tests pass
```

**Why prefer `make calibrate` over `pension-model calibrate --write`:** the
runtime reads the per-class term-vested benefit cashflow stream from
`plans/{plan}/data/funding/current_term_vested_cashflow.csv`, which is
generated from `pvfb_term_current` in `calibration.json`. When calibration
writes new `pvfb_term_current` values, the CSV must be regenerated to match.
The Make target does both. Doing them separately is fine but easy to forget;
the runtime's input-load identity check (NPV at baseline rate ≈
`pvfb_term_current`) will trip if the CSV is stale and point at the build
script to fix.

Calibration output includes:
- **Normal cost calibration table**: model NC vs AV NC, nc_cal factor, flags for outliers
- **AAL calibration table**: model AAL vs AV AAL, pvfb_term_current, gap percentage
- **Out-of-sample checks**: quantities NOT calibrated (e.g., payroll) that serve as model quality indicators (shown only if `val_payroll` is provided in `valuation_inputs`)
- **Comparison with existing calibration.json**: diff against stored values to detect drift

### Diagnostic Red Flags

- `nc_cal` outside [0.8, 1.2] — model is structurally off for that class
- `pvfb_term_current` > 20% of `val_aal` — large unexplained liability gap
- Payroll ratio far from 1.0 — workforce/salary data issues

These suggest model or data problems, not just calibration needs. Investigate before accepting.

### Key Files

```
plans/{plan}/config/calibration.json   # Computed calibration factors (loaded at runtime)
src/pension_model/core/calibration.py  # Calibration computation and diagnostics
src/pension_model/plan_config.py       # Stable config API surface
```

Calibration targets come from the `valuation_inputs` section of `plan_config.json`: `val_norm_cost` (per-class NC rate) and `val_aal` (per-class total AAL). Optional `val_payroll` enables out-of-sample payroll checks.

---

## How to Add a New Plan

### Step 1: Create the Directory Structure

```bash
mkdir -p plans/{plan}/config
mkdir -p plans/{plan}/data/{demographics,decrements,mortality,funding}
mkdir -p plans/{plan}/baselines
```

Once `plans/{plan}/config/plan_config.json` exists, the plan is auto-discovered by `pension-model list`.

### Step 2: Prepare Data Files

You need at minimum these CSV files (replace `{class}` with your class name, e.g., `"all"` for single-class plans):

| Directory | File | Description |
|-----------|------|-------------|
| demographics/ | `{class}_salary.csv` | Salary by age and YOS |
| demographics/ | `{class}_headcount.csv` | Headcount by age and YOS |
| demographics/ | `salary_growth.csv` | Salary growth rates by YOS |
| demographics/ | `retiree_distribution.csv` | Current retiree age and benefit distribution |
| decrements/ | `{class}_termination_rates.csv` | Termination rates (see [termination_rate_design.md](design/termination_rate_design.md)) |
| decrements/ | `{class}_retirement_rates.csv` | Retirement rates by age and tier |
| mortality/ | `base_rates.csv` | Base mortality rates by age, gender, status |
| mortality/ | `improvement_scale.csv` | Mortality improvement rates by age, gender, year |
| funding/ | `init_funding.csv` | Initial assets, liabilities, contribution rates |
| funding/ | `return_scenarios.csv` | Investment return scenarios by year |

Use the FRS data files (`plans/frs/data/`) as format templates. Salary and headcount can be wide format (age rows, YOS columns) or long format (age, yos, value columns).

### Step 3: Write plan_config.json

Start by copying `plans/frs/config/plan_config.json` and customizing each section:

1. **Identity:** set `plan_name` and `plan_description`
2. **`economic`:** discount rates, payroll growth, inflation, expected return
3. **`benefit`:** employee contribution rate, FAS years, benefit types, COLA rules, `cal_factor` (start with 1.0)
4. **`funding`:** set `model` to `"frs"` (multi-class aggregation) or `"trs"` (single-class), amortization method and period, asset smoothing
5. **`ranges`:** start year, model period, `new_year` (plan design cutoff)
6. **`classes`:** list of class names matching your data file prefixes
7. **`tiers`:** define tiers with entry year ranges and eligibility rules
8. **`benefit_multipliers`:** per-class, per-tier benefit formulas
9. **`plan_design`:** DB/DC allocation ratios
10. **`valuation_inputs`:** per-class AV targets (`val_norm_cost`, `val_aal` at minimum)

For single-class plans, use `"classes": ["all"]` and a single entry in `valuation_inputs`, `benefit_multipliers`, etc.

### Step 4: Run Initial Calibration

```bash
pension-model calibrate {plan}
```

Review the diagnostics:
- `nc_cal` values near 1.0 are healthy
- `pvfb_term_current` small relative to AAL is healthy
- Large values indicate data or config problems — debug before proceeding

When satisfied:

```bash
pension-model calibrate {plan} --write
```

### Step 5: Validate

```bash
pension-model run {plan} --no-test
```

Compare `output/{plan}/summary.csv` against the plan's actuarial valuation report. Check that year-1 funded ratio, employer contribution rate, and AAL are in the right ballpark.

If you have R model outputs, place them in `plans/{plan}/baselines/` for automated comparison.

### Step 6: Add Tests

At minimum, add:

- A funding baseline test comparing pipeline output against your baselines (follow `tests/test_pension_model/test_funding_baseline.py` as a template)
- The existing consistency tests (`test_consistency.py`) work automatically for any plan since they check actuarial identities, not specific values

### Checklist

- [ ] `plans/{plan}/config/plan_config.json` exists and `pension-model list` shows the plan
- [ ] All required CSV files in `plans/{plan}/data/` with correct naming
- [ ] `pension-model calibrate {plan}` runs without error, diagnostics look reasonable
- [ ] `pension-model calibrate {plan} --write` writes `calibration.json`
- [ ] `pension-model run {plan} --no-test` produces output in `output/{plan}/`
- [ ] Year-1 funded ratio and contribution rate match AV report approximately
- [ ] Tests added and passing

---

## Scenarios

Scenarios override baseline assumptions while keeping calibration fixed. They allow policy analysis — "what if returns are lower?" or "what if we eliminate COLA?" — without recomputing calibration.

A scenario file is a JSON document with `name`, `description`, and `overrides`:

```json
{
  "name": "low_return",
  "description": "Pessimistic investment return: 5%",
  "overrides": {
    "economic": {
      "model_return": 0.05,
      "return_scen": "model"
    }
  }
}
```

The `overrides` dict is deep-merged into `plan_config.json` before constructing `PlanConfig`. Any section of the config can be overridden: `economic`, `benefit` (including `cola`), `funding`, `ranges`.

```bash
pension-model run frs --no-test --scenario scenarios/low_return.json
```

Output goes to `output/{plan}/` (same location as baseline). Three example scenarios ship with the project in `scenarios/`:

- `low_return.json` — 5% return (vs baseline ~6.7%)
- `high_discount.json` — higher discount rate
- `no_cola.json` — zero cost-of-living adjustments

---

## Testing

### Running Tests

```bash
pytest tests/ -v                         # all tests (verbose)
pytest tests/test_pension_model/ -v      # core model tests only
pytest tests/ -k "calibration" -v        # filter by name
pension-model run frs                    # runs model + tests automatically
pension-model run frs --test-only        # tests only, no model run
```

The repo also has a `Makefile` that bundles common workflows. `make help` lists
all targets. The most useful ones:

```bash
make r-match                             # FRS/TXTRS R-baseline scenario tests
make verify-cashflows                    # term-vested CSV identity check
make calibrate plan=frs                  # calibrate + rebuild that plan's term-vested CSV
make run plan=txtrs scenario=baseline    # run one cell, append rows to output/all_runs.csv
make run-all                             # run every (plan, scenario) cell
make compare a=txtrs/baseline b=txtrs-av/baseline
                                         # pairwise long-format diff between two cells
```

The compare target writes `output/compare_<a>__vs__<b>.csv` (long format) and
prints a per-metric summary. Works for any pair — across plans, across
scenarios, or both.

For the proposed long-run taxonomy, retention rules, and run-profile model,
see [testing_strategy.md](testing_strategy.md). The current suite still mixes
permanent invariants, reviewed-baseline regressions, and transitional
R-reproduction tests; that document is the intended guide for rationalizing
them over time.

### Test Suite Organization

The test suite in `tests/test_pension_model/` is organized into three layers:

**Layer 1: R Baseline Match (regression)**

| File | What It Tests |
|------|--------------|
| `test_funding_baseline.py` | Full 31-year funding output compared column-by-column against R baselines in `plans/frs/baselines/`. Parametrized across all 7 FRS classes. This is the gold-standard exact-regression test. |
| `test_stage3_loader.py` | Data loading correctness: mortality matches Excel source, adjustment ratios work, design ratios match R, year-1 and year-30 AAL match R baselines. |

**Layer 2: Actuarial Identity Checks (invariants)**

| File | What It Tests |
|------|--------------|
| `test_consistency.py` | Identities that must hold regardless of plan: AAL = sum of components, UAL = AAL - AVA, funded ratio = AVA/AAL, MVA roll-forward balance, ER contribution = NC + amortization + admin + DC, aggregate FRS = sum of classes, AAL roll-forward for legacy and new cohorts, payroll ratios sum to 1. |
| `test_calibration.py` | Computed `nc_cal` and `pvfb_term_current` match stored `calibration.json`. Flags if large classes (regular, special) drift from nc_cal near 1.0. |

**Layer 3: Reasonableness (sanity)**

| File | What It Tests |
|------|--------------|
| `test_rundown.py` | Year-by-year reasonableness: population stable or declining, AAL grows with payroll, funded ratio stays bounded, MVA stays positive, report output well-formed. |
| `test_benefit_tables.py` | Unit tests for each benefit table builder: correct shapes, value ranges, required columns present. |
| `test_data_integrity.py` | Shared decrement files are identical across classes that should share them. |
| `test_plan_config.py` | Config loading, required fields present, tier resolution, plan discovery works. |
| `test_vectorized_resolvers.py` | Vectorized tier/COLA/benefit-multiplier/reduction-factor resolution matches scalar versions. Parametrized across FRS and TRS. |

### Adding Tests for a New Plan

A new plan automatically gets Layer 2 coverage — the consistency tests check actuarial identities against whatever the model produces.

For Layer 1 (baseline match), provide reference output CSVs in `plans/{plan}/baselines/` and add parametrized test functions following `test_funding_baseline.py` as a template.

For Layer 3 (reasonableness), `test_rundown.py` can be extended with plan-specific bounds if the defaults don't fit.

### Skipped Tests

Some tests are marked `skip` because they depend on Excel source files not committed to the repo. These verify the original data extraction from actuarial valuation spreadsheets and are only needed during initial plan setup.

---

## Design Deep Dives

Specialized design decisions are documented in separate files:

- [Early Retirement Reduction Design](design/early_retirement_reduction_design.md) — the three reduction patterns (formula-based, age-based table, YOS x age matrix), how they're stored in config vs CSV, and policy levers for scenario analysis.
- [Termination Rate Design](design/termination_rate_design.md) — structural patterns (YOS-only, select & ultimate, years-from-normal-retirement), the `lookup_type` CSV format, and why data isn't pre-expanded.
