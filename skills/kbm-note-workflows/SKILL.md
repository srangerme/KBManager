---
name: kbm-note-workflows
description: Use for KBManager note add, get, list, view, and deprecate workflows.
---

# KBManager Note Workflows

## Note Add

- Collect note content from the user or message.
- If the user supplied a non-empty title, call `kb.note.add` with that title.
- If no title was supplied, call `kb.note.add` in the title-generation flow,
  generate `{"title": "<non-empty>"}` from `note-title.md`, and resume.
- Has no review gate.

## Note Get And View

- Use `kb.note.get` for a specific note.
- List/view display may read object files or indexes for display only.
- Mark deprecated notes as outdated when shown.
- Do not use notes as source evidence for candidate creation.

## Note Deprecate

- Requires Claude Code UI.
- Requires explicit review gate.
- Call `kb.note.deprecate` only after explicit user approval.
