---
description: Inspect workspace schema drift and plan a migration
---

# KBManager Clean

Inspect the current workspace layout and object fields, then use Claude Code to plan a migration for current-design schema or directory drift reported by the API.

Claude Code flow:

1. Call the read-only inspection API:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.clean.inspect '{}' --pretty
   ```

2. If the API returns `needs_llm`, use `llm_request` to generate the structured migration plan.
3. Show the full plan to the user and request one explicit confirmation before changing files.
4. Only after confirmation, execute the plan directly in the workspace files. This privileged direct-edit permission applies only to `/clean` migration execution.
5. After migration, call `kb.index.rebuild` and report updated indexes and issues.

Rules:

- Do not edit files before the user confirms the full migration plan.
- Do not overwrite files when the plan reports a target path conflict.
- Do not delete object bodies.
- Other commands must continue to write objects only through KBManager APIs.
