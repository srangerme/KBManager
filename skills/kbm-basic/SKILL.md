---
name: kbm-basic
description: Use this skill as the baseline for any KBManager task, especially when the user asks about repository structure, object boundaries, file roles, global rules, safe writes, prohibited direct edits, review gates, URL handling, source evidence, derived indexes, controlled direct-edit exceptions, or how KBManager data should be read or modified. Trigger for all KBManager workflows before object writes, API calls, file edits, migrations, candidate/source/knowledge/note/knowledgebase operations, or when deciding whether to use kb.* APIs versus direct file changes.
---

# KBManager Basic

When this skill is used, explicitly tell the user: `Using skill: kbm-basic`.

Use this skill before any KBManager workflow when you need the global operating
rules or repository model.

## Repository Model

- KBManager stores all data in the user's workspace as Markdown, PDF, HTML, YAML,
  and derived index files.
- Object files are the source of truth. Derived indexes are display and lookup
  aids only.
- The first layer is Claude Code UI, `/kbm:ask`, skills, prompt orchestration,
  user review, and result presentation.
- The second layer is the internal `kb.*` API reached through
  `scripts/kbmanager_plugin.py`.

## Write Boundary

- Use `kb.*` APIs for object writes.
- Do not directly create, edit, move, or delete source, candidate, knowledge,
  knowledgebase, note, or index files.
- Do not physically delete objects. Use deprecate, reject, defer, or archive
  semantics through the API.
- Direct-edit exceptions are limited to:
  - clean migration execution after the full plan is reviewed and approved in
    Claude Code UI,
  - explicit outline YAML updates through `kbm-kb-outline-workflows`.

## Review And Entry Rules

- Do not continue a review-gated flow without explicit user approval.
- Do not treat LLM output, generated drafts, candidate text, or suggestions as
  user approval.
- Every `kb.*` payload includes required `entrypoint` and required `dry_run`.
- Use `entrypoint: "claude_code"` from Claude Code UI.

## Sources And Facts

- Do not invent facts or evidence.
- Candidate and knowledge evidence must trace to allowed upstream objects.
- Notes are not source evidence for candidate creation.
- For URL source input, pass the original URL to `kb.source.add`; do not fetch,
  browse, export, scrape, save, or retry URL content in Claude Code.

## References

- `docs/架构设计.md`
- `docs/对象.md`
- `docs/Interface.md`
- `docs/API设计.md`
