# AGENTS.md — UI build rules (Next + Tailwind + shadcn)

## Tech stack (locked)
- Next.js App Router (TypeScript)
- Tailwind CSS
- shadcn/ui (Radix primitives)
- lucide-react icons

## UI quality bar (non-negotiable)
- Consistent spacing scale: prefer p-4/p-6, gap-2/3/4, max-w containers where appropriate
- Corners: rounded-2xl for cards/dialogs
- Shadows: subtle (avoid heavy shadows)
- Typography hierarchy: clear H1/H2/body/label
- States: loading (skeleton), empty, error must exist for every data view
- Responsive: mobile first; sidebar collapses to Sheet/Drawer on small screens
- Accessibility: keyboard nav for menus/dialogs; proper labels for inputs

## Component rules
- Prefer shadcn/ui components over hand-rolled HTML.
- If a component doesn’t exist, create it in /components/ui with the same patterns.
- Avoid introducing new UI libraries unless asked.

## Dev workflow
- Before coding: propose a short plan (files + steps).
- After changes: run (in order) typecheck, lint, build.
- Keep diffs minimal and readable.

## Project deployment workflow
- For tasks involving GitHub remotes, AWS release/sync, live `.env`, Gmail OAuth deployment, or host nginx changes, read `skills/aws-release/SKILL.md` before making changes.
- Prefer `scripts/release_aws_main.sh` for the normal push -> AWS sync -> verify workflow.
- If a host-only fix is applied on AWS, mirror the intended architecture back into repo docs before ending the task.
