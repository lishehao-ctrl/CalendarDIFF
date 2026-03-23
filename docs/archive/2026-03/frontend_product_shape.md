# Frontend Product Shape

## Summary
This document defines how the CalendarDIFF frontend should feel from the user's point of view.

The visual style is already strong. The main convergence target is content structure, page hierarchy, and action priority.

The target product lanes are:

- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

This guidance is based on direct inspection of the live frontend using Playwright, not only source-code reading.

## Product frame
The user is not managing backend tables.

The user is doing four jobs:

1. review detected graded-event changes
2. teach the system when labels refer to the same thing
3. keep source intake healthy
4. manually repair what the system cannot safely infer

The frontend should make those jobs obvious and ordered.

## Core rules
- `Changes` is the main workspace.
- `Families` is a governance workspace, not a bulk form wall.
- `Sources` is an intake and health workspace.
- `Manual` is a repair tool, not the default operating mode.
- `Settings` stays thin.
- The home page should route attention, not behave like a generic dashboard.

## Current issues seen in the live UI
- Login/register copy still talks about `resolve links`, which is an old product concept.
- The home page gives similar weight to `Next move` and `Shortcuts`, so it does not act as a true attention router.
- `Changes` feels more like a moderation queue than the primary operations workspace.
- `Families` defaults into a dense editor view instead of a triage-first governance surface.
- `Manual` feels like direct table maintenance instead of structured repair.
- `Settings` still contains transitional messaging that should not survive into the stable product shape.

## Page-by-page target shape

### `/`
Purpose:
- route the user to the most valuable next action

Primary sections:
- `Primary attention`
- `Course hotspots`
- `Secondary lanes`

What the page should answer:
- what needs action now
- which course is most chaotic
- where the user should go next

What to reduce:
- dashboard-like duplication
- equal-weight shortcut cards

### `/changes`
Purpose:
- be the primary decision workspace

Target layout:
- left: change inbox
- right: decision workspace

Inbox behavior:
- group by course or hotspot first
- keep status filters available, but secondary
- each row should show:
  - event/family label
  - old time -> new time
  - primary source
  - ambiguity/confidence signal

Decision workspace sections:
- `What changed`
- `Why the system thinks this`
- `Canonical match`
- `Decision`

Primary actions:
- `Approve`
- `Reject`
- `Edit then approve`
- `Approve and learn`

`Approve and learn` should be first-class because it matches the real user workflow:
- the change is correct
- the label is not yet canonical
- the user wants approval and learning in one pass

### `/families`
Purpose:
- canonical governance and semantic cleanup

Default view:
- triage-first, not edit-first

Top-level sections:
- `Needs attention`
- `Likely duplicates`
- `High-usage families`

Course-scoped view:
- after narrowing to a course, show:
  - canonical label
  - alias/raw-type preview
  - usage count
  - merge candidate count
  - pending impact

Editing behavior:
- only open full controls after selecting a family
- avoid showing many open editors at once

### `/sources`
Purpose:
- source connection and health management

Primary sections:
- `Connected sources`
- `Attention needed`
- `Recent sync activity`
- `Add source`

Primary source-card actions:
- `Sync now`
- `Reconnect`
- `Archive` or `Reactivate`

What not to do here:
- source cards should not become semantic-management surfaces

### `/manual`
Purpose:
- structured repair workspace for exceptions

Target opening state:
- `Add missing event`
- `Fix existing event`

The page should explicitly tell the user:
- use `Changes` first for detected updates
- use `Families` when naming is unstable
- use `Sources` when intake is unhealthy
- use `Manual` when the system cannot safely cover the case

### `/settings`
Purpose:
- thin account/runtime preferences

Keep:
- timezone
- notify/login email display
- small runtime summary if useful

Remove:
- transitional copy about where other modules moved

## Content priorities by lane
- `Sources`: health, sync, connection state
- `Changes`: decisions, evidence, canonical alignment
- `Families`: merge, alias, canonical label governance
- `Manual`: repair
- `Settings`: preferences only

## Copy guidance
- avoid old language like `links`, `resolve links`, or `review items`
- prefer:
  - `changes`
  - `families`
  - `timeline`
  - `canonical label`
  - `source health`
  - `manual repair`

## Near-term content changes
Highest-value fixes:

1. remove `resolve links` from login/register hero copy
2. turn the home page into an attention router
3. make `Changes` emphasize decisioning over queue mechanics
4. make `Families` emphasize governance over editing density
5. make `Manual` explain when it is the right tool
6. remove transitional “moved” content from `Settings`

## Non-goals
- no visual redesign mandate
- no new visual system
- no large component rewrite required to adopt this shape
- no need to expose backend implementation language in the UI

## Implementation note
The current UI already has enough structural pieces to support this shape.

The next pass should mainly:
- reorder content
- change section emphasis
- simplify over-dense editors
- promote the right actions

It does not need a new look.
