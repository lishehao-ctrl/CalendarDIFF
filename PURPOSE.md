# CalendarDIFF Purpose

## Goal

CalendarDIFF exists to stably detect whether incoming multi-platform signals imply a meaningful deadline or schedule change for grade-relevant academic events.

The system is not trying to classify all course-related communication. It is trying to maintain a backend canonical event-time database and decide whether a new signal should create, update, or leave unchanged the known due-date state for an event.

## Canonical Product Objective

The backend should maintain a canonical database of events and their effective deadlines or scheduled times.

Each new source signal should be interpreted against that database to answer:

1. does this signal contain a clear time-bearing academic event?
2. if yes, does it imply a new event, a changed event, or no effective change?
3. if it implies a change, can that change be applied deterministically or reviewed safely?

## Primary Detection Purpose

The primary detection purpose is:

detect explicit time signals for grade-relevant items that should affect the canonical event-time database.

This includes:

1. newly announced homework, quiz, exam, project, or similar graded item with a clear due time
2. due-date or due-time changes for an existing graded item
3. rescheduled quizzes, exams, or other graded assessments
4. bulk time-change rules that affect multiple existing graded items

## High-Priority Event Types

The system should prioritize event types that clearly affect grades:

1. homework
2. quiz
3. exam
4. midterm
5. final exam
6. project
7. problem set
8. other clearly graded deliverables

Lab can affect grades in some courses, but the default product stance is conservative:

1. lab reports or clearly graded lab deliverables may be included
2. recurring lab sessions, general lab logistics, and mass lab notifications should not be a default target

## Out of Scope by Default

The system should not try to treat the following as target events unless they contain a direct, explicit graded deadline signal:

1. recurring lab sessions
2. discussion sections
3. office hours
4. study advice
5. exam-format explanations
6. skipped-sections notices
7. grade-release or grade-change notices
8. submission confirmations
9. FAQ digests
10. thread summaries
11. generic course announcements

## Source Roles

### ICS

ICS is primarily a structured inventory and deterministic time-diff source.

Expected role:

1. provide canonical scheduled times for known events
2. surface deterministic time changes when the calendar event itself changes
3. rarely act as an announcement-only source

### Gmail

Gmail is primarily a time-signal source.

Expected role:

1. detect explicit graded-item time signals that matter to the event-time database
2. capture both newly announced graded items and changed graded items
3. capture bulk rule-based schedule changes when clearly stated
4. ignore noisy mass mail that does not carry an explicit actionable time signal

## Detection Contract

For Gmail-like unstructured inputs, the effective contract is:

1. `unknown`: no clear grade-relevant time signal for the canonical event-time database
2. `atomic`: one clear grade-relevant time signal affecting a single event
3. `directive`: one clear rule affecting multiple existing grade-relevant events

For structured sources like ICS, the contract is:

1. `unknown`: not a monitored grade-relevant event
2. `relevant`: a monitored grade-relevant event with usable time information

## Decision Philosophy

The system should be conservative.

When uncertain:

1. prefer `unknown`
2. avoid converting informational mail into a false deadline change
3. avoid treating recurring session logistics as canonical graded events
4. favor precision over aggressive recall for noisy mass-mail categories

## Success Criteria

The system is successful when it can reliably answer:

1. did a grade-relevant event deadline or schedule meaningfully change?
2. did a grade-relevant event with a clear time get newly announced?
3. can that signal be aligned to the backend canonical event-time database?

The system is not successful merely because it recognized that an email was course-related.
