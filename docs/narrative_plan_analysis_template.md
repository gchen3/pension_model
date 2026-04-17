# Narrative Plan Analysis Template

## Purpose

New-plan prep should begin with a narrative analysis of the pension plan itself,
based on the AV and other immediately relevant documents.

This is the first structured interpretation step in prep.

Its purpose is to answer:

```text
What kind of plan is this, how does it work at a high level, and what does that
imply for the model inputs we will need to build?
```

This document provides a standard template and content specification for that analysis.

## Why This Step Comes First

Source coverage and gap analysis are much easier once we understand the plan's
structure.

Without a narrative plan analysis, it is too easy to:

- miss important plan features
- misclassify classes or tiers
- misunderstand which reported tables matter
- ask the wrong source sufficiency questions
- build the wrong target mapping into stage-3 inputs

The narrative analysis should therefore come before the detailed source
coverage matrix and gap report.

## Recommended Output

For each plan, create a markdown document such as:

```text
prep/{plan}/reports/narrative_plan_analysis.md
```

The analysis should be concise but specific. It should be written for someone
who needs to understand both the pension plan and its implications for the
runtime input contract.

## Required Sections

## 1. Plan Identity And Source Set

State:

- plan name
- plan year or valuation year
- documents reviewed
- any important supporting documents beyond the AV and ACFR

Minimum source metadata:

- document ID
- full title
- report year
- relevant pages or sections used in the narrative

## 2. Executive Summary

Provide a short overview of:

- what kind of plan this is
- the main member groups and benefit structures
- the main actuarial and data implications for prep

This should be readable on its own.

## 3. Overall Plan Structure

Describe the broad structure of the plan.

Examples:

- DB-only
- DB plus DC
- DB plus cash balance
- hybrid with different benefit structures by tier or member type
- presence of DROP or similar overlays

Questions to answer:

- What are the major benefit legs?
- Are there optional or elective benefit structures?
- Are some plan features present only for some groups or tiers?

## 4. Membership Structure

Describe the participant groups that matter for modeling.

Include, where available:

- active, retired, terminated vested, disabled, beneficiaries, DROP participants
- major member classes
- tiers
- whether classes share or differ in benefit rules
- whether classes share or differ in decrement or mortality assumptions
- high-level member counts by group or class

Questions to answer:

- What are the natural model classes?
- What are the natural model tiers?
- Are there grouped classes for some purposes and separate classes for others?

## 5. Benefit Design Overview

Describe how benefits are calculated at a high level.

Include:

- general benefit formula structure
- final average salary or career-average rules
- vesting rules
- normal retirement eligibility
- early retirement eligibility and reductions
- COLA features
- employee and employer contribution features where relevant
- refund-of-contribution features where relevant
- any cash balance or DC crediting rules where relevant

Do not attempt to reproduce every statutory detail here. The goal is to
understand what input structures the model will need.

## 6. Funding And Valuation Context

Summarize the valuation and funding features that matter for runtime inputs.

Include:

- valuation date
- funding policy or statutory contribution context if relevant
- asset valuation method at a high level
- any obvious links between AV/ACFR-reported values and runtime funding inputs

This section is descriptive. Calibration remains a computed artifact rather than
document-sourced data.

## 7. Key Actuarial Assumptions And Tables

Summarize the main actuarial assumptions used by the plan and the reported
actuarial tables.

At minimum, discuss:

- discount rate
- investment return assumption, when reported
- payroll growth and inflation if reported
- mortality basis and improvement scale
- termination assumptions
- retirement assumptions
- disability assumptions if relevant
- salary increase assumptions
- any early-retirement reduction tables or similar benefit tables

Be precise:

- `discount rate` is the rate used to discount future cash flows to present values
- `investment return assumption` is the rate used to project asset earnings

If a source uses the same numeric value for both, note that explicitly rather
than treating the terms as interchangeable.

The point is not merely to list assumptions, but to identify what prep artifacts
they imply.

## 8. Reported Data Structures That Matter For Prep

Summarize the kinds of reported tables available in the AV and ACFR that are
likely to matter for canonical inputs.

Examples:

