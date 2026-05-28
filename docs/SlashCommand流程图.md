# 单入口流程图

本文描述 `/kbm:ask` 的第一层交互流程。流程只展开到调用第二层 `kb.*`
API 为止，不描述 API 内部读写细节。

标记含义：

- `(user)`：用户输入、回复、选择或确认。
- `(ask)`：`/kbm:ask` 编排。
- `(skill)`：`kbm-*` skill 提供的流程、规则或 API 参考。
- `(LLM)`：意图解析、`needs_llm` 输出生成、review assist 或结果整理。
- `(api)`：第二层 `kb.*` API 调用。

## 1. Claude Code UI 总流程

```mermaid
flowchart TD
  A["(user) /kbm:ask <request>"] --> B["(ask) 解析意图和输入"]
  B --> C["(skill) 读取 kbm-basic"]
  C --> D["(skill) 读取 kbm-api-ui"]
  D --> W["(skill) 读取匹配的 kbm-*-workflows"]
  W --> E{"(ask) 输入是否足够"}
  E -- 否 --> F["(user) 在 Claude Code UI 补充输入"]
  F --> B
  E -- 是 --> I["(api) 调用 kb.* operation"]
  I --> J{"(api) status"}
  J -- needs_llm --> K["(LLM) 按 llm_request 和 schema 生成 llm_result"]
  K --> L["(api) resume 同一 operation"]
  L --> J
  J -- needs_review --> M["(ask) 在 Claude Code UI 展示选项、影响或草案"]
  M --> N["(user) 确认、选择或提交 reviewed payload"]
  N --> O["(api) 调用 review-gated write operation 或 resume"]
  O --> J
  J -- success/failed/partial --> Z["(ask) 汇报结果"]
```

## 2. 旧 Slash Command 到 Skill 的映射

旧的细粒度 slash command 不再作为入口暴露，只作为 `/kbm:ask` 意图和 workflow skill 的历史流程来源。

| 旧流程 | 当前承载 |
| --- | --- |
| source add / source deprecate | `kbm-source` |
| candidate review | `kbm-candidate` |
| note add / note deprecate / note list / note view | `kbm-note` |
| knowledgebase create / knowledgebase list / knowledgebase map | `kbm-kb` |
| knowledgebase outline create / set-default / archive | `kbm-kb-outline` |
| init / check / clean | `kbm-maintenance` |

## 3. Source Add

```mermaid
flowchart TD
  A["(user) source file/path/url"] --> B{"(ask) 是否带 user_prompt"}
  B -- 是 --> C["(LLM) rewrite source ingest prompt"]
  C --> D["(user) 确认或修改 prompt fragment"]
  D --> E["(api) kb.source.add"]
  B -- 否 --> E
  E --> G["(LLM) source ingest needs_llm"]
  G --> H["(api) resume kb.source.add"]
  H --> I["(api) kb.candidate.create"]
  I --> J["(LLM) candidate create needs_llm"]
  J --> K["(api) resume kb.candidate.create"]
  K --> L["(ask) 展示 source/candidate ID、bindto 和 outline suggestions"]
```

## 4. Review-Gated Workflows

```mermaid
flowchart TD
  A["(ask) 计划 review-gated workflow"] --> D["(ask) 展示影响、选项或草案"]
  D --> E["(user) 明确确认、选择或提交 reviewed payload"]
  E --> F["(api) 调用 matching review-gated operation"]
  F --> G["(ask) 汇报结果"]
```

Review-gated workflows include source deprecate, candidate defer, knowledge
accept/reject/merge/deprecate, knowledgebase create, outline create/set-default/archive,
note deprecate, and clean migration execution.

## 5. Read-Only And Utility Workflows

```mermaid
flowchart TD
  A["(ask) read-only or utility intent"] --> B{"(ask) operation"}
  B -- list/view --> C["(ask) 只读读取对象或索引用于展示"]
  B -- map --> D["(api) kb.knowledgebase.map"]
  B -- check --> E["(api) kb.index.rebuild"]
  B -- init --> F["(api) kb.init"]
  C --> H["(ask) 汇报结果"]
  D --> H
  E --> H
  F --> H
```

Read-only display may use indexes for locating and displaying objects, but indexes
are not factual evidence and must not be written back into object facts.
