# Data Preparation Goals

## Overview

In this phase we are developing methods for preparing a pension plan's runtime inputs from source documents, for use in a generalized pension model that we are developing. After we develop these methods we will use them to help us add new pension plans to the repo so that the model can run them.

Among other things this requires:

- developing a narrative description of each new pension plan and a description of relevant source documents
- developing a checklist that defines the inputs we need for the pension model -- demographic data, initial values, actuarial methods, funding methods, benefit rules, and all of the items that are required for the model
- assessing each new plan's available inputs against the checklist to identify what we have and what we need
- developing procedures for how we will fill gaps — sometimes we will fill them by looking again in source documents, sometimes by finding supplemental source documents, and sometimes by developing estimating methods that do the best they can with available plan data perhaps supplemented with data from the ACS or other sources
- to the extent we use estimating methods we prefer to have a library of methods that can be used for other plans and we prefer to use methods consistently across plans
- the provenance of all input data must be carefully and clearly identified

To help us develop these methods we are working with two known plans, the Florida Retirement System (frs) and the Texas Teachers Retirement System (txtrs), that were used in prior R models developed by a different organization, Reason. The input data for those plans was complete enough to run models but was not well documented. Our current exercise is to develop properly sourced data for new versions of these plans — frs-av and txtrs-av (the `av` suffix stands for actuarial valuation, which is the primary but not the only official source document). In this exercise we will only develop data for frs-av and txtrs-av that we can properly source from authoritative documents we have gathered for the plans, or that we can estimate from properly sourced data using methods that we will use consistently across plans — no ad hoc data and no one-off estimation methods.

> **The cardinal rule of this phase.** If we cannot find needed data for a
> plan, we will never simply take data from its Reason counterpart. We will
> look for better data or develop an estimating method. This may require
> human interaction.

Because frs and txtrs have some unsourced data and used some sub-optimal estimating methods, we expect our input data for frs-av and txtrs-av to differ slightly from the input data Reason developed for frs and txtrs. Still, we expect that when frs-av and txtrs-av are run through the pension model the results will be similar (but not identical) to those for frs and txtrs. We want to know these differences, which is why we recently added a Makefile capability that makes comparisons of scenarios and plans easier. Large differences will be caution flags.

We are currently focused on txtrs-av. After we prepare input data for txtrs-av to our satisfaction, we will do the same for frs-av, which will be more complicated.

We expect that when we are done with txtrs-av and frs-av we will have procedures and technical methods that will help us develop input data for additional plans.

The goal here is not just to develop properly sourced and documented input data for txtrs-av and frs-av — it is to establish a robust framework for future data-prep efforts.

This document is a project-level rule. Read it before starting any data-prep work, including small edits.

## Inputs and outputs

Data prep produces a plan's runtime inputs — `plan_config.json`, all CSV
files under `data/`, and the calibration file — from **authoritative source
documents**, primarily the plan's actuarial valuation (AV).

The output is the runtime input set under `plans/{plan}/`. The inputs to the
process are the source PDFs and reference tables under
`prep/{plan}/sources/` and `prep/common/sources/`.

## The cardinal rule

**Every value in a plan's runtime inputs must trace to a source document, or
to a documented estimation method.** No exceptions.

- Values from another plan (legacy or otherwise) are **not** a source. They
  may be a hint about what to look for in the AV. They are NEVER a value
  source.
- "I copied this from the legacy txtrs config" is not a source. If the AV
  publishes the value, transcribe it from the AV. If the AV does not, mark
  it missing or supply a documented estimation method.
- "Default value used in similar plans" is not a source.
- Silence is not a source. If we don't know where a value came from, that
  is a defect.

## Source hierarchy

For each plan:

1. **Actuarial valuation (AV)** — the source document.
2. **AV-referenced external sources** — tables, scales, or standards that
   the AV explicitly names (e.g., a published mortality table, an SOA
   improvement scale).
3. **Auxiliary documents** — ACFR, experience study, GASB report. Used only
   for estimation support, reconciliation, or clue-mining. They do not
   override the AV. A plan-specific review may justify a stronger role; it
   must be documented when it does.

The same hierarchy holds when an item is missing from the AV: look at
AV-referenced external sources before reaching for ACFR or experience study.

## Provenance is mandatory

Every required runtime input has a row in `prep/{plan}/input_checklist.csv`.
Every row records:

- where the value lives in the runtime
- status (`missing`, `partial`, `have`, `N/A`)
- source type (see vocabulary below)
- source document, printed page, PDF page, table or section
- method ID (when derived or estimated)
- notes (gaps, plug placeholders, issue references)

Free-text comment blocks inside `plan_config.json` (e.g., `source_notes`)
are not adequate provenance. They don't scale and they don't have a schema.
Migrate any provenance there into the input checklist.

## Source-type vocabulary

These are the only valid values for `source_type`:

- `AV-direct` — transcribed from a specific page/table of the AV.
- `AV-derived` — built from AV data through a documented transform
  (e.g., band-to-point active grid).
- `AV-referenced-external` — value comes from an external table the AV
  explicitly names (e.g., PubT-2010(B) mortality, Scale UMP 2021).
