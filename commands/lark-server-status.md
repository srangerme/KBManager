---
description: Show the KBManager Feishu/Lark message server status
---

# KBManager Lark Server Status

Show whether the KBManager Feishu/Lark message server is running for
`${CLAUDE_PROJECT_DIR}`. Status is determined by process-name scanning, not only
by `.lark/server.pid`.

Run only the bundled daemon:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_lark_server.py" status --root "${CLAUDE_PROJECT_DIR}"
```

Rules:

- Do not create or edit KBManager object files directly.
- Show the running flag, pids, process name, log path, settings path, and pid file value.
