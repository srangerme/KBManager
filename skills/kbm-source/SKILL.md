---
name: kbm-source
description: 当用户要求添加、导入、摄取、登记、附加或废弃 KBManager source 时使用此 skill。适用于 source 文件、目录、URL、网页、PDF、HTML、Markdown、原始研究材料、source ingestion、source add、source deprecate，以及把外部或本地材料转为 pending KBManager candidates 的请求。此 skill 专用于 source 生命周期操作；调用 kb.source.add、kb.source.deprecate 或从新 source 创建 candidates 前，应与 kbm-basic 和 kbm-api-ui 配合使用。若用户是在创建 knowledgebase 时提供 source/file/URL 作为定义上下文，使用 kbm-kb，不使用本 source add workflow。
---

# KBManager Source Workflows

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-source`。

## Source Add

用于文件、目录或 URL source 摄取，并随后强制创建 pending candidate。
仅当用户意图是登记 KBManager source 或从材料生成 pending candidates 时使用；
knowledgebase create 的 source-like context 不走此流程。

1. 应用 `kbm-basic`。
2. 使用 `kbm-api-ui`。
3. 对 Claude Code UI，在调用 API 前，可选择通过
   `source-ingest-prompt-rewrite.md` 重写临时用户指导。
4. 调用 `kb.source.add`。
5. 使用 API 提供的 prompt 和 schema 处理 `needs_llm`。
6. source 创建后，始终调用 `kb.candidate.create`。
7. 处理 candidate 创建的 `needs_llm`。
8. 报告 source IDs、candidate IDs、warnings 和下一步操作。

Source add 没有 review gate。此工作流中 candidate 创建是强制的，并且只创建
pending candidates。

## Source Deprecate

用于明确的 source deprecation 请求。

- 需要 Claude Code UI。
- 需要 review gate。
- 只有在获得明确批准后，才调用带 review gate 的 source deprecation API。
