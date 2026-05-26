---
description: Deprecate a source after explicit user confirmation
---

# KBManager Source Deprecate

Use `$ARGUMENTS` as `<source-id> reason:<reason>` or as JSON payload.

Before calling the API, ask the user to explicitly confirm deprecation if the current message does not already include confirmation. Then call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.source.deprecate '<payload-json>' --pretty
```

Required payload fields:

- `source_id`
- `reason`
- `decision`: `"deprecate"`
- `reviewed_by`

Do not edit source metadata directly. This user review confirmation must identify `reviewed_by`.
After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
