---
name: kbm-source-workflows
description: Use this skill for KBManager source workflows whenever the user asks to add, import, ingest, register, attach, or deprecate sources. Trigger on requests involving source files, directories, URLs, webpages, PDFs, HTML, Markdown, raw research material, source ingestion, source add, source deprecate, or turning external/local material into pending KBManager candidates. This skill is specifically for source lifecycle operations and should be combined with kbm-basic and kbm-api-ui before calling kb.source.add, kb.source.deprecate, or creating candidates from newly added sources.
---

# KBManager Source Workflows

When this skill is used, explicitly tell the user: `Using skill: kbm-source-workflows`.

## Source Add

Use for file, directory, or URL source ingestion followed by mandatory pending
candidate creation.

1. Apply `kbm-basic`.
2. Use `kbm-api-ui`.
3. For Claude Code UI, optional temporary user guidance may be rewritten through
   `source-ingest-prompt-rewrite.md` before calling the API.
4. Call `kb.source.add`.
5. Handle `needs_llm` using the API-provided prompt and schema.
6. After source creation, always call `kb.candidate.create`.
7. Handle candidate creation `needs_llm`.
8. Report source IDs, candidate IDs, warnings, and next actions.

Source add has no review gate. Candidate creation is mandatory in this workflow
and creates pending candidates only.

## Source Deprecate

Use for explicit source deprecation requests.

- Requires Claude Code UI.
- Requires review gate.
- Call the review-gated source deprecation API only after explicit approval.
