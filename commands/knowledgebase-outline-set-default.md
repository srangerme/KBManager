---
description: Set the default outline for a knowledgebase
---

# KBManager Knowledgebase Outline Set Default

Use `$ARGUMENTS` as optional JSON or text containing `knowledgebase_id` and `outline_id`.

Claude Code flow:

1. If `knowledgebase_id` is missing, read `indexes/kb-index.md`, list active KB IDs, and ask the user to choose one.
2. If `outline_id` is missing, read the KB frontmatter or its `outlines_file`, list non-archived outlines, and ask the user to choose one.
3. Show the current default outline and the requested new default.
4. Ask the user for explicit confirmation and wait until the user has replied; parse the reply as the review decision.
5. Call `kb.knowledgebase.outline.set_default` with `review.decision: "approve"`.
6. Report the updated default outline and automatic `kb.index.rebuild` result.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/kbmanager_plugin.py" kb.knowledgebase.outline.set_default '<payload-json>' --pretty
```

Payload:

```json
{
  "knowledgebase_id": "kb-20260527-001-title",
  "outline_id": "workflow",
  "review": {"decision": "approve"}
}
```

Hard rules:

- Do not edit outline files directly for this operation.
- The selected outline must exist and be active.
- Do not modify knowledge `bindto`.
