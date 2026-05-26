---
description: Review a pending candidate and accept, reject, defer, or merge it
---

# KBManager Candidate Review

Use `$ARGUMENTS` as an optional `candidate_id`. If no ID is provided, call `kb.candidate.next_pending`, then `kb.candidate.get`.

Required payload fields:

- `decision` when the user chooses a review action.

Optional payload fields:

- `candidate_id`
- `reason`
- `merge_targets`

Helper invocation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.get '<payload-json>' --pretty
```

For the next pending candidate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.next_pending '{}' --pretty
```

For a specific candidate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.get '{"candidate_id":"<candidate-id>"}' --pretty
```

Review flow:

1. Load the candidate via API.
2. Display the candidate Markdown directly in Claude Code. This is read-only and must not use VSCode.
3. Provide a read-only review summary with evidence status, suggested `bindto`, outline change suggestions, and risks.
4. Ask the user to choose exactly one decision: `accept`, `reject`, `defer`, or `merge`.
5. Do not call any write API until the user confirms the decision.
6. For `reject`, call `kb.knowledge.reject`.
7. For `defer`, call `kb.candidate.defer`.
8. For `accept`, display a reviewed Markdown draft in Claude Code, wait until the user has replied with approval or edits, parse the reviewed payload, then call `kb.knowledge.accept`.
9. For `merge`, ask for the target knowledge ID, display a reviewed merge draft in Claude Code, wait until the user has replied with approval or edits, parse the reviewed payload, then call `kb.knowledge.merge`.

Accept Claude Code flow:

1. Display a Markdown draft in Claude Code with YAML frontmatter and body based on the candidate and review assist:

   ```markdown
   ---
   title: <reviewed title>
   evidence:
     - source_id: <source ID>
       locator: <locator>
       quote: <supporting quote>
   bindto:
     - kb_id: <knowledgebase ID>
       outline_node: <outline node ID or path>
       reason: <binding reason>
   ---

   ## Summary

   <reviewed summary>

   ## Content

   <reviewed knowledge content>
   ```

2. Ask the user to reply with `approve` to use the draft or with edited Markdown frontmatter and body.
3. After the user has replied, parse frontmatter fields `title`, `evidence`, and `bindto`, and the Markdown body sections `Summary` and `Content`. Empty `bindto` must be passed as `[]`, not omitted.
4. Call `kb.knowledge.accept` only with the parsed reviewed content plus `decision: "accept"`.

Merge Claude Code flow:

1. Ask for a target knowledge ID before producing the merge draft.
2. Display the proposed merged title, summary, content, evidence, and suggested `bindto` in Claude Code.
3. Ask the user to reply with `approve` to use the draft or with edited Markdown frontmatter and body.
4. After the user has replied, parse frontmatter fields `title`, `evidence`, and `bindto`, and the Markdown body sections `Summary` and `Content`. Empty `bindto` must be passed as `[]`, not omitted.
5. Call `kb.knowledge.merge` only with the parsed reviewed content, the target knowledge ID, and `decision: "merge"`.

Hard rules:

- Never accept, reject, defer, or merge without explicit user decision.
- For `accept` and `merge`, never call the write API until the user has replied in Claude Code with approval or reviewed content.
- Reviewed `evidence` is part of the accept/merge payload and must remain traceable to the candidate's source evidence.
- Reviewed `bindto` must be `[]` when there is no knowledgebase binding. When present, each item must include an existing `kb_id`, an existing `outline_node`, and a binding reason.
- If the candidate includes `outline_change_suggestions`, show them to the user and ask whether to proceed without changing outline. This command must not modify knowledgebase outline directly and accept/merge APIs must not update outline.
- Never edit candidate or knowledge files directly.
- Never use index content as a fact source.
- After a successful status change, report the API's automatic `kb.index.rebuild` result. Do not run a separate rebuild from the command.
