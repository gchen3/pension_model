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

From the project directory:

```bash
pension-model frs                # run the FRS model + baseline validation tests
pension-model frs --no-test      # run model only, skip tests
pension-model frs --test-only    # run tests only
```

## Calibration

Calibration computes adjustment factors so the model's baseline output matches the actuarial valuation report. Run it after changing benefit formulas, data, or decrement tables — not after changing policy assumptions.

```bash
pension-model calibrate            # compute calibration and print diagnostics
pension-model calibrate --write    # also write factors to configs/frs/calibration.json
```

See [docs/calibration.md](docs/calibration.md) for details and [docs/developer.md](docs/developer.md) for the full developer guide.
