# KBManager Plugin API Catalog

Use this reference when invoking KBManager Claude Code plugin commands or calling the helper script directly.

## Helper Invocation

All plugin API calls go through:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <operation> '<payload-json>' --pretty
```

The helper maps `<operation>` to `kbmanager.application` and defaults `root` to `${CLAUDE_PROJECT_DIR}`. The JSON payload is keyword arguments for the operation. `root` may be included in the payload only when intentionally overriding the workspace.

## Slash Commands

### `/kbm:init`

Initialize the current Claude project as a KBManager workspace.

Payload for `kb.init`:

- Optional: `dry_run` boolean, default `false`.

### `/kbm:source-add <path-or-url>`

Add a local Markdown/PDF file, directory, or URL as source, then create pending candidate drafts.

Initial `kb.source.add` payload:

- Required: `input_path` string.
- Optional: `title` string.
- Optional: `tags` string list.
- Optional: `authors` string list.
- Optional command-only fields: `user_prompt`, `confirm_user_prompt`, `reviewed_user_prompt`.

Resume `kb.source.add` payload:

- Required: same `input_path`.
- Required: `resume_token`.
- Required: `llm_result`.
- Optional: repeat `title`, `tags`, `authors` if supplied initially.

`llm_result` for one input must include:

- `input_path` string.
- `summary` non-empty string.
- `tags` string list.
- `cleaned_content` non-empty string that references the requested `input_path`.

For directory input, use `llm_result.sources`, one item per requested input path, each with the same fields.

Then call `kb.candidate.create`:

- Required: `source_ids` non-empty string list.
- Resume requires `resume_token` and `llm_result`.

Candidate `llm_result`:

- `candidates` list.
- Each item: optional `id`, required `title`, `summary`, `content`, `evidence`, `bindto`, optional `outline_change_suggestions`.
- `evidence` items use `source_id` or `object_id` or `id`, plus `locator`, plus at least one of `quote`, `excerpt`, or `snippet`.
- `bindto` must be `[]` or items with `kb_id`, `outline_id`, `node_id`, `reason`.

URL rule: pass the original URL to `kb.source.add`. Do not independently fetch, browse, export, scrape, or save the URL in Claude Code.

### `/kbm:source-deprecate <source-id> reason:<reason>`

Mark a source deprecated after explicit user confirmation.

Payload for `kb.source.deprecate`:

- Required: `source_id`.
- Required: `reason`.
- Required: `decision`: `"deprecate"`.
- Required: `reviewed_by`.

### `/kbm:candidate-review [candidate-id]`

Review a pending candidate and choose `accept`, `reject`, `defer`, or `merge`.

Read payloads:

- `kb.candidate.next_pending`: `{}`; current implementation accepts no filters.
- `kb.candidate.get`: required `candidate_id`.

Reject payload for `kb.knowledge.reject`:

- Required: `candidate_id`.
- Required: `decision`: `"reject"`.
- Required: `reason`.
- Required: `reviewed_by`.

Defer payload for `kb.candidate.defer`:

- Required: `candidate_id`.
- Required: `decision`: `"defer"`.
- Required: `reason`.
- Required: `reviewed_by`.

Accept payload for `kb.knowledge.accept`:

- Required: `candidate_id`.
- Required: `decision`: `"accept"`.
- Required: `reviewed_by`.
- Required: reviewed `title`.
- Required: reviewed `summary`.
- Required: reviewed `content`.
- Required: reviewed `evidence`.
- Required: reviewed `bindto`; use `[]` when there are no bindings.
- Optional: `reason`.

Merge payload for `kb.knowledge.merge`:

- Required: `candidate_id`.
- Required: `target_knowledge_id`.
- Required: `decision`: `"merge"`.
- Required: `reviewed_by`.
- Required: reviewed `summary`.
- Required: reviewed `content`.
- Required: reviewed `evidence`.
- Required: reviewed `bindto`; use `[]` when there are no bindings.
- Optional: `reason`.

Never call accept/merge/reject/defer until the user has confirmed the decision and reviewed payload.

### `/kbm:knowledgebase-create <path-or-url>`

Create a knowledgebase from temporary source-like context. The input does not become a source object.

Payload for `kb.knowledgebase.create`:

- Required: `title`.
- Required: `review`: mapping with `decision: "approve"`.
- Required: `description` non-empty string.
- Required: `tags` string list.
- Required: `scope` with clear included and excluded scope.
- Required: `default_outline_id`.
- Required: `outlines`.
- Optional: `knowledgebase_id`.

Do not call this API until the user approves or edits the generated knowledgebase draft.

### `/kbm:knowledgebase-list [knowledgebase-id]`

Read-only display command.

- Without ID: read `indexes/kb-index.md`.
- With ID: read `indexes/knowledgebase/<knowledgebase-id>-knowledge-index.md`.

No API call is required. Do not rebuild indexes from this command; suggest `/kbm:check` if stale or missing.

### `/kbm:knowledgebase-map [knowledgebase-id]`

Generate a temporary left-to-right Mermaid map.

Payload for `kb.knowledgebase.map`:

- Optional: `knowledgebase_id`; omit it when not supplied.
- Optional: `output_path`.

The API writes a temporary Markdown file only. Open it in VSCode if available, otherwise display returned Markdown.

### `/kbm:knowledgebase-outline-create [knowledgebase-id] <path-or-url>`

Create a new outline for an active knowledgebase from temporary context.

Payload for `kb.knowledgebase.outline.create`:

- Required: `knowledgebase_id`.
- Required: `outline` mapping.
- Required: `review`: mapping with `decision: "approve"`.

Required `outline` fields:

- `id`.
- `title`.
- `description`.
- `status`: usually `"active"`.
- `nodes` list.

Do not create source objects from the input. Do not set the new outline as default in this command.

### `/kbm:knowledgebase-outline-set-default [knowledgebase-id] [outline-id]`

Set the default active outline after user confirmation.

Payload for `kb.knowledgebase.outline.set_default`:

- Required: `knowledgebase_id`.
- Required: `outline_id`.
- Required: `review`: mapping with `decision: "approve"`.

The selected outline must exist and be active.

### `/kbm:knowledgebase-outline-archive [knowledgebase-id] [outline-id]`

Archive a non-default outline after user confirmation.

Payload for `kb.knowledgebase.outline.archive`:

- Required: `knowledgebase_id`.
- Required: `outline_id`.
- Required: `review`: mapping with `decision: "approve"`.
- Optional: `allow_existing_bindings` boolean; set true only when the user explicitly accepts the impact on existing bindings.

Do not archive the current default outline. Do not modify knowledge `bindto`.

### `/kbm:note-add`

Add a note from Markdown collected in Claude Code.

Initial payload for `kb.note.add`:

- Required: `content` non-empty string.
- Required for the slash command title-generation flow: `needs_llm: true`.
- Optional: `title` non-empty string.
- Optional: `note_id`.
- Use the note-title LLM flow when command instructions require title generation.

Resume payload:

- Required: same `content`.
- Required: `resume_token` when API returned `needs_llm`.
- Required: `llm_result` with `title` non-empty string.
- Optional: repeat `title` or `note_id` if supplied initially.

Never pass `title: ""`; omit blank optional fields.

### `/kbm:note-list`

Read-only display command. Read `indexes/note-index.md` from the workspace and display it. Do not call `kb.index.rebuild`.

### `/kbm:note-view <note-id>`

Read a note through API, then display the full Markdown file.

Payload for `kb.note.get`:

- Required: `note_id`.

After success, read `note.path` relative to `${CLAUDE_PROJECT_DIR}` and display frontmatter and body.

### `/kbm:note-deprecate <note-id> reason:<reason>`

Deprecate a note after explicit user confirmation.

Payload for `kb.note.deprecate`:

- Required: `note_id`.
- Required: `reason`.
- Required: `decision`: `"deprecate"`.
- Required: `reviewed_by`.

### `/kbm:check`

Rebuild derived indexes and report consistency issues.

Payload for `kb.index.rebuild`:

- Optional: `scope`: one of `all`, `source`, `candidate`, `knowledge`, `knowledgebase`, `note`, `review_queue`, `tag`; default is all.
- Optional: object ID field when narrowing to one object.
- Optional: `dry_run` boolean.

Do not write object files from this command.

### `/kbm:clean`

Inspect workspace schema drift and plan migration.

Payload for `kb.clean.inspect`: `{}`.

If it returns `needs_llm`, generate a migration plan from the returned request, show the full plan, and wait for one explicit user confirmation before changing files. This is the only command with privileged direct workspace edits after approval.

### Lark Server Slash Commands

`/kbm:lark-server-start`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_lark_server.py" start --root "${CLAUDE_PROJECT_DIR}"
```

