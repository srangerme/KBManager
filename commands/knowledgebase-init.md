---
description: Initialize a knowledge base shell from source-like input
---

# KBManager Knowledgebase Init

Use `$ARGUMENTS` as `<knowledgebase-id> <path-or-url>` unless the user supplied JSON. This command initializes an existing knowledgebase shell through `kb.knowledgebase.init`.

Required payload fields:

- `knowledgebase_id`
- `input_path`

Optional payload fields:

- `user_instruction`

Flow:

1. Parse or ask for a non-empty `knowledgebase_id` and `input_path`.
2. Call `kb.knowledgebase.init` with those fields.
3. If `input_path` is a URL, do not try to download, open, print, export, scrape, or save the page yourself. Pass the original URL directly to the API.
4. If the response is `needs_llm`, use the returned `llm_request.prompt` and `output_schema_definition` to produce a structured `llm_result` containing `description`, `tags`, `scope`, and `outline`.
5. Resume `kb.knowledgebase.init` with the same `resume_token` and `llm_result`.
6. When the API returns `needs_review`, display the draft in Claude Code and wait for the user to approve or provide edited structured fields.
7. Resume `kb.knowledgebase.init` with the same `resume_token`, `review.decision: "approve"`, and the reviewed payload.
8. Report the knowledgebase ID, initialized fields, path, and automatic `kb.index.rebuild` result.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.init '<payload-json>' --pretty
```

Hard rules:

- This command must not create source objects.
- This command must not write to `data/raw/` or `data/cleaned/`.
- The source-like input is temporary initialization context only and must not be added to source indexes or knowledgebase member views.
- Do not modify knowledge files or knowledgebase member lists directly.
- Do not call the final write resume until the user has approved or edited the reviewed payload in Claude Code.
- URL acquisition is owned by the API. If the API reports failure, report its error and any `data/failed/` path; do not attempt another acquisition method.
