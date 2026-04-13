# Pension Model — Demo

Narration support for a ~30-minute screen-share walkthrough. Audience: policy researchers / analysts.

---

## 1\. Background & approach

A Python simulation model for **public-pension policy research** — projects AAL, UAL, assets, funded ratios, and employer contributions over long horizons, across plans and scenarios, with no plan-specific code.

**Summary of goals:** Reproduce two reference R models exactly (Florida FRS, Texas TRS), generalize so new plans are config + data only, then use it to analyze policy alternatives. ONLY AFTER MODEL IS SUFFICIENTLY GENERALIZED DO WE IMPLEMENT IMPROVEMENTS TO THE R MODEL. BEFORE THAT, OPEN GITHUB ISSUES IDENTIFYING POTENTIAL IMPROVEMENTS.

-   Full goals, priorities, and design principles: [model\_goals.md](model_goals.md)

---

## 2\. Quick demo — matching R

Run the following commands. Each run writes to `output/<plan>/` and updates the shared workbook [output/truth\_tables.xlsx](../output/truth_tables.xlsx).

bash

Copy

```bash
# Florida FRS baseline — skip tests, write truth tablepension-model run frs --no-test --truth-table# Texas TRS baseline — samepension-model run txtrs --no-test --truth-table
```

Then open `output/truth_tables.xlsx` and show:

-   `frs_Py` / `txtrs_Py` — Python results (overwritten each run).
-   `frs_R` / `txtrs_R` — R baseline (frozen reference).
-   `frs_diff` / `txtrs_diff` — **the punchline sheet**: R, Python, and diff side by side, column by column. Diffs are at float noise (~1e-15).

This workbook is the evidence that Python matches R. It’s regenerated on every run, so it can’t drift silently.

---

## 3\. Model structure at a glance

| Folder | What’s in it |
| --- | --- |
| [src/pension\_model/](../src/pension_model/) | The Python package — CLI (command line interface), core computation modules, plan-config loader |
| [plans/](../plans/) | One subfolder per plan (`frs/`, `txtrs/`, …): Each has `config/`, `data/`, `baselines/` |
| [scenarios/](../scenarios/) | JSON overrides for policy experiments (low\_return, no\_cola, high\_discount) |
| [scripts/](../scripts/) | One-off utilities: data extraction, baseline building, validation |
| [tests/](../tests/) | Pytest suite — R-baseline regression + identity checks |
| [output/](../output/) | Run artifacts: `summary.csv`, `liability_stacked.csv`, `truth_tables.xlsx` |
| [baseline\_outputs/](../baseline_outputs/) | Intermediate calibration / entrant-profile outputs |
| [docs/](../docs/) | This doc, [model\_goals.md](model_goals.md), architecture notes |
| [R\_model/](../R_model/) | The reference R models (FRS and TXTRS) — read-only ground truth |

**The core idea:** everything plan-specific lives in `plans/<plan>/`. The Python code in `src/pension_model/` and `scenarios/*.json` is plan-agnostic.

### Inside a plan — using FRS

-   [plans/frs/config/plan\_config.json](../plans/frs/config/plan_config.json) — classes (admin, regular, senior\_mgmt, judges, eco, eso, …), benefit formulas, COLA, funding policy, economic assumptions, valuation targets.
-   [plans/frs/config/calibration.json](../plans/frs/config/calibration.json) — per-class `nc_cal` and `pvfb_term_current` (see §5).
-   `plans/frs/data/` — “stage-3” model-input CSVs: demographics, decrements, mortality, funding inputs.
-   `plans/frs/baselines/` — R reference outputs for regression tests (whether anything that once worked has since been broken).

---

## 4\. How the model works — FRS example

What happens, in order, when you run `pension-model run frs --no-test`:

1.  **Load config.** Read `plans/frs/config/plan_config.json`, merge in `calibration.json`, and merge any `--scenario` overrides on top.
2.  **Build benefit tables.** For every membership class, build a large lookup table keyed by entry age × years of service × age. Contains salary, accrued benefit, annuity factor, PVFB, PVFS, normal cost — all the per-cohort actuarial quantities, computed once up front using vectorized pandas/NumPy.
3.  **Project the workforce.** For each class, simulate a 30-year horizon cohort by cohort: actives decrement each year (termination, retirement, mortality, disability); new entrants arrive according to the entrant profile.
4.  **Aggregate liabilities.** Sum benefit quantities across cohorts and states (active, terminated-vested, current retirees) year by year.
5.  **Funding model.** Apply contribution policy, asset smoothing (corridor for FRS, gain/loss deferral for TRS), and amortization to get contributions, AVA, MVA, and funded ratio each year.
6.  **Write outputs.** `summary.csv`, `liability_stacked.csv`, and — with `--truth-table` — the Excel workbook sheets.

