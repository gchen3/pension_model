# Input Preparation Workplan

## Purpose

This document lays out a concrete workplan for upstream input preparation for `pension_model`.

The immediate pilot goal is:

- determine whether we can reproduce the current canonical stage-3/runtime inputs for FRS and TXTRS from source PDFs rather than from Reason's extracted spreadsheets and hard-coded work
- do so in a way that is traceable, repeatable, and generalizable to future plans

The longer-run goal is:

- build a prep system that can turn idiosyncratic pension reporting into consistent model inputs for a general pension model

## Current Boundary

The current runtime boundary remains:

``` text
plans/{plan}/config/
plans/{plan}/data/
plans/{plan}/baselines/
```

Those are the published runtime artifacts the model consumes.

Upstream input preparation should live outside that boundary so the distinction stays clear:

- `plans/` stays the top-level runtime folder
- `prep/` should become the top-level folder for upstream source handling, extraction, normalization, estimation, validation, and build machinery

Proposed top-level split:

``` text
plans/
  frs/
    config/
    data/
    baselines/
  txtrs/
    ...

prep/
  common/
    schemas/
    checks/
    methods/
    build/
    reports/
  frs/
    sources/
    extracted/
    normalized/
    estimated/
    reports/
  txtrs/
    ...
```

## Decisions Already Made

The following are treated as settled for planning purposes:

- Primary acceptance for input preparation is exact reproduction of the canonical stage-3/runtime inputs.
- End-to-end model runs are secondary guardrails, used occasionally rather than as the main prep test.
- All canonical monetary outputs are stored in dollars. If a source reports values in thousands or millions, prep must scale them to dollars explicitly.
- `discount rate` and `investment return assumption` are distinct concepts and must be documented precisely. They may have the same numeric value in a plan, but prep should not treat the terms as interchangeable.
- New-plan prep should begin with a narrative analysis of the pension plan itself, based on the AV and other documents. See `New-Plan Narrative Analysis` below for the required scope and outputs.
- New-plan prep must include a source sufficiency and gap report: what the AV and ACFR provide, what can be derived, and what remains missing.
- New-plan integration should proceed in multiple cuts. Start with a simpler, AV-faithful representation that can produce a usable canonical input set, then add plan-specific detail in later passes as source support and model value justify it.
- Provenance must be tracked for all data. In general, document plus page and/or table is enough. Cell-level lineage is not the default.
- Provenance page citations must distinguish `printed page` from `PDF/electronic page`. Printed page should be the primary human-facing citation when available, and PDF page should also be recorded when practical.
- Some required inputs may be judgmental, derived, or estimated rather than directly sourced.
- Estimation methods should be shared across plans when the missing-data pattern is the same.
- Legacy unresolved Reason logic and new-plan estimation are different cases and must be documented differently.
- Calibration is a computed artifact used to match the actuarial valuation. It is not document-sourced.
- AV and ACFR PDFs alone may not be sufficient for all required inputs.
- For FRS and TXTRS, source selection should prioritize the document vintages used by the reviewed R-model baselines, not necessarily the latest available reports.
- For new plans, source selection should generally start with the latest available official documents unless there is a specific reason to use an older vintage.
- Within a plan, the actuarial valuation should generally be treated as the authoritative source, but ACFRs and related accounting documents may help fill gaps when used carefully and explicitly.
- For new plans, prep should adhere to actuarial-valuation treatment as much as possible. If a prep rule departs from AV treatment, the departure should be explicit, justified, and documented as a modeling or estimation choice rather than treated as if it were source-direct.
- Similar concepts reported in AVs and ACFRs may legitimately differ because of scope, terminology, accounting rules, actuarial rules, or measurement date differences.
- The job of prep is to build consistent model input data from inconsistent and idiosyncratic source reporting.

## Immediate Pilot

The first pilot is narrow and concrete:

- FRS
- TXTRS

The pilot question is:

``` text
Can we reproduce the current reviewed stage-3/runtime inputs for FRS and TXTRS
from source PDFs alone, or identify precisely what cannot be recovered from
those PDFs and why?
```

Success for the pilot does not require a new runtime architecture. It requires:

- a documented source inventory
- a documented data-requirements inventory
- a documented have-versus-need gap report
- a reproducible path from sources to canonical stage-3 artifacts
- validation that the built artifacts match the current canonical stage-3 data

