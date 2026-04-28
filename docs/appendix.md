
## 7. Plan features via config — DC, CB, DROP

Optional plan features are turned on in config, not in code. A plan's `plan_config.json` declares which features apply; the Python pipeline reads those declarations and selects the right code paths. Below are the three non-DB features currently wired up.

> **Known limitations** are flagged per-feature. Config keys and data-file patterns are stable; specific field names inside each feature's dict may still evolve — treat the JSON snippets as representative rather than frozen.

### 7a. Defined Contribution (DC)

- **Exercised today:** FRS (the FRS Investment Plan) and TRS (the ORP).

- **Activation:** add `"dc"` to `benefit.benefit_types`. Presence of the string is the switch; there is no boolean flag.

- **Allocation:** DC's share of each cohort is set by `plan_design` ratios; for FRS, DC employer contribution rates sit in `valuation_inputs` per class.

- **TRS config block** (fuller, because TRS exposes DC assumptions directly):

  ``` json
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

  ``` json
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

- **Interest crediting rate (ICR)** is computed each year from the return scenario using a floor-cap-with-upside-share formula implemented in [src/pension_model/core/icr.py](../src/pension_model/core/icr.py). That's the knob that makes CB interesting for policy work — change `icr_floor`, `icr_cap`, or `icr_upside_share` to change the risk-sharing shape.

- **Limitations:** CB has not yet been validated against an external actuarial reference. Annuity conversion uses a fixed rate rather than age-based commutation factors.

### 7c. Deferred Retirement Option Plan (DROP)

- **Exercised today:** FRS only.

- **Activation:** boolean flag at plan level.

  ``` json
  "funding": {
    "has_drop": true,
    "drop_reference_class": "regular"
  }
  ```

  `drop_reference_class` says which class's retirement rates and benefits govern DROP entry assumptions — FRS uses "regular" as a proxy for the plan as a whole.

- **Data files:** tier-specific DROP entry probabilities at `plans/frs/baselines/decrement_tables/drop_entry_tier{1,2}.csv` — the probability an active member enters DROP by age × YOS.

- **Limitations (from [repo_goals.md](../meta-docs/repo_goals.md)):** FRS DROP is currently modeled as a simplified adjustment to the active cohort, not as a full sub-cohort with its own state, interest credits, and cash-flow separation. This matches the reference R model but is a known limitation — full state-based DROP is on the long-term roadmap and will land when a plan with a richer DROP design requires it.

### How scenarios interact with these features

