# Shared External Sources

Use this folder for raw shared source materials used across more than one plan.

Examples:

- SOA mortality tables
- mortality improvement scales
- other standard actuarial reference tables
- approved external demographic references

Recommended process:

1. Put the raw source file here.
2. Add or update a row in:
   - [prep/common/source_registry.csv](/home/donboyd5/Documents/python_projects/pension_model/prep/common/source_registry.csv)
3. If full provenance is not yet available, record what you know and set
   `provenance_status` to `partial`.
4. When a reviewed shared table is created from the source, place it under:
   - [prep/common/reference_tables](/home/donboyd5/Documents/python_projects/pension_model/prep/common/reference_tables)

Minimum metadata to capture early, even if provenance is incomplete:

- a stable `source_id`
- local filename
- document or table name
- source organization
- version or publication year if known
- SHA-256 hash when available
- a short note on expected use

Important terminology:

- `investment return assumption` and `discount rate assumption` are distinct
- mortality basis names and full mortality-rate values are distinct
- improvement-scale name and full scale values are distinct

Do not wait for perfect provenance before staging a source here, but do not
leave provenance status ambiguous.
