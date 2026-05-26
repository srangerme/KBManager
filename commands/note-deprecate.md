---
description: Deprecate a note after explicit user confirmation
---

# KBManager Note Deprecate

Use `$ARGUMENTS` as `<note-id> reason:<reason>` or as JSON payload. Ask for explicit confirmation if it is missing.

Call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.note.deprecate '<payload-json>' --pretty
```

Required payload fields:

- `note_id`
- `reason`
- `decision`: `"deprecate"`

Do not edit or move note files directly.
After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
