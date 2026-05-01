# TXTRS-AV Input Checklist

Plan-level view of every input the runtime needs to run `txtrs-av`, with status and source for each. Generated from `prep/txtrs-av/input_checklist.csv` by `prep/common/render_input_checklist.py`. Schema is documented in `prep/common/reports/input_checklist_README.md`.

## Status summary

| status | count |
| --- | --- |
| have | 69 |
| partial | 11 |
| missing | 1 |
| N/A | 14 |
| **total** | **95** |

## Open gaps

Rows with status `missing` or `partial`.

| category | item | status | source_type | notes |
| --- | --- | --- | --- | --- |
| valuation_inputs | val_payroll | missing | — | Not currently in txtrs-av valuation_inputs; available from AV if needed |
| decrements | retirement_rates | partial | AV-derived | Source publishes M/F separately; runtime accepts one schedule so M/F are averaged. Source-backed but with a known simplification. |
| demographics | retiree_distribution | partial | AV-derived | Life annuities only (475891). Disabled annuities (Table 19) and survivors deferred — issue #71 |
| funding_policy | ava_smoothing_recognition_period | partial | AV-derived | DIVERGENCE: AV specifies 5-year phase-in ("five-year phase-in...minimum rate of 20% per year"). Config has 4 and the model architecture is hardcoded for 4-year phasing (4 deferral buckets in src/pension_model/core/_funding_helpers.py with fractions 3/4, 2/3, 1/2 = 25%/year recognition over 4 years). Setting the config to 5 will not match the AV without model code changes (5th bucket + 1/5 fractions). See phase-anytime issue and phase-post-r generalization issue. |
| funding_policy | funding_lag | partial | source-unverified | Searched cert letter and Appendix 2 on 2026-05-01. AV does not state a "1-year lag" directly. AV does say "the next opportunity there is to change the contribution rate, which in this case would be September 1, 2025 following the 2025 legislative session" — consistent with a ~1-year gap between valuation cert (Nov 2024) and next rate-change opportunity (Sep 2025), but not a direct statement of the funding_lag parameter. Likely reflects TX legislative cycle / state FY timing as a modeling convention. |
| funding_year0 | defer_y1_legacy | partial | AV-derived | AV publishes one aggregate remaining deferral; per-year split is reconstructed. Only y2 is populated; y1/y3/y4 set to 0. |
| funding_year0 | defer_y2_legacy | partial | AV-derived | Carries the full aggregate remaining deferral per source_notes funding_note |
| funding_year0 | defer_y3_legacy | partial | AV-derived | Set to 0 — published aggregate not split by year |
| funding_year0 | defer_y4_legacy | partial | AV-derived | Set to 0 — published aggregate not split by year |
| mortality | base_rates | partial | estimated | Active half source-direct from PubT-2010(B). Retiree half is fallback estimator: AV-named 2021 TRS Healthy Pensioner table is not public. Issues #72 and #73. |
| term_vested | avg_deferral_years | partial | estimated | First-cut default of 12; refine from valuation term-vested demographics. Plan_config note flags this as provisional. Issue #76 |
| term_vested | avg_payout_years | partial | estimated | First-cut default of 25; refine from valuation term-vested demographics |

## Full checklist by category

### Plan meta

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| data_dir | required | have | runtime-only | — |  |
| plan_description | required | have | runtime-only | — |  |
| plan_name | required | have | runtime-only | — |  |

