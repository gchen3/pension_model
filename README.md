This repo contains a Python pension simulation model for policy research. It began as a reproduction of the Reason Foundation's R model of the Florida Retirement System, then evolved into a more general runtime that supports multiple plans through configuration and data rather than plan-specific Python code.

The repository's scope is intentionally narrow: it owns the canonical runtime model, plan configuration, canonical plan input tables, calibration, and validation. Upstream extraction and normalization from source PDFs, spreadsheets, or other actuarial workbooks are expected to happen before inputs land in `plans/<plan>/data/`.

Exact reproduction of current R-model results remains a hard constraint. Cleanup and generalization work should make the model easier to read and extend without changing outputs.

## Documentation

- [meta-docs/repo_goals.md](meta-docs/repo_goals.md) explains the project's goals, constraints, and current repo boundary.
- [docs/developer.md](docs/developer.md) is the main developer guide, including runtime flow, plan structure, calibration, and testing.
- [docs/architecture_map.md](docs/architecture_map.md) is the shortest map of the current config, liability, and funding architecture.

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

By default, `pension-model run <plan>` and `pension-model run <plan> --test-only`
run a shared-core plus plan-specific validation subset rather than the full
repository test suite. `--no-test` still skips tests entirely.

For the broader test taxonomy and long-run test/run model, see
[docs/testing_strategy.md](docs/testing_strategy.md). For a full-suite run,
use `pytest` directly.

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

Calibration computes adjustment factors so the model's baseline output matches the actuarial valuation report. Calibration is part of the baseline setup, not scenario analysis: run it after changing benefit formulas, canonical plan data, decrement tables, or valuation targets, but not after changing policy assumptions for a scenario run.

```bash
pension-model calibrate frs               # compute calibration and print diagnostics
pension-model calibrate frs --write       # also write factors to plans/frs/config/calibration.json
pension-model calibrate txtrs             # works for any plan
```

`calibration.json` is loaded as part of plan configuration and then reused by baseline and scenario runs until the underlying baseline setup changes.

See [docs/developer.md](docs/developer.md) for calibration architecture and diagnostics, and [docs/architecture_map.md](docs/architecture_map.md) for the current runtime split between config, liability, and funding responsibilities.