Current pilot source set:

- FRS:
  - `Florida FRS Valuation 2022.pdf`
  - `2022-23_ACFR.pdf`
  - `2023_GASB68_TOC.pdf`
- TXTRS:
  - `Texas TRS Valuation 2024.pdf`
  - `Texas TRS ACFR 2023.pdf`

These are the current pilot documents because the immediate goal is to reproduce
the reviewed baselines that were anchored to the sources used by Reason. For new
plans, the default should usually be the latest official source set instead.

## New-Plan Narrative Analysis

New-plan prep should begin with a narrative analysis of the pension plan itself.

This should happen before detailed source coverage and gap reporting, because it
establishes what kind of plan we are dealing with, what kinds of inputs the
model will likely need, and where the likely mismatches between reported data
and required canonical inputs will arise.

At minimum, the narrative analysis should cover:

- overall structure of the plan, such as DB-only, DB plus DC, cash balance, or hybrid
- key characteristics of each benefit structure, including member counts where available
- member classes, groups, and tiers
- overview of how benefits are calculated
- key actuarial assumptions
- overview of actuarial tables used

The narrative analysis should not be purely descriptive. It should also identify:

- likely runtime benefit types and features the model will need to represent
- likely classes and tiers for runtime inputs
- likely decrement, mortality, retiree-distribution, and funding inputs
- likely source gaps, ambiguities, and judgment points
- any plan features that may pressure the current runtime contract
- what will be modeled directly
- what will be excluded from direct modeling
- what may be approximated because it is too small, too rare, not separately
  reported, or not material enough to model directly

Each narrative should therefore include an explicit section on:

- modeled scope
- exclusions
- simplifications
- why each exclusion or simplification was made

These scope choices are not assumed to be permanent.

In some plans, the right practical sequence will be:

1. start with a simpler representation
2. rely more heavily on calibration to hit reviewed valuation targets
3. add structural detail over time as source support, validation evidence, and
   modeling value justify it
4. reduce reliance on calibration as more plan-specific structure is modeled

This should be treated as the default onboarding strategy for new plans:

- first cut:
  - represent the main plan structure
  - capture the dominant member groups and benefit rules
  - stay as close to AV treatment as possible
  - produce the required canonical inputs in the form the runtime expects
  - avoid premature complexity
- later cuts:
  - add secondary member groups, rare elections, finer class splits, and more
    detailed source-driven structure where that detail materially improves the
    model
  - reduce reliance on broad proxies or calibration where the source support is
    strong enough to do so

So the prep record should distinguish between:

- `current exclusion`
- `current simplification`
- `candidate future inclusion`

An early exclusion may therefore be a temporary scope decision rather than a
final statement that the feature will never be modeled.

This is important for both old and new plans. A useful prep narrative should
not only explain the plan; it should explain the modeling boundary we are
choosing within that plan.

## Early Architecture Gate

Before building the prep pipeline in earnest, we should review whether the current runtime data contract is the right target.

This needs to happen early because a bad target structure will make prep harder and more brittle.

Questions for the early review:

- Should runtime inputs remain organized primarily as per-class files, or move toward more stacked tables with explicit identifier columns?
- Does `plan_config.json` currently mix too many concerns?
- Should document-sourced values, runtime/modeling choices, and computed artifacts be separated more clearly?
- Do funding seed data and valuation targets belong in cleaner separate artifacts?
- Does the current structure generalize beyond FRS and TXTRS without awkward exceptions?

The review should end with one of three decisions:

1.  Keep the current runtime contract as-is for now and treat it as `v1`.
2.  Make a small number of targeted runtime-contract changes before prep work begins.
3.  Keep the runtime contract stable for now, but define a cleaner prep-canonical structure upstream of it.

Bias:

- prefer stability unless there is a strong case for changing the runtime contract now
- make the decision consciously and early, not accidentally later

## Core Prep Principles

- Be strict at the canonical-output edge and flexible at the source-facing edge.
- Preserve actuarial structure where possible rather than flattening it away.
- Never silently estimate or silently normalize units.
- Never blur `legacy unresolved reconstruction` and `new estimation`.
- Never silently resolve AV-versus-ACFR differences. Differences should be classified and documented.
- Every published prep artifact should be reviewable and reproducible.
- Keep shared logic out of plan-specific folders.
- Keep runtime inputs behavior-preserving unless and until a separate approved change is made.

