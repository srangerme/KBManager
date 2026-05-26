---
description: Create and initialize a knowledge base from source-like input
---

# KBManager Knowledgebase Create

Use `$ARGUMENTS` as `<path-or-url>` unless the user supplied JSON. This command creates a minimal knowledgebase shell, then initializes its `description`, `tags`, `scope`, and `outline` from the source-like input.

Claude Code flow:

1. Parse or ask for a non-empty `input_path`.
2. Ask the user for a non-empty `title` unless JSON already supplied one.
3. Call `kb.knowledgebase.create` with `title` and optional `knowledgebase_id`.
4. Call `kb.knowledgebase.init` with the created `knowledgebase_id` and `input_path`.
5. If `input_path` is a URL, do not try to download, open, print, export, scrape, or save the page yourself. Pass the original URL directly to the API.
6. If the response is `needs_llm`, use the returned `llm_request.prompt` and `output_schema_definition` to produce a structured `llm_result` containing `description`, `tags`, `scope`, and `outline`.
7. Resume `kb.knowledgebase.init` with the same `resume_token` and `llm_result`.
8. When the API returns `needs_review`, display the draft in Claude Code and wait for the user to approve or provide edited structured fields.
9. Resume `kb.knowledgebase.init` with the same `resume_token`, `review.decision: "approve"`, and the reviewed payload.
10. Report the knowledgebase ID, initialized fields, path, and automatic `kb.index.rebuild` result.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.create '<payload-json>' --pretty
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.init '<payload-json>' --pretty
```

Required payload fields:

- `title`
- `input_path`

Hard rules:

- This command must not create source objects.
- This command must not write to `data/raw/` or `data/cleaned/`.
- The source-like input is temporary initialization context only and must not be added to source indexes or knowledgebase member views.
- Do not modify knowledge files or knowledgebase member lists directly.
- Do not call the final write resume until the user has approved or edited the reviewed payload in Claude Code.
- URL acquisition is owned by the API. If the API reports failure, report its error and any `data/failed/` path; do not attempt another acquisition method.
- Do not create or edit knowledgebase files directly.
- After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
