---
description: Create a new outline for an existing knowledgebase
---

# KBManager Knowledgebase Outline Create

Use `$ARGUMENTS` as optional JSON or text containing `knowledgebase_id` and `input_path`.

Claude Code flow:

1. If `knowledgebase_id` is missing, read `indexes/kb-index.md`, list active KB IDs, and ask the user to choose one.
2. If `input_path` is missing, ask the user for a file path or URL.
3. Read or summarize the file/URL as temporary outline creation context only. Do not create source objects.
4. Use the bundled `knowledgebase-create` prompt style, but generate only one outline draft with `id`, `title`, `description`, `status: active`, and `nodes`.
5. Display the outline draft and wait until the user has replied with approval or edited structured fields; parse the reply into the reviewed outline.
6. After approval, call `kb.knowledgebase.outline.create` with the reviewed outline and `review.decision: "approve"`.
7. Report the updated knowledgebase ID, outline ID, outlines file, and automatic index rebuild result.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/kbmanager_plugin.py" kb.knowledgebase.outline.create '<payload-json>' --pretty
```

Payload:

```json
{
  "knowledgebase_id": "kb-20260527-001-title",
  "outline": {
    "id": "workflow",
    "title": "Workflow",
    "description": "Process-oriented view.",
    "status": "active",
    "nodes": []
  },
  "review": {"decision": "approve"}
}
```

Hard rules:

- Do not edit knowledgebase files directly.
- Do not create source objects from the input.
- Do not set the new outline as default; use `/kbm:knowledgebase-outline-set-default`.
- After success, report the API's automatic `kb.index.rebuild` result.