## Shared Knowledge Capture

Reverse-engineering work on FRS and TXTRS should be treated as an investment in
the future prep system, not just as plan-specific archaeology.

So as useful knowledge is discovered, it should be promoted out of plan-specific
notes into shared artifacts under `prep/common/` and `docs/`.

At minimum, the repo should preserve:

- reusable source-faithful transform methods
- reusable legacy-reconstruction patterns that reveal common prep risks
- reusable estimation methods
- reusable validation and reconciliation checks
- provenance conventions
- runtime build rules
- cross-plan lessons learned
- first-year cash-flow treatment rules when observed year-0 inputs are broader
  than the later-year modeled benefit concept
- mortality review rules that separate missing external source tables from
  ambiguity about how the named improvement scale or convergence rule should be
  implemented

Recommended shared homes:

- `prep/common/methods/method_registry.md`
- `prep/common/checks/consistency_check_catalog.md`
- `prep/common/build/current_stage3_build_rules.md`
- `prep/common/reports/cross_plan_lessons.md`

Plan-specific evidence should still remain in `prep/{plan}/reports/`, but the
generalizable method and design knowledge should be committed as shared repo
artifacts so it can guide prep for new plans.

## Required Prep Layers

The prep system should have five layers:

1.  `sources`
2.  `extracted`
3.  `normalized`
4.  `estimated`
5.  `built`

Target flow:

``` text
source PDFs and supporting docs
  -> extracted source tables
  -> normalized reviewed prep artifacts
  -> derived / estimated artifacts when needed
  -> built canonical stage-3/runtime inputs
  -> validation and reports
```

### 1. Sources

Each plan should maintain a source registry covering all documents used:

- AV PDF
- ACFR PDF
- experience studies if needed
- statute or plan document excerpts if needed
- external reference sources if later approved

Shared external reference sources that apply across plans should live under:

- `prep/common/sources/`
- `prep/common/reference_tables/`

Examples include:

- SOA mortality base-table workbooks
- SOA mortality improvement scales
- other standard tables reused across plans

For each source document record:

- source document ID, such as `AV_2024`
- full title
- valuation or fiscal year
- file path or external location
- document hash if practical
- notes on what the document is expected to supply

The source registry should also record:

- whether the document is an official source document, an officially published derivative, or a renamed local copy of an official document
- whether the document was chosen because it matches a reviewed historical baseline or because it is the latest available official document
- whether the stored filename is the original filename or a local canonical filename

Mortality is the first active example of this shared-source pattern. The current
pilot already relies on shared SOA references under `prep/common/sources/` for
FRS, and likely for part of TXTRS as well.

### Page-reference convention

When provenance records cite pages, they should identify page type explicitly:

- `printed page`: the page label printed in the report itself, such as `C-4`,
  `A-5`, or `205`
- `PDF/electronic page`: the viewer or file page number used by PDF tools

Default rule:

- use printed page as the primary citation when available
- also record PDF/electronic page when practical
- if only one is known, record that and leave the other blank rather than
  guessing

This matters because actuarial valuations and ACFRs often have front matter,
appendices, and internal page labels that do not align with PDF page offsets.

### Source precedence within a plan

Default precedence when similar concepts appear in multiple documents:

1. actuarial valuation
2. ACFR
3. other related official documents such as GASB reports
4. approved external reference sources when explicitly needed

This is only a default. Prep must still document why a particular source was
used for a particular quantity.

### Legacy unresolved reconstruction vs new estimation

These two situations must be handled separately.

#### Legacy unresolved reconstruction

This applies when the current reviewed baseline contains a value or rule that
can be reproduced but not yet fully explained from source documents.

Documentation should record:

- the runtime value or rule
- the evidence currently supporting it
- candidate reconstruction methods tested
- whether each candidate succeeded, partially matched, or failed
- what remains unknown

These items should remain explicitly marked as unresolved rather than presented
as confirmed source lineage.

#### New-plan estimation

This applies when a new plan does not publish a required input and we choose to
fill the gap with an approved method.

Documentation should record:

- the exact method used
- the exact inputs used
- the exact parameters and constants used
- why estimation was necessary
- diagnostics, checks, and validation results

