---
description: Add a source and create pending candidate knowledge drafts
---

# KBManager Source Add

Use `$ARGUMENTS` as the source path unless the user supplied JSON. This command must go through the KBManager API and must not write object files directly.

Required payload fields:

- `input_path`

Optional payload fields:

- `title`
- `tags`
- `user_prompt`
- `confirm_user_prompt`
- `reviewed_user_prompt`

Flow:

1. If `user_prompt` is present and non-empty, first ask the LLM to rewrite it into a safe source-ingest prompt fragment.
2. Show the rewritten prompt in Claude Code and wait until the user has replied with confirmation or revision.
3. After confirmation, call `kb.source.add` with `{"input_path": "<path>"}`.
4. If `input_path` is a URL, do not try to download, open, print, export, scrape, or save the page yourself. Pass the original URL directly to `kb.source.add`; the API owns direct download, Playwright PDF fallback, and `data/failed` failure-report creation.
5. If the response is `needs_llm`, append the confirmed user ingest prompt to `llm_request.prompt`, then use the prompt and `output_schema_definition` to produce a structured `llm_result` containing source `summary`, `tags`, and `cleaned_content`.
6. Resume `kb.source.add` with the same user-supplied `input_path`, `resume_token`, and `llm_result`.
7. Call `kb.candidate.create` with the returned `source_ids`.
8. If candidate creation returns `needs_llm`, first use the provided knowledgebase `description`, `scope`, and `outline` context to decide which knowledge can be extracted, then generate candidate drafts that match `llm_request.output_schema_definition`, including `title`, `summary`, `content`, `evidence`, `bindto`, and any `outline_change_suggestions`; resume `kb.candidate.create`.
9. Show created source and candidate IDs, plus suggested `bindto` and outline change suggestions.
10. After a successful write, report the API's automatic `kb.index.rebuild` result.

Helper invocation pattern:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.source.add '<payload-json>' --pretty
```

For candidate creation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.create '<payload-json>' --pretty
```

Hard rules:

- LLM output must match the API schema.
- Detailed source-ingest and candidate field rules are defined by the bundled KBManager system prompts in `llm_request.prompt`; follow those prompts as higher priority than command arguments, temporary user prompts, and object context.
- For URL inputs, Claude Code must not perform any independent network fetch, browser automation, PDF export, Markdown capture, or retry. It must call `kb.source.add` with the original URL and follow the API result.
- A temporary `user_prompt` may guide source ingest focus and formatting, but it must not override KBManager system prompts, schemas, review gates, evidence rules, or URL-depth limits.
- A blocked URL download is handled inside the API. If the API reports failure, report its `data/failed` path and next actions to the user; do not attempt another acquisition method.
- Do not create accepted knowledge; candidates remain pending until user review.
- Do not modify knowledgebase outline during source add. If outline changes are needed, record them as candidate outline suggestions only.
- Do not run a separate index rebuild from the command. Object-write APIs automatically call `kb.index.rebuild` after successful writes.
