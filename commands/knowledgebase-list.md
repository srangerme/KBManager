---
description: Open or inspect the knowledgebase index
disable-model-invocation: true
---

# KBManager Knowledgebase List

Use `$ARGUMENTS` as an optional `knowledgebase_id`. This command is read-only.

- Without an ID, display `indexes/kb-index.md`.
- With an ID, display `indexes/knowledgebase/<id>-knowledge-index.md`.

Read the selected index and show the Markdown content directly in Claude Code:

```bash
python3 -c 'import os, sys; from pathlib import Path; print((Path(os.environ["CLAUDE_PROJECT_DIR"]) / sys.argv[1]).read_text(encoding="utf-8"))' '<selected-index-path>'
```

- These default list views should hide deprecated knowledgebase and knowledge entries.
- If the index is missing or stale, suggest `/kbm:check`.
- Do not call `kb.index.rebuild` from this list command.