New-plan estimation should always be fully specified, even when legacy
reconstruction remains partly unresolved.

### Handling legitimate AV-versus-ACFR differences

Prep should assume that AV and ACFR values for similar concepts may differ for
legitimate reasons, including:

- different scope of the covered plan or system
- different terminology
- different measurement date
- different actuarial versus accounting rules
- different recognition or smoothing methods

Prep should therefore not treat every difference as an error. Instead, the
workflow should classify differences into categories such as:

- same concept, same measurement basis
- same concept, different measurement basis
- related but not identical concept
- terminology difference requiring dictionary mapping

The actuarial valuation should generally be treated as authoritative, but other
documents may be used to fill gaps, sometimes with simple scaling or bridging
methods, when that is explicitly documented and reviewable.

### Term dictionary and concept mapping

Prep should maintain a small working dictionary of major terms and their likely
relationships across actuarial and accounting documents.

Examples:

- UAAL or unfunded actuarial accrued liability
- NPL or net pension liability
- actuarial accrued liability
- total pension liability
- actuarial value of assets
- fiduciary net position

This dictionary should not assume exact equivalence. It should explain how terms
are related, where they differ, and which one maps to which runtime or prep
concept.

### Source filename policy

One early operating decision is whether to:

- preserve original filenames exactly as obtained from source websites, or
- adopt a local canonical naming system

Current bias:

- prefer a local canonical naming system for consistency across plans

But this creates an additional provenance obligation:

- the source registry must preserve the original document title and original
  filename when known
- any local canonical filename must map back to the original source identity

This decision does not need to be finalized immediately, but the workplan should
treat it as an explicit operational choice rather than letting naming drift ad hoc.

### 2. Extracted

These are raw extracted tables from source documents.

They should preserve source structure rather than runtime structure.

Each extracted artifact should record:

- source document ID
- page number
- table or exhibit label
- source units
- extraction method
- review status

### 3. Normalized

These are reviewed domain tables in consistent forms suitable for later build steps.

Examples:

- active salary/headcount tables
- salary growth assumptions
- termination assumption tables
- retirement assumption tables
- early-retirement reduction tables
- retiree distributions
- valuation targets
- funding seed data
- plan-rule metadata

These artifacts should preserve actuarial meaning even when the final runtime format is different.

### 4. Estimated

This layer exists only when required inputs cannot be obtained directly or derived from source documents alone.

Every estimated artifact must identify:

- whether it is derived, estimated, or a manual override
- method ID
- method version
- inputs used
- plan-specific parameters if any
- diagnostics and review notes

Estimation hierarchy:

1.  direct from plan documents
2.  derived from plan documents
3.  estimated from plan-specific published data
4.  estimated from approved external reference sources

For FRS and TXTRS, the pilot assumption is that we should not need external borrowing unless the gap report proves otherwise.

### 5. Built

These are the published canonical artifacts written to `plans/{plan}/`.

For now, this means exact reproduction of the current runtime contract, unless the early architecture gate approves changes.

## Provenance Model

Provenance should be first-class.

Default provenance grain:

- artifact-level provenance

That means a reviewed prep artifact should normally be traceable to:

- source document ID
- document year
- page
- table/exhibit label
- source units
- extraction or derivation method

Use finer-grained provenance only when an artifact mixes multiple source tables or methods.

For computed artifacts such as calibration:

- provenance is computational lineage, not document lineage
- link to the stage-3/runtime inputs used
- link to the valuation targets used
- record method/version and run metadata

## Unit Rules

Monetary values:

- canonical prep outputs and runtime outputs must be in dollars
- source units must be explicit
- scaling to dollars must be explicit and reviewable

Non-monetary values:

- headcounts remain counts
- ages and YOS remain integer values
- rates and percentages must use the canonical numeric form the runtime expects

Unit handling rules:

- never guess units
- flag mixed-unit tables
- reconcile totals after scaling

## Coverage and Gap Reporting

Every plan should have a source coverage matrix mapping requirements to sources.

For each required stage-3 or runtime artifact, assign one of:

- `direct_from_av`
- `direct_from_acfr`
- `derived_from_av_acfr`
- `referenced_not_published`
- `missing_from_pdfs`
- `runtime_only_or_modeling_choice`
- `computed`

Every plan should also have a gap report that answers:

