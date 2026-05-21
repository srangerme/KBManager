---
description: Initialize a KBManager workspace in the current Claude project directory
disable-model-invocation: true
---

# KBManager Init

Initialize KBManager in `${CLAUDE_PROJECT_DIR}`. Treat `$ARGUMENTS` as optional JSON API arguments; default to `{"dry_run": false}` when no arguments are provided.

Run only the bundled helper:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.init '<payload-json>' --pretty
```

Rules:

- Do not create or edit KBManager object files directly.
- If the API returns `failed`, show the structured errors and stop.
- If initialization succeeds, summarize created paths and next actions.