### Economic assumptions

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| dr_current | required | have | AV-direct | AV_2024; printed p. 60 / PDF p. 67; Appendix 2 §1 Investment Return Rate | Verified 2026-05-01: "Investment Return Rate 7.00% per annum, compounded annually, composed of an assumed 2.30% inflation rate and a 4.70% real rate of return, net of investment expenses." |
| dr_new | required | have | AV-direct | AV_2024; printed p. 60 / PDF p. 67; Appendix 2 §1 Investment Return Rate | Verified 2026-05-01: AV cites a single 7.00% investment return rate; we apply the same rate to new entrants as a modeling default consistent with US public-pension convention. |
| dr_old | required | have | AV-direct | AV_2024; printed p. 60 / PDF p. 67; Appendix 2 §1 Investment Return Rate | Verified 2026-05-01: 7.00% AV investment return rate. Used by the cashflow-estimation pathway anchored to the published-rate quantity. |
| inflation | required | have | AV-direct | AV_2024; printed p. 60 / PDF p. 67; Appendix 2 §1 Investment Return Rate | Verified 2026-05-01: AV §1 cites "an assumed 2.30% inflation rate" as a component of the 7.00% return. Same 2.30% inflation appears in §3 Rates of Salary Increase and in the PAYROLL GROWTH section. |
| model_return | required | have | AV-direct | AV_2024; printed p. 60 / PDF p. 67; Appendix 2 §1 Investment Return Rate | Verified 2026-05-01: 7.00% AV investment return rate. Equal to dr_current by US public-pension convention. |
| payroll_growth | required | have | AV-direct | AV_2024; printed p. 66 / PDF p. 73; Appendix 2 §PAYROLL GROWTH FOR FUNDING OF UNFUNDED ACTUARIAL ACCRUED LIABILITY | Verified 2026-05-01: "Total payroll is expected to grow at 2.90% per year. The total general wage increase assumption of 2.90% is made up of an inflation rate of 2.30% plus a 0.60% real wage growth." Distinct from individual-member salary growth tail (2.95% = 2.30% inflation + 0.65% productivity, p. 63 / PDF 70). |
| pop_growth | optional | N/A | runtime-only | — | Not used in txtrs-av config |

### Ranges (modeling grid)

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| max_age | required | have | runtime-only | — |  |
| max_yos | required | have | runtime-only | — |  |
| min_age | required | have | runtime-only | — |  |
| min_entry_year | required | have | runtime-only | — |  |
| model_period | required | have | runtime-only | — |  |
| new_year | required | have | runtime-only | — |  |
| start_year | required | have | AV-direct | AV_2024; Title page | 2024 |

### Benefit rules

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| benefit_types | required | have | AV-direct | AV_2024; Plan provisions | DB only |
| cola_block | required | have | AV-direct | AV_2024; printed p. 46 / PDF p. 53; Appendix 1 sections A-E (silence on automatic COLA); H, I (historical ad hoc COLAs); cert letter p. 3 / PDF p. 4 (2023 ad hoc COLA already paid) | Verified 2026-05-01: TX TRS has no automatic ongoing COLA. Appendix 1 mentions only historical ad hoc COLAs (1991, 1993 Legislatures) and the 88th Legislature 2023 one-time COLA already paid in FY 2024 and reflected in the 2024 AAL. All cola.*_active = 0.0 and current_retire = 0.0 are AV-supported by silence on automatic COLA. |
| db_ee_cont_rate | required | have | AV-direct | AV_2024; printed p. 53 / PDF p. 60; Appendix 1 Section F — MEMBER CONTRIBUTIONS | Verified 2026-05-01 against AV: Appendix 1 F states "8.25% for Fiscal Years on and after 2024." Cert letter on printed p. 3 / PDF p. 4 corroborates: "member contribution rate has increased from 7.70% to the current 8.25% in Fiscal Year 2024." Statutory phase-in (2019 Legislature) completed FY 2025. |
| db_ee_interest_rate | required | have | plan-admin-direct | BENEFITS_HANDBOOK; printed p. 7 / PDF p. 10; Member Contribution Account — Interest Earned | Verified 2026-05-01: "Interest on your contributions is currently calculated at the rate of 2% a year. TRS credits interest on Aug. 31 of each year." Also published on https://www.trs.texas.gov/pension-benefits/know-benefits/understand-benefits/member-contributions: "Keep in mind, your contributions continue to earn 2% interest per year." The AV does not restate this rate; statute delegates the rate to the TRS Board, which has set it at 2%. Searched AV Appendix 1 (printed pp. 46-53) and Appendix 2 §1-4 (printed pp. 60-66); only 5%/year on DROP accounts is mentioned in the AV (Appendix 1 A.6 b.5). |
| fas_years_default | required | have | AV-direct | AV_2024; printed p. 46 / PDF p. 53; Appendix 1 Section A.2 — Standard Annuity | Verified 2026-05-01: "average of the highest five annual salaries (based on creditable compensation)." Default applies to non-grandfathered members. |
| fas_years_grandfathered | conditional | have | AV-direct | AV_2024; printed p. 46 / PDF p. 53; Appendix 1 Section A.2 — Standard Annuity | Verified 2026-05-01: "Members who as of August 31, 2005, were either age 50, had 25 years of service, or whose age plus service totaled 70 have their standard annuity calculated using the average of their highest three annual salaries." |
| min_benefit_monthly | optional | have | AV-direct | AV_2024; printed p. 46 / PDF p. 53; Appendix 1 Section A.2 — Normal Retirement Benefits | Verified 2026-05-01: "Greater of standard annuity, or $150 per month." |
| cash_balance_block | conditional | N/A | — | — | DB-only plan |
| dc_block | conditional | N/A | — | — | DB-only plan |
| retire_refund_ratio | optional | N/A | — | — | Omitted from txtrs-av per source_notes |

