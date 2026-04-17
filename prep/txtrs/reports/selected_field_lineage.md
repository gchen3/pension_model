# TXTRS Selected Field Lineage

## Purpose

This document is a first field-level lineage pass for selected high-value TXTRS
runtime artifacts.

It is intentionally partial. The goal is to document the most important
source-to-runtime relationships before attempting full field-level coverage.

Primary references:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
- [Texas TRS ACFR 2023.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20ACFR%202023.pdf)
- [plans/txtrs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/config/plan_config.json)

## Status Legend

- `extracted`: value can be taken directly from a source table or source text
- `derived`: value is source-grounded but needs transformation or combination
- `referenced_not_published`: source basis is known but full table values are not published in the plan PDFs
- `runtime_only`: runtime/modeling value, not document-sourced
- `computed`: produced by procedure rather than sourced from documents

## Selected Config Fields

| Runtime field | Status | Source basis | Source location | Transformation / build rule | Notes |
| --- | --- | --- | --- | --- | --- |
| `economic.dr_current` | `extracted` | Liability discount rate used in valuation present-value calculations | AV Appendix 2 actuarial assumptions overview, printed p. `60`, PDF p. `67` | Store as decimal `0.07` | Keep conceptually separate from the asset return assumption even when equal numerically. |
| `economic.model_return` | `extracted` | Investment return assumption | AV Appendix 2 actuarial assumptions overview, printed p. `60`, PDF p. `67`; funding summary cross-check in Table 2, printed p. `17`, PDF p. `24` | Store as decimal `0.07` | Same numeric value as discount rate in current source set, but not the same concept. |
| `economic.inflation` | `extracted` | Inflation assumption | AV Appendix 2 actuarial assumptions overview, printed p. `60`, PDF p. `67` | Store as decimal `0.023` | Directly source-linked. |
| `funding.amo_pay_growth` | `extracted` | Payroll growth assumption | AV Appendix 2 payroll-growth note, printed p. `66`, PDF p. `73` | Store as decimal `0.029` | Directly source-linked. |
| `benefit.fas_years_default` | `extracted` | Highest five annual salaries for most members | AV Appendix 1 plan provisions | Store as integer `5` | Clean source-to-runtime mapping. |
| `benefit.fas_years_grandfathered` | `extracted` | Highest three annual salaries for grandfathered members | AV Appendix 1 plan provisions | Store as integer `3` | Clean source-to-runtime mapping. |
| `benefit.min_benefit_monthly` | `extracted` | Minimum monthly annuity | AV Appendix 1 plan provisions | Store as dollars `150` | Published directly. |
| `benefit_types` | `runtime_only` | Runtime/model generalization | Current config structure | No direct source basis for `cb` or `dc` in the reviewed TXTRS PDFs | Strong candidate for later runtime-contract review. |
| `tiers.grandfathered`, `tiers.intermediate`, `tiers.current` | `derived` | Cohort logic by grandfathering, hire date, and vesting status | AV Appendix 1 and related narrative discussion | Encode cohort rules into current tier objects | Source-grounded, but current tier object shape is a runtime abstraction. |
| `benefit_multipliers.all.all_tiers.flat` | `extracted` | 2.3% benefit multiplier | AV Appendix 1 plan provisions | Store as decimal `0.023` | Strong source grounding. |
| `valuation_inputs.all.ben_payment` | `extracted` | Pension benefit payments | AV Table 8a `Change in Plan Net Assets`, printed p. `26`, PDF p. `33` | Map `$15,258,219,146` directly to config | This is a direct valuation-table match. |
| `valuation_inputs.all.retiree_pop` | `extracted` | Retired members and beneficiaries | AV Table 2 `Summary of Cost Items`, printed p. `17`, PDF p. `24` | Map `508,701` directly to config | The earlier ACFR mismatch is explained by different source year and scope. |
| `valuation_inputs.all.total_active_member` | `extracted` | Active contributing members not in DROP | AV Table 2 `Summary of Cost Items`, printed p. `17`, PDF p. `24` | Map `970,872` directly to config | The valuation also shows active subtotal `970,874`, which includes 2 members in DROP. |
| `valuation_inputs.all.val_norm_cost` | `extracted` | Gross normal cost | AV Table 2 `Summary of Cost Items`, printed p. `17`, PDF p. `24`, item `4.a. Gross normal cost` | Map `12.10%` to config decimal `0.121` | Strong source grounding. |
| `valuation_inputs.all.val_aal` | `extracted` | Actuarial accrued liability | AV Table 2 `Summary of Cost Items`, printed p. `17`, PDF p. `24`, item `7. Actuarial Accrued Liability` | Map `$273,095,060,051` directly to config | Strong source grounding. |

## Selected Data Artifacts

