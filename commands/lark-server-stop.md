---
description: Stop the KBManager Feishu/Lark message server
disable-model-invocation: true
---

# KBManager Lark Server Stop

Stop the KBManager Feishu/Lark message server for `${CLAUDE_PROJECT_DIR}`.
The daemon finds the server by process name for this workspace and cleans up
`.lark/server.pid`.

Run only the bundled daemon:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_lark_server.py" stop --root "${CLAUDE_PROJECT_DIR}"
```

Rules:

- Do not create or edit KBManager object files directly.
- Show the process name, stopped pids, and log path.