> **Key functions / call graph:** *to be filled in closer to the meeting once in-progress refactors settle.* The folder-level picture above is stable; the function-name detail is not worth pinning down today.

---

## 5\. Calibration

The model is **calibrated, not reconstructed** — rather than modeling every actuarial detail from first principles, we apply two small per-class adjustment factors so our results land on the published actuarial valuation.

-   `nc_cal` — multiplicative scaling on normal cost.
-   `pvfb_term_current` — additive UAL adjustment for current terminated-vested members.

Computed by:

bash

Copy

```bash
pension-model calibrate frs --write
```

This runs the pipeline uncalibrated, compares aggregate AAL and NC against targets pulled from `valuation_inputs` in `plan_config.json`, derives the two factors per class, and writes `plans/frs/config/calibration.json`. Subsequent `run` commands pick that file up automatically.

> **Worked example / function walkthrough:** *to be filled in closer to the meeting.*

---

## 6\. Policy simulation

Scenarios are JSON files that override specific config sections. No code changes, no new plan.

Example — [scenarios/low\_return.json](../scenarios/low_return.json):

json

Copy

```json
{  "name": "low_return",  "description": "Pessimistic investment return: 5% (vs baseline 6.7% FRS / 7% TRS)",  "overrides": {    "economic": {      "model_return": 0.05,      "return_scen": "model"    }  }}
```

Run it:

bash

Copy

```bash
pension-model run frs --no-test --scenario scenarios/low_return.json --truth-table
```

Outputs land under `output/frs/low_return/` rather than `output/frs/`, so baseline and scenario artifacts never collide. **Calibration factors are not re-derived** — calibration is part of the baseline, not the scenario.

Scenarios are **plan-agnostic by design** — no plan name appears anywhere in a scenario file. The loader just deep-merges the `overrides` dict into whatever plan config was passed on the command line, so the same `low_return.json` works for FRS, TRS, or any future plan.

Overrideable sections today include `economic`, `benefit.cola`, `funding` (amortization, smoothing), and `ranges` (projection horizon). Adding a new scenario dimension typically means adding the knob to config, not writing new code.

