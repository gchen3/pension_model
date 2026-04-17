# Common Prep Area

`prep/common/` holds upstream prep assets that are shared across plans.

Use this area for:

- shared source registries and schemas
- common external reference documents, such as SOA mortality tables
- reviewed shared reference tables derived from those sources
- shared validation checks
- shared estimation methods
- shared build/export utilities

Recommended usage:

- raw shared source documents: `sources/`
- reviewed shared tables derived from those sources: `reference_tables/`
- shared schema and registry specs: `schemas/`
- shared validation logic and check specs: `checks/`
- shared estimation methods: `methods/`
- shared build/export logic or specs: `build/`
- shared reports: `reports/`

This area is upstream prep only. Runtime inputs still belong under `plans/{plan}/`.
