---
description: Rebuild KBManager indexes and check consistency
disable-model-invocation: true
---

# KBManager Check

Rebuild derived indexes from object files and report consistency issues:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.index.rebuild '{}' --pretty
```

Rules:

- Summarize updated index paths and consistency issues.
- Do not write object files from this command.
- Index writes must happen only through `kb.index.rebuild`.
