---
name: kbm-kb-outline
description: 当用户要求创建 outline、设置 default outline、archive outline、编辑/更新/重排/重命名/移动/拆分/合并 outline YAML nodes、修复 outline bindings 或维护 knowledgebase 结构时使用此 skill。适用于 outline create、outline set-default、default outline、archive outline、outline YAML、bindto risks、node IDs、层级变化、section trees、taxonomy changes，以及对现有 outline 文件的受控直接编辑。此 skill 仅用于 knowledgebase outline 生命周期和明确的 outline YAML 维护。
---

# KBManager Knowledgebase Outline Workflows

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-kb-outline`。

## Outline Create

- 需要 Claude Code UI。
- 需要明确的 review gate。
- 使用 reviewed outline content 调用 `kb.knowledgebase.outline.create`。

## Outline Set Default

- 需要 Claude Code UI。
- 需要明确的 review gate。
- 获得批准后调用 `kb.knowledgebase.outline.set_default`。

## Outline Archive

- 需要 Claude Code UI。
- 需要明确的 review gate。
- 请求批准前检查 binding risk。
- 获得批准后调用 `kb.knowledgebase.outline.archive`。

## Outline Update Direct-Edit Exception

仅在用户明确要求更新现有 outline YAML 文件时使用。
这是用于 LLM 辅助 outline 维护的受控直接编辑例外。

- 不要通过直接编辑创建新 outline。
- 不要通过直接编辑设置 default 或 archive。
- 不要修改 knowledge、candidate、source、note、index 或 source files。
- 定位 knowledgebase Markdown 文件及其 `outlines_file`。
- 确认目标 `outline_id`。
- 搜索 accepted knowledge 中与该 knowledgebase 和 outline 匹配的 `bindto` entries。
- 只编辑目标 outline YAML nodes。
- 对 rename、move、reorder 和大多数 split/merge 情况，保留稳定的 node IDs。
- 除非用户明确接受 binding repair，否则不要移除已绑定 node。
- 编辑后通过 `/kbm:ask` 或 `kb.index.rebuild` 运行 check。
- 报告 changed node IDs、preserved IDs 和 binding risks。