`/kbm:lark-server-status`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_lark_server.py" status --root "${CLAUDE_PROJECT_DIR}"
```

`/kbm:lark-server-stop`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_lark_server.py" stop --root "${CLAUDE_PROJECT_DIR}"
```

These commands must not create or edit KBManager object files directly.

## Direct API Summary

### Initialization

`kb.init`: create workspace directories, indexes, placeholders, and `.lark/settings.json.example`.

- Optional: `dry_run`.

### Source

`kb.source.add`: add source and cleaned content through LLM boundary.

- Required: `input_path`.
- Optional: `title`, `tags`, `authors`, `dry_run`.
- Resume: `resume_token`, `llm_result`.

`kb.source.deprecate`: mark source deprecated.

- Required: `source_id`, `reason`, `decision: "deprecate"`, `reviewed_by`.

### Candidate

`kb.candidate.create`: create pending candidates from sources.

- Required: `source_ids`.
- Resume: `resume_token`, `llm_result`.

`kb.candidate.get`: read candidate.

- Required: `candidate_id`.

`kb.candidate.next_pending`: read next pending candidate.

- Payload: `{}`.

`kb.candidate.defer`: defer candidate.

- Required: `candidate_id`, `decision: "defer"`, `reason`, `reviewed_by`.

### Knowledge

