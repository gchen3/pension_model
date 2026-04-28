# Pension Model — Demo

## 1. Background & approach

A Python simulation model for **public-pension policy research** — projects AAL, UAL, assets, funded ratios, and employer contributions over long horizons, across plans and scenarios, with no plan-specific code.

**Summary of goals:** Reproduce two reference R models exactly (Florida FRS, Texas TRS), generalize so new plans are config + data only, then use it to analyze policy alternatives. ONLY AFTER MODEL IS SUFFICIENTLY GENERALIZED DO WE IMPLEMENT IMPROVEMENTS TO THE R MODEL. BEFORE THAT, OPEN GITHUB ISSUES IDENTIFYING POTENTIAL IMPROVEMENTS.

- Full goals, priorities, and design principles: [repo_goals.md](../meta-docs/repo_goals.md)

### How this learns from and builds on our R model

Stacked DataFrames across membership classes. All 7 FRS classes live in one DataFrame with class_name as a categorical column, so class-level operations are one vectorized call instead of a 7x loop (developer.md:95).

Inequality joins instead of if/else chains. Tier assignment, benefit multipliers, early-retirement reductions, and COLA rules are resolved by joining against lookup tables keyed by ranges — no per-row branching, no per-plan conditional code.

Build benefit tables once, vectorized. Every per-cohort actuarial quantity (salary, accrued benefit, annuity factor, PVFB, PVFS, normal cost) is computed up front across all entry ages × YOS × ages in a single vectorized pandas/NumPy pass, rather than looping cohort-by-cohort as the R model does.

------------------------------------------------------------------------

## 2. Quick demo — matching R

Run the following commands. Each run writes to `output/<plan>/` and updates the shared workbook [output/truth_tables.xlsx](../output/truth_tables.xlsx).

``` bash
# Florida FRS baseline — skip tests, write truth table
pension-model run frs --no-test --truth-table

# Texas TRS baseline — same
pension-model run txtrs --no-test --truth-table
```

Open `output/truth_tables.xlsx` and show:

- `frs_Py` / `txtrs_Py` — Python results (overwritten each run).

- `frs_R` / `txtrs_R` — R baseline (frozen reference).

- `frs_diff` / `txtrs_diff` — **the punchline sheet**: R, Python, and diff side by side, column by column. Diffs are at float noise (\~1e-15).

This workbook is the evidence that Python matches R. It’s regenerated on every run – if differences are non-zero, they are highlighted in Excel.

------------------------------------------------------------------------

## 3. Model structure at a glance

| Folder | What’s in it |
|------------------------------------|------------------------------------|
| [src/pension_model/](../src/pension_model/) | The Python package — CLI (command line interface), core computation modules, plan-config loader |
| [plans/](../plans/) | One subfolder per plan (`frs/`, `txtrs/`, …): Each has `config/`, `data/`, `baselines/` |
| [scenarios/](../scenarios/) | JSON overrides for policy experiments (low_return, no_cola, high_discount) |
| [scripts/](../scripts/) | One-off utilities: data extraction, baseline building, validation |
| [tests/](../tests/) | Pytest suite — check for R-baseline regression, check identities and similar calculations |
| [output/](../output/) | Results of simulation runs: `summary.csv`, `liability_stacked.csv`, `truth_tables.xlsx` (gitignored) |
| [docs/](../docs/) | This doc, architecture notes, design docs (see also [meta-docs/repo_goals.md](../meta-docs/repo_goals.md)) |
| [R_model/](../R_model/) | The reference R models (FRS and TXTRS) — copied per environment, not tracked |

**The core idea:** everything plan-specific lives in `plans/<plan>/`. The Python code in `src/pension_model/` is plan-agnostic as are the JSON files in and `scenarios/*.json` .

### Inside a plan — using FRS

- [plans/frs/config/plan_config.json](../plans/frs/config/plan_config.json) — classes (admin, regular, senior_mgmt, judges, eco, eso, …), benefit formulas, COLA, funding policy, economic assumptions, valuation targets.
- [plans/frs/config/calibration.json](../plans/frs/config/calibration.json) — per-class `nc_cal` and `pvfb_term_current` (see §5).
- `plans/frs/data/` — “stage-3” model-input CSVs: demographics, decrements, mortality, funding inputs.
- `plans/frs/baselines/` — R reference outputs for regression tests (whether anything that once worked has since been broken).

------------------------------------------------------------------------

## 4. How the model works — FRS example

What happens, in order, when you run `pension-model run frs --no-test`:

1.  **Load config.** Read `plans/frs/config/plan_config.json`, merge in `calibration.json`, and merge any `--scenario` overrides on top.
2.  **Build benefit tables.** For every membership class, build a large lookup table keyed by entry age × years of service × age. Contains salary, accrued benefit, annuity factor, PVFB, PVFS, normal cost — all the per-cohort actuarial quantities, computed once up front using vectorized pandas/NumPy.
3.  **Project the workforce.** For each class, simulate a 30-year horizon cohort by cohort: actives decrement each year (termination, retirement, mortality, disability); new entrants arrive according to the entrant profile.
4.  **Aggregate liabilities.** Sum benefit quantities across cohorts and states (active, terminated-vested, current retirees) year by year.
5.  **Funding model.** Apply contribution policy, asset smoothing (corridor for FRS, gain/loss deferral for TRS), and amortization to get contributions, AVA, MVA, and funded ratio each year.
6.  **Write outputs.** `summary.csv`, `liability_stacked.csv`, and — with `--truth-table` — the Excel workbook sheets.

### Call sequence — which function does each stage

