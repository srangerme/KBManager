# Claude Code Plugin

KBManager can be installed as a Claude Code plugin. The plugin provides
`kbm-*` skills and an internal JSON payload file helper for calling the KBManager Python API.
It does not expose Claude Code commands, does not use MCP, and does not provide
a public CLI.

## Plugin Contents

The repository root is the plugin root:

- `.claude-plugin/plugin.json`: plugin manifest.
- `skills/kbm-*`: domain skills plus API-specific `references/` files for
  payloads, result fields, rules, Deep Research, and controlled outline updates.
- `scripts/kbmanager_plugin.py`: internal JSON payload file bridge to the `kb.*` API.
- `src/kbmanager/`: KBManager core.
- `system-prompts/`: built-in LLM prompts used by API and workflow boundaries.

The plugin package must not include command files or user workspace data such as
`commands/`, `data/`, `knowledge/`, `candidates/`, `notes/`, or `indexes/`.

## Skills

All KBManager skills use the `kbm-` prefix:

- `kbm-source`: source add and source deprecate workflows.
- `kbm-candidate`: candidate create, get, next pending, and review workflows.
- `kbm-note`: note add, get, list, view, and deprecate workflows.
- `kbm-kb`: knowledgebase create, list, map, outline, and controlled outline YAML update workflows.
- `kbm-maintenance`: init, check, clean inspect, and clean migration workflows.
- `kbm-research-on`: generate a Deep Research prompt from a knowledgebase.
- `kbm-download-paper-pdf`: find and download legal public paper PDFs to `/tmp/kbm-downloads` without using credentials, login, library access, or paywall bypasses.

High-level workflow intent stays in each `SKILL.md`. API payloads, result
fields, resume/review constraints, and hard rules live in API-specific files in
each domain skill's `references/` directory.

Internal LLM steps such as source ingest, candidate creation, note title
generation, clean migration planning, and knowledgebase drafting remain
`system-prompts/` modules triggered by API `needs_llm`.

During ordinary user workflows, Claude Code must treat plugin-provided
`SKILL.md`, `references/`, `system-prompts/`, `src/kbmanager/`,
`scripts/kbmanager_plugin.py`, and other packaged resources as read-only. These
resources may be changed only when the user explicitly asks for plugin
development or maintenance.

`kbm-download-paper-pdf` intentionally does not provide bundled downloader
scripts. Claude Code performs the search and download workflow directly, then
must verify `/tmp/kbm-downloads` and base its final download summary only on
files that actually exist and pass the PDF checks.

## Runtime Flow

Claude Code workflows load the relevant `kbm-*` skills and invoke the helper
when they need a `kb.*` operation:

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py <operation> /path/to/payload.json --pretty
```

Claude Code must write the operation payload as a JSON object file first, then
pass that file path to the helper. The helper imports `src/kbmanager` from the
installed plugin and calls the requested API operation with
`${CLAUDE_PROJECT_DIR}` as the default root. If the API returns `needs_llm`,
Claude Code generates the required `llm_result` from the returned prompt/schema
and resumes the same operation with another JSON payload file. Final
review-gated write operations are intercepted by the bundled PreToolUse hook,
which reads the payload file and asks the user for approval before the helper
command executes.

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
