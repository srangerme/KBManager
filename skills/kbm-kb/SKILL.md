---
name: kbm-kb
description: 创建、查看、映射或维护 KBManager knowledgebase 与 outline，包括 scope、tags、default outline、taxonomy nodes 和 outline YAML edits。仅作为 KB 定义上下文的材料不触发 source 摄取。
---

# KBManager Knowledgebase 与 Outline 工作流

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-kb`。

执行具体 workflow 时，只读取该小节列出的 API reference。

此 skill 覆盖所有 KB 相关工作流：knowledgebase create/list/map，以及 outline create/set-default/archive 和用户明确要求时的 outline YAML 受控维护。

普通用户 workflow 中，不得修改 plugin 提供的 `SKILL.md`、`references/`、
`system-prompts/`、`src/kbmanager/`、`scripts/kbmanager_plugin.py` 或其他版本化资源。
只有用户明确要求进行 plugin 开发或维护时，才允许修改这些资源。

## Knowledgebase 创建

用于创建新的 active knowledgebase 和配套 outlines YAML。

本流程引用：

- `references/kb.knowledgebase.create.md`

### 意图流程图

```mermaid
flowchart TD
  A["(user) path 或 JSON"] --> B["(ask) 收集 input_path 和 title"]
  B --> C["(api) kb.knowledgebase.create"]
  C --> D{"(api) status"}
  D -- needs_llm --> E["(LLM) 按 API llm_request 生成 description/tags/scope/default_outline_id/outlines draft"]
  E --> F["(api) resume kb.knowledgebase.create"]
  F --> G{"(api) status"}
  G -- needs_review --> H["(ask) 在 Claude Code UI 展示 draft"]
  H --> I["(user) approve 或编辑 reviewed payload"]
  I --> J["(api) kb.knowledgebase.create approve"]
  J --> K["(ask) 汇报 KB ID、Markdown path、outlines YAML path 和自动 index rebuild"]
```

1. 收集 title 和 source-like definition context。
3. API 返回 `needs_llm` 时，按返回的 `llm_request` 生成 description、tags、scope、default outline 和 outlines draft，并用同一 resume token 恢复。
4. API 返回 `needs_review` 时，在 Claude Code UI 中展示 draft，包含 scope includes/excludes、default outline、outline nodes 和风险提示。
5. 收集明确批准或编辑后的 reviewed payload。
6. 再次调用 `kb.knowledgebase.create`，携带 reviewed payload 和 `review.decision: approve`。
7. 报告 knowledgebase ID、knowledgebase path、outlines file、created objects 和 next actions。

Knowledgebase create 需要 review gate。

用户给出的 source、file 或 directory 只是临时定义上下文。此工作流不创建 source/candidate，不得调用 `kb.source.add`，不得调用 `kb.candidate.create`，不得写入 `data/raw` 或 `data/cleaned`，也不得把该 input 记录为 candidate/knowledge evidence。

## Knowledgebase 列表和查看

本流程引用：无。此流程只读读取 object files 或 derived indexes。

### 意图流程图

```mermaid
flowchart TD
  A["(user) optional knowledgebase_id"] --> B{"(ask) 是否提供 ID"}
  B -- 否 --> C["(ask) 只读显示 indexes/kb-index.md"]
  B -- 是 --> D["(ask) 只读显示 indexes/knowledgebase/<id>-knowledge-index.md"]
  C --> E["(ask) 如果缺失或过期，建议 check"]
  D --> E
```

- 可以只读读取 object files 或 derived indexes 用于展示。
- 不要将 index text 视为 factual evidence。
- 展示 deprecated、archived 或 inactive 状态时明确标记。
- List/view 不修改 objects，不运行 write APIs。

## Knowledgebase 映射

本流程引用：

- `references/kb.knowledgebase.map.md`

### 意图流程图

```mermaid
flowchart TD
  A["(user) optional knowledgebase_id"] --> B["(api) kb.knowledgebase.map"]
  B --> C["(ask) 读取返回 path/markdown/issues"]
  C --> D{"(ask) code 可用?"}
  D -- 是 --> E["(ask) 打开临时 Markdown map"]
  D -- 否 --> F["(ask) 打印 path 和 markdown"]
  E --> G["(ask) 如有 issues，建议 check"]
  F --> G