| \# | Stage | Function | File : line |
|------------------|------------------|------------------|------------------|
| 1 | Load config | `load_plan_config(config_path, calibration_path=None, scenario_path=None) -> PlanConfig` | [plan_config.py:1470](../src/pension_model/plan_config.py#L1470) |
| 2 | Build benefit tables | `build_plan_benefit_tables(inputs_by_class, constants) -> dict` | [core/pipeline.py:72](../src/pension_model/core/pipeline.py#L72) |
| 3 | Project workforce | `project_workforce(initial_active, separation_rates, benefit_decisions, mortality_rates, entrant_profile, class_name, start_year, model_period, …) -> dict` | [core/workforce.py:19](../src/pension_model/core/workforce.py#L19) |
| 4 | Aggregate liabilities | `compute_active_liability`, `compute_term_liability`, `compute_retire_liability`, `compute_refund_liability` | [core/pipeline.py:260](../src/pension_model/core/pipeline.py#L260), [:375](../src/pension_model/core/pipeline.py#L375), [:458](../src/pension_model/core/pipeline.py#L458), [:420](../src/pension_model/core/pipeline.py#L420) |
| 5 | Funding model | `run_funding_model(liability_results, funding_inputs, constants) -> dict` | [core/funding_model.py:124](../src/pension_model/core/funding_model.py#L124) |
| 6 | Write outputs | `_write_outputs`, `_emit_truth_table` | [cli.py:205](../src/pension_model/cli.py#L205), [:221](../src/pension_model/cli.py#L221) |

The function that ties stages 2–4 together is [`run_plan_pipeline(constants, …)`](../src/pension_model/core/pipeline.py#L911) in `core/pipeline.py`. The top-level CLI driver is [`_run_plan`](../src/pension_model/cli.py#L313) (invoked by `cmd_run` at [cli.py:429](../src/pension_model/cli.py#L429), which is what `pension-model run frs --no-test` calls).

**Reading strategy for a new contributor:** start at `cli.py:_run_plan`, follow it into `run_plan_pipeline` in `core/pipeline.py`, then let each stage's function pull you into the next module. Every stage function has a docstring describing inputs and outputs.

------------------------------------------------------------------------

## 5. Calibration

The model is **calibrated** in the same way the Reaon models are, so that baseline results approximate the published actuarial valuation.

- `nc_cal` — multiplicative scaling on normal cost.
- `pvfb_term_current` — additive UAL adjustment for current terminated-vested members.

Computed by:

``` bash

pension-model calibrate frs # show potential calibration factors
# pension-model calibrate frs --write  # this will write the calibration factors to calibration.json
```

This runs the pipeline uncalibrated, compares aggregate AAL and NC against targets pulled from `valuation_inputs` in `plan_config.json`, and derives the two factors per class. With the –write option, it writes `plans/frs/config/calibration.json`. Subsequent `run` commands pick that file up automatically.

### 

## 6. Policy simulation

Scenarios are JSON files that override specific config sections. No code changes, no new plan.

Example — [scenarios/low_return.json](../scenarios/low_return.json):

``` json
{
  "name": "low_return",
  "description": "Pessimistic investment return: 5% (vs baseline 6.7% FRS / 7% TRS)",
  "overrides": {
    "economic": {
      "model_return": 0.05,
      "return_scen": "model"
    }
  }
}
```

Run the scenario:

``` bash
pension-model run frs --no-test --scenario scenarios/low_return.json --truth-table
```

Outputs are written to `output/frs/low_return/` rather than `output/frs/`, so baseline and scenario results never overwrite each other. **Calibration factors are not re-derived** — calibration is part of the baseline, not the scenario.

Scenarios are **plan-agnostic by design** — no plan name appears anywhere in a scenario file. The loader just merges the `overrides` into whatever plan config was passed on the command line, so the same `low_return.json` works for FRS, TRS, or any future plan.

Overrideable sections include `economic`, `benefit.cola`, `funding` (amortization, smoothing), and `ranges` (projection horizon). Adding a new scenario dimension typically means adding the parameter to config, not writing new code. Expanding this will be one of the next areas of work.

Open gap (tracked as [issue #44](https://github.com/donboyd5/pension_model/issues/44)) will validate overrides against the target plan and either warn or stop with a clear message if a plan does not have a parameter to be overridden.

Other scenarios currently in the repo: [no_cola.json](../scenarios/no_cola.json), [high_discount.json](../scenarios/high_discount.json).

------------------------------------------------------------------------

## 7. Where we are and what’s next — discussion

**Where we are:**

- Two reference plans match R within negligible floating point differences: FRS (7 classes, DROP) and Texas TRS (1 class).
- Zero plan-specific Python code — everything plan-specific is JSON + CSV.
- Scenario system working; `low_return` validated bit-identical to R.
- Improvements still needed:
  - Still room for more stacking of data frames - will make code cleaner, easier to read, and more intuitive
  - Rationalize the tests
  - Validate additional scenarios against FRS and Texas TRS
  - Strengthen and routinize the path from AV/ACFR –\> csv and json model inputs
  - Further generalizations

**Questions for discussion**:

1.  **Most valuable policy simulations?** DR sensitivities, COLA variants, contribution-policy alternatives, stress tests on asset returns? – need a list of 3 or 4 useful policies to examine – we'll run the R model(s) and run python and make sure we get same results
2.  **Next plan or two to add? Can we consider this satisfying the next deliverable?**
    1.  Maybe something not too complicated, to be sure we can generalize to these plans?
3.  **Most important plan features to add?** what's important? what plan has it?