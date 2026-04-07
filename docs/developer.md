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
- **Reproduce first, then extend.** The baseline for each plan matches the R model output (bit-identical for FRS, within ~5 ppm for TRS). Improvements are made one at a time with measured impact.
- **Calibrated.** Small adjustment factors align model output with actuarial valuation (AV) reports rather than trying to match every detail from first principles.
- **Fast.** Benefit tables are built in a single stacked pass across all membership classes. Workforce projection uses NumPy matrix operations. Only the stage-3-to-results solve time matters — data prep and tests can be slower.
- **Well tested.** 248 tests verify R baseline match, actuarial identities, and year-by-year reasonableness.

**Current scope.** Two reference plans are implemented: FRS (7 membership classes, DB/DC) and Texas TRS (1 class, DB/CB/DC). The model supports defined benefit, defined contribution, and cash balance benefit types.

**Non-goals.** This is not a replacement for an actuarial valuation. It does not model individual member records and does not optimize contribution policy.

---

## Architecture Overview

### Package Map

```
src/
  pension_model/              CLI, config loader, pipeline orchestration
    core/                     All computation: benefit tables, workforce,
                              calibration, funding projection
  pension_config/             Type definitions, plan-specific adapters
  pension_tools/              Stateless utility functions (actuarial math,
                              salary projection, mortality lookups)
plans/                        Per-plan config and data (not a Python package)
  frs/                        Florida Retirement System
  txtrs/                      Texas Teachers Retirement System
scenarios/                    Scenario override files (JSON)
tests/                        Test suite
docs/                         Documentation
```

`pension_model` imports from `pension_config` and `pension_tools`; those two packages do not import from each other or from `pension_model`. `plans/` is pure data — no Python code.

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
        -> ann_factor
          -> benefit
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
  compute_funding()  ───────────────────>  year-by-year funding projection
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

- **`discover_plans()`** (`plan_config.py:1399`) scans `plans/*/config/plan_config.json` and returns a dict mapping plan names to config paths. Plans are auto-discovered — no registry to maintain.
- **`load_plan_config()`** (`plan_config.py:1278`) reads `plan_config.json` into a frozen `PlanConfig` dataclass. It also loads `calibration.json` (per-class `nc_cal` and `pvfb_term_current`). If `--scenario` is provided, the scenario's overrides are deep-merged into the config before constructing `PlanConfig`.

`PlanConfig` is the single source of truth for the run. It replaces the old `ModelConstants` + `tier_logic.py` modules with table-driven lookups.

### 2. Data Loading

**`load_plan_inputs()`** (`core/data_loader.py:391`) calls `load_plan_data()` for each class in `constants.classes`.

Per-class files follow a naming convention: `{class}_salary.csv`, `{class}_headcount.csv`, `{class}_termination_rates.csv`, `{class}_retirement_rates.csv`. Shared files (mortality, salary growth, retiree distribution) have no class prefix. If a per-class file isn't found, the loader falls back to an unprefixed version.

Each class gets a dict containing salary/headcount DataFrames, decrement tables, a `CompactMortality` object (built from `base_rates.csv` + `improvement_scale.csv`), and annuity factor inputs.

### 3. Benefit Table Construction

**`build_plan_benefit_tables()`** (`core/pipeline.py:66`) orchestrates the five-table chain:

| Step | Builder | What It Produces |
|------|---------|-----------------|
| 1 | `build_salary_headcount_table()` | Entry age, entry year, projected salary, headcount for each (age, yos) cell |
| 2 | `build_salary_benefit_table()` | Salary, FAS, DB employee balance, tier assignment, retirement status for each cohort trajectory |
| 3 | `build_separation_rate_table()` | Combined termination + retirement rates by (entry_age, age, yos, tier) |
| 4 | `build_ann_factor_table()` | Annuity factors, mortality-discount matrices, distribution ages |
| 5 | `build_benefit_val_table()` | PVFB, PVFS, normal cost for each cohort — the inputs to liability calculation |

Steps 1-3 are built per class (class-specific inputs), then stacked. Steps 4-5 operate on the stacked result. All builders are in `core/benefit_tables.py`.

### 4. Workforce Projection and Liability

**`project_workforce()`** (`core/workforce.py:19`) runs a matrix-based year-by-year projection for each class. Starting from the initial active population, it applies separation rates to move members from active to terminated, then to retired or refunded. New entrants are added each year based on the entrant profile.

The function returns four DataFrames: `wf_active`, `wf_term`, `wf_retire`, `wf_refund` — each with (entry_age, age, year, count).

