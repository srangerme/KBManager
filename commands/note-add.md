---
description: Add a note to the KBManager workspace
---

# KBManager Note Add

Collect note Markdown through Claude Code. Do not create note files directly; parse the user's reply and pass the payload through the KBManager API.

Claude Code flow:

1. Ask the user to reply in Claude Code with note Markdown. Show this optional frontmatter shape:

   ```markdown
   ---
   title:
   ---

   ```

2. Wait until the user has replied, then parse the Markdown:
   - Frontmatter `title` is optional; if it is missing or blank, omit `title` from the payload.
   - The Markdown body after frontmatter is the required `content`.
3. If the body is empty, stop and ask the user to add note content.
4. Always call `kb.note.add` first with `needs_llm: true` and the parsed `content`, plus `title` when non-empty.
5. Use the returned `llm_request` to generate a `llm_result` with `title`, then resume `kb.note.add` with the same payload, `needs_llm: true`, `resume_token`, and `llm_result`.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.note.add '<payload-json>' --pretty
```

Rules:

- Never pass `title: ""`; omit blank optional fields.
- Always use the note title LLM flow before writing the note, even when the user provided a title.
- Do not call `kb.note.add` until the user has replied in Claude Code with note content.
- Do not write note files directly.
- After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
