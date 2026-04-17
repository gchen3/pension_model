# TXTRS Valuation Input Scope Notes

## Purpose

This note records the current understanding of the scope behind the TXTRS
`valuation_inputs` fields in runtime config.

The main question was whether the current config values were tied to the 2023
ACFR headline membership counts or to the 2024 actuarial valuation tables.

## Current Runtime Values

Source:

- [plans/txtrs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/config/plan_config.json)

Current key fields:

- `total_active_member = 970,872`
- `retiree_pop = 508,701`
- `ben_payment = 15,258,219,146`
- `val_norm_cost = 0.121`
- `val_aal = 273,095,060,051`

## What The 2023 ACFR Publishes

Source:

- [Texas TRS ACFR 2023.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20ACFR%202023.pdf)

Headline ACFR figures include:

- active contributing members = `953,295`
- inactive nonvested = `424,658`
- inactive vested = `134,100`
- retirement recipients = `489,921`
- total participants = `2,001,974`

Those do **not** match the runtime config values directly.

## What The 2024 Valuation Publishes

Source:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
  - Table 2 `Summary of Cost Items`, printed p. 17 / PDF p. 24
  - Table 8a `Change in Plan Net Assets`, printed p. 26 / PDF p. 33

Published 2024 valuation figures:

- active members = `970,874`
- active contributing not in DROP = `970,872`
- in DROP = `2`
- retired members and beneficiaries = `508,701`
- benefit payments = `15,258,219,146`
- actuarial accrued liability = `273,095,060,051`
- gross normal cost = `12.10%`

Page anchors:

- Table 2, printed p. `17` / PDF p. `24`
  - `active contributing members not in DROP = 970,872`
  - `retired members and beneficiaries = 508,701`
  - `gross normal cost = 12.10%`
  - `actuarial accrued liability = 273,095,060,051`
- Table 8a, printed p. `26` / PDF p. `33`
  - `benefit payments = 15,258,219,146`

## Main Finding

The current runtime `valuation_inputs` are valuation-scoped, not ACFR-summary-scoped.

More specifically:

- `total_active_member = 970,872` matches the valuation’s `active contributing
  members not in DROP`
- `retiree_pop = 508,701` matches the valuation’s `retired members and
  beneficiaries`
- `ben_payment = 15,258,219,146` matches the valuation funding table directly
- `val_norm_cost` and `val_aal` also match the valuation tables directly

So the prior mismatch was not really a contradiction. It was a scope and source
issue:

- ACFR 2023 headline counts are one basis
- valuation 2024 participant counts are another basis
- current runtime follows the valuation basis

## Practical Implication For Prep

For TXTRS, the prep workflow should default `valuation_inputs` to the actuarial
valuation tables, not the ACFR membership summary, unless there is a specific
documented reason to do otherwise.

The ACFR still matters for:

- cross-checking reasonableness
- understanding plan-level terminology
- explaining differences in scope and year

But the authoritative mapping for these runtime fields appears to be the 2024
valuation.
