---
description: Start the KBManager Feishu/Lark message server
---

# KBManager Lark Server Start

Start the user-side KBManager Feishu/Lark message server for `${CLAUDE_PROJECT_DIR}`.
The daemon stops any existing KBManager Lark server for this workspace before
starting a new detached process from the current plugin installation.

Run only the bundled daemon:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_lark_server.py" start --root "${CLAUDE_PROJECT_DIR}"
```

Rules:

- Do not create or edit KBManager object files directly.
- Do not run note/source write APIs or Git commands from this slash command.
- Show the returned pid, process name, log path, and any stopped old pids.
