---
description: Open a Mermaid knowledge hierarchy map in VSCode
disable-model-invocation: true
---

# KBManager Knowledgebase Map

Use `$ARGUMENTS` as an optional `knowledgebase_id`. This command is read-only.

- Without an ID, generate a Mermaid map for all accepted knowledge.
- With an ID, generate a Mermaid map for accepted knowledge in that knowledgebase.
- The map is written to a temporary Markdown file outside the repository and opened in VSCode.

Call `kb.knowledgebase.map` through the plugin helper:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/kbmanager_plugin.py" kb.knowledgebase.map "{\"knowledgebase_id\": \"${ARGUMENTS}\"}" --pretty
```

After the helper returns JSON:

- Read `path` from the JSON result.
- If `$ARGUMENTS` is empty, pass `null` or omit `knowledgebase_id`; do not pass an empty string.
- Open the generated temporary Markdown file with:

```bash
code --reuse-window '<path-from-result>'
```

- If `code` is not available, print the generated file path and the returned `markdown` content in Claude Code.
- If the command reports hierarchy issues, show the `issues` list to the user and suggest `/kbm:check`.
