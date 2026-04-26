# High Discount Discount-Rate Basis Plan

Date: 2026-04-25
Branch: `scenario_testing`

## Context

The FRS `high_discount` scenario currently does not match between the R workflow and the Python workflow, while `low_return` and `no_cola` match to floating-point noise.

Current comparison against the existing R high-discount truth table:

- `aal_boy`: max Python minus R difference about `+1.724B`
- `mva_boy`: max difference about `+1.695B`
- `ava_boy`: max difference about `+1.695B`
- `benefits_fy`: max difference about `+0.178B`
- 2023 funded-ratio difference about `-0.00643`

Root cause found:

- In R, current term-vested members are special-cased.
- R builds the current term-vested benefit payment stream using the baseline discount rate `dr_current_ = 0.067`.
- R then values that payment stream using the scenario valuation rate `dr_current = 0.075`.
- Python currently uses `constants.economic.dr_current` for both steps, so under `high_discount` it uses `0.075` both to build the payment stream and to value it.

Key R code:

- `R_model/R_model_frs/Florida FRS liability model.R`
- Current term-vested section:
  - `retire_ben_term <- get_pmt(r = dr_current_, ...)`
  - `aal_term_current_est = roll_pv(rate = dr_current, ...)`

Key Python code:

- `src/pension_model/core/pipeline_current.py`
- `compute_current_term_vested_liability()` currently uses one `discount_rate = constants.economic.dr_current` for both `_get_pmt(...)` and `_roll_pv(...)`.

An in-memory Python experiment confirmed that if Python uses `0.067` for current term-vested payment construction and `0.075` for valuation, then `high_discount` matches R to floating-point precision.

Important actuarial interpretation:

- The current R behavior is more defensible than the current Python behavior for the current term-vested component, because a valuation discount-rate sensitivity should generally revalue projected payments rather than changing the nominal payment stream.
- The R workflow is still not fully ideal as a general actuarial design because discount-rate roles are not explicit everywhere. Some active/future-member valuation calculations use the scenario rate deeply through annuity factors, PVFB, PVFS, and normal cost.
- Long term, the model should separate cash-flow projection assumptions from valuation-basis assumptions explicitly.

## Goals

1. First, make Python match the current R workflow for FRS `high_discount`, using the same role vocabulary that will support the later explicit-basis refactor.
2. Add tests proving R and Python match for the FRS `high_discount` scenario, and tests documenting the intended cash-flow-vs-valuation discount-rate split.
3. Then refactor toward an explicit discount-rate basis design that separates:
   - rates used to project or allocate benefit cash flows
   - rates used to present-value those cash flows for AAL/PVFB/PVFS
   - rates used for asset-return projections

Do this in that order. Do not change R semantics before Python can reproduce the current R truth table. However, Phase 1 and Phase 2 should be designed as stepping stones toward Phase 3, not as temporary term-vested-only naming that will need to be undone.

Naming convention:

- `cashflow_discount_rate`: the rate used to construct or allocate nominal cash flows, including synthetic current term-vested benefit payment streams.
- `valuation_discount_rate`: the rate used to present-value cash flows for AAL/PVFB/PVFS/normal cost.
- `"baseline_dr_current"` and `"scenario_dr_current"` are basis/source names, not role names.
- Avoid names such as `payment_discount_rate`, `benefit_discount_rate`, and `baseline_discount_rate` in new design text. They blur whether the name describes the role of the rate or the source of the rate.

## Implementation Plan

### Phase 1: Match Current R Behavior In Python, Using Future-Compatible Rate Roles

- Preserve baseline economic assumptions before scenario overrides are merged.
  - In `load_plan_config(...)`, keep a copy of the original plan JSON economic block before `_deep_merge(...)`.
  - Store it in `raw`, for example as `raw["_baseline_economic"]`.
  - Add a small `PlanConfig` property such as `baseline_dr_current` that returns `raw["_baseline_economic"]["dr_current"]`, falling back to `dr_current` when no scenario is loaded.

- Add explicit discount-rate basis resolution that separates role from source.
  - Add a small resolver, for example `_resolve_discount_rate_basis(...)`, that maps source names to rates:
    - `"scenario_dr_current"` resolves to the scenario-loaded `dr_current`.
    - `"baseline_dr_current"` resolves to the pre-scenario baseline `dr_current`.
  - Add config-backed role properties with conservative defaults:
    - `modeling.cashflow_discount_basis = "scenario_dr_current"` by default
    - `modeling.valuation_discount_basis = "scenario_dr_current"` by default
  - FRS should set or resolve:
    - `cashflow_discount_basis = "baseline_dr_current"`
    - `valuation_discount_basis = "scenario_dr_current"`
  - This keeps the high-discount R-match behavior narrow in Phase 1, while using names that can later apply to active, retiree, refund, PVFB/PVFS, normal cost, and annuity-factor calculations.

- Update `compute_current_term_vested_liability(...)`.
  - Split the current single `discount_rate` into:
    - `cashflow_discount_rate`
    - `valuation_discount_rate`
  - For FRS R-match behavior:
    - `cashflow_discount_rate` resolves from `"baseline_dr_current"` and is `0.067`.
    - `valuation_discount_rate` resolves from `"scenario_dr_current"` and is `0.075`.
  - Use `cashflow_discount_rate` in `_get_pmt(...)`.
  - Use `valuation_discount_rate` in `_roll_pv(...)`.
  - For the `bell_curve` method, use `valuation_discount_rate` for present-value calculations. Do not invent additional cash-flow behavior unless tests show that method needs a separate cash-flow construction basis.

- Expected effect:
  - Baseline, `low_return`, and `no_cola` remain unchanged because their discount-rate valuation basis is not changed.
  - `high_discount` should now match R.

### Phase 2: Add Regression Tests For Scenario Matching

- Add a focused config-role test.
  - Load FRS with `scenarios/high_discount.json`.
  - Assert the baseline source is still available:
    - `baseline_dr_current == 0.067`
    - scenario-loaded `dr_current == 0.075`
  - Assert the role resolution:
    - `cashflow_discount_basis == "baseline_dr_current"`
    - `valuation_discount_basis == "scenario_dr_current"`
    - resolved `cashflow_discount_rate == 0.067`
    - resolved `valuation_discount_rate == 0.075`
  - The test should make it clear that baseline/scenario are sources, while cashflow/valuation are roles.

- Add a focused FRS scenario truth-table regression test.
  - Suggested file: `tests/test_pension_model/test_truth_table_frs_scenarios.py`
  - Use the in-process pipeline rather than shelling out.
  - Load config with:
    - `plans/frs/config/plan_config.json`
    - `plans/frs/config/calibration.json`
    - scenario path `scenarios/high_discount.json`
  - Run liability and funding.
  - Build the Python truth table with `build_python_truth_table(...)`.
  - Compare to `plans/frs/baselines/r_truth_table_high_discount.csv`.

- Assertion:
  - Compare common numeric truth-table columns.
  - Use absolute tolerance `<= 0.001` for dollar columns.
  - Use tighter tolerance, around `1e-12`, for funded-ratio columns if practical.
  - If the frozen R scenario CSV uses an older truth-table layout, compare only columns whose definitions match the current Python truth-table columns.

- Include at least `high_discount`.
  - If runtime is acceptable, parameterize the same test for:
    - `low_return`
    - `high_discount`
    - `no_cola`
  - Mark as `slow`, `regression`, and `plan_frs`.

- Verification commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pension_model/test_truth_table_frs_scenarios.py -q
.\.venv\Scripts\python.exe -c "import pension_model.cli as c; c.main()" run frs --no-test --scenario scenarios/high_discount.json --truth-table
```

- Manual acceptance:
  - `output/frs/high_discount/truth_table.csv` matches `plans/frs/baselines/r_truth_table_high_discount.csv`.
  - Max differences should be floating-point noise only.
  - The tests document that the current term-vested cash-flow stream is built on baseline `dr_current`, then valued using scenario `dr_current`.

### Phase 3: Make Discount-Rate Roles Explicit

After Phase 1 and Phase 2 pass, refactor the model design so the rate roles are clear instead of implicit.

- Introduce explicit conceptual rate roles:
  - `cashflow_projection` basis: assumptions that determine nominal projected benefits, refunds, payroll, COLA, mortality, retirement, termination, and any synthetic current term-vested payment allocation.
  - `valuation` basis: discount rates used to present-value expected cash flows for AAL, PVFB, PVFS, normal cost, and annuity factors.
  - `asset_return` basis: return paths or assumptions used to roll MVA/AVA and investment income.

- Update scenario vocabulary over time.
  - Keep existing scenario files working for backward compatibility.
  - Long-term scenario files should distinguish:
    - valuation discount rate overrides
    - asset-return overrides
    - cash-flow projection overrides
  - Example intent for a valuation-only high-discount sensitivity:

```json
{
  "name": "high_discount",
  "overrides": {
    "valuation": {
      "dr_current": 0.075,
      "dr_new": 0.075,
      "valuation_discount_basis": "scenario_dr_current"
    },
    "economic": {
      "model_return": 0.075
    },
    "cashflow_projection": {
      "cashflow_discount_basis": "baseline_dr_current"
    }
  }
}
```

- Refactor Python first behind compatibility properties.
  - Add new properties while keeping `economic.dr_current`, `economic.dr_new`, and `economic.model_return` usable.
  - Update internal naming toward `cashflow_discount_rate`, `valuation_discount_rate`, and `asset_return` roles where it reduces ambiguity.
  - Avoid a large mechanical rename until tests protect current behavior.

- Refactor the R workflow second.
  - Because `R_model/R_model_frs/` is ignored and locally supplied, treat R edits as local reference-model work unless the user explicitly wants those files force-added.
  - In R, update function signatures conceptually from one `dr_current` role to separate roles such as:
    - `valuation_discount_rate`
    - `cashflow_discount_rate`
    - `asset_model_return`
  - Preserve old parameter names as wrappers or defaults if practical.

- Baseline management after R refactor:
  - Preserve old current-R comparison outputs if useful, for example as `r_truth_table_high_discount_legacy_r.csv`.
  - Regenerate `r_truth_table_high_discount.csv` only after deciding that the new explicit-basis R workflow is the new reference truth.
  - Re-run Python against the regenerated R truth table.

## Acceptance Criteria

- Current R-match phase:
  - FRS `low_return` still matches R.
  - FRS `no_cola` still matches R.
  - FRS `high_discount` now matches R to floating-point noise.
  - Tests document the high-discount behavior so it cannot regress silently.

- Explicit-basis phase:
  - The code distinguishes cash-flow projection rates from valuation discount rates.
  - Scenario files can express valuation-only discount-rate sensitivities without changing nominal benefit cash flows unless explicitly requested.
  - R and Python still match for whichever R truth baseline is designated current.

## Notes For Next Session

- Do not work on `main`.
- `memory-bank/` is ignored by Git unless files are force-added.
- `R_model/R_model_frs/` and `R_model/R_model_txtrs/` are ignored by Git and contain local manually supplied R files/data.
- The immediate implementation target is Phase 1 plus the high-discount regression test.
