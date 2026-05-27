---
name: kbm-knowledgebase-workflows
description: Use for KBManager knowledgebase create, list, and map workflows.
---

# KBManager Knowledgebase Workflows

## Knowledgebase Create

1. Gather title and source-like context.
2. Generate a knowledgebase draft using the internal prompt module.
3. Show description, tags, scope, default outline, and outlines in Claude Code UI.
4. Collect explicit approval or edited reviewed content.
5. Call `kb.knowledgebase.create`.

Knowledgebase create requires a review gate.

## Knowledgebase List

- Read derived indexes or object files for display only.
- Do not treat index text as factual evidence.
- Mark deprecated or archived states when visible.

## Knowledgebase Map

- Call `kb.knowledgebase.map`.
- Has no review gate.
