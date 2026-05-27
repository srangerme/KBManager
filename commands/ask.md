---
description: Understand a KBManager request and orchestrate the correct API workflow
---

# KBManager Ask

Use `$ARGUMENTS` as the user's KBManager request. This is the only KBManager
slash command. Understand the user's intent, select the relevant `kbm-*` skill,
then call the bundled helper script as needed.

## Required Skills

- Use `kbm-basic` for global write, review, source, URL, index, and deletion rules.
- Use `kbm-api-ui` before calling `scripts/kbmanager_plugin.py` from Claude Code UI
  or explaining UI-callable API payloads.
- Use the matching workflow skill for the user's intent:
  `kbm-source-workflows`, `kbm-candidate-workflows`, `kbm-note-workflows`,
  `kbm-knowledgebase-workflows`, `kbm-kb-outline-workflows`, or
  `kbm-maintenance-workflows`.
- Use `kbm-research-on` when generating a Deep Research prompt from a knowledgebase.
- Use the outline update section of `kbm-kb-outline-workflows` only for direct
  outline YAML updates explicitly requested by the user.

## Core Rules

- Do not create, edit, move, or delete KBManager object files directly.
- Use `kb.*` APIs through `scripts/kbmanager_plugin.py` for object writes.
- The privileged clean migration path may directly edit files only after the full
  migration plan is shown in Claude Code UI and explicitly approved by the user.
- Explicit outline YAML updates through `kbm-kb-outline-workflows` are a separate
  controlled direct-edit exception.
- Do not treat derived indexes as facts.
- Do not physically delete source, note, candidate, knowledge, or knowledgebase objects.
- If an API returns `needs_llm`, generate output matching its returned schema and
  resume the same operation with the same `resume_token`.
- If an API returns `needs_review`, pause in Claude Code UI and collect an explicit
  user decision before calling a write API.
- For URL source input, do not fetch, browse, export, scrape, save, or retry the URL
  in Claude Code. Pass the original URL to `kb.source.add`.

## Helper Invocation

Call the internal JSON helper for `kb.*` operations:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <kb.operation> '<payload-json>' --pretty
```

Payloads must be JSON objects. Read the JSON result and report status, object IDs,
warnings, errors, diffs, and next actions.

Every `kb.*` API payload must include `entrypoint` and `dry_run`. Use
`entrypoint: "claude_code"` when called from Claude Code UI. Set
`dry_run: true` when validating a request without executing writes, file moves,
or LLM resume.

## Intent Workflow

1. Parse the user's request into an intent, required inputs, and likely workflow.
2. Load `kbm-basic`, the relevant API skill, and the matching workflow skill before executing the workflow.
3. If required inputs are missing, ask for them in Claude Code UI.
4. Execute only the API calls allowed by the chosen workflow.
5. Handle `needs_llm` with the API-provided prompt/schema and resume token.
6. Handle `needs_review` in Claude Code UI before any write API continues.
7. Summarize the final result with created, updated, deprecated, rejected, or
   deferred object IDs and any returned warnings or errors.