### Plan structure (classes, tiers, multipliers)

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| benefit_multipliers | required | have | AV-direct | AV_2024; printed p. 46 / PDF p. 53; Appendix 1 Section A.2 — Standard Annuity | Verified 2026-05-01: "The product of 2.3% of the member's average compensation multiplied by years of creditable service." Flat 2.3% applies all tiers. |
| class_groups | required | have | runtime-only | — |  |
| classes | required | have | AV-direct | AV_2024; Plan provisions | Single class "all" |
| plan_design | required | have | runtime-only | — | DB-only |
| tiers | required | have | AV-direct | AV_2024; Plan provisions; Appendix 1 | 4 tiers: grandfathered, pre_2007, vested_2014, current. vested_2014 boundary is approximated by entry year per tier_encoding_note in plan_config |

### Funding policy

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| ava_smoothing_recognition_period | required | partial | AV-derived | AV_2024; printed p. 67 / PDF p. 74; Appendix 2 §ACTUARIAL VALUE OF ASSETS | DIVERGENCE: AV specifies 5-year phase-in ("five-year phase-in...minimum rate of 20% per year"). Config has 4 and the model architecture is hardcoded for 4-year phasing (4 deferral buckets in src/pension_model/core/_funding_helpers.py with fractions 3/4, 2/3, 1/2 = 25%/year recognition over 4 years). Setting the config to 5 will not match the AV without model code changes (5th bucket + 1/5 fractions). See phase-anytime issue and phase-post-r generalization issue. |
| funding_lag | required | partial | source-unverified | AV_2024; printed p. 68 / PDF p. 75; Appendix 2 §REASONABLE ACTUARIALLY DETERMINED CONTRIBUTION (ADC) PER ASOP 4 | Searched cert letter and Appendix 2 on 2026-05-01. AV does not state a "1-year lag" directly. AV does say "the next opportunity there is to change the contribution rate, which in this case would be September 1, 2025 following the 2025 legislative session" — consistent with a ~1-year gap between valuation cert (Nov 2024) and next rate-change opportunity (Sep 2025), but not a direct statement of the funding_lag parameter. Likely reflects TX legislative cycle / state FY timing as a modeling convention. |
| amo_method | required | have | AV-direct | AV_2024; printed p. 68 / PDF p. 75; Appendix 2 §ACTUARIALLY DETERMINED EMPLOYER CONTRIBUTION (ADEC) | Verified 2026-05-01: "The ADEC is determined as the level percentage of payroll that will cover the Fund's normal cost and amortize the Fund's unfunded liabilities..." Cost method is Entry Age Normal (same section). |
| amo_pay_growth | required | have | AV-direct | AV_2024; printed p. 66 / PDF p. 73; Appendix 2 §PAYROLL GROWTH FOR FUNDING OF UNFUNDED ACTUARIAL ACCRUED LIABILITY | Verified 2026-05-01: same 2.90% payroll growth assumption used for UAAL amortization. |
| amo_period_current | required | have | AV-direct | AV_2024; Funding policy | 28 years |
| amo_period_new | required | have | AV-direct | AV_2024; printed p. 68 / PDF p. 75; Appendix 2 §ACTUARIALLY DETERMINED EMPLOYER CONTRIBUTION (ADEC) | Verified 2026-05-01: "...if the fixed rate contributions produce a funding period in excess of 30 years then a 30-year amortization period is used." The AV uses one amortization stream; the model applies the 30-year cap as the period for new gain/loss layers added after the valuation date. Modeling convention consistent with the AV's stated 30-year cap. |
| ava_smoothing_method | required | have | AV-direct | AV_2024; printed p. 67 / PDF p. 74; Appendix 2 §ACTUARIAL VALUE OF ASSETS | Verified 2026-05-01: "The actuarial value of assets is equal to the market value of assets less a five-year phase-in of the excess/(shortfall) between expected investment return and actual income." Method is gain/loss style — recognizes the difference between actual and expected returns over a phase-in period. |
| policy | required | have | AV-direct | AV_2024; printed p. 3 / PDF p. 4; Cert letter §FINANCING OBJECTIVE OF THE PLAN; Appendix 2 §ACTUARIAL COST METHOD (printed p. 68 / PDF p. 75) | Verified 2026-05-01: "The employee, employer, and State contribution rates are established by State law..." Cert letter and §ACTUARIAL COST METHOD both confirm rates set by statute / Legislative appropriation. |
| statutory_ee_rate_schedule | conditional | have | AV-direct | AV_2024; Funding policy |  |
| statutory_er_rate_components | conditional | have | AV-direct | AV_2024; Funding policy | Includes public-edu surcharge |