- what we have
- what we can derive
- what we do not have
- what is judgmental
- what requires estimation
- what cannot be recovered from the PDFs alone

## Validation Model

Validation should happen at several levels.

### Source-table integrity checks

- row totals match detail rows
- column totals match detail columns
- grand totals reconcile
- percentages and rates sum correctly where expected
- no silent missing cells in required ranges

### Cross-table consistency checks

- total active headcount from headcount tables agrees with reported totals where applicable
- payroll from salary/headcount data reconciles to reported payroll targets where applicable
- retiree distributions reconcile to reported retiree counts and benefit totals
- class totals reconcile to plan totals
- AV and ACFR values agree where they should, or differences are documented

### Domain checks

- ages and YOS within valid ranges
- rates within valid ranges
- monotonic or shape checks where actuarially expected
- required identifiers and lookup types present

### Artifact checks

- schema and column checks
- provenance completeness checks
- unit normalization checks
- explicit status for extracted, derived, estimated, or computed values

### Primary acceptance checks

- built canonical outputs match current stage-3/runtime artifacts exactly, or with explicitly documented tolerances where unavoidable

### Secondary guardrails

- occasional end-to-end model runs for FRS and TXTRS
- milestone checks when runtime loaders or the runtime contract change

## Shared Versus Plan-Specific Logic

Shared logic belongs in `prep/common/`:

- source manifest schemas
- coverage and gap report generation
- unit normalization
- consistency checks
- shared estimation methods
- build/export utilities

Plan-specific logic belongs in `prep/{plan}/`:

- source manifests
- source-specific extraction specs
- plan-specific page/table mappings
- plan-specific parameters and overrides
- plan-specific reports and unresolved issues

Avoid copying shared logic into each plan folder.

## Workplan Phases

## Phase 0: Freeze and Describe the Current Runtime Contract

Goal:

- create a precise written inventory of what the runtime currently needs

Tasks:

- list every required artifact under `plans/{plan}/config/` and `plans/{plan}/data/`
- record required columns, units, keys, and optional files
- distinguish document-sourced values, runtime/modeling values, and computed values
- define exact comparison rules for stage-3 equivalence

Deliverables:

- runtime input contract spec
- exact stage-3 equivalence rules

Exit criteria:

- we can state exactly what must be reproduced for FRS and TXTRS

## Phase 1: Early Runtime-Contract Review

Goal:

- decide whether the current runtime structure should change before prep is built

Tasks:

- review the current runtime contract against likely multi-plan needs
- identify any high-value structural changes worth making early
- decide whether to freeze the current contract as `v1`

Deliverables:

- short architecture decision memo

Exit criteria:

- explicit decision to keep, adjust, or separate the runtime contract

## Phase 2: Define Prep Governance Artifacts

Goal:

- define the common artifacts and metadata the prep system will require

Tasks:

- define source registry format
- define provenance fields
- define coverage matrix format
- define gap report format
- define artifact status categories
- define unit-normalization rules

Deliverables:

- prep metadata spec
- source naming and source-registry conventions
- concept dictionary / terminology-mapping conventions

Exit criteria:

- common prep artifacts and terminology are fixed

## Phase 3: Narrative Plan Analysis

Goal:

- produce a structured narrative understanding of the plan before detailed extraction design begins

Tasks:

- read the AV and any immediately relevant supporting documents
- summarize plan structure and benefit types
- summarize classes, groups, and tiers
- summarize benefit formulas at a level sufficient to reason about runtime inputs
- summarize key actuarial assumptions and actuarial tables
- identify likely input implications, likely gaps, and likely judgment points

Deliverables:

- narrative plan analysis template/spec
- FRS narrative plan analysis
- TXTRS narrative plan analysis

Exit criteria:

- we have a written understanding of what kind of plan is being modeled and what that implies for prep and runtime inputs

## Phase 4: FRS and TXTRS Source Sufficiency Review

Goal:

- determine what AV and ACFR PDFs alone can and cannot provide

Tasks:

- inventory the source PDFs for FRS and TXTRS
- record why those vintages were selected for the pilot
- catalog relevant pages and tables
- map each runtime requirement to source coverage status
- identify missing or ambiguous requirements
- classify major AV-versus-ACFR differences rather than treating them as automatic conflicts

Deliverables:

- FRS source registry
- TXTRS source registry
- FRS coverage matrix and gap report
- TXTRS coverage matrix and gap report

