# Runtime Contract Review

## Purpose

This memo frames the early review of the current runtime input contract.

The question is not whether the current contract works for FRS and TXTRS today.
It does. The question is whether it is the right downstream target to build the
next phase of upstream input preparation around.

## Decision To Make

Before building a substantial prep pipeline, decide one of:

1. keep the current runtime contract as `v1`
2. make a small number of targeted runtime-contract changes now
3. keep the current runtime contract stable, but define a cleaner prep-canonical
   layer upstream of it

The default bias should be conservative:

- keep the runtime contract stable unless there is a clear high-value reason to
  change it now

## What Is Good About the Current Contract

- It is concrete and already exercised by two plans.
- The runtime boundary is conceptually clear: canonical inputs live under
  `plans/{plan}/`.
- The loader already handles both multi-class and single-class patterns.
- Calibration is already separated into its own file, which is structurally good.
- The contract is good enough to support a first prep pilot without redesigning
  the runtime first.

## Why Review It Anyway

The prep effort will make the downstream target more important than before.

If the target contract is awkward, the prep system will absorb that awkwardness.
That is acceptable for a short pilot, but it is expensive if it becomes the
long-run operating model for many plans.

## Main Review Questions

### 1. Per-class files versus stacked runtime tables

Current pattern:

- many files such as `{class}_salary.csv` and `{class}_termination_rates.csv`

Review question:

- is that still the right runtime structure for a broader multi-plan model, or
  should runtime eventually prefer fewer stacked tables with explicit identifier
  columns?

### 2. Mixed concerns inside `plan_config.json`

Current pattern:

- source-linked values, runtime/modeling settings, and compatibility choices all
  live in one config document

Review question:

- should those concerns be separated more cleanly before prep work depends on them?

### 3. Source-linked values versus computed artifacts

Current pattern:

- calibration is separate, which is good
- valuation-linked targets and runtime settings still live together in config

Review question:

- is the boundary between source-linked and computed/runtime artifacts clear
  enough for long-run maintenance?

### 4. Runtime fallback logic versus one canonical shape

Current pattern:

- loaders accept multiple filenames and a few legacy variants

Review question:

- should the long-run runtime contract expose one stricter canonical shape even
  if the loader continues to accept compatibility variants?

### 5. Provenance and unit handling

Current pattern:

- runtime files do not carry prep provenance
- units are handled by convention rather than by explicit runtime metadata

Review question:

- should provenance remain an upstream-only concern, or does the runtime
  contract need some clearer hooks or conventions to support it?

## Criteria For Changing The Contract Now

Change the runtime contract now only if most of the following are true:

- the change materially reduces long-run prep complexity
- the change materially improves multi-plan generality
- the change can be made without threatening exact reproduction of current results
- the change is small enough to validate carefully
- the change is better done before prep workflows are built around the current shape

If those conditions are not met, the better choice is usually:

- freeze the current runtime contract as `v1`
- build prep against it
- revisit runtime restructuring after the prep pilot

## Likely Conservative Path

Based on the current repo state, the likely conservative path is:

- keep the current runtime contract stable for the initial prep pilot
- define a cleaner upstream prep layer with provenance, coverage analysis,
  estimation methods, and validation
- use the pilot to learn where the current runtime contract is genuinely painful
- revisit runtime structure after that evidence exists

## What Evidence Would Justify Reconsideration

The following would be strong signals that the runtime contract should change sooner:

- repeated awkward plan-specific exceptions in prep just to satisfy runtime naming
- repeated need to duplicate the same source-linked concept across multiple runtime files
- inability to express important cross-plan structures cleanly
- confusion caused by mixed responsibilities inside `plan_config.json`
- high maintenance burden from per-class file proliferation

### Current Concrete Example: Mortality

Mortality is now the clearest concrete example of contract pressure.

- FRS source mortality uses richer member-category mappings and table variants
  than the current runtime mortality labels express.
- TXTRS source mortality appears to use different active and retiree basis
  families, while the current runtime talks in terms of one base-table label
  plus one improvement scale.

This does not force an immediate runtime redesign, but it is strong evidence
that the prep pilot should treat mortality as a test case when deciding whether
the current runtime contract is merely sufficient for `v1` or is also the right
long-run shape.

## Immediate Recommendation

For the next pass of work:

- treat the current runtime contract as the working target
- do not redesign it casually
- document the decision pressure points now
- revisit the contract after the FRS/TXTRS PDF-to-stage-3 pilot exposes real constraints