**`_project_and_aggregate_class()`** (`core/pipeline.py:780`) joins workforce output with benefit_val to compute liability components (active AAL, term AAL, retire AAL, refund AAL, normal cost, benefit payments). These are aggregated by year into a single liability DataFrame per class.

### 5. Funding Projection

**`load_funding_inputs()`** (`core/funding_model.py:26`) reads `init_funding.csv` (initial assets and liabilities), `return_scenarios.csv` (investment returns by year), and `amort_layers.csv` (existing UAL amortization schedules).

**`compute_funding()`** (`core/funding_model.py:125`, FRS) or **`compute_funding_trs()`** (`core/funding_model.py:660`, TRS) runs the year-by-year funding projection. For each year:

1. Get payroll, benefits, AAL from liability output
2. Apply calibration: `nc_rate = nc_rate_est * nc_cal`; `aal = aal_est + pvfb_term_current`
3. Project MVA: `(mva + contributions - benefits) * (1 + return)`
4. Smooth AVA using corridor method (80%-120% of MVA) with gain-loss recognition
5. Compute UAL = AAL - AVA, amortize by layer
6. Calculate employer contribution: NC + amortization + admin + DC

The funding model variant is selected by `config.funding_model` (`"frs"` or `"trs"`).

### 6. Output

**`build_plan_summary()`** normalizes FRS (dict of per-class DataFrames) and TRS (single DataFrame) funding output into a standardized format. The CLI prints a parameters block and a year-1/year-30 comparison table, then writes:

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
- **`acfr_data`** — per-class actuarial valuation targets: `val_norm_cost`, `val_aal`, `val_payroll`, `outflow`, `total_active_member`

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

Calibration adjusts the model so its baseline output matches the actuarial valuation report. It produces three factors:

1. **`cal_factor`** (global) — multiplied into every DB benefit calculation. Typically ~0.9-1.0.
2. **`nc_cal`** (per class) — fine-tunes each class's normal cost rate: `nc_cal = AV_NC / model_NC`. Values near 1.0 mean the model is accurate.
3. **`pvfb_term_current`** (per class) — closes the AAL gap: `pvfb_term = AV_AAL - model_AAL`.

**When to recalibrate:** after changing benefit formulas, salary scales, decrement tables, or AV targets. **When not to:** after changing policy/scenario assumptions (discount rate, COLA, investment return). Scenarios reuse baseline calibration.

```bash
pension-model calibrate frs              # compute and print diagnostics
pension-model calibrate frs --write      # write to plans/frs/config/calibration.json
pension-model run frs                    # verify output and tests pass
```

**Red flags.** `nc_cal` outside [0.8, 1.2] or `pvfb_term_current` > 20% of `val_aal` indicate model or data problems, not just calibration needs. Investigate before accepting.

For full details on calibration architecture, the three-factor design, and diagnostic interpretation, see [calibration.md](calibration.md).

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
| decrements/ | `{class}_termination_rates.csv` | Termination rates (see [termination_rate_design.md](termination_rate_design.md)) |
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
10. **`acfr_data`:** per-class AV targets (`val_norm_cost`, `val_aal` at minimum)

For single-class plans, use `"classes": ["all"]` and a single entry in `acfr_data`, `benefit_multipliers`, etc.

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

### Test Suite Organization

The test suite has 248 tests across 9 files in `tests/test_pension_model/`. They are organized into three layers:

**Layer 1: R Baseline Match (regression)**

| File | What It Tests |
|------|--------------|
| `test_funding_baseline.py` | Full 31-year funding output compared column-by-column against R baselines in `plans/frs/baselines/`. Parametrized across all 7 FRS classes. This is the gold-standard "bit-identical to R" test. |
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

13 tests are marked `skip` because they depend on Excel source files not committed to the repo. These verify the original data extraction from actuarial valuation spreadsheets and are only needed during initial plan setup.

---

## Design Deep Dives

Specialized design decisions are documented in separate files:

- [Early Retirement Reduction Design](early_retirement_reduction_design.md) — the three reduction patterns (formula-based, age-based table, YOS x age matrix), how they're stored in config vs CSV, and policy levers for scenario analysis.
- [Termination Rate Design](termination_rate_design.md) — structural patterns (YOS-only, select & ultimate, years-from-normal-retirement), the `lookup_type` CSV format, and why data isn't pre-expanded.
- [Calibration Architecture](calibration.md) — full details on the three calibration factors, diagnostic interpretation, and the calibration pipeline.
