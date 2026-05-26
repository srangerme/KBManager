---
name: knowledgebase-deep-research-prompt
description: Generate a ChatGPT Deep Research prompt from a KBManager knowledgebase definition. Use when the user provides a knowledgebase ID or Markdown and wants a research prompt grounded in that knowledgebase description, scope, and outline.
---

# Knowledgebase Deep Research Prompt

Generate a prompt for ChatGPT Deep Research from a KBManager knowledgebase definition.

## Inputs

- A knowledgebase ID, or
- The Markdown content of a `type: knowledge-base` object.

## Rules

- Read only the target knowledgebase object and any minimal context needed to identify it.
- Use the knowledgebase `description`, `scope`, and `outline` as the research boundary.
- Do not write KBManager object files.
- Do not call KBManager write APIs.
- Do not treat derived indexes as facts; indexes may only help locate the object.
- Do not include private workspace content unrelated to the selected knowledgebase.
- Require the final report to include a references section listing original source URLs explicitly.

## Output

Return only the Deep Research prompt. The prompt must ask for:

- Research goals derived from the knowledgebase description.
- Inclusion and exclusion boundaries derived from `scope`.
- A report structure derived from `outline`.
- Citations for factual claims.
- A final references list with original URLs.
