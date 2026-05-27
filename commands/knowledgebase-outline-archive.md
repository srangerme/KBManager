---
description: Archive an outline for a knowledgebase
---

# KBManager Knowledgebase Outline Archive

Use `$ARGUMENTS` as optional JSON or text containing `knowledgebase_id` and `outline_id`.

Claude Code flow:

1. If `knowledgebase_id` is missing, read `indexes/kb-index.md`, list active KB IDs, and ask the user to choose one.
2. If `outline_id` is missing, read the KB frontmatter or its `outlines_file`, list active outlines, and ask the user to choose one.
3. If the target is the default outline, stop and ask the user to run `/kbm:knowledgebase-outline-set-default` first.
4. Check whether accepted knowledge is bound to the target outline. If there are bindings, show the affected knowledge IDs, ask for explicit confirmation, and wait until the user has replied; parse the reply as the review decision.
5. Call `kb.knowledgebase.outline.archive` with `review.decision: "approve"`. Include `allow_existing_bindings: true` only if the user explicitly accepted the binding impact.
6. Report the archived outline and automatic `kb.index.rebuild` result.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/kbmanager_plugin.py" kb.knowledgebase.outline.archive '<payload-json>' --pretty
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

- Do not physically delete outline nodes.
- Do not archive the current default outline.
- Do not modify knowledge `bindto`.
