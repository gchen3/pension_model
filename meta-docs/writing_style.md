# Writing Style

This applies to all prose a colleague might read: docs, PR descriptions,
issue and PR comments, code review comments, commit messages, and
end-of-task summaries.

**Default to plain English.** Reserve technical terms for code-level
references — function names, configuration keys, column names, formula
identifiers, file paths.

## Drop dead words

Prefer the shorter form when it carries the same meaning.

| Avoid | Use |
|---|---|
| build out | build |
| leverage | use |
| utilize | use |
| in order to | to |
| at this point in time | now |
| due to the fact that | because |
| a wide variety of | many |
| in the event that | if |
| with regard to | about |
| has the ability to | can |

## Translate jargon

Don't expect a reader to know terms specific to actuarial, accounting,
or programming traditions. Paraphrase. The rule of thumb: would a smart
reader who hasn't worked in this domain understand the surrounding
sentence?

| Avoid | Use |
|---|---|
| scaffolding | (describe what was added) |
| upstream prep system | tools for preparing input data |
| source registry | record of source documents |
| provenance ledger | record of where each piece of data came from |
| AV-first plan | a plan built from its published valuation report |
| synthetic payment stream | estimated stream of future payments |
| PV the cashflows | compute today's value of those cashflows |
| anchored to data meaning | (describe the actual constraint plainly) |
| stage-3 inputs | model inputs |

## Avoid developer shorthand

These phrases are common in developer culture but read as insider talk
to anyone outside it. Prefer the literal version.

| Avoid | Use |
|---|---|
| Two things land here | This PR does two things |
| this lands X | this adds X / this does X |
| ship the feature | release the feature |
| spin up a service | start a service |
| stand up an environment | set up an environment |
| kick off the run | start the run |
| wire up | connect / hook up |

## When jargon is fine

Identifiers — function names, configuration keys, column names, file
paths, citations — stay as-is. Rewriting them loses precision.

In code comments, write what the surrounding code does not already say.
A clear name beats a comment that restates it.

## Test before posting

Read your draft as if you didn't write it. If a sentence makes you
reach for a term's meaning, paraphrase. If a paragraph is dense, break
it up. If a word is doing nothing, cut it.