| Runtime artifact / field group | Status | Source basis | Source location | Transformation / build rule | Notes |
| --- | --- | --- | --- | --- | --- |
| `data/demographics/all_headcount.csv` | `derived` | Table 17 active-member count matrix | AV Table 17, printed p. `41`, PDF p. `48` | Convert banded matrix to tidy `age,yos,count` rows using a reviewed band-to-point mapping rule | Current runtime appears to use representative ages such as 22, 27, 32 and representative YOS values such as 2, 7, 12. |
| `data/demographics/all_salary.csv` | `derived` | Table 17 average-compensation matrix | AV Table 17, printed p. `41`, PDF p. `48` | Convert banded matrix to tidy `age,yos,salary` rows using the same band-to-point mapping rule | Monetary values remain in dollars; runtime values appear tied to the printed compensation cells after canonicalization. |
| `data/demographics/salary_growth.csv` | `derived` | Inflation plus service-related salary increase assumptions | AV Appendix 2, printed p. `63`, PDF p. `70` | Normalize source assumption structure into runtime CSV | Source is clear, but runtime table is a canonical expression. |
| `data/demographics/entrant_profile.csv` | `derived` | AV Appendix 2 `NEW ENTRANT PROFILE` summary table | AV Appendix 2, printed p. `69`, PDF p. `76` | Convert published age-band counts and salaries into the runtime single-age canonical form, or identify a richer supporting source if needed | Source now exists in the PDF, but the current runtime artifact is more granular than the published summary table. |
| `data/demographics/retiree_distribution.csv` | `derived` | Retiree counts and benefit amounts | AV Table 15b, printed p. `39`, PDF p. `46`; Table 20, printed p. `44`, PDF p. `51`; ACFR retiree totals as cross-check | Build canonical age distribution from summarized source data | Not obviously a direct one-table extraction target. |
| `data/decrements/retirement_rates.csv` | `derived` | Retirement assumptions with cohort-specific adjustments | AV Appendix 2 retirement assumptions, printed pp. `62-63`, PDF pp. `69-70` | Normalize source rates into `age,tier,retire_type,retire_rate` | Current runtime is simpler than the full source logic. |
| `data/decrements/termination_rates.csv` | `derived` | Termination assumptions | AV Appendix 2 termination assumptions, printed p. `61`, PDF p. `68` | Convert source structure into lookup-based runtime schema | Exact build rule still needs confirmation. |
| `data/decrements/reduction_gft.csv` | `derived` | Grandfathered early-retirement reduction table | AV Appendix 1 plan provisions | Convert printed reduction table to tidy `age,yos,reduce_factor,tier` rows | Closely aligned to source structure. |
| `data/decrements/reduction_others.csv` | `derived` | Non-grandfathered early-retirement reduction table | AV Appendix 1 plan provisions | Convert printed reduction table to tidy rows | Closely aligned to source structure. |
| `data/funding/init_funding.csv` core fields: `year`, `total_payroll`, `total_aal`, `total_ava`, `total_mva`, `roa`, `er_stat_base_rate`, `public_edu_surcharge_rate` | `derived` | AV key results and plan-funding discussion | AV Table 2, printed p. `17`, PDF p. `24`; Table 3b, printed p. `19`, PDF p. `26`; Table 8a, printed p. `26`, PDF p. `33` | Normalize published values into one wide canonical row | Verified direct matches include `total_aal = 273,095,060,051`, `total_ava = 212,520,440,440`, `total_mva = 210,543,258,495`, `total_payroll = 61,388,248,000`, `er_stat_base_rate = 8.25%`, `public_edu_surcharge_rate = 1.90%`, and benefit payments of `15,258,219,146`. |
| `data/mortality/base_rates.csv` | `referenced_not_published` | 2021 TRS of Texas Healthy Pensioner Mortality Tables | AV Appendix 2 mortality section, printed pp. `60` and `64`, PDF pp. `67` and `71` | Load external standard table values | The valuation identifies the basis but does not clearly publish the full table values. |
| `data/mortality/improvement_scale.csv` | `referenced_not_published` | Scale UMP 2021 | AV Appendix 2 mortality section, printed p. `64`, PDF p. `71` | Load external scale values | Same issue as above. |

## Immediate Follow-Up

The next useful TXTRS lineage pass should pin down exact source-table references
for:

- the detailed build rule for `all_headcount.csv` and `all_salary.csv`
- whether any source document actually publishes entrant information in a usable form
- the exact source and operational meaning of the 2021 TRS healthy-pensioner
  mortality tables
- whether `Scale UMP 2021` is a direct runtime match to shared MP-2021 rates or
  needs a plan-specific interpretation

See also:

- [valuation_input_scope.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/valuation_input_scope.md)
- [entrant_profile_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/entrant_profile_mapping.md)
- [active_grid_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/active_grid_mapping.md)
- [page_crosswalk.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/page_crosswalk.md)
