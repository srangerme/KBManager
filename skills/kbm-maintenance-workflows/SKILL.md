---
name: kbm-maintenance-workflows
description: Use for KBManager init, check, clean inspect, and clean migration workflows.
---

# KBManager Maintenance Workflows

## Init

- Use from Claude Code UI.
- Call `kb.init`.
- Has no review gate.
- Report created structure and warnings.

## Check

- Call `kb.index.rebuild`.
- Treat the operation as consistency checking and derived index rebuilding.
- Do not automatically repair object files unless the user requests a separate
  reviewed workflow.

## Clean Inspect And Migration

- Call `kb.clean.inspect` for read-only layout/schema inspection.
- Plan generation may use `needs_llm`.
- Migration execution requires Claude Code UI approval of the full migration plan.
- Clean migration execution is a controlled direct-edit exception.
