# Cross-Plan Lessons From FRS And TXTRS

## Purpose

This memo captures reusable lessons from reverse-engineering FRS and TXTRS
inputs so they can inform forward-looking prep for new plans.

The point is not to preserve every plan-specific fact. The point is to preserve
the patterns, risks, and useful techniques that are likely to recur.

## Main Lessons

### 1. The AV is usually the primary source, but not the only useful source

Across both pilots, the actuarial valuation is usually the authoritative source
for:

- actuarial assumptions
- funding values
- plan provisions summarized for modeling
- active-member demographic structure

But the ACFR remains important for:

- cash-flow categories
- statistical tables
- class splits not shown in the valuation
- clue-mining for legacy constructed values

So the right rule is:

- use AV first for authoritative sourcing
- use ACFR second for gap-filling, reconciliation, and legacy clue mining

### 2. A lot of runtime inputs are `derived`, not directly published

The most reusable lesson from both plans is that many runtime artifacts are not
raw source tables.

Common cases:

- grouped source tables transformed to canonical point grids
- grouped entrant profiles converted to canonical single-age rows
- plan-wide totals allocated across classes
- grouped retiree data smoothed into age-by-age distributions

This argues for a prep architecture that treats `derived` as normal, not as an
exception.

### 3. Exact stage-3 reproduction is a strong and practical prep test

For both pilots, the most useful working test has been:

- can the reviewed prep path reproduce canonical runtime artifacts exactly?

This has already paid off:

- TXTRS active headcount and salary grids can now be reproduced exactly from
  the valuation PDF
- TXTRS entrant profile can now be reproduced exactly from the valuation PDF

That is enough to justify keeping stage-3 equivalence as the primary prep gate.

### 4. Some artifacts are source-faithful transforms; others are legacy model-mediated

The pilots show a clean distinction:

- `source-faithful transform`
  - TXTRS active grid
  - TXTRS entrant profile
- `legacy model-mediated`
  - FRS class benefit-outflow constants
  - FRS retiree distribution smoothing
  - TXTRS retiree distribution smoothing

This distinction matters operationally:

- source-faithful transforms can become shared prep methods
- legacy model-mediated artifacts need reconstruction logs, not silent reuse

### 5. Reverse-engineering knowledge needs a shared home

Without shared docs, lessons from FRS and TXTRS would stay trapped in:

- plan notes
- issue threads
- workbook memory

So reusable knowledge should be pushed into:

- `prep/common/methods/`
- `prep/common/checks/`
- `prep/common/reports/`
- `docs/`

### 6. Provenance only helps if the page convention is unambiguous

The pilots exposed a real practical problem:

- printed report pages and PDF pages are often different

That is now a shared rule:

- printed page is primary
- PDF page is also recorded when practical

This sounds small, but it is critical for reproducibility.

### 7. Discount rate and investment return assumption must stay separate

The pilots reinforced that source documents and legacy artifacts often blur the
terminology.

Prep should not.

Even when the numbers match, we should preserve the conceptual distinction
between:

- liability discount rate
- investment return assumption

### 8. Shared external reference materials deserve their own common source area

Mortality work made this clear.

Some plans reference:

- SOA mortality tables
- improvement scales
- other shared external reference tables

Those should not live inside a single plan folder. They belong in:

- `prep/common/sources/`
- `prep/common/reference_tables/`

And they need provenance just like plan-specific sources.

### 9. Legacy clues and new estimation should never be conflated

The pilots already contain both kinds of work:

- legacy reconstruction attempts against Reason-era inputs
- new forward-looking method design for future plans

They are not the same.

We should keep separate labels for:

- `legacy_unresolved`
- `partially_reconstructed`
- `estimated_documented`

### 10. Grouped source data does not automatically imply we need synthetic single-year tables

The pilots make this point strongly.

So far, grouped-to-canonical transforms have been enough for the successful
TXTRS cases. Constructing synthetic single-year tables would have added an
unnecessary estimation layer.

So the current bias should be:

- do not construct synthetic single-year tables unless grouped data is too
  coarse to support stable modeling or exact runtime reproduction

If that changes later, the single-year reconstruction method should be treated
as a deliberate shared estimation method, not an ad hoc convenience.

### 11. First-year observed cash flows may be broader than the model's later-year benefit concept

FRS exposed an important pattern that is likely to recur.

The initial observed year may be anchored to:

- valuation asset-development cash flows
- ACFR deductions totals
- class-allocated disbursement lines

Those first-year observed values can be broader than the narrower modeled
benefit-payment concept used in later projection years.

Implications:

- do not assume a first-year `benefit` input is conceptually identical to later
  projected benefit payments
- check whether year 0 includes refunds, admin expense, transfers, or other
  disbursements in the observed source path
- document explicitly when the first-year input is a proxy backed out from a
  broader cash-flow concept

This is not just a plan-specific FRS detail. It is a general prep risk whenever
the best class-level source is a valuation funding table rather than a direct
benefit-payment table.

### 12. Mortality gaps can combine missing source tables with ambiguous implementation rules

TXTRS shows that a mortality gap is not always solved just by obtaining the
named external table.

The unresolved pieces may include both:

- missing plan-specific base rates
- uncertainty about how the improvement scale is meant to be operationalized

Examples of implementation ambiguity:

- whether `Scale UMP 2021` is identical to a shared `MP-2021` workbook
- whether `immediate convergence` means use ultimate rates immediately or only
  after the published horizon
- whether disabled-retiree mortality floors are applied before or after
  projection

So mortality prep should be treated as a two-part task:

1. acquire the source tables
2. confirm the intended implementation rule

Without both, a runtime mortality artifact may be reproducible but still not be
source-faithful.

## Recurring Source Situations To Expect On New Plans

These patterns already look likely to recur:

- valuation names a mortality basis but does not publish full rates
- valuation names an improvement scale but leaves its implementation ambiguous
- ACFR and AV totals differ for legitimate scope or measurement reasons
- initial observed-year cash flows are broader than the later-year modeled
  benefit concept
- plan provisions are clear in prose but not directly encoded as tidy tables
- active members are published in grouped age/service form
- entrant profiles are published in grouped form
- retiree information is published only as broad category totals
- small subgroups or rare elections exist but are not material enough to model
  directly at first

These patterns should drive common prep templates, checks, and methods.

## What Should Carry Forward For New Plans

The following should be treated as durable shared assets:

- method registry entries
- check catalog entries
- provenance conventions
- page-crosswalk conventions
- source-registry conventions
- runtime build rules
- cross-plan lessons
- narrative analysis template
- gap-report structure

## What Should Stay Plan-Specific

The following should remain under `prep/{plan}/`:

- plan narratives
- source inventories
- source sufficiency reports
- artifact lineage notes
- reconstruction logs
- unresolved plan-specific issue notes

## Immediate Implication

As we continue reverse-engineering FRS and TXTRS, we should keep asking:

- is this a plan-specific fact?
- or is this a reusable prep pattern that belongs in `prep/common/`?

That question is how the pilot work becomes a useful prep system instead of a
collection of two well-documented exceptions.