All three feature dicts are reachable from scenario overrides via the usual deep-merge — e.g., a scenario could set `benefit.cash_balance.icr_floor: 0.0` to stress-test the CB floor, or `funding.has_drop: false` to suspend DROP. Remember the silent-no-op gap on plans that lack the feature ([issue #44](https://github.com/donboyd5/pension_model/issues/44)) — a CB scenario run against FRS today won't error, it just won't do anything.

------------------------------------------------------------------------

## 8. Stepping through the model (optional / deeper-dive)

### Interactive REPL — closest to the R experience

Open the Positron Python console and call the pipeline stages one at a time, keeping intermediates in named variables so you can inspect them (`df.head()`, `df.info()`, `df.query(...)`, `df.describe()`).

> **Where to run this:** from the repo root of `pension-model` , with its Python environment active. The cells use paths relative to the repo root. In Positron, set the working directory to that folder before pasting.

**Starter cells:**

``` python
# --- imports and config load ---
from pathlib import Path
from pension_model.plan_config import load_plan_config

cfg = load_plan_config(Path("plans/frs/config/plan_config.json"))
cfg.scenario_name            # None for baseline
list(cfg.raw.keys())         # top-level config sections
```

``` python
# --- drill into a config section ---
cfg.raw["economic"]          # discount rates, model return, growth rates
cfg.raw["classes"]           # list of membership classes
cfg.raw["benefit"]["benefit_types"]   # ['db', 'dc'] for FRS, ['db', 'cb', 'dc'] for TRS
```

``` python
# --- inspect a data file directly ---
import pandas as pd

salary = pd.read_csv("plans/frs/data/demographics/regular_salary.csv")
salary.head()
salary.shape
salary.describe()
```

``` python
# --- inspect run outputs after a previous `pension-model run frs --no-test` ---
summary = pd.read_csv("output/frs/summary.csv")
summary.head()
summary.columns.tolist()

liab = pd.read_csv("output/frs/liability_stacked.csv")
liab.head()
```

``` python
# --- cell 5: compare baseline vs a scenario output ---
base = pd.read_csv("output/frs/summary.csv").set_index("year")
low  = pd.read_csv("output/frs/low_return/summary.csv").set_index("year")
(low["funded_ratio"] - base["funded_ratio"]).head(10)
```

**Deeper cells — drive the pipeline one stage at a time:**

``` python
# --- cell 6: one call end-to-end (then pick apart the result) ---
from pension_model.core.pipeline import run_plan_pipeline

liability = run_plan_pipeline(cfg)   # dict {class_name: liability DataFrame}
list(liability.keys())
liability["regular"].columns.tolist()
liability["regular"][["year", "total_aal_est", "total_payroll_est",
                      "nc_rate_db_legacy_est"]].head()
```

``` python
# --- benefit tables ---
from pension_model.core.data_loader import load_plan_inputs
from pension_model.core.pipeline import build_plan_benefit_tables

inputs_by_class = load_plan_inputs(cfg)          # reads model-input (stage-3) CSVs
plan_tables = build_plan_benefit_tables(inputs_by_class, cfg)
list(plan_tables.keys())                         # 'salary_benefit', 'ann_factor',
                                                 # 'benefit', 'final_benefit',
                                                 # 'benefit_val', ...
bvt = plan_tables["benefit_val"]
bvt[bvt["class_name"] == "regular"].head()       # PVFB / PVFS / NC per cohort
```

``` python
# --- cell 8: stage 5 on its own — funding model ---
from pension_model.core.funding_model import load_funding_inputs, run_funding_model

funding_inputs = load_funding_inputs(cfg.resolve_data_dir() / "funding")
funding = run_funding_model(liability, funding_inputs, cfg)

list(funding.keys())                             # classes + 'frs' (aggregate)
agg = funding["frs"]
agg[["year", "mva_eoy", "ava_eoy", "funded_ratio", "er_contribution"]].head(10)
```

``` python
# --- cell 9: quick sanity plot (matplotlib) ---
import matplotlib.pyplot as plt

agg.plot(x="year", y=["mva_eoy", "ava_eoy"], title="FRS assets: MVA vs AVA")
plt.show()
```

The first five cells are safe to try out today. Cells 6–8 require that the `pension_model` package be importable in your Python environment — run `pip install -e .` from the repo root once, and they'll work for every subsequent session.



## Appendix A — Naming conventions

A decoder ring for the short names you’ll see on screen. Python code leans on short variable names by convention; once you know what they stand for, the code reads fast.

### A.1 Common variable-name abbreviations

| Name | Stands for | What it is |
|------------------------|------------------------|------------------------|
| `cfg`, `config` | **P**lan **Config** | The full plan specification loaded from `plan_config.json` (a frozen `PlanConfig` dataclass). |
| `ctx` | **F**unding **Context** | A bundle of state passed into the funding model — scalars, strategies, and DataFrames for one funding compute run. |
| `wf` | **W**ork**f**orce | The projected active-member DataFrame (one row per cohort × year). |
| `bt` | **B**enefit **T**ype | One of `"db"` (defined benefit), `"cb"` (cash balance), `"dc"` (defined contribution). |
| `sbt` | **S**alary / **B**enefit **T**able | Per-cohort actuarial table: salary, final average salary, accrued benefit. |
| `df` | Pandas **D**ata**F**rame | Generic name for a table; just the pandas convention. |

### A.2 Actuarial acronyms (appear in column names, outputs, config)

| Acronym | Meaning |
|------------------------------------|------------------------------------|
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
|------------------------------------|------------------------------------|
| `PlanConfig` | Frozen dataclass holding every parameter parsed from `plan_config.json`. |
| `FundingContext` | State for one funding compute: scalars, smoothing strategy, roll-forward frames. |
| `CompactMortality` | Mortality rates keyed by age × gender × class. |
| `CalibrationTargets` | Inputs to calibration (target AAL / NC from the valuation). |
| `CalibrationResult` | Outputs of calibration (`nc_cal`, `pvfb_term_current` per class). |

### A.4 Module naming — `src/pension_model/`

- **Nouns, not verbs.** `benefit_tables.py`, `workforce.py`, `funding_model.py` — each module is named for what it *produces* or *is about*.
- **Top level** (`src/pension_model/*.py`): entry points and cross-cutting utilities — `cli.py`, `plan_config.py`, `truth_table.py`.
- **`core/` subpackage**: the computation engine — `benefit_tables.py`, `workforce.py`, `pipeline.py`, `funding_model.py`, `calibration.py`, `mortality_builder.py`, `data_loader.py`, etc.
- **Leading underscore** (e.g., `_funding_core.py`, `_funding_helpers.py`, `_funding_strategies.py`) marks a module as *internal* — an implementation detail of the funding model, not intended for outside callers. Read the non-underscored `funding_model.py` first; dip into the underscored ones only when you need the mechanics.

### A.5 Plan config — top-level sections of `plan_config.json`

| Section | What lives there |
|------------------------------------|------------------------------------|
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
|------------------------------------|------------------------------------|
| `demographics/` | `{class}_salary.csv`, `{class}_headcount.csv`, `{class}_salary_growth.csv`, `retiree_distribution.csv` |
| `decrements/` | `{class}_retirement_rates.csv`, `{class}_termination_rates.csv` |
| `mortality/` | Base tables; names vary by source (SOA table × gender). |

If you see a filename you don’t recognize in a demo, the leading token is almost always the membership class.

## Appendix B Calibration

The earlier command `pension-model calibrate frs`:

1.  Calls [`cmd_calibrate`](../src/pension_model/cli.py#L351) in `cli.py`.
2.  Runs the pipeline once with **neutral** calibration (every class's `nc_cal = 1.0` or whatever is in calibration.json, `pvfb_term_current = 0.0`) via `run_plan_pipeline(constants)`.
3.  Pulls per-class targets from `valuation_inputs` in `plan_config.json` using [`build_targets_from_config`](../src/pension_model/core/calibration.py#L120). Each target is a `CalibrationTargets(val_norm_cost, val_aal, …)` — the AAL and NC rate the plan's actuarial valuation reports.
4.  Calls [`run_calibration(liability_results, targets, start_year)`](../src/pension_model/core/calibration.py#L78), which loops classes and calls [`calibrate_class`](../src/pension_model/core/calibration.py#L45) for each.The resulting calibration factors are then written to `plans/frs/config/calibration.json`. Every subsequent `pension-model run frs …` loads that file via `load_plan_config(..., calibration_path=...)` and applies the factors inside the pipeline.

**Why two factors?** `nc_cal` captures scaling discrepancies in normal cost (typically from decrement-table or salary-scale differences vs. the AV's assumptions, and from use of grouped data when instead the AV was based on member-level data). `pvfb_term_current` absorbs the AAL gap that's left over — mostly the difference between a cohort-level model and an AV's member-by-member liability. These two sets of calibrations are enough to hit two targets exactly.
