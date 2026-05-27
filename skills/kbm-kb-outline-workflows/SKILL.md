---
name: kbm-kb-outline-workflows
description: Use this skill for KBManager knowledgebase outline workflows whenever the user asks to create an outline, set a default outline, archive an outline, edit/update/reorder/rename/move/split/merge outline YAML nodes, repair outline bindings, or maintain a knowledgebase structure. Trigger on outline create, outline set-default, default outline, archive outline, outline YAML, bindto risks, node IDs, hierarchy changes, section trees, taxonomy changes, and controlled direct edits to existing outline files. This skill is only for knowledgebase outline lifecycle and explicit outline YAML maintenance.
---

# KBManager Knowledgebase Outline Workflows

When this skill is used, explicitly tell the user: `Using skill: kbm-kb-outline-workflows`.

## Outline Create

- Requires Claude Code UI.
- Requires explicit review gate.
- Call `kb.knowledgebase.outline.create` with reviewed outline content.

## Outline Set Default

- Requires Claude Code UI.
- Requires explicit review gate.
- Call `kb.knowledgebase.outline.set_default` after approval.

## Outline Archive

- Requires Claude Code UI.
- Requires explicit review gate.
- Check binding risk before asking for approval.
- Call `kb.knowledgebase.outline.archive` after approval.

## Outline Update Direct-Edit Exception

Use only when the user explicitly asks to update an existing outline YAML file.
This is a controlled direct-edit exception for LLM-assisted outline maintenance.

- Do not create a new outline through direct editing.
- Do not set default or archive through direct editing.
- Do not modify knowledge, candidate, source, note, index, or source files.
- Locate the knowledgebase Markdown file and its `outlines_file`.
- Confirm the target `outline_id`.
- Search accepted knowledge for `bindto` entries matching the knowledgebase and
  outline.
- Edit only the target outline YAML nodes.
- Preserve stable node IDs for rename, move, reorder, and most split/merge cases.
- Do not remove a bound node unless the user explicitly accepts binding repair.
- Run check through `/kbm:ask` or `kb.index.rebuild` after the edit.
- Report changed node IDs, preserved IDs, and binding risks.
