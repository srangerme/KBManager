---
description: Open a Mermaid knowledgebase outline map in VSCode
disable-model-invocation: true
---

# KBManager Knowledgebase Map

Use `$ARGUMENTS` as an optional `knowledgebase_id`. This command is read-only.

- Without an ID, generate a Mermaid map for all active knowledgebase outlines and accepted knowledge bindings.
- With an ID, generate a Mermaid map for that knowledgebase outline and accepted knowledge bound through `bindto`.
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
- If the command reports invalid `bindto`, missing outline nodes, unbound knowledge, or other structure issues, show the `issues` list to the user and suggest `/kbm:check`.
