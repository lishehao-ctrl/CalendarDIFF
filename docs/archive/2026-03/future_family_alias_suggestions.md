# Future Family Alias Suggestions

This note records a future direction only. It is not part of the current runtime contract.

## Current stance

- Gmail / ICS extraction may preserve source-near aliases such as `HW`, `Write-up`, or `Take-home Final`.
- Family management is responsible for deciding whether multiple aliases should merge into one canonical family.
- Alias pressure is intentionally shifted away from the LLM extraction layer.

## Future suggestion direction

If alias suggestions are added later, they should be advisory only at first.

Recommended shape:

- detect a new raw type or item alias under an existing course stem
- compare it against known family aliases using case-insensitive and punctuation-light normalization
- use ordinal, due-time similarity, and repeated co-occurrence as supporting evidence
- surface a merge suggestion to the user instead of auto-merging

Examples:

- `HW` -> suggest merge with family using `Homework`
- `Write-up` -> suggest merge with family using `Lab Report`
- `Take-home Final` -> suggest merge with family using `Final Exam`

## Why defer it

- false-positive alias merges are expensive because they corrupt canonical consistency
- extraction quality and family governance need to stay separable
- the current product can already work with source-near aliases as long as family management stays strong
