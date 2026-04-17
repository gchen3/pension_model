# Artifact Provenance Schema

## Purpose

Artifact provenance records how a reviewed prep artifact was produced from one
or more source documents or upstream prep artifacts.

It is the second provenance layer:

- source registry answers `what source documents exist and why are we using them?`
- artifact provenance answers `what source material or upstream artifacts produced this specific prep artifact?`

Use this for:

- extracted artifacts
- normalized artifacts
- estimated artifacts
- built canonical runtime artifacts produced by prep

Do not use document-lineage fields for computed artifacts like calibration.
Those should use computational lineage instead.

## Recommended Columns

| Column | Meaning |
| --- | --- |
| `artifact_id` | Stable identifier for the artifact or artifact slice. |
| `artifact_stage` | `extracted`, `normalized`, `estimated`, or `build`. |
| `artifact_path` | Repo-relative path to the artifact. |
| `artifact_grain` | `artifact`, `table_section`, `column_group`, or `row_group`. Default is `artifact`. |
| `source_ids` | One or more `source_id` values from the source registry, separated consistently. |
| `printed_pages` | Printed report page labels when available, such as `C-4`, `A-5`, or `205`. |
| `pdf_pages` | PDF/electronic page references when known. |
| `page_reference_notes` | Notes explaining page offsets, missing page labels, or mixed page conventions. |
| `table_or_section_labels` | Source table, exhibit, or section labels. |
| `source_units` | Units as presented in the source, such as `dollars`, `thousands`, `percent`, or `count`. |
| `canonical_units` | Units stored in the artifact after normalization. Monetary artifacts should normally be `dollars`. |
| `provenance_type` | `extracted`, `derived`, `estimated`, `runtime_only`, `computed`. |
| `lineage_status` | `confirmed`, `partially_reconstructed`, `legacy_unresolved`, `estimated_documented`, `runtime_only`, or `computed`. |
| `extraction_method` | Method used to get the source content, such as `manual`, `pdf_table_extraction`, `ocr`, `external_reference_load`. |
| `transform_method_id` | Named transform or estimation method used, if any. |
| `transform_method_version` | Version tag for the transform or estimation method. |
| `review_status` | `unreviewed`, `reviewed`, `approved`, or other agreed status. |
| `notes` | Free-form notes about scope, caveats, or unresolved questions. |

## Grain Rule

Default to `artifact` grain.

Only go more granular when:

- one artifact mixes multiple source tables
- one artifact mixes extracted and estimated content
- one artifact combines multiple source vintages or scopes

This keeps provenance useful without turning it into cell-level bookkeeping.

## Page Convention

When both are known, record both:

- `printed_pages` for the page label shown in the report itself
- `pdf_pages` for the file/viewer page number

Use printed page as the primary human-facing citation. Do not guess missing page
values. Leave unknown fields blank and explain in `page_reference_notes` when
needed.

## Legacy Reconstruction vs New Estimation

`lineage_status` is where we distinguish:

- `confirmed`: source-to-artifact lineage is well supported and reviewed
- `partially_reconstructed`: source linkage is mostly understood, but some
  transformations or details remain to be tightened
- `legacy_unresolved`: current reviewed value can be reproduced, but upstream
  Reason-era logic or constants are not yet fully explained
- `estimated_documented`: artifact includes a new-plan estimation method that is
  fully specified and documented
- `runtime_only`: runtime/modeling artifact with no document-source claim
- `computed`: produced by a procedure such as calibration, not document-sourced

This prevents two different situations from being conflated:

- unresolved reconstruction of a legacy reviewed baseline
- fully documented estimation for a new plan

## Rate Terminology

When provenance notes discuss actuarial assumptions, keep these concepts
distinct:

- `discount rate assumption`: used to discount future cash flows to present values
- `investment return assumption`: used to project asset earnings

If a source uses the same numeric value for both, record that explicitly.
