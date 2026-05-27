---
name: kbm-kb-outline-workflows
description: Use for KBManager knowledgebase outline create, set-default, archive, and explicit controlled outline YAML update workflows.
---

# KBManager Knowledgebase Outline Workflows

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