```

- 使用 `kb.knowledgebase.map`。
- 可针对单个 knowledgebase ID，或省略 ID 生成全局 map。
- 该 API 生成临时 Mermaid map；不修改 object facts 或 repo-tracked indexes。
- 没有 review gate。
- 报告 map path、warnings、issues 和可展示的 markdown。

## Outline 创建

本流程引用：

- `references/kb.knowledgebase.outline.create.md`

### 意图流程图

```mermaid
flowchart TD
  A["(user) knowledgebase_id + input_path"] --> B{"(ask) 是否缺 KB ID"}
  B -- 是 --> C["(ask) 只读列出 active KB IDs 并询问"]
  B -- 否 --> D["(ask) 读取/概括临时 outline context，不创建 source"]
  C --> D
  D --> E["(ask) 按 KB skill 规则整理单个 outline draft"]
  E --> F["(ask) 展示 outline draft"]
  F --> G["(user) approve 或编辑 reviewed outline"]
  G --> H["(api) kb.knowledgebase.outline.create"]
  H --> I["(ask) 汇报 outline ID 和自动 index rebuild"]
```

- 用于给 active knowledgebase 增加新 outline。
- 需要 knowledgebase ID 和 reviewed outline payload。
- 在 Claude Code UI 中展示 outline title、description、nodes、scope fit 和 node ID 设计。
- 获得明确 approve 后调用 `kb.knowledgebase.outline.create`。
- 需要 review gate。

## 设置默认 Outline

本流程引用：

- `references/kb.knowledgebase.outline.set_default.md`

### 意图流程图

```mermaid
flowchart TD
  A["(user) knowledgebase_id + outline_id"] --> B{"(ask) 是否缺参数"}
  B -- 是 --> C["(ask) 只读列出 KB 或 active outlines 并询问"]
  B -- 否 --> D["(ask) 展示当前 default 和新 default"]
  C --> D
  D --> E["(user) 明确确认 approve"]
  E --> F["(api) kb.knowledgebase.outline.set_default"]
  F --> G["(ask) 汇报 updated default 和自动 index rebuild"]
```

- 用于设置 active outline 为 knowledgebase default outline。
- 需要 knowledgebase ID、outline ID 和明确 approve。
- 调用前确认目标 outline 存在且 active。
- 获得批准后调用 `kb.knowledgebase.outline.set_default`。
- 需要 review gate。

## Outline 归档

本流程引用：

- `references/kb.knowledgebase.outline.archive.md`

### 意图流程图

```mermaid
flowchart TD
  A["(user) knowledgebase_id + outline_id"] --> B{"(ask) 是否缺参数"}
  B -- 是 --> C["(ask) 只读列出 KB 或 active outlines 并询问"]
  B -- 否 --> D{"(ask) 是否 default outline"}
  C --> D
  D -- 是 --> E["(ask) 停止并要求先 set default"]
  D -- 否 --> F["(ask) 检查 accepted knowledge bindings"]
  F --> G{"(ask) 是否存在 bindings"}
  G -- 是 --> H["(ask) 展示 affected knowledge IDs 并请求确认"]
  G -- 否 --> I["(user) approve archive"]
  H --> I
  I --> J["(api) kb.knowledgebase.outline.archive"]
  J --> K["(ask) 汇报 archived outline 和自动 index rebuild"]
```

- 用于 archive non-default outline。
- 需要 knowledgebase ID、outline ID 和明确 approve。
- 归档前检查 binding risk：是否有 accepted knowledge 的 `bindto` 指向该 outline。
- 不能直接 archive default outline；必须先 set another default。
- 如果存在 bindings，除非用户明确接受风险或指定 repair plan，否则不要继续。
- 获得批准后调用 `kb.knowledgebase.outline.archive`。
- 需要 review gate。

## Outline YAML 直接编辑例外

本流程引用：无。此流程是受控 direct-edit exception，不是 `kb.*` API。

仅当用户明确要求编辑/更新/重排/重命名/移动/拆分/合并现有 outline YAML nodes 时使用。这是 LLM 辅助 outline 维护的受控直接编辑例外。

- 不要通过直接编辑创建新 outline；使用 `kb.knowledgebase.outline.create`。
- 不要通过直接编辑设置 default 或 archive；使用对应 API。
- 不要修改 knowledge、candidate、source、note、index 或 source files。
- 定位 knowledgebase Markdown 文件及其 `outlines_file`。
- 确认目标 `outline_id`。
- 搜索 accepted knowledge 中与该 knowledgebase 和 outline 匹配的 `bindto` entries。
- 只编辑目标 outline YAML nodes。
- 对 rename、move、reorder 和大多数 split/merge 情况，保留稳定 node IDs。
- 除非用户明确接受 binding repair，否则不要移除已绑定 node。
- 编辑后通过 `kb.index.rebuild` 或 `/kbm:ask` check workflow 验证。
- 报告 changed node IDs、preserved IDs、removed IDs、binding risks 和建议修复。

## Scope 和 Binding 规则

- Knowledgebase scope 用 `includes` 和 `excludes` 表示边界。
- Outline 是组织结构，不是 evidence。
- Knowledge 归属通过 knowledge object 的 `bindto` 表达，必须引用 kb ID、outline ID、node ID 和 reason。
- Outline change suggestions 不自动修改 outlines；必须走 outline workflow 或 direct-edit exception。