### Valuation inputs (per class)

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| val_payroll | optional | missing | — | AV_2024; Table 3b covered payroll | Not currently in txtrs-av valuation_inputs; available from AV if needed |
| ben_payment | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 Summary of Cost Items | $15.258B |
| er_dc_cont_rate | conditional | have | AV-direct | AV_2024; N/A — DB-only | 0.0 |
| retiree_pop | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 | 508701 |
| total_active_member | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 | 970872 |
| val_aal | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 | $273.095B |
| val_norm_cost | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 | 12.1% |
| headcount_group | optional | N/A | runtime-only | — | Single-class plan |

### Funding year-0 seed (init_funding.csv)

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| defer_y1_legacy | required | partial | AV-derived | AV_2024; printed p. 20 / PDF p. 27; Table 4 | AV publishes one aggregate remaining deferral; per-year split is reconstructed. Only y2 is populated; y1/y3/y4 set to 0. |
| defer_y2_legacy | required | partial | AV-derived | AV_2024; printed p. 20 / PDF p. 27; Table 4 | Carries the full aggregate remaining deferral per source_notes funding_note |
| defer_y3_legacy | required | partial | AV-derived | AV_2024; printed p. 20 / PDF p. 27; Table 4 | Set to 0 — published aggregate not split by year |
| defer_y4_legacy | required | partial | AV-derived | AV_2024; printed p. 20 / PDF p. 27; Table 4 | Set to 0 — published aggregate not split by year |
| aal_legacy | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 | Equals total_aal in single-tier plan |
| admin_exp_rate | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 | 0.14% |
| ava_legacy | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 |  |
| mva_legacy | required | have | AV-direct | AV_2024; printed p. 20 / PDF p. 27; Table 4 |  |
| total_aal | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 |  |
| total_ava | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 |  |
| total_mva | required | have | AV-direct | AV_2024; printed p. 20 / PDF p. 27; Table 4 Development of Actuarial Value of Assets |  |
| total_payroll | required | have | AV-direct | AV_2024; printed p. 17 / PDF p. 24; Table 2 |  |
| year | required | have | AV-direct | AV_2024; Title page | 2024 |
| aal_new | conditional | N/A | — | — | Zero — no new tier at year 0 |
| ava_new | conditional | N/A | — | — |  |
| defer_y1_new | conditional | N/A | — | — |  |
| defer_y2_new | conditional | N/A | — | — |  |
| defer_y3_new | conditional | N/A | — | — |  |
| defer_y4_new | conditional | N/A | — | — |  |
| mva_new | conditional | N/A | — | — |  |

### Calibration (computed)

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| cal_factor | required | have | computed | — | 1.0 in txtrs-av |
| nc_cal | required | have | computed | — | Computed by pension-model calibrate |
| pvfb_term_current | required | have | computed | — | Single-class plug absorbs per-bucket gaps; issue #48 |

