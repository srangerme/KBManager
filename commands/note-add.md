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
   tags: []
   bindings: []
   ---

   ```

2. Wait until the user has replied, then parse the Markdown:
   - Frontmatter `title` is optional; if it is missing or blank, omit `title` from the payload.
   - Frontmatter `tags` is optional and must become a JSON string array.
   - Frontmatter `bindings` is optional and must become a JSON array of objects shaped like `{"type": "source|candidate|knowledge|knowledge-base", "id": "<object-id>"}`.
   - The Markdown body after frontmatter is the required `content`.
3. If the body is empty, stop and ask the user to add note content.
4. Always call `kb.note.add` first with `needs_llm: true` and the parsed `content`, `title` when non-empty, `tags`, and `bindings`.
5. Use the returned `llm_request` to generate a `llm_result` with `title` and optional `summary`, then resume `kb.note.add` with the same payload, `needs_llm: true`, `resume_token`, and `llm_result`.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.note.add '<payload-json>' --pretty
```

Rules:

- Use `bindings` only for existing source, candidate, knowledge, or knowledge-base IDs.
- Never pass `title: ""`; omit blank optional fields.
- Always use the note title/summary LLM flow before writing the note, even when the user provided a title.
- Do not call `kb.note.add` until the user has replied in Claude Code with note content.
- Do not write note files directly.
- After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
