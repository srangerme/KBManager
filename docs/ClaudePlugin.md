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
/kbm:clean
/kbm:init
/kbm:knowledgebase-create [title]
/kbm:knowledgebase-init <knowledgebase-id> <path-or-url>
/kbm:knowledgebase-list [knowledgebase-id]
/kbm:knowledgebase-map [knowledgebase-id]
/kbm:lark-server-start
/kbm:lark-server-status
/kbm:lark-server-stop
/kbm:note-add
/kbm:note-deprecate <note-id> reason:<reason>
/kbm:note-list
/kbm:note-view <note-id>
/kbm:source-add <path>
/kbm:source-deprecate <source-id> reason:<reason>
```

Most commands are prompt-driven command instructions. They instruct Claude Code
to call the bundled helper, which invokes the second-layer API. Read-only
list/view commands may read workspace index files directly, but must not edit
KBManager object files.

KBManager uses "skill" only for user-triggerable conversational helpers. LLM
steps embedded inside commands, such as source ingest, candidate creation,
candidate review assistance, merge assistance, and knowledgebase initialization,
remain internal system prompts rather than user-facing skills. The planned
`knowledgebase-deep-research-prompt` skill is user-triggerable: it reads a
knowledgebase definition and produces a ChatGPT Deep Research prompt whose final
report must list original reference URLs explicitly.

`/kbm:knowledgebase-init <knowledgebase-id> <path-or-url>` initializes an
existing knowledgebase shell through the `kb.knowledgebase.init` API. The input
is temporary context only; it does not become a source object or a knowledgebase
member.

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

## Feishu/Lark Server

KBManager also provides plugin-managed commands for the user-side Feishu/Lark
message server:

```txt
/kbm:lark-server-start
/kbm:lark-server-status
/kbm:lark-server-stop
```

The server runs as a detached process for the current `${CLAUDE_PROJECT_DIR}`.
`start` stops any existing KBManager Lark server for the same workspace by
process-name marker before launching a new process from the current plugin
installation. This means after a plugin update and `/reload-plugins`, running
`/kbm:lark-server-start` switches the server to the current plugin cache.

User configuration remains in `.lark/settings.json`; runtime state is limited to
`.lark/server.pid` and `.lark/logs/server.log`. The pid file is only auxiliary:
`start`, `stop`, and `status` identify the real process by the workspace-specific
process name.

### Feishu/Lark Message Commands

After the server is running, incoming Feishu/Lark messages are handled inside the
user workspace:

```txt
help
view <id>
list kb
list <kb-id>
list note
ask <question>
note <content>
<plain source text, URL, or one .md/.pdf file>
```

- `help` replies with the supported Feishu/Lark command syntax.
- `view <id>` returns the object content for `note-*`, `knowledge-*`, `kb-*`,
  or `source-*`. Markdown objects are returned as Markdown text. PDF/HTML source
  objects return their metadata and the server also tries to send the original
  source file.
- `list kb` returns `indexes/kb-index.md`; `list <kb-id>` returns
  `indexes/knowledgebase/<kb-id>-knowledge-index.md`; `list note` returns
  `indexes/note-index.md`.
- `ask <question>` runs `claude -p` in the current user workspace and replies
  with plain text. The prompt instructs Claude Code to read workspace files only
  as needed, avoid file writes or Git state changes, and return any required
  clarification as text instead of opening UI confirmation.
- Messages beginning with `note` add a note. Other non-command text is treated
  as source input. A file-only message is treated as source input when the file
  is a single `.md` or `.pdf`.

All text replies are sent as Feishu/Lark rich-text `post` messages first, with
plain-text fallback if rich-text delivery is rejected. Markdown headings, lists,
links, inline styles, and code blocks are rendered through the rich-text path.
Markdown tables are converted into readable indented bullet groups because Lark
post messages do not provide a native table element.

The `.lark/settings.json` `ack_only` flag is a debug switch. When it is `true`,
the server acknowledges every Feishu/Lark message as successful and does not
read objects, call Claude Code, run Git, or write KBManager data.

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
still pause for the user decision before calling write APIs. `/kbm:clean` is
the only migration command that may directly edit workspace files, and only
after showing the generated migration plan and receiving explicit user
confirmation.

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

If the Feishu/Lark server is running, restart it after reloading plugins:

```txt
/kbm:lark-server-start
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
