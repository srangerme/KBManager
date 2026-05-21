---
description: Create a reviewed knowledge base
---

# KBManager Knowledgebase Create

Collect title, description, acceptance criteria, optional tags, and optional body from the user. Generate a Markdown draft, display it in Claude Code for user review, then call the API only after the user has replied with approval or reviewed content.

Claude Code flow:

1. Display this Markdown draft shape in Claude Code:

   ```markdown
   ---
   title: <title>
   description: <description>
   acceptance_criteria: <acceptance criteria>
   tags: []
   ---

   <optional reviewed body>
   ```

2. Ask the user to reply with `approve` to use the draft or with edited Markdown frontmatter and body.
3. After the user has replied, parse frontmatter fields `title`, `description`, `acceptance_criteria`, `tags`, and the Markdown body.
4. Ask for explicit approval if the user has not already approved creation.
5. Call `kb.knowledgebase.create` only with the parsed reviewed content plus `decision: "approve"` and `reviewed_by: "user"`.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.create '<payload-json>' --pretty
```

Required approved payload fields:

- `title`
- `description`
- `acceptance_criteria`
- `decision`: `"approve"`
- `reviewed_by`: `"user"`

Do not call `kb.knowledgebase.create` until the user has replied in Claude Code with approval or reviewed content.
Do not create or edit knowledgebase files directly.
After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