- `plan-admin-direct` — value transcribed from an authoritative
  plan-administrator publication that is not the AV: a member benefits
  handbook published by the plan, an official member-facing page on the
  plan's website, the plan administrator's published rules, or a
  governing statute the plan administrator implements verbatim. Used when
  the AV does not state the value but the plan administrator does, in a
  publication intended for plan members or the public. Treated as nearly
  equal to `AV-direct` in reliability but recorded distinctly so we can
  see what's not in the AV. The source must be cited with URL or
  document title plus printed-page or PDF-page reference.
- `estimated` — produced by a documented method registered in
  `prep/common/methods/method_registry.md` because no source publishes the
  value. Prefer reusing an existing registered method over creating a new
  one. Create a new method only when an existing one cannot fit — typically
  because the plan has a feature that no current method handles. The
  rationale must be recorded in the method registry.
- `computed` — produced by a procedure inside this repo (e.g., calibration).
- `runtime-only` — a model-engine choice with no plan-document analog. Used
  only for true engine settings (cohort grid bounds, projection horizon,
  class group labels). **Not a parking spot for unverified values.**

Estimating methods may consult supplemental data sources such as the
American Community Survey (ACS), prior valuations, or other public data.
These supplements are inputs to a method; they are **not** sources of value
in their own right and never qualify a row as `AV-direct` or
`AV-referenced-external`.

## What is not a valid source

- "Same value as legacy txtrs" / "same value as legacy frs"
- "Carried over from the existing config"
- "Default value used in similar plans"
- "Common practice for this kind of plan"
- "It worked when we ran the model"

If a value cannot be traced to one of the source-type categories above, its
status is `missing`. The note may record what we suspect — for example,
"legacy txtrs sets this to X; AV provenance unknown; verify against AV
narrative" — but the status remains `missing` until the AV (or another
authoritative source) is read and the value is confirmed.

## When the AV does not publish a value

Three valid responses:

1. **Look at AV-referenced external sources** for the value. If found,
   record as `AV-referenced-external`.
2. **Estimate** with a documented method. Record as `estimated` and reference
   the method ID. The method must explain its assumptions and limits.
3. **Mark `missing`** and note what is needed to fill the gap.

Do not invent a value. Do not import a value from another plan as a stopgap.

## New-plan workflow

For each new plan:

1. Copy `prep/common/input_checklist_template.csv` to
   `prep/{plan}/input_checklist.csv`.
2. For each row, locate the value in the AV. Record source, page, table.
3. For rows the AV does not publish, decide between AV-referenced external,
   estimated method, or missing. Record the decision.
4. Build the runtime inputs (`plan_config.json` and CSVs) only from rows
   that are `have` or `partial`. `missing` rows are tracked openly; they
   are not silently filled with values from another plan.
5. Track open gaps in the markdown view of the checklist
   (`prep/{plan}/reports/input_checklist.md`) and in GitHub issues.

This workflow generalizes. Plan-specific judgment is required for what
counts as a satisfying source for a given row, but the workflow shape does
not change.

## Multi-cut philosophy

A first cut for a new plan represents the main plan structure, stays close
to AV treatment, and produces a usable canonical input set. Later cuts add
secondary detail and reduce reliance on proxies or heavy calibration.

Documented gaps are explicit, not forgotten. A gap that survives the first
cut is recorded — in the input checklist and in an issue — not buried.

## Validation expectations

Data-prep work for an AV-first plan is **not** a Match-R exercise. The data
will differ slightly from the legacy Reason build, so model results will
differ slightly. We expect:

- frs-av results to be similar to (but not identical to) frs results.
- txtrs-av results to be similar to (but not identical to) txtrs results.
- Large differences are caution flags and must be investigated and explained
  before the plan is considered ready.

Same model, different data. The pension model itself is a **single general
model**. We do not introduce a new modeling method for an AV-first plan.
Whatever runs frs runs frs-av; whatever runs txtrs runs txtrs-av. Pair
differences come from data only — sourced AV-first inputs vs. legacy Reason
inputs — not from changes in the model engine, decrement logic, funding
math, or smoothing rules. If a difference seems to require a model change,
that is a separate decision and a separate issue, not part of AV-first data
prep.

Comparison tooling. Use the comparison capability in the repo Makefile to
diff scenarios and plans (e.g., frs vs. frs-av, txtrs vs. txtrs-av) and to
surface where the differences come from.

## What this is not

- Not a procedure for porting legacy plans. Legacy plans (txtrs, frs) are
  reference runs whose behavior we want to approximate. Their config and CSV
  values are not authoritative sources for AV-first plans.
- Not optional. If a value enters runtime inputs without provenance, it is
  a defect to be removed or back-filled. Open an issue and fix it; do not
  let it sit.

## Cleanup standard

When a value is found in a plan's runtime inputs without source provenance:

1. Mark the corresponding row in `input_checklist.csv` as `missing` (or
   `partial / source-unverified` if the value is plausible but not yet
   confirmed).
2. Add a note recording what is known (e.g., "legacy txtrs sets this to
   gain_loss with 4-year recognition; AV provenance to be verified").
3. Open or reference a GitHub issue (`phase-anytime`) to verify the value
   against the AV.
4. Do not remove the value from the runtime config if doing so breaks the
   model run, but do not treat the existence of the value in config as
   evidence of provenance.

## Why this matters

The pension model's credibility rests on each plan's inputs being traceable
to authoritative sources. A model that reproduces R numbers but cannot
defend where its inputs came from is not a research tool — it is a black box
with the wrong claims attached. AV-first prep is what separates this repo
from a port.
