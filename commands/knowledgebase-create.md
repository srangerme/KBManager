---
description: Create a minimal knowledge base shell
---

# KBManager Knowledgebase Create

Use `$ARGUMENTS` as an optional knowledgebase `title`. If no non-empty title is provided, ask the user for the title, then call the API to create a minimal knowledgebase shell. Full `description`, `tags`, `scope`, and `outline` are initialized later by `/kbm:knowledgebase-init <knowledgebase-id> <path-or-url>`.

Claude Code flow:

1. Parse `$ARGUMENTS` as `title`; if it is empty, ask for a non-empty `title`.
2. Call `kb.knowledgebase.create` with `title` and optional `knowledgebase_id`.
3. Report the created knowledgebase ID and path.
4. Tell the user the next step is `/kbm:knowledgebase-init <knowledgebase-id> <path-or-url>` with source-like input.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.create '<payload-json>' --pretty
```

Required payload fields:

- `title`

Do not collect or invent `description`, `scope`, `outline`, or `tags` in this command.
Do not create or edit knowledgebase files directly.
After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
