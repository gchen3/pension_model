## Architecture Map

This document describes the current runtime structure of the pension model after the refactor that separated config, liability, and funding responsibilities more cleanly.

## Runtime Flow

The model runs in four main stages:

1. Plan config is loaded and validated.
2. Canonical input tables are loaded and prepared.
3. The liability pipeline builds benefit tables, projects the workforce, and computes AAL-related outputs.
4. The funding pipeline rolls liabilities, assets, contributions, and funded status forward by year.

At a high level:

```text
plan_config.json + CSV inputs
  -> PlanConfig + prepared input tables
  -> liability pipeline
  -> funding pipeline
  -> summary / stacked outputs / truth table
```

The repo boundary for that flow is intentionally narrow: the runtime expects
canonical plan config plus canonical plan data under `plans/{plan}/`. Raw
extraction from PDFs, Excel workbooks, or ad hoc actuarial source files is
upstream prep work, not part of the core runtime architecture described here.

## Main Modules

### Config layer

- [src/pension_model/plan_config.py](../src/pension_model/plan_config.py) is the stable public import surface.
- [src/pension_model/config_schema.py](../src/pension_model/config_schema.py) defines `PlanConfig`, which is the main typed contract used across the model.
- [src/pension_model/config_loading.py](../src/pension_model/config_loading.py) handles plan discovery, JSON loading, scenario merging, and calibration-file loading.
- [src/pension_model/config_validation.py](../src/pension_model/config_validation.py) handles non-fatal config warnings and missing-file checks.
- [src/pension_model/config_helpers.py](../src/pension_model/config_helpers.py) contains derived helper logic, such as retirement parameter extraction and plan-design ratio lookup.
- [src/pension_model/config_resolvers.py](../src/pension_model/config_resolvers.py) is the public resolver surface for tier, COLA, benefit multiplier, and early-retirement reduction logic.

The main architectural rule here is: config loading, config schema, compatibility helpers, and rule resolution are now separate concerns.

Within that layer, `plan_config.py` is the compatibility/public surface; the
other config modules are the implementation split behind it.

### Input-loading layer

- [src/pension_model/core/data_loader.py](../src/pension_model/core/data_loader.py) loads demographics, decrements, mortality, retiree distribution, and funding inputs.
- `load_plan_inputs()` is the main bridge from `PlanConfig` to runtime-ready tables.

This layer also prepares a few derived runtime artifacts, such as:

- headcount adjustment ratios
- reduction tables
- compact mortality objects
- funding input tables

That keeps file I/O and format normalization outside the liability and funding math.

### Liability layer

- [src/pension_model/core/pipeline.py](../src/pension_model/core/pipeline.py) is the liability orchestration layer.
- `run_plan_pipeline()` is the main entry point.
- `build_plan_benefit_tables()` builds the plan-wide stacked benefit-table chain.

The liability stage is now split into:

- [src/pension_model/core/benefit_tables.py](../src/pension_model/core/benefit_tables.py): salary/headcount, separation, annuity-factor, benefit, and present-value tables
- [src/pension_model/core/workforce.py](../src/pension_model/core/workforce.py): workforce projection
- [src/pension_model/core/pipeline_projected.py](../src/pension_model/core/pipeline_projected.py): projected active, term, refund, and retiree liability components
- [src/pension_model/core/pipeline_current.py](../src/pension_model/core/pipeline_current.py): current retiree and current term-vested components

This stage produces class-by-class liability outputs that feed the funding model.

### Funding layer

- [src/pension_model/core/funding_model.py](../src/pension_model/core/funding_model.py) is the public funding entry point.
- `run_funding_model()` dispatches to the unified funding compute driver.

The funding stage is now split into:

- [src/pension_model/core/_funding_setup.py](../src/pension_model/core/_funding_setup.py): funding context, frame setup, amortization-state setup, and calibration of funding frames from liability outputs
- [src/pension_model/core/_funding_phases.py](../src/pension_model/core/_funding_phases.py): year-loop phase helpers
- [src/pension_model/core/_funding_core.py](../src/pension_model/core/_funding_core.py): `_compute_funding()`, the unified funding driver
- [src/pension_model/core/_funding_strategies.py](../src/pension_model/core/_funding_strategies.py): AVA smoothing and contribution strategy objects
- [src/pension_model/core/_funding_helpers.py](../src/pension_model/core/_funding_helpers.py): low-level funding math helpers

The funding model now reads as:

1. resolve setup/context
2. prepare funding frames and amortization state
3. run the year loop
4. finalize aggregate outputs

## Benefit-Type Handling

The model is built around a shared engine that can represent different benefit structures within one plan.

### DB

Defined-benefit logic is the core path:

- benefit tables compute DB salary-linked benefits and refund balances
- liability outputs produce DB active, term, refund, and retiree components
- funding outputs roll DB liabilities, assets, and contributions forward

### DC

Defined-contribution handling is deliberately narrower:

- DC affects workforce/member allocation and payroll splits
- DC employer contribution rates flow through the funding frames when the plan schema includes DC payroll columns
- DC contributions are treated as employer outflows, but they do not create DB AAL

Architecturally, this means DC is present in the liability/funding plumbing, but not in the DB liability math itself.

### Cash balance

Cash balance is handled as a separate benefit leg where applicable:

- plan config declares `cb` in `benefit_types`
- liability tables compute CB balances/benefits and CB normal cost columns
- funding frames carry CB payroll and CB-related normal cost when the plan has that leg

Cash balance therefore shares the main engine, but has its own columns and capability gates instead of being squeezed into DB logic.

### DROP

DROP is handled in the funding stage, not as a separate liability engine:

- the funding context identifies whether a plan has DROP
- the year loop can create/use a synthetic `"drop"` funding frame
- DROP payroll, benefits, refunds, AAL, and AVA reallocation are projected and then accumulated back into the aggregate

So DROP is modeled as a funding-specific overlay on top of the liability outputs rather than as a separate plan-wide pipeline.

## Data Structures That Matter Most

The most important runtime structures are:

- `PlanConfig`: typed plan contract
- `inputs_by_class`: prepared raw inputs keyed by class name
- stacked benefit tables: plan-wide tables carrying `class_name`
- workforce projection tables: active / term / refund / retire outputs by class
- `liability_results`: class-keyed liability DataFrames
- `funding_inputs`: initial funding, return scenarios, amortization layers
- `FundingContext`: resolved runtime funding configuration
- `funding`: class-keyed and aggregate funding DataFrames

## Current Design Boundaries

The architecture is now substantially cleaner than before, but a few important boundaries remain:

- Liability and funding are separate stages linked by class-keyed liability outputs.
- File I/O and schema normalization are outside the main liability/funding math.
- Config schema and config-resolution logic are separated from file loading.
- Funding strategy selection is config-driven, but the unified year loop still lives in one driver.
- `cli.py`, `plan_config.py`, `core/pipeline.py`, and `core/funding_model.py` are the main public orchestration surfaces; the underscore-prefixed funding modules are implementation details behind that surface.

## What Is Still Intentionally Transitional

Some parts are cleaner than before but still intentionally conservative because exact reproduction remains a hard constraint:

- legacy compatibility exports remain in place for callers/tests
- some funding and benefit logic is still column-driven rather than represented with richer domain objects
- some config values still come from `raw`-backed properties on `PlanConfig`
- tests are still organized partly around R-reproduction and historical workflow rather than a fully rationalized testing taxonomy

That is deliberate. The refactor so far is aimed at making the model easier to read and extend without changing current results.
