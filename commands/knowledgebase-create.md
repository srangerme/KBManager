---
description: Create and initialize a knowledge base from source-like input
---

# KBManager Knowledgebase Create

Use `$ARGUMENTS` as `<path-or-url>` unless the user supplied JSON. This command drafts a full knowledgebase definition from source-like input, asks for user review, then creates the knowledgebase in one API call.

Claude Code flow:

1. Parse or ask for a non-empty `input_path`.
2. Ask the user for a non-empty `title` unless JSON already supplied one.
3. Read or summarize the input material as temporary creation context only. If `input_path` is a URL, use it as source-like context for drafting; do not create a source object.
4. Use the bundled `knowledgebase-create` system prompt to produce a structured draft containing `description`, `tags`, `scope`, `default_outline_id`, and `outlines`.
5. Display the draft in Claude Code and wait for the user to approve or provide edited structured fields.
6. After user approval, call `kb.knowledgebase.create` with `title`, optional `knowledgebase_id`, the reviewed fields, and `review.decision: "approve"`.
7. Report the knowledgebase ID, Markdown path, outlines YAML path, and automatic `kb.index.rebuild` result.

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.create '<payload-json>' --pretty
```

Required payload fields:

- `title`
- `review`
- `description`
- `tags`
- `scope`
- `default_outline_id`
- `outlines`

Optional payload fields:

- `knowledgebase_id`

Hard rules:

- This command must not create source objects.
- This command must not write to `data/raw/` or `data/cleaned/`.
- The source-like input is temporary creation context only and must not be added to source indexes or knowledgebase member views.
- Do not modify knowledge files or knowledgebase member lists directly.
- Do not call `kb.knowledgebase.create` until the user has replied with the title and approved or edited the reviewed payload in Claude Code.
- Do not create or edit knowledgebase files directly.
- After success, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