Open gap (tracked as [issue #44](https://github.com/donboyd5/pension_model/issues/44)): the merge silently creates any key it doesn’t find, so a scenario that overrides a feature a given plan lacks (e.g., a 3-tier COLA override on a single-tier plan, or a DROP-suspension scenario on a plan without DROP) quietly no-ops instead of failing loudly. The enhancement will validate overrides against the target plan and either warn or stop with a clear message.

Other scenarios currently in the repo: [no\_cola.json](../scenarios/no_cola.json), [high\_discount.json](../scenarios/high_discount.json).

---

## 7\. Plan features via config — DC, CB, DROP

Optional plan features are turned on in config, not in code. A plan's `plan_config.json` declares which features apply; the Python pipeline reads those declarations and selects the right code paths. Below are the three non-DB features currently wired up.

> **Known limitations** are flagged per-feature. Config keys and data-file patterns are stable; specific field names inside each feature's dict may still evolve — treat the JSON snippets as representative rather than frozen.

### 7a. Defined Contribution (DC)

- **Exercised today:** FRS (the FRS Investment Plan) and TRS (the ORP).
- **Activation:** add `"dc"` to `benefit.benefit_types`. Presence of the string is the switch; there is no boolean flag.
- **Allocation:** DC's share of each cohort is set by `plan_design` ratios; for FRS, DC employer contribution rates sit in `valuation_inputs` per class.
- **TRS config block** (fuller, because TRS exposes DC assumptions directly):

  ```json
  "benefit": {
    "benefit_types": ["db", "cb", "dc"],
    "dc": {
      "ee_cont_rate": 0.0225,
      "assumed_return": 0.07,
      "return_volatility": 0.12
    }
  }
  ```

- **Data files:** DC shows up as `payroll_dc_legacy`, `payroll_dc_new`, `er_dc_rate_legacy`, `er_dc_rate_new` columns in each plan's `init_funding.csv`. No DC-specific decrement files — DC members don't have mortality-driven cash flows, only account-balance accumulation.
- **Limitations:** no vesting delay modeled, no embedded options (early-withdrawal penalties, annuitization choice). Straightforward account-balance accumulation.

### 7b. Cash Balance (CB)

- **Exercised today:** TRS only. FRS has no CB.
- **Activation:** add `"cb"` to `benefit.benefit_types` **and** provide a `benefit.cash_balance` block. Both are required; just the `benefit_types` entry alone won't do anything.
- **TRS config block:**

  ```json
  "benefit": {
    "benefit_types": ["db", "cb", "dc"],
    "cash_balance": {
      "ee_pay_credit": 0.06,
      "er_pay_credit": 0.09,
      "vesting_yos": 5,
      "icr_smooth_period": 5,
      "icr_floor": 0.04,
      "icr_cap": 0.07,
      "icr_upside_share": 0.5,
      "annuity_conversion_rate": 0.04,
      "return_volatility": 0.12
    }
  }
  ```

- **Interest crediting rate (ICR)** is computed each year from the return scenario using a floor-cap-with-upside-share formula implemented in [src/pension\_model/core/icr.py](../src/pension_model/core/icr.py). That's the knob that makes CB interesting for policy work — change `icr_floor`, `icr_cap`, or `icr_upside_share` to change the risk-sharing shape.
- **Limitations:** CB has not yet been validated against an external actuarial reference. Annuity conversion uses a fixed rate rather than age-based commutation factors.

### 7c. Deferred Retirement Option Plan (DROP)

- **Exercised today:** FRS only.
- **Activation:** boolean flag at plan level.

  ```json
  "funding": {
    "has_drop": true,
    "drop_reference_class": "regular"
  }
  ```

  `drop_reference_class` says which class's retirement rates and benefits govern DROP entry assumptions — FRS uses "regular" as a proxy for the plan as a whole.
- **Data files:** tier-specific DROP entry probabilities at `plans/frs/baselines/decrement_tables/drop_entry_tier{1,2}.csv` — the probability an active member enters DROP by age × YOS.
- **Limitations (from [model\_goals.md](model_goals.md)):** FRS DROP is currently modeled as a simplified adjustment to the active cohort, not as a full sub-cohort with its own state, interest credits, and cash-flow separation. This matches the reference R model but is a known limitation — full state-based DROP is on the long-term roadmap and will land when a plan with a richer DROP design requires it.

### How scenarios interact with these features

All three feature dicts are reachable from scenario overrides via the usual deep-merge — e.g., a scenario could set `benefit.cash_balance.icr_floor: 0.0` to stress-test the CB floor, or `funding.has_drop: false` to suspend DROP. Remember the silent-no-op gap on plans that lack the feature ([issue #44](https://github.com/donboyd5/pension_model/issues/44)) — a CB scenario run against FRS today won't error, it just won't do anything.

---

## 8\. Stepping through the model (optional / deeper-dive)

Two ways to inspect what the code is actually doing. Use whichever matches the question.

### 8a. Interactive REPL — closest to the R experience

Open the Positron Python console and call the pipeline stages one at a time, keeping intermediates in named variables so you can inspect them (`df.head()`, `df.info()`, `df.query(...)`, `df.describe()`).

> **Where to run this:** from the repo root of whichever checkout has `pension-model` installed in its Python environment (usually `d:/python_projects/pension_model/`). The cells use paths relative to the repo root. In Positron, set the working directory to that folder before pasting.

**Starter cells — stable, safe to try out now:**

```python
# --- cell 1: imports and config load ---
from pathlib import Path
from pension_model.plan_config import load_plan_config

cfg = load_plan_config(Path("plans/frs/config/plan_config.json"))
cfg.scenario_name            # None for baseline
list(cfg.raw.keys())         # top-level config sections
```

```python
# --- cell 2: drill into a config section ---
cfg.raw["economic"]          # discount rates, model return, growth rates
cfg.raw["classes"]           # list of membership classes
cfg.raw["benefit"]["benefit_types"]   # ['db', 'dc'] for FRS, ['db', 'cb', 'dc'] for TRS
```

```python
# --- cell 3: inspect a data file directly ---
import pandas as pd

salary = pd.read_csv("plans/frs/data/demographics/regular_salary.csv")
salary.head()
salary.shape
salary.describe()
```

```python
# --- cell 4: inspect run outputs after `pension-model run frs --no-test` ---
summary = pd.read_csv("output/frs/summary.csv")
summary.head()
summary.columns.tolist()

liab = pd.read_csv("output/frs/liability_stacked.csv")
liab.head()
```

```python
# --- cell 5: compare baseline vs a scenario output ---
base = pd.read_csv("output/frs/summary.csv").set_index("year")
low  = pd.read_csv("output/frs/low_return/summary.csv").set_index("year")
(low["funded_ratio"] - base["funded_ratio"]).head(10)
```

> **Deeper cells** (call `build_plan_benefit_tables`, `project_workforce`, `run_funding_model` stage by stage): *to be filled in closer to the meeting* once the function names and signatures settle. The five cells above use only the public loader and CSV outputs, both of which are stable.

### 8b. VSCode / Positron debugger — true line-by-line stepping

When REPL isn’t enough, set a breakpoint and step through.

1.  Open the file containing the stage you want to inspect.
2.  Click the gutter next to a line (or press **F9**) to set a breakpoint.
3.  **Run → Start Debugging (F5)** using a launch config that runs the CLI as a module.
4.  Step controls:
    -   **F10** — step *over* the current line
    -   **F11** — step *into* a function call
    -   **Shift-F11** — step *out* of the current function
    -   **F5** — continue to the next breakpoint
5.  **Variables** panel (left) shows locals at the paused frame.
6.  **Debug Console** (bottom) evaluates arbitrary Python against the paused frame — e.g. type `bt.shape` or `bt.query("eayos == 25").head()`.

> **Minimal `.vscode/launch.json` snippet:** *to be filled in closer to the meeting* once the CLI entry-point name is settled.

Mental model for an R user: the breakpoint + Variables panel is the Python analog to running R line by line with the environment pane open. The Debug Console is the Python analog to typing at the R prompt while paused.

---

## 9\. Where we are and what’s next — discussion prompts

**Where we are:**

-   Two reference plans match R at float noise: FRS (7 classes, DROP) and Texas TRS (1 class).
-   Zero plan-specific Python code — everything plan-specific is JSON + CSV.
-   Scenario system working; `low_return` validated bit-identical to R.

**Open questions for the group** (discussion, not presentation):

1.  **Next plan to add?** CalPERS? NYSLRS? Something smaller to stress-test generalization first?
2.  **Most valuable policy simulations?** DR sensitivities, COLA variants, contribution-policy alternatives, stress tests on asset returns?
3.  **Features we don’t yet model that you’d want?** Full DROP sub-cohort model, disability retirees as a separate state, variable/conditional COLAs, hybrid DB+DC stacked tiers, employee-choice tiers.
4.  **Outputs / visualizations?** What format makes scenario results easiest for policy audiences to read?
5.  **Validation appetite?** For a new plan, what level of R-or-AV matching does this audience need before trusting scenario results?

---

## Appendix A — Naming conventions

A decoder ring for the short names you’ll see on screen. Python code leans on short variable names by convention; once you know what they stand for, the code reads fast.

### A.1 Common variable-name abbreviations

| Name | Stands for | What it is |
| --- | --- | --- |
| `cfg`, `config` | **P**lan **Config** | The full plan specification loaded from `plan_config.json` (a frozen `PlanConfig` dataclass). |
| `ctx` | **F**unding **Context** | A bundle of state passed into the funding model — scalars, strategies, and DataFrames for one funding compute run. |
| `wf` | **W**ork**f**orce | The projected active-member DataFrame (one row per cohort × year). |
| `bt` | **B**enefit **T**ype | One of `"db"` (defined benefit), `"cb"` (cash balance), `"dc"` (defined contribution). |
| `sbt` | **S**alary / **B**enefit **T**able | Per-cohort actuarial table: salary, final average salary, accrued benefit. |
| `df` | Pandas **D**ata**F**rame | Generic name for a table; just the pandas convention. |

### A.2 Actuarial acronyms (appear in column names, outputs, config)

| Acronym | Meaning |
| --- | --- |
| `aal` | **A**ctuarial **A**ccrued **L**iability — PV of benefits already earned. |
| `ual` | **U**nfunded **A**ctuarial **L**iability — `aal − ava`. |
| `nc` | **N**ormal **C**ost — PV of benefits earned in the coming year. |
| `pvfb` | **P**resent **V**alue of **F**uture **B**enefits — all benefits a member will ever receive. |
| `pvfs` | **P**resent **V**alue of **F**uture **S**alary — used to denominate NC rates. |
| `ava` | **A**ctuarial **V**alue of **A**ssets — smoothed asset value. |
| `mva` | **M**arket **V**alue of **A**ssets — actual market balance. |
| `dr` | **D**iscount **R**ate (variants: `dr_current`, `dr_new`, `dr_old`). |
| `ea` | **E**ntry **A**ge — age when the member first entered the plan. |
| `yos` | **Y**ears **O**f **S**ervice — tenure. |
| `fas` | **F**inal **A**verage **S**alary — averaging window used in the benefit formula. |
| `cola` | **C**ost-**O**f-**L**iving **A**djustment — retiree benefit increase. |

### A.3 Key classes (dataclasses) — the “nouns” the code passes around

| Class | What it holds |
| --- | --- |
| `PlanConfig` | Frozen dataclass holding every parameter parsed from `plan_config.json`. |
| `FundingContext` | State for one funding compute: scalars, smoothing strategy, roll-forward frames. |
| `CompactMortality` | Mortality rates keyed by age × gender × class. |
| `CalibrationTargets` | Inputs to calibration (target AAL / NC from the valuation). |
| `CalibrationResult` | Outputs of calibration (`nc_cal`, `pvfb_term_current` per class). |

### A.4 Module naming — `src/pension_model/`

-   **Nouns, not verbs.** `benefit_tables.py`, `workforce.py`, `funding_model.py` — each module is named for what it *produces* or *is about*.
-   **Top level** (`src/pension_model/*.py`): entry points and cross-cutting utilities — `cli.py`, `plan_config.py`, `truth_table.py`.
-   **`core/` subpackage**: the computation engine — `benefit_tables.py`, `workforce.py`, `pipeline.py`, `funding_model.py`, `calibration.py`, `mortality_builder.py`, `data_loader.py`, etc.
-   **Leading underscore** (e.g., `_funding_core.py`, `_funding_helpers.py`, `_funding_strategies.py`) marks a module as *internal* — an implementation detail of the funding model, not intended for outside callers. Read the non-underscored `funding_model.py` first; dip into the underscored ones only when you need the mechanics.

### A.5 Plan config — top-level sections of `plan_config.json`

| Section | What lives there |
| --- | --- |
| `data` | Path to the plan’s data directory. |
| `economic` | Discount rates (`dr_current`, `dr_new`, `dr_old`), `model_return`, payroll / population growth, inflation. |
| `benefit` | Employee contribution rate, FAS averaging window, benefit types, COLA schedules. |
| `funding` | DROP flag, amortization method and period, funding lag, AVA smoothing parameters. |
| `ranges` | Age/year bounds, projection length, max YOS. |
| `classes` | List of membership classes (e.g., `regular`, `admin`, `judges`). |
| `class_groups` | Class-grouping rules for shared eligibility logic. |
| `tiers` | Tier definitions: eligibility rules, COLA keys, early-retirement reductions. |
| `benefit_multipliers` | Per-class, per-tier benefit accrual formulas (graded or flat). |
| `plan_design` | DB / DC design ratios by class and plan period. |
| `valuation_inputs` | Per-class ACFR snapshot: AAL, NC, payroll, headcount, benefit payments — the calibration targets. |
| `modeling` | Age groupings, mortality forward shift, method flags. |
| `salary_growth_col_map` | Maps each class to its salary-growth column name. |
| `base_table_map` | Maps each class to its mortality base table. |

### A.6 Data filenames — `plans/<plan>/data/`

Pattern: `{class}_{kind}.csv`.

| Subfolder | Typical files |
| --- | --- |
| `demographics/` | `{class}_salary.csv`, `{class}_headcount.csv`, `{class}_salary_growth.csv`, `retiree_distribution.csv` |
| `decrements/` | `{class}_retirement_rates.csv`, `{class}_termination_rates.csv` |
| `mortality/` | Base tables; names vary by source (SOA table × gender). |

If you see a filename you don’t recognize in a demo, the leading token is almost always the membership class.