# FRS Selected Field Lineage

## Purpose

This document is a first field-level lineage pass for selected high-value FRS
runtime artifacts.

It is intentionally partial. The goal is to document the most important
source-to-runtime relationships before attempting full field-level coverage.

Primary references:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
- [2022-23_ACFR.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2022-23_ACFR.pdf)
- [plans/frs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/config/plan_config.json)

## Status Legend

- `extracted`: value can be taken directly from a source table or source text
- `derived`: value is source-grounded but needs transformation or combination
- `referenced_not_published`: source basis is known but full table values are not published in the plan PDFs
- `runtime_only`: runtime/modeling value, not document-sourced
- `computed`: produced by procedure rather than sourced from documents

## Selected Config Fields

| Runtime field | Status | Source basis | Source location | Transformation / build rule | Notes |
| --- | --- | --- | --- | --- | --- |
| `economic.dr_current` | `extracted` | Funding valuation discount rate | AV Appendix A economic assumptions, printed p. `A-3`, PDF p. `52` | Store as decimal `0.067` | Keep distinct from asset return concept even when equal numerically. |
| `economic.dr_new` | `runtime_only` | Current runtime assumption for new entrants / new cohorts | Current config structure | No separate source identified yet | Same numeric value as `dr_current` today, but conceptually separate. |
| `economic.model_return` | `extracted` | Investment return assumption | AV executive summary and Appendix A economic assumptions, printed pp. `1-2` and `A-3`, PDF p. `52` for the Appendix A assumption table | Store as decimal `0.067` | This is the assumed asset earnings rate, not the discount-rate concept. |
| `economic.inflation` | `extracted` | Inflation assumption | AV Appendix A, printed p. A-3 | Store as decimal `0.024` | Directly source-linked. |
| `funding.amo_pay_growth` | `extracted` | Aggregate payroll growth assumption | AV Appendix A, printed p. `A-3`, PDF p. `52` | Store as decimal `0.0325` | Used in amortization policy. |
| `funding.ava_smoothing.method` and related smoothing parameters | `extracted` | Asset valuation method | AV Appendix A, printed p. `A-3`, PDF p. `52` | Map narrative description to runtime fields `corridor_low`, `corridor_high`, `gain_loss_recognition` | Strongly source-grounded. |
| `tiers.tier_1` and `tiers.tier_2` eligibility blocks | `extracted` | Tier I and Tier II retirement/vesting rules | AV Appendix B, printed pp. `B-5` to `B-10`, PDF pp. `78` to `83`; ACFR Note 1, printed pp. `33-35` | Encode source rules into normalized eligibility objects | These are among the cleanest source-to-runtime mappings. |
| `tiers.tier_3` | `runtime_only` | Forward-looking runtime extension beyond reported source tiers | Current config structure | No direct source basis identified | Should be treated as runtime/modeling, not document-sourced. |
| `benefit_multipliers.*` | `extracted` | Class-specific service multipliers | AV Appendix B, printed pp. `B-6` to `B-9`, PDF pp. `79` to `82`; ACFR Note 1, printed pp. `34-35` | Encode printed benefit-per-year schedules into current JSON structure | Strong source grounding. |
| `valuation_inputs.{class}.retiree_pop` | `extracted` | Annuitant counts by class/system | AV Table C-5, printed p. `C-4`, PDF p. `96` | Use class-specific annuitant counts | Current values appear sourced from AV class totals. |
| `valuation_inputs.{class}.total_active_member` | `derived` | Active members by class | ACFR `Active FRS Members by System/Class`, printed p. `191`, PDF p. `193` | Select the historical column that aligns with the reviewed baseline year, not necessarily latest column | Example: `regular = 537128`, `special = 72925`, `admin = 104`, `judges = 2075`, and `senior_management = 7610` match the 2022 column in the ACFR table rather than 2023. |
| `valuation_inputs.{class}.val_aal` | `extracted` | Class actuarial accrued liability | AV Table 3-2, printed p. `24`, PDF p. `29`, near the `d. Total Actuarial Liability (a)+(b)+(c)` row | Map printed values in thousands to whole-dollar config values | Verified examples: `regular = $145,585,523`, `special = $45,070,773`, `admin = $90,337`, `judges = $1,545,348`, `eco = $138,008`, `eso = $751,363`, `senior_management = $6,039,701` in thousands. |
| `valuation_inputs.{class}.val_payroll` | `extracted` | Class payroll used in the baseline config | ACFR `Annual FRS Payroll by System/Class`, printed p. `191`, PDF p. `193` | Select the historical column aligned to the reviewed baseline year and convert directly from dollars | Verified 2022-column matches for current config examples: `regular = 29,126,383,663`, `special = 5,451,709,307`, `admin = 5,381,322`, `judges = 211,724,251`, `senior_management = 824,335,420`. |
| `valuation_inputs.{class}.ben_payment` | `derived` | Current runtime values are exactly `class_outflow * ben_payment_ratio`, where the ratio comes from the ACFR deductions table and the class outflows now appear to come from valuation Table 2-4 line `3` `Benefit Payments and other Disbursements` | AV Table 2-4, printed p. `18`, PDF p. `23`; ACFR pension-plan deductions table, printed p. `155`, PDF p. `157`; ACFR statistical `Total Annual Benefits by System/Class`, printed p. `205`, PDF p. `207`; AV Table C-5, printed p. `C-4`, PDF p. `96`; [plans/frs/baselines/input_params.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/input_params.json); [scripts/extract/extract_baseline.R](/home/donboyd5/Documents/python_projects/pension_model/scripts/extract/extract_baseline.R) | Apply `11,944,986,866 / 12,763,932,044` to class outflows that match valuation Table 2-4 line `3` almost exactly | Exact runtime reproduction is now explained and provenance is much stronger. The remaining issue is conceptual: Table 2-4 line `3` is a broader class-disbursement concept for plan year `2021/2022`, not a direct class benefit-payment table. |
| `plan_design.*` | `derived` | FRS Pension Plan vs Investment Plan choice behavior | AV and ACFR describe DB/DC choice at system level; current runtime encodes design ratios | Requires interpretive mapping beyond source text | This is a prime field set for later runtime-contract review. |

## Selected Data Artifacts

| Runtime artifact / field group | Status | Source basis | Source location | Transformation / build rule | Notes |
| --- | --- | --- | --- | --- | --- |
| `data/demographics/regular_headcount.csv` | `derived` | Regular Class age-by-service member counts | AV Table C-8, printed p. `C-6`, PDF p. `98` | Convert printed matrix to tidy `age,yos,count` rows | The first rows in the current file match the Regular Class printed matrix structure. |
| `data/demographics/regular_salary.csv` | `derived` | Regular Class average salary by age and service | AV Table C-8, printed p. `C-6`, PDF p. `98` | Convert printed matrix to tidy `age,yos,salary` rows | Monetary values must remain in dollars. |
| `data/demographics/retiree_distribution.csv` | `derived` | Grouped retiree and disability counts / annual benefits by age | AV Tables C-1 and C-2, printed p. `C-2`, PDF p. `94` | Apply legacy workbook smoothing from grouped valuation age bands to single ages, then compute `avg_benefit` and ratios | The grouped inputs are now directly source-grounded, and the current runtime file matches the workbook output to floating-point precision. The remaining unresolved step is whether to treat that smoothing as a legacy-only reconstruction or a future documented prep method. |
| `data/decrements/regular_retirement_rates.csv` | `derived` | Tier I and Tier II retirement assumptions for Regular members | AV Appendix A retirement assumptions, printed pp. `A-5` to `A-12`, PDF pp. `54` to `61` | Normalize printed retirement tables into `age,tier,retire_type,retire_rate` rows | Current runtime collapses richer source distinctions into a simpler table. |
| `data/decrements/regular_termination_rates.csv` | `derived` | Withdrawal assumptions for Regular members | AV Appendix A withdrawal tables, printed pp. `A-13` to `A-21`, PDF pp. `62` to `70` | Translate age/service source matrix into lookup-based runtime schema | Current runtime is not gender-specific, so some build step must reconcile source male/female tables. |
| `data/funding/init_funding.csv` core fields: `year`, `total_payroll`, `total_aal`, `total_ava`, `total_mva`, `roa` | `derived` | AV funding exhibits and asset/liability sections, plus ACFR payroll support | AV Table 2-3, printed p. `17`, PDF p. `22`; Table 2-4, printed p. `18`, PDF p. `23`; Table 2-6, printed p. `20`, PDF p. `25`; Table 3-2, printed p. `24`, PDF p. `29`; Table 4-11, printed p. `39`, PDF p. `44`; ACFR `Annual FRS Payroll by System/Class`, printed p. `191`, PDF p. `193` | Normalize source figures into one wide canonical row per class-year | `total_aal` is tied to the valuation liability table by class; `total_payroll` for current config-aligned classes appears tied to the ACFR 2022 payroll column; AVA/MVA/ROA come from valuation funding exhibits. |
| `data/funding/amort_layers.csv` fields `class`, `amo_period`, `amo_balance`, `date` | `derived` | UAL amortization base tables | AV Table 4-3, printed p. `31`, PDF p. `36` | Convert printed amortization bases to one row per class/base | Directly source-grounded but still a structured build output. |
| `data/mortality/base_rates.csv` | `referenced_not_published` | PUB-2010 mortality basis and member-category mappings | AV Appendix A mortality section, printed pp. `A-4` to `A-5`, PDF pp. `53` to `54` | Load external standard table values and apply source-specific category mapping | The plan PDFs identify the basis but do not reproduce the full table values. |
| `data/mortality/improvement_scale.csv` | `referenced_not_published` | MP-2018 improvement scale | AV Appendix A mortality section, printed pp. `A-4` to `A-5`, PDF pp. `53` to `54` | Load external scale values | Same issue as above. |

## Immediate Follow-Up

The next useful FRS lineage pass should pin down exact table references for:

- the full `ben_payment` derivation path
- whether Table 2-4 line `3` is the right conceptual first-year target for
  class benefit payments or only a practical proxy
- AVA/MVA/ROA and class funding fields in `init_funding.csv`
- the EOC-to-runtime split rule for `eco`, `eso`, and `judges`
- the specific build rule from male/female withdrawal tables to the current non-gendered runtime termination files
- whether the current retiree-distribution smoothing should remain a legacy
  reconstruction note or become an explicit documented prep method

See also:

- [funding_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/funding_mapping.md)
- [page_crosswalk.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/page_crosswalk.md)
- [retiree_distribution_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/retiree_distribution_mapping.md)
- [year0_cashflow_treatment.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/year0_cashflow_treatment.md)
