# Source Registry Schema

## Purpose

The source registry records every document or external reference source used in
the input-preparation workflow.

It is the first provenance layer.

Use:

- `prep/{plan}/source_registry.csv` for plan-specific sources
- `prep/common/source_registry.csv` for shared external references used across plans

## Required Columns

| Column | Meaning |
| --- | --- |
| `source_id` | Stable identifier within the registry, such as `AV_2022`, `ACFR_2023`, or `SOA_PUB2010_GENERAL_EMPLOYEE`. |
| `scope` | `plan` or `common`. |
| `plan_or_group` | Plan code such as `frs` or `txtrs`, or `common` for shared sources. |
| `document_title` | Full source title when known. |
| `document_type` | Short type such as `av`, `acfr`, `gasb`, `experience_study`, `mortality_table`, `improvement_scale`, `statute`, `other`. |
| `report_year` | Main year associated with the document, such as valuation year or fiscal year. |
| `valuation_date_or_fy_end` | More precise period marker when known, such as `2022-07-01` or `2023-06-30`. |
| `local_path` | Repo-relative path to the stored file. |
| `sha256` | SHA-256 hash of the stored file when available. |
| `official_status` | `official_original`, `official_renamed_local_copy`, `official_derivative`, `external_reference`, or `unknown`. |
| `selected_for` | Why this source was chosen, such as `matches_reviewed_baseline`, `latest_official_available`, `shared_reference`, `gap_fill`, `other`. |
| `source_precedence_rank` | Default precedence rank within a plan or common source set. Lower means higher precedence. |
| `source_unit_notes` | High-level note on source units if relevant, especially for monetary tables reported in thousands or millions. |
| `origin_url` | Source URL when known. May be blank until provenance is complete. |
| `original_filename` | Original filename when known, even if the local file has been renamed. |
| `local_filename` | Stored local filename. |
| `filename_policy` | `original`, `canonical_local`, or `unknown`. |
| `expected_use` | What this source is expected to supply, such as `plan provisions`, `active membership`, `mortality basis`, `funding targets`. |
| `notes` | Free-form notes, including provenance gaps or usage cautions. |
| `provenance_status` | `complete`, `partial`, `needs_review`, or `missing`. |

## Terminology Precision

When a source document mentions both investment earnings on assets and
present-value discounting, keep the terms separate in notes and downstream
artifacts:

- `investment return assumption`: used to project asset earnings
- `discount rate assumption`: used to discount future cash flows to present values

If a source uses the same numeric value for both, record that explicitly rather
than collapsing the concepts.

## Notes

- The registry is document-level provenance, not table-level provenance.
- It is acceptable to leave `origin_url`, `original_filename`, or some status
  fields blank initially, as long as `provenance_status` reflects that the
  record is incomplete.
- Shared external references such as SOA mortality tables belong in the common
  registry, not in a single plan registry.
- Page citations belong in artifact provenance, not the source registry. When
  artifact provenance cites pages, it should distinguish printed pages from
  PDF/electronic pages.