### Term-vested cashflow parameters

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| avg_deferral_years | required | partial | estimated | — | First-cut default of 12; refine from valuation term-vested demographics. Plan_config note flags this as provisional. Issue #76 |
| avg_payout_years | required | partial | estimated | — | First-cut default of 25; refine from valuation term-vested demographics |
| method | required | have | runtime-only | — | deferred_annuity |

### Demographics

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| retiree_distribution | required | partial | AV-derived | AV_2024; printed p. 42 / PDF p. 49; Table 18 Distribution of Life Annuities by Age | Life annuities only (475891). Disabled annuities (Table 19) and survivors deferred — issue #71 |
| active_headcount | required | have | AV-derived | AV_2024; printed p. 41 / PDF p. 48; Table 17 Distribution of Active Members by Age and Service |  |
| active_salary | required | have | AV-derived | AV_2024; printed p. 41 / PDF p. 48; Table 17 |  |
| entrant_profile | optional | have | AV-derived | AV_2024; printed p. 69 / PDF p. 76; Appendix 2 NEW ENTRANT PROFILE |  |
| salary_growth | required | have | AV-direct | AV_2024; printed p. 63 / PDF p. 70; Appendix 2 salary increase assumptions |  |

### Decrements

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| retirement_rates | required | partial | AV-derived | AV_2024; printed p. 62 / PDF p. 69; Appendix 2 rates of retirement | Source publishes M/F separately; runtime accepts one schedule so M/F are averaged. Source-backed but with a known simplification. |
| reduction_gft | conditional | have | AV-direct | AV_2024; printed p. 47 / PDF p. 54; Appendix 1 grandfathered early-retirement reduction table |  |
| reduction_others | conditional | have | AV-direct | AV_2024; printed p. 47 / PDF p. 54; Appendix 1 non-grandfathered early-retirement reduction table |  |
| termination_rates | required | have | AV-derived | AV_2024; printed p. 61 / PDF p. 68; Appendix 2 rates of termination | Select-and-ultimate preserved |

### Mortality

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| base_rates | required | partial | estimated | AV_2024; SOA_PUB2010_AMOUNT; TXTRS_AV_PROTO; printed p. 60;64 / PDF p. 67;71; AV mortality narrative + PubT-2010(B) Below-Median + TX prototype | Active half source-direct from PubT-2010(B). Retiree half is fallback estimator: AV-named 2021 TRS Healthy Pensioner table is not public. Issues #72 and #73. |
| improvement_scale | required | have | AV-referenced-external | AV_2024; SOA_MP2021; printed p. 64 / PDF p. 71; Scale UMP 2021 (ultimate rates of MP-2021) | Immediate-convergence interpretation inferred from AV plus experience study plus GASB 67 |
| male_mp_forward_shift | optional | have | AV-direct | AV_2024; printed p. 60 / PDF p. 67; AV mortality assumptions narrative | 2 years forward per AV |
| mortality_base_table_name | required | have | runtime-only | — | Label "txtrs_av_av_first" identifies the AV-first build path |
| mortality_improvement_scale_name | required | have | runtime-only | — | Label "ump_2021_immediate" |

### Funding data

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| current_term_vested_cashflow | required | have | computed | — | Built from pvfb_term_current plus dr_current plus COLA plus term_vested parameters. Issue #76. |
| return_scenarios | required | have | runtime-only | AV_2024; Table 12c assumption rate | Long-term rate is AV-direct; recession scenarios are modeling-choice stress paths |
| amort_layers | conditional | N/A | — | — | No FRS-style layered amortization for txtrs-av |

### Modeling switches

| item | required | status | source_type | source citation | notes |
| --- | --- | --- | --- | --- | --- |
| entrant_salary_at_start_year | optional | have | runtime-only | — |  |
| use_earliest_retire | optional | N/A | runtime-only | — | Not present in txtrs-av config |

## What this checklist is for

- A single place to see, per plan, what is sourced, partially sourced, estimated, computed, or still missing.
- A reusable shape: copy `prep/common/input_checklist_template.csv` for a new plan, fill in the right-hand columns as documents arrive.
- Complementary to `artifact_provenance.csv`, `source_registry.csv`, and the artifact coverage matrix. The checklist drills into individual scalars in `init_funding.csv`, `valuation_inputs`, and the calibration block — places where one row per file is too coarse to see the gaps.
