---
name: kbm-basic
description: Use for KBManager fundamentals: repository structure, object boundaries, file roles, global rules, write prohibitions, review gates, URL handling, index semantics, and controlled direct-edit exceptions.
---

# KBManager Basic

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
