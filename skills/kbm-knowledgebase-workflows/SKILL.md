---
name: kbm-knowledgebase-workflows
description: Use this skill for KBManager knowledgebase workflows whenever the user asks to create a knowledgebase, define a knowledgebase scope, list knowledgebases, map a knowledgebase, inspect available knowledgebases, or generate a reviewed knowledgebase draft with title, description, tags, scope, and default outline. Trigger on knowledgebase create/list/map language, KB definition, domain scope, knowledgebase catalog, knowledge map, and approved creation of new KBManager knowledgebase objects. Use outline-specific skill for outline lifecycle or YAML node edits.
---

# KBManager Knowledgebase Workflows

When this skill is used, explicitly tell the user: `Using skill: kbm-knowledgebase-workflows`.

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