- active headcount or payroll by age/service
- retiree counts or benefit distributions
- valuation target tables
- funding seed values
- decrement or assumption tables
- member counts by class or tier

Questions to answer:

- Which reported tables already look close to stage-3 needs?
- Which ones are clearly aggregated too heavily?
- Which important inputs appear to be referenced but not published?

## 9. Implications For Runtime Inputs

Translate the narrative into likely runtime implications.

Discuss:

- likely `benefit_types`
- likely classes
- likely tiers
- likely need for class-specific versus shared decrement tables
- likely mortality table mapping
- likely funding input shape
- whether table-based reduction inputs will be needed
- whether entrant profiles appear likely to be needed or available

This is the bridge from descriptive narrative to prep design.

## 10. Modeling Scope, Exclusions, And Simplifications

Document what the model is expected to include and what it is not expected to
include in plan representation.

At minimum, discuss:

- populations included in scope
- populations excluded from scope
- benefit features included in scope
- benefit features excluded from scope
- rare elections or decisions that may be ignored or approximated
- small subclasses or benefit legs that may be combined, omitted, or treated as
  immaterial
- whether the exclusion is source-driven, runtime-driven, or a deliberate
  modeling simplification
- any known or expected effect on canonical inputs or reviewed outputs
- whether the choice is likely temporary or likely durable
- whether the feature is a candidate for later inclusion as the model becomes
  more source-structured and less calibration-dependent

Use clear labels where possible:

- `included`
- `excluded`
- `approximated`
- `not separately reported`
- `candidate future inclusion`

The goal is to avoid silent scope choices. A future reader should be able to
see not only what the plan is, but also what we chose to represent and what we
did not.

Also make clear when a simpler initial representation is intentional. In some
plans, the practical path will be:

- start with a simpler model representation
- use calibration more heavily to hit valuation targets
- add complexity later where it materially improves source faithfulness or
  reduces dependence on calibration

So exclusions and simplifications should be documented as either:

- current working scope decisions
- likely durable exclusions
- likely temporary simplifications to be revisited later

## 11. Likely Gaps, Judgment Points, And Risks

Identify likely issues before detailed coverage work begins.

Examples:

- important tables referenced but not published
- quantities that may need derivation
- likely judgment calls in mapping source concepts to canonical inputs
- likely estimation needs
- plan features that may stress the current runtime contract

This section is an early warning system, not the final gap report.

## Output Style

The narrative should be:

- concise
- factual
- explicit about uncertainty
- explicit about what is source-based versus inferred

It should avoid:

- unsupported guesses
- line-by-line statutory detail that does not affect prep
- pretending that unclear source material is clear

## Suggested Template

```markdown
# Narrative Plan Analysis: {plan}

## Source Set
- Document list with IDs, years, and relevant pages

## Executive Summary
- Short overview of plan type, member structure, and likely prep implications

## Overall Plan Structure
- DB / DC / CB / hybrid structure
- DROP or other overlays

## Membership Structure
- Classes
- Tiers
- Major reported participant groups

## Benefit Design Overview
- Formula structure
- Retirement eligibility
- Early retirement and reductions
- COLA
- Contributions / refunds / CB / DC features as relevant

## Funding And Valuation Context
- Valuation date
- Funding context
- Asset valuation context

## Key Actuarial Assumptions And Tables
- Mortality
- Termination
- Retirement
- Salary growth
- Discount / inflation / payroll growth
- Other relevant tables

## Reported Data Structures That Matter For Prep
- Key AV / ACFR tables and what they appear to provide

## Implications For Runtime Inputs
- Likely benefit types
- Likely classes and tiers
- Likely table requirements

## Modeling Scope, Exclusions, And Simplifications
- Populations/features included
- Populations/features excluded
- Known simplifications or approximations

## Likely Gaps, Judgment Points, And Risks
- Early list of likely trouble spots
```

## Completion Standard

A narrative plan analysis is complete enough to move on when:

- a reviewer can understand the broad structure of the plan
- the likely runtime-input implications are explicit
- modeled scope and exclusions are explicit
- likely gaps and judgment points are already visible
- the later coverage matrix and gap report have a clear frame of reference