`kb.knowledge.accept`: promote pending candidate to accepted knowledge.

- Required: `candidate_id`, `decision: "accept"`, `reviewed_by`, `title`, `summary`, `content`, `evidence`, `bindto`.
- Optional: `reason`.

`kb.knowledge.merge`: merge pending candidate into existing knowledge.

- Required: `candidate_id`, `target_knowledge_id`, `decision: "merge"`, `reviewed_by`, `summary`, `content`, `evidence`, `bindto`.
- Optional: `reason`.

`kb.knowledge.reject`: reject pending candidate.

- Required: `candidate_id`, `decision: "reject"`, `reason`, `reviewed_by`.

`kb.knowledge.deprecate`: mark accepted knowledge deprecated.

- Required: `knowledge_id`, `reason`, `decision: "deprecate"`, `reviewed_by`.

### Knowledgebase

`kb.knowledgebase.create`: create active knowledgebase and outlines file.

- Required: `title`, `description`, `tags`, `scope`, `default_outline_id`, `outlines`, `review.decision: "approve"`.
- Optional: `knowledgebase_id`.

`kb.knowledgebase.outline.create`: append outline.

- Required: `knowledgebase_id`, `outline`, `review.decision: "approve"`.

`kb.knowledgebase.outline.set_default`: set default outline.

- Required: `knowledgebase_id`, `outline_id`, `review.decision: "approve"`.

`kb.knowledgebase.outline.archive`: archive non-default outline.

- Required: `knowledgebase_id`, `outline_id`, `review.decision: "approve"`.
- Optional: `allow_existing_bindings`.

`kb.knowledgebase.map`: generate left-to-right Mermaid map.

- Optional: `knowledgebase_id`, `output_path`.

### Note

`kb.note.add`: add note.

- Required: `content`.
- Optional: `title`, `note_id`.
- Optional: `needs_llm`; set `true` to force the note-title LLM boundary.
- Resume if `needs_llm`: `resume_token`, `llm_result: {title: <non-empty string>}`.

`kb.note.get`: read note.

- Required: `note_id`.

`kb.note.deprecate`: deprecate note.

- Required: `note_id`, `reason`, `decision: "deprecate"`, `reviewed_by`.

### Index and Clean

`kb.index.rebuild`: rebuild derived indexes.

- Optional: `scope`, object ID, `dry_run`.

`kb.clean.inspect`: read-only schema drift inspection.

- No required payload fields.

## Feishu/Lark Message Commands

After `/kbm:lark-server-start`, incoming Feishu/Lark messages in the user workspace support:

- `help`: show message command syntax.
- `view <id>`: return content for `note-*`, `knowledge-*`, `kb-*`, or `source-*`.
- `list kb`: return `indexes/kb-index.md`.
- `list <kb-id>`: return `indexes/knowledgebase/<kb-id>-knowledge-index.md`.
- `list note`: return `indexes/note-index.md`.
- `map [kb-id]`: call `kb.knowledgebase.map` and send the generated left-to-right Mermaid Markdown file.
- `ask <question>`: run read-oriented Claude Code answer in the workspace.
- `note <content>`: add a note.
- Plain source text, URL, or a single `.md` or `.pdf` file: treat as source input.

If `.lark/settings.json` has `ack_only: true`, the server acknowledges messages only and does not read objects, call Claude Code, run Git, or write KBManager data.
