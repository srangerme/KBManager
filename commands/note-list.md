---
description: Open or inspect the note index
disable-model-invocation: true
---

# KBManager Note List

Display `indexes/note-index.md` from `${CLAUDE_PROJECT_DIR}` in Claude Code. This command is read-only.

If the index exists, read the file and show the Markdown content directly in Claude Code:

```bash
python3 -c 'import os; from pathlib import Path; print((Path(os.environ["CLAUDE_PROJECT_DIR"]) / "indexes/note-index.md").read_text(encoding="utf-8"))'
```

The note index is a default list view and should hide deprecated notes.

If the index is missing or stale, suggest `/kbm:check`. Do not call `kb.index.rebuild` from this list command.