Exit criteria:

- we have a documented have-versus-need report for both pilot plans

## Phase 5: Define Normalized Prep Schemas

Goal:

- establish reviewed plan-independent structures for extracted and normalized data

Tasks:

- define normalized tables for demographics
- define normalized tables for decrements
- define normalized tables for retiree distributions
- define normalized tables for valuation and funding seed data
- define normalized tables for plan rules where needed

Deliverables:

- normalized prep schema spec

Exit criteria:

- we can describe the reviewed prep layer independent of any one plan

## Phase 6: Define Shared Validation Checks

Goal:

- make validation systematic rather than ad hoc

Tasks:

- define source-table integrity checks
- define cross-table consistency checks
- define schema and provenance checks
- define exact stage-3 equivalence checks
- define when end-to-end model checks are required

Deliverables:

- consistency-check catalog

Exit criteria:

- validation rules are explicit and reusable

## Phase 7: Define Shared Estimation Methods

Goal:

- create a disciplined method library for recurring missing-data patterns

Tasks:

- identify likely recurring gaps
- classify which are estimable and which are not
- define method IDs and versioning rules
- define method inputs, outputs, assumptions, and diagnostics
- define backtesting expectations

Deliverables:

- shared estimation-method registry

Exit criteria:

- estimation is governed and reusable rather than plan-by-plan improvisation

## Phase 8: Pilot FRS and TXTRS PDF-to-Stage-3 Reproduction

Goal:

- test whether the pilot plans can be rebuilt from source PDFs

Tasks:

- build plan-specific extraction and normalization workflows for FRS
- build plan-specific extraction and normalization workflows for TXTRS
- use shared checks and shared methods where applicable
- build canonical stage-3/runtime outputs
- compare built outputs to the committed canonical artifacts

Deliverables:

- FRS PDF-to-stage-3 reproduction report
- TXTRS PDF-to-stage-3 reproduction report

Exit criteria:

- exact match to canonical stage-3/runtime inputs, or a precise documented list of irrecoverable gaps and why they exist

## Phase 9: Add Ongoing Acceptance and Maintenance Routines

Goal:

- make prep reviewable and maintainable over time

Tasks:

- define acceptance routines for future plans
- define when guardrail end-to-end checks run
- define review expectations for new estimation methods
- define update procedures when a new AV or ACFR is published

Deliverables:

- ongoing prep maintenance checklist

Exit criteria:

- the prep system is usable for future plans, not only for the pilot

## Deliverables Summary

The workplan should ultimately produce at least these documents and artifact classes:

- runtime input contract spec
- runtime-contract review memo
- narrative plan analysis template/spec
- source registry spec
- provenance spec
- source naming convention
- term dictionary / concept mapping guidance
- source coverage matrix spec
- gap report spec
- normalized prep schema spec
- consistency-check catalog
- shared estimation-method registry
- FRS narrative plan analysis
- TXTRS narrative plan analysis
- FRS pilot gap report
- TXTRS pilot gap report
- FRS reproduction report
- TXTRS reproduction report

## Major Risks

- AV and ACFR PDFs may not contain enough detail for exact stage-3 reconstruction.
- Some current runtime inputs are already judgmental, derived, or shaped by prior modeling choices.
- Estimation methods can become ad hoc if not governed by shared specs and method versioning.
- The current runtime contract may be serviceable for FRS and TXTRS but awkward for future plans.
- Exact comparison requires precise rules for units, scaling, rounding, missing values, and identifier ordering.

## Open Questions

- Should the runtime contract change now, or should we freeze it and build prep against it first?
- Which current runtime artifacts are genuinely document-sourced, and which are better understood as model-shaping choices?
- Which missing-data patterns deserve shared estimation methods first?
- What minimum source set, beyond AV and ACFR, should be considered acceptable for a new plan when the PDFs are insufficient?
- How much provenance detail is enough for mixed-source normalized artifacts?

## Recommended Next Step

Start with Phase 0, Phase 1, and Phase 3 design artifacts before any extraction implementation:

- document the current runtime data contract exactly
- decide whether that contract should change before prep work is built
- define the narrative plan analysis template and use it to frame FRS and TXTRS

That gives the prep effort a stable target and reduces the risk of building a careful upstream pipeline against the wrong downstream structure.
