This repo contains a Python pension simulation model. It was based initially on the Reason Foundation's R model of the Florida Retirement System, generalized for more plans, and optimized to reduce looping through classes.

## Requirements

- [Python 3.11+](https://www.python.org/downloads/)
- Git

## Installation

```bash
git clone https://github.com/donboyd5/pension_model.git
cd pension_model
python -m venv .venv
```

Activate the virtual environment:

- **Linux / macOS:** `source .venv/bin/activate`
- **Windows (Command Prompt):** `.venv\Scripts\activate`
- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`

Then install:

```bash
pip install -e .
```

You must activate the virtual environment each time you open a new terminal. You'll know it's active when your prompt shows `(.venv)`.

## Running the model

Available plans: `frs` (Florida Retirement System), `txtrs` (Texas TRS). Substitute plan names in the examples below.

```bash
pension-model list                        # list discovered plans
pension-model run frs --no-test           # run model only, skip tests
pension-model run frs                     # run model + baseline validation tests
pension-model run frs --test-only         # run tests only
pension-model run frs --truth-table       # also write R-vs-Python truth table to Excel
pension-model run frs --no-test --scenario scenarios/low_return.json  # run a scenario
```

Plans are auto-discovered from `plans/<plan>/config/plan_config.json`. Each plan
directory contains everything needed to run that plan:

```
plans/
  frs/
    config/       plan_config.json, calibration.json
    data/         stage 3 CSVs (demographics, decrements, mortality, funding)
    baselines/    R model reference outputs (for validation)
  txtrs/
    config/
    data/
    baselines/
```

### Output

Every plan produces the same console output (parameters, year 1/30 summary)
and the same output files under `output/<plan>/` (or `output/<plan>/<scenario>/`
when `--scenario` is used):

| File | Contents |
|------|----------|
| `summary.csv` | Plan-wide annual summary: headcounts, payroll, AAL, UAL, assets, contributions, funded ratios |
| `liability_stacked.csv` | Detailed liability components by class and year |

With `--truth-table`, two additional files are written for R-vs-Python comparison:

| File | Contents |
|------|----------|
| `truth_table.csv` | Plan-wide truth table (same columns as R baseline) |
| `truth_tables.xlsx` | Shared workbook with R and Python sheets per plan |

### Scenarios

Scenarios override baseline assumptions while keeping calibration factors fixed.
Create a JSON file with an `overrides` dict that deep-merges into the plan config:

```json
{
  "name": "low_return",
  "description": "Pessimistic investment return: 5%",
  "overrides": {
    "economic": { "model_return": 0.05, "return_scen": "model" }
  }
}
```

See `scenarios/` for examples. Overridable sections: `economic` (discount rate,
investment return, inflation, payroll growth), `benefit.cola`, `funding`
(amortization method/period, asset smoothing), `ranges` (model_period).

Note: when overriding `model_return` separately from `dr_current`, set
`"return_scen": "model"` so the funding model uses the model return column
instead of the assumption (discount rate) column.

## Calibration

Calibration computes adjustment factors so the model's baseline output matches the actuarial valuation report. Run it after changing benefit formulas, data, or decrement tables -- not after changing policy assumptions.

```bash
pension-model calibrate frs               # compute calibration and print diagnostics
pension-model calibrate frs --write       # also write factors to plans/frs/config/calibration.json
pension-model calibrate txtrs             # works for any plan
```

See [docs/calibration.md](docs/calibration.md) for details and [docs/developer.md](docs/developer.md) for the full developer guide.
