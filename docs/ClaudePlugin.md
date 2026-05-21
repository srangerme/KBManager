# Claude Code Plugin

KBManager can be installed as a Claude Code plugin. The plugin provides
namespaced slash commands and calls the KBManager Python API from the plugin
package. It does not use MCP and does not provide a public CLI.

## Plugin Contents

The repository root is the plugin root:

- `.claude-plugin/plugin.json`: plugin manifest.
- `commands/*.md`: Claude Code plugin commands.
- `scripts/kbmanager_plugin.py`: internal command bridge to the Python API.
- `scripts/register_marketplace.py`: registers this plugin in a local
  marketplace.
- `src/kbmanager/`: KBManager core.
- `system-prompts/`: built-in LLM prompts.

The plugin package must not include user workspace data such as `data/`,
`knowledge/`, `candidates/`, `notes/`, or `indexes/`.

## Command Names

Claude Code namespaces plugin commands with the plugin name. After installation,
commands are invoked as:

```txt
/kbm:candidate-review [candidate-id]
/kbm:check
/kbm:init
/kbm:knowledgebase-create
/kbm:knowledgebase-list [knowledgebase-id]
/kbm:note-add
/kbm:note-deprecate <note-id> reason:<reason>
/kbm:note-list
/kbm:note-view <note-id>
/kbm:source-add <path>
/kbm:source-deprecate <source-id> reason:<reason>
```

Most commands are prompt skills. They instruct Claude Code to call the bundled
helper, which invokes the second-layer API. Read-only list/view commands may
read workspace index files directly, but must not edit KBManager object files.

## First Install

From Claude Code, add the local marketplace directory and install the plugin:

```bash
python3 /home/sranger/codes/sranger/KBManager/scripts/register_marketplace.py
```

The script writes the marketplace manifest and creates
`/home/sranger/codes/claude-code-marketplace/plugins/kbm` as a symlink to
this repository. Claude Code requires local plugin sources to be relative to the
marketplace root.

```txt
/plugin marketplace add /home/sranger/codes/claude-code-marketplace
/plugin install kbm@sranger-marketplace
/reload-plugins
```

For development without installing, launch Claude Code with:

```bash
claude --plugin-dir <path-to-kbmanager-repo>
```

Then run `/help` and verify the `kbm:*` commands are listed.

After installing the plugin, initialize a user workspace from the target project
directory:

```txt
/kbm:init
```

The workspace files created by `kb.init` are user data. They remain in the user
project and are not part of the plugin installation.

## Runtime Flow

1. The user runs a `kbm:*` command.
2. Claude Code loads the command instructions from the installed plugin.
3. The command invokes:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <operation> '<payload-json>'
   ```

4. The helper imports `src/kbmanager` from the installed plugin and calls the
   requested API operation with `${CLAUDE_PROJECT_DIR}` as the default root.
5. If the API returns `needs_llm`, Claude Code generates the required
   `llm_result` from `llm_request.prompt` and resumes the same API operation.
6. If the API returns `needs_review`, Claude Code pauses and asks the user for an
   explicit decision before calling write APIs.

## Permissions

Claude Code may ask before running the helper command because slash commands use
the Bash tool to execute `scripts/kbmanager_plugin.py`. To avoid repeated prompts
for KBManager plugin calls, add a user-level allow rule in
`~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 */scripts/kbmanager_plugin.py *)"
    ]
  }
}
```

Use a user-level setting rather than committing project-local personal
permissions. This only allows Claude Code to run the KBManager plugin helper; it
does not bypass KBManager review gates. Commands that return `needs_review`,
request reviewed content in Claude Code, or require explicit confirmation must
still pause for the user decision before calling write APIs.

## Versioning

The plugin version is `.claude-plugin/plugin.json` `version`.

- Patch: command wording, docs, non-breaking fixes.
- Minor: new commands or non-breaking API orchestration.
- Major: deleted or renamed commands, changed object format, or incompatible
  user-visible workflow changes.

Bump the version for every release. If the version does not change, Claude Code
may skip plugin updates.

When deleting a command, remove the file from `commands/`, bump the version, and
document the removal in release notes. After users update and reload plugins,
the deleted command should no longer appear in `/help`.

## Update

For normal updates:

```txt
/plugin marketplace update sranger-marketplace
/plugin update kbm@sranger-marketplace
/reload-plugins
```

If Claude Code reports `Plugin "kbm" is not installed` while updating an old
KBManager install, the local install was recorded under the legacy marketplace
name `kbmanager`. Reinstall under the current `kbm` plugin identity:

```txt
/plugin uninstall kbmanager@sranger --keep-data
/plugin marketplace update sranger-marketplace
/plugin install kbm@sranger-marketplace
/reload-plugins
```

If update state is confusing, reinstall while preserving data:

```txt
/plugin uninstall kbm@sranger-marketplace --keep-data
/plugin install kbm@sranger-marketplace
/reload-plugins
```

Claude Code copies installed plugins into a versioned cache. Old versions may
remain on disk temporarily, but they are not active after the new version is
installed and plugins are reloaded.

## Uninstall

Uninstall the plugin with:

```txt
/plugin uninstall kbm@sranger-marketplace --keep-data
/reload-plugins
```

After uninstall:

- `kbm:*` commands disappear.
- Plugin cache and persistent plugin data may be pruned by Claude Code.
- User workspace data remains untouched.

KBManager does not provide an automatic command to delete user knowledge data.
If a user wants to remove a knowledge workspace, they must delete that project
data explicitly.

## Data Boundary

Plugin install, update, and uninstall affect only Claude Code plugin state. User
knowledge data lives only in the user workspace:

- `data/`
- `knowledge/`
- `candidates/`
- `notes/`
- `indexes/`

The plugin must not write user objects to `${CLAUDE_PLUGIN_ROOT}`,
`${CLAUDE_PLUGIN_DATA}`, marketplace directories, or source repositories.
