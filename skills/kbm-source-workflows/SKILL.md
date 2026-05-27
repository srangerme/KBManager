---
name: kbm-source-workflows
description: Use for KBManager source add and source deprecate workflows.
---

# KBManager Source Workflows

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
