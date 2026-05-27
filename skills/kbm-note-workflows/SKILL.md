---
name: kbm-note-workflows
description: Use this skill for KBManager note workflows whenever the user asks to add, capture, save, title, get, list, view, show, or deprecate notes. Trigger on note add, note title generation, personal notes, observations, scratch notes, note list/view/get/deprecate language, deprecated note display, and requests involving notes that are not evidence sources for candidate creation. This skill is for note lifecycle actions, not source ingestion or evidence-backed candidate creation.
---

# KBManager Note Workflows

When this skill is used, explicitly tell the user: `Using skill: kbm-note-workflows`.

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
