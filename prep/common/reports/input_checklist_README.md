# Input Checklist — How to Use

## What this is

`prep/common/input_checklist_template.csv` is the plan-agnostic list of every
input the runtime needs to run a plan today. One row per input item.

For each new plan, copy the template to `prep/{plan}/input_checklist.csv` and
fill in the right-hand columns as data arrives. Generate a markdown view at
`prep/{plan}/reports/input_checklist.md` so the state of the plan can be read
at a glance.

## File pair

```
prep/common/input_checklist_template.csv     # plan-agnostic master list
prep/{plan}/input_checklist.csv              # filled-in instance per plan
prep/{plan}/reports/input_checklist.md       # human-readable view, regenerated
```

## Columns

| column | meaning |
| --- | --- |
| `category` | grouping (economic, benefit, funding_year0, demographics, mortality, …) |
| `item` | short item identifier |
| `description` | plain-English description |
| `runtime_location` | filename or config path where the value lands |
| `required` | `required`, `optional`, or `conditional` (e.g., only if plan has DROP) |
| `status` | `missing`, `partial`, `have`, or `N/A` |
| `source_type` | `AV-direct`, `AV-derived`, `AV-referenced-external`, `estimated`, `runtime-only`, `computed` |
| `source_doc` | source ID from `prep/{plan}/source_registry.csv` (e.g., `AV_2024`) |
| `printed_page` | printed page in source |
| `pdf_page` | PDF page in source |
| `table_or_section` | (e.g., "Table 17", "Appendix 2 salary increase") |
| `method_id` | method registry ID when derived or estimated |
| `notes` | provenance, gaps, plug placeholders, issue references |

## Granularity rules

- **Detailed (one row per scalar)** for the year-0 funding seed, valuation
  inputs, calibration plugs, term-vested parameters, and the small economic
  block. These are the spots most likely to have item-by-item gaps.
- **Block-level (one row per coherent block)** for the rest of plan_config.json:
  benefit rules, tier definitions, funding policy, plan structure, ranges. A
  block-level row is enough because these blocks are typically published
  together and either fully sourced or fully missing.
- **Artifact-level (one row per file)** for demographics, decrements, and
  mortality data tables. Per-column detail lives in `artifact_provenance.csv`.

## Status vocabulary

- `missing` — not yet built or not yet sourced
- `partial` — some fields filled but not all, or filled with provisional values
- `have` — built and sourced
- `N/A` — does not apply to this plan (e.g., DC block on a DB-only plan)

The `source_type` column says how strong the source link is. For partial or
have rows, fill in `source_doc`, `printed_page`, `pdf_page`, and
`table_or_section` so a reader can verify.

## Relationship to other prep artifacts

This checklist is a **planning view**. It is complementary to:

- `prep/{plan}/source_registry.csv` — sources copied into the plan.
- `prep/{plan}/artifact_provenance.csv` — file-level provenance for built
  artifacts, including per-table extraction methods. The checklist's
  artifact-level rows reuse the source/page/method fields recorded there.
- `prep/{plan}/check_manifest.csv` — checks that should pass once data is
  built.
- `prep/{plan}/reports/artifact_coverage_matrix.md` — narrative view of
  what is direct, derived, estimated, or missing at the artifact level.

When in doubt, the checklist points at a runtime location; the provenance and
source registry explain how that location was filled.

## Updating the template

The template will need new rows whenever the runtime adds a required input.
Edit `prep/common/input_checklist_template.csv` on its own short branch, then
sync each plan's instance.
