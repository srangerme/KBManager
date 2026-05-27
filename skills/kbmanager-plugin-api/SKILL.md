---
name: kbmanager-plugin-api
description: Use when operating the KBManager Claude Code plugin, invoking `/kbm:*` slash commands, calling the bundled `kb.*` Python API through `scripts/kbmanager_plugin.py`, handling KBManager API `needs_llm` or `needs_review` responses, or answering questions about KBManager plugin APIs, command parameters, review gates, Lark message commands, and safe workspace write boundaries.
---

# KBManager Plugin API

Use this skill as the operating guide for the KBManager Claude Code plugin.

## Core Rules

- Prefer the user-facing `/kbm:*` slash command when the user asks to operate KBManager from Claude Code.
- Call the bundled helper directly only when a slash command instruction requires it or when implementing/debugging plugin behavior:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <kb.operation> '<payload-json>' --pretty
  ```

- Use `${CLAUDE_PROJECT_DIR}` as the user workspace root unless the command explicitly supplies a root.
- Do not create, edit, move, or delete KBManager object files directly. Use `kb.*` APIs for object writes. The only exception is `/kbm:clean` after showing a full migration plan and receiving explicit user confirmation.
- Do not treat files under `indexes/` as facts. Indexes are derived views used for locating and displaying objects.
- Do not physically delete source, note, candidate, knowledge, or knowledgebase objects. Use the relevant deprecate/reject/defer API.
- If an API returns `needs_llm`, generate output matching the returned schema and resume the same operation with the same `resume_token`.
- If an API returns `needs_review`, stop and collect an explicit user decision before calling any write API.
- For URL source inputs, do not fetch, browse, export, scrape, or save the URL in Claude Code. Pass the original URL to `kb.source.add`; the API owns acquisition and failure reports.

## Parameter Reference

Read [references/api-catalog.md](references/api-catalog.md) before invoking or explaining a KBManager command/API that needs parameters. It contains:

- `/kbm:*` slash command syntax.
- `kb.*` operation purpose and payload fields.
- Required and optional parameters.
- Review-gated operations and allowed decisions.
- Lark server commands and Feishu/Lark message commands.

## Review Handling

Require explicit user confirmation before write APIs for:

- Source deprecation.
- Candidate defer.
- Knowledge accept, merge, reject, or deprecate.
- Knowledgebase create.
- Knowledgebase outline create, set default, or archive.
- Note deprecation.

For reviewed content, pass only the user-approved or user-edited payload to the write API. Do not write LLM drafts directly as object facts.

## Reporting

After each operation, report:

- API status and operation name.
- Created, updated, deprecated, rejected, or deferred object IDs.
- Any `warnings`, `errors`, `diffs`, and `next_actions`.
- Any automatic `kb.index.rebuild` result returned by the API. Do not run a separate rebuild after APIs that already rebuilt indexes.
