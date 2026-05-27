---
name: kbm-research-on
description: Generate a ChatGPT Deep Research prompt from a KBManager knowledgebase definition when the user wants to continue research based on that knowledgebase.
---

# KBManager Research On

Generate a prompt for ChatGPT Deep Research from a KBManager knowledgebase.

## Inputs

- A knowledgebase ID, or
- Markdown content of a `type: knowledge-base` object.

## Rules

- Read only the target knowledgebase object and minimal context needed to identify it.
- Use the knowledgebase `description`, `scope`, and outline as the research boundary.
- Do not write KBManager object files.
- Do not call KBManager write APIs.
- Do not treat derived indexes as facts; indexes may only help locate the object.
- Do not include private workspace content unrelated to the selected knowledgebase.

## Output

Return only the Deep Research prompt. The prompt must ask for:

- research goals derived from the knowledgebase description,
- inclusion and exclusion boundaries derived from `scope`,
- report structure derived from the outline,
- citations for factual claims,
- a final references list for sources used in the research report.
