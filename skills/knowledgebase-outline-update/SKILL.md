---
name: knowledgebase-outline-update
description: Use when updating an existing KBManager knowledgebase outline YAML file in Claude Code: add, rename, move, split, merge, reorder, or remove outline nodes while preserving stable node IDs, bindto validity, manifest consistency, and KBManager checkability. Use only for outline updates, not for creating outlines, setting default outlines, or archiving outlines.
---

# KBManager Outline Update

Update existing outline nodes by editing the KBManager `-outlines.yml` file. This skill is installed with the KBManager Claude Code plugin.

## Boundaries

- Do not create a new outline. Use `/kbm:knowledgebase-outline-create`.
- Do not set the default outline. Use `/kbm:knowledgebase-outline-set-default`.
- Do not archive an outline. Use `/kbm:knowledgebase-outline-archive`.
- Do not modify knowledge, candidate, source, note, or index files directly.
- Do not use Mermaid or Markdown as an outline source of truth.

## Workflow

1. Locate the KB Markdown file under `knowledge/bases/`.
2. Read its `outlines_file` value and open the matching same-name `-outlines.yml`.
3. Confirm the target `outline_id`.
4. Search accepted knowledge for `bindto` entries matching `kb_id + outline_id`.
5. Edit only the target outline nodes in `-outlines.yml`.
6. If outline metadata changes (`title`, `description`, `status`), also sync the KB frontmatter `outlines` manifest.
7. Run `/kbm:check` or the plugin helper operation `kb.index.rebuild` after editing.
8. Report changed node IDs, preserved IDs, and any bindto risks.

## Node ID Rules

- Rename: change `title` or `summary`, keep `id`.
- Move or reorder: keep `id`.
- Split: keep the original `id` on the child that best preserves the old meaning; create new IDs only for genuinely new concepts.
- Merge: avoid deleting bound node IDs. Prefer keeping one node and moving content into it.
- Remove: do not remove a node with existing `bindto` unless the user explicitly accepts that follow-up binding repair is needed.

## YAML Shape

```yaml
kb_id: kb-20260527-001-title
default_outline_id: canonical
outlines:
  - id: canonical
    title: Main Outline
    description: Default structure
    status: active
    nodes:
      - id: sec-1
        title: Section 1
        summary: ""
        children: []
```

Each bindable node must be a mapping with an explicit non-empty `id`.
