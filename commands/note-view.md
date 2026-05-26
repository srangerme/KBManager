---
description: View a note by ID
---

# KBManager Note View

Use `$ARGUMENTS` as the note ID. Call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.note.get '{"note_id": "<note-id>"}' --pretty
```

If the API returns `success`, read `note.path` from the JSON result and display
the complete note Markdown content directly in Claude Code:

```bash
python3 -c 'import os, sys; from pathlib import Path; print((Path(os.environ["CLAUDE_PROJECT_DIR"]) / sys.argv[1]).read_text(encoding="utf-8"))' '<note.path>'
```

Rules:

- Report the displayed note path.
- Show the full Markdown file content by default, including frontmatter and body.
- Do not replace the note body with a summary.
- If reading the file fails, show the note path and the read error.
- Do not edit note files.
