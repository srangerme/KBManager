---
name: kbm-candidate-workflows
description: Use this skill for KBManager candidate workflows whenever the user asks to create candidates from sources, fetch a candidate, show the next pending item, review pending knowledge, accept, reject, defer, merge, approve, edit reviewed payloads, or process candidate decisions. Trigger on candidate create/get/next_pending/review/defer/reject/accept/merge language, pending candidate queues, review items, evidence-backed candidate content, and converting candidates into accepted knowledge. This skill governs candidate lifecycle actions and review-gated candidate decisions.
---

# KBManager Candidate Workflows

When this skill is used, explicitly tell the user: `Using skill: kbm-candidate-workflows`.

## Candidate Create

- Usually follows source add.
- Call `kb.candidate.create` with source IDs.
- Handle `needs_llm` using the API-provided prompt and schema.
- Creates pending candidates only.
- Has no review gate.

## Candidate Get Or Next Pending

- Use `kb.candidate.get` for a specific candidate.
- Use `kb.candidate.next_pending` from Claude Code UI when the user asks for the
  next review item.
- Treat both as read-only.

## Candidate Review

Use when the user wants to accept, reject, defer, merge, or otherwise review a
candidate.

1. Retrieve the candidate.
2. Optionally generate read-only review assistance.
3. Show candidate content, evidence, bindto suggestions, and options in Claude
   Code UI.
4. Collect explicit user decision or edited reviewed payload.
5. Call the matching review-gated API.
6. Report accepted, rejected, deferred, or merged object IDs and warnings.
