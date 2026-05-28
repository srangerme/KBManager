# Claude Code Plugin

KBManager can be installed as a Claude Code plugin. The plugin provides
`kbm-*` skills and an internal JSON helper for calling the KBManager Python API.
It does not expose Claude Code commands, does not use MCP, and does not provide
a public CLI.

## Plugin Contents

The repository root is the plugin root:

- `.claude-plugin/plugin.json`: plugin manifest.
- `skills/kbm-*`: operating knowledge for API calls, workflows, rules, Deep Research, and controlled outline updates.
- `scripts/kbmanager_plugin.py`: internal JSON bridge to the `kb.*` API.
- `src/kbmanager/`: KBManager core.
- `system-prompts/`: built-in LLM prompts used by API and workflow boundaries.

The plugin package must not include command files or user workspace data such as
`commands/`, `data/`, `knowledge/`, `candidates/`, `notes/`, or `indexes/`.

## Skills

All KBManager skills use the `kbm-` prefix:

- `kbm-usage`: global object boundaries, API payload/result rules, write boundaries, review gates, and helper invocation rules.
- `kbm-source`: source add and source deprecate workflows.
- `kbm-candidate`: candidate create, get, next pending, and review workflows.
- `kbm-note`: note add, get, list, view, and deprecate workflows.
- `kbm-kb`: knowledgebase create, list, map, outline, and controlled outline YAML update workflows.
- `kbm-maintenance`: init, check, clean inspect, and clean migration workflows.
- `kbm-research-on`: generate a Deep Research prompt from a knowledgebase.
- `kbm-download-paper-pdf`: find and download legal public paper PDFs to `/tmp/kbm-downloads` without using credentials, login, library access, or paywall bypasses.

Internal LLM steps such as source ingest, candidate creation, note title
generation, clean migration planning, and knowledgebase drafting remain
`system-prompts/` modules triggered by API `needs_llm`.

## Runtime Flow

Claude Code workflows load the relevant `kbm-*` skills and invoke the helper
when they need a `kb.*` operation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <operation> '<payload-json>' --pretty
```

The helper imports `src/kbmanager` from the installed plugin and calls the
requested API operation with `${CLAUDE_PROJECT_DIR}` as the default root. If the
API returns `needs_llm`, Claude Code generates the required `llm_result` from
the returned prompt/schema and resumes the same operation. If the API returns
`needs_review`, Claude Code pauses and asks the user for an explicit decision
before any write API continues.

## Permissions

Claude Code may ask before running the helper command because workflows use the
Bash tool. To avoid repeated prompts for KBManager plugin API calls, add a
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
- Major: deleted command support, changed object format, or incompatible user-visible workflow changes.
