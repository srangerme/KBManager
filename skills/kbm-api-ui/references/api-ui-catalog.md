# KBManager UI API Catalog

Use this catalog for Claude Code UI calls.

## Global Payload Fields

Every `kb.*` API payload requires both fields:

```yaml
entrypoint: claude_code
dry_run: false
```

- `dry_run: true` validates payload shape, entrypoint permission, object
  existence, state preconditions, and review gate requirements.
- Dry run never writes object files, moves files, or resumes LLM output.

## Review Gate Operations

These operations require explicit Claude Code UI review:

- `kb.source.deprecate`
- `kb.candidate.defer`
- `kb.knowledge.accept`
- `kb.knowledge.reject`
- `kb.knowledge.merge`
- `kb.knowledge.deprecate`
- `kb.knowledgebase.create`
- `kb.knowledgebase.outline.create`
- `kb.knowledgebase.outline.set_default`
- `kb.knowledgebase.outline.archive`
- `kb.note.deprecate`
- clean migration execution after `kb.clean.inspect`

## No Review Gate Operations

These operations do not require review gates:

- `kb.init`
- `kb.source.add`
- `kb.candidate.create`
- `kb.candidate.get`
- `kb.candidate.next_pending`
- `kb.knowledgebase.map`
- `kb.note.add`
- `kb.note.get`
- `kb.index.rebuild`
- `kb.clean.inspect`
- list/view read-only display workflows

## Operations

- `kb.init`: initialize workspace structure.
- `kb.source.add`: add file, directory, or URL source; may return `needs_llm`.
- `kb.candidate.create`: create pending candidates from source IDs; may return `needs_llm`; no review gate.
- `kb.candidate.get`: read one candidate.
- `kb.candidate.next_pending`: read next pending candidate.
- `kb.candidate.defer`: review-gated candidate decision.
- `kb.knowledge.accept`: review-gated candidate acceptance.
- `kb.knowledge.reject`: review-gated candidate rejection.
- `kb.knowledge.merge`: review-gated merge into existing knowledge.
- `kb.knowledge.deprecate`: review-gated knowledge deprecation.
- `kb.knowledgebase.create`: review-gated knowledgebase creation from reviewed content.
- `kb.knowledgebase.outline.create`: review-gated outline creation.
- `kb.knowledgebase.outline.set_default`: review-gated default outline update.
- `kb.knowledgebase.outline.archive`: review-gated outline archival.
- `kb.knowledgebase.map`: generate or return a knowledgebase map.
- `kb.note.add`: add a note; may request LLM title generation.
- `kb.note.get`: read one note.
- `kb.note.deprecate`: review-gated note deprecation.
- `kb.index.rebuild`: rebuild derived indexes and report consistency issues.
- `kb.clean.inspect`: inspect layout/schema drift and optionally request an LLM
  migration plan.

## Result Handling

Report `status`, `operation`, created/updated/deprecated objects, diffs, warnings,
errors, review options, and next actions. Do not run an extra index rebuild after
a write API that already reports automatic rebuild output.
