# Claude Code Plugin

KBManager can be installed as a Claude Code plugin. The plugin exposes one
namespaced slash command, `/kbm:ask`, and calls the KBManager Python API through
an internal JSON helper. It does not use MCP and does not provide a public CLI.

## Plugin Contents

The repository root is the plugin root:

- `.claude-plugin/plugin.json`: plugin manifest.
- `commands/ask.md`: the only Claude Code plugin command.
- `skills/kbm-*`: operating knowledge for API calls, workflows, rules, Deep Research, and controlled outline updates.
- `scripts/kbmanager_plugin.py`: internal JSON bridge to the `kb.*` API.
- `src/kbmanager/`: KBManager core.
- `system-prompts/`: built-in LLM prompts used by API and workflow boundaries.

The plugin package must not include user workspace data such as `data/`,
`knowledge/`, `candidates/`, `notes/`, or `indexes/`.

## Command Name

After installation, users invoke KBManager through:

```txt
/kbm:ask <request>
```

Examples:

```txt
/kbm:ask initialize this workspace
/kbm:ask add this PDF as a source and create candidates
/kbm:ask show pending candidate review
/kbm:ask rebuild indexes and report consistency issues
```

`/kbm:ask` understands the user intent, loads the relevant `kbm-*` skill, then
calls the internal helper script. Fine-grained lifecycle operations
remain `kb.*` API operations, not separate slash commands.

## Skills

All KBManager skills use the `kbm-` prefix:

- `kbm-basic`: repository structure, object boundaries, file roles, global rules, and direct-edit exceptions.
- `kbm-api-ui`: Claude Code UI-callable APIs, parameters, flowcharts, review gates, and `dry_run`.
- `kbm-source`: source add and source deprecate workflows.
- `kbm-candidate`: candidate create, get, next pending, and review workflows.
- `kbm-note`: note add, get, list, view, and deprecate workflows.
- `kbm-kb`: knowledgebase create, list, and map workflows.
- `kbm-kb-outline`: outline create, set-default, archive, and explicit controlled outline YAML update workflows.
- `kbm-maintenance`: init, check, clean inspect, and clean migration workflows.
- `kbm-research-on`: generate a Deep Research prompt from a knowledgebase.

Internal LLM steps such as source ingest, candidate creation, note title
generation, clean migration planning, and knowledgebase drafting remain
`system-prompts/` modules triggered by API `needs_llm`. Review assistance and
temporary source-ingest prompt guidance are skill/ask workflow rules, not
standalone system prompt files.

## Runtime Flow

1. The user runs `/kbm:ask`.
2. Claude Code loads `commands/ask.md`.
3. `/kbm:ask` selects relevant `kbm-*` skills.
4. The command invokes:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <operation> '<payload-json>' --pretty
   ```

5. The helper imports `src/kbmanager` from the installed plugin and calls the
   requested API operation with `${CLAUDE_PROJECT_DIR}` as the default root.
6. If the API returns `needs_llm`, Claude Code generates the required
   `llm_result` from the returned prompt/schema and resumes the same operation.
7. If the API returns `needs_review`, Claude Code pauses and asks the user for an
   explicit decision before any write API continues.

Every `kb.*` API payload includes `entrypoint` and `dry_run`. Claude Code UI
calls use `entrypoint: "claude_code"`. `dry_run: true` validates without writes,
file moves, or LLM resume.

## Permissions

Claude Code may ask before running the helper command because `/kbm:ask` uses
the Bash tool. To avoid repeated prompts for KBManager plugin API calls, add a
user-level allow rule in `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 */scripts/kbmanager_plugin.py *)"
    ]
  }
}
```

These rules allow helper execution only. They do not bypass KBManager review
gates or direct-edit restrictions.

## Versioning

The plugin version is `.claude-plugin/plugin.json` `version`.

- Patch: wording, docs, prompt clarification, non-breaking fixes.
- Minor: new non-breaking workflow or API orchestration.
- Major: deleted or renamed commands, changed object format, or incompatible
  user-visible workflow changes.

Deleting old slash commands and keeping only `/kbm:ask` requires a major version
bump. After users update and reload plugins, deleted commands should no longer
appear in `/help`.
