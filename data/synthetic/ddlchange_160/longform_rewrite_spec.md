# Longform Rewrite Spec (`ddlchange_160`)

This document defines hard constraints for the longform rewrite pass applied on `2026-03-02`.

## Objectives

- Upgrade raw payload realism for both email and ICS.
- Preserve all IDs and gold-compatible semantics.
- Increase textual variance for same-subject samples.
- Keep existing distribution and ambiguity ratios unchanged.

## Non-Negotiable Invariants

- Keep dataset size exactly:
  - `mail raw = 120`
  - `ics pairs = 40` (`80` files)
- Keep IDs stable:
  - `email_id`, `pair_id`, `UID`, file names, and path references unchanged.
- Keep label alignment stable:
  - no changes to `gold_mail_120.jsonl`, `ambiguity_mail_120.jsonl`,
  - no changes to `gold_diff_40.jsonl`, `ambiguity_40.jsonl`.
- Keep language mix stable:
  - `24/160` mixed-language samples (`mail=18`, `ics=6`).

## Mail Rewrite Rules

- Rewrite scope: `mail/raw_mail_120.jsonl` only.
- Immutable fields:
  - `email_id`, `from`, `subject`, `date`.
- Mutable field:
  - `body_text`.
- Target length:
  - each `body_text` in `[900, 1600]` chars.
- Recommended aggregate:
  - median `>=1100`,
  - p90 `<=1600`.
- Required content blocks per email:
  - background/context,
  - policy boundary,
  - primary conclusion,
  - execution checklist,
  - exception path,
  - reminder/disclaimer.
- Semantic guardrail:
  - exactly one dominant conclusion aligned with gold label/event type.
  - ambiguous samples may keep soft wording but must not invert gold label.

## ICS Rewrite Rules

- Rewrite scope: `ics/pairs/*.ics`.
- Immutable fields:
  - `UID`, `DTSTART`, `DTEND`, `SUMMARY`.
- Mutable field:
  - `DESCRIPTION`.
- Target length:
  - every `VEVENT DESCRIPTION` in `[450, 900]` chars.
- Recommended aggregate:
  - median `>=550`.
- Keep pair semantics:
  - `DUE_CHANGED`, `CREATED`, `NO_CHANGE`, `REMOVED_CANDIDATE` stay unchanged.
- Description requirements:
  - background + reason + execution hints + FAQ/operational note.
  - text may be verbose, but diff evidence must stay compatible with gold class.

## Diversity Rules

- Same-subject clusters (mail event type + drop cluster, ICS diff class) should avoid near-duplicate phrasing.
- Validation uses sentence/token similarity heuristics and tracks max intra-cluster similarity.

## Review Logging

- Update `qa/review_log_mail.jsonl` and `qa/review_log_ics.jsonl`.
- Required note after rewrite:
  - `longform_rewrite_passed`.

## Baseline Snapshot

- Archive pre-rewrite baseline at:
  - `archive/pre_longform_20260302/`
- Snapshot includes:
  - pre-rewrite `mail/raw_mail_120.jsonl`,
  - pre-rewrite `ics/pairs/*.ics`,
  - relevant pair index/gold/ambiguity files for traceability.

