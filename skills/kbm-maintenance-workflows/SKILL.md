---
name: kbm-maintenance-workflows
description: Use this skill for KBManager maintenance workflows whenever the user asks to initialize a KBManager workspace, check consistency, rebuild indexes, inspect layout/schema cleanliness, clean or migrate the repository, generate or execute a migration plan, validate object/index state, or repair structural issues through an approved migration. Trigger on kb.init, kb.index.rebuild, kb.clean.inspect, clean migration, init/check/clean/migrate language, derived index rebuilding, and reviewed maintenance plans.
---

# KBManager Maintenance Workflows

When this skill is used, explicitly tell the user: `Using skill: kbm-maintenance-workflows`.

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
