# Slash Command 流程图

本文描述第一层 slash command 的交互流程。流程只展开到调用第二层 `kb.*` API 为止，不描述 API 内部读写细节。

标记含义：

- `(user)`：用户输入、回复、选择或确认。
- `(interface)`：Claude Code / slash command 编排；review 草案和用户补充内容都通过 Claude Code 交互。
- `(LLM)`：第一层用于意图解析、结果整理、问题展示或问答范围判断。
- `(api)`：第二层 `kb.*` API 调用。

## 流程影响审查

| Slash command | 结论 | 说明 |
| --- | --- | --- |
| `/candidate review [candidate-id]` | 修改 | 展示 evidence、`bindto` 和 outline 修改建议；accept/merge 的 reviewed payload 包含 evidence，不自动改 outline。 |
| `/check` | 修改 | 展示 `bindto` 和 outline 节点一致性问题。 |
| `/clean` | 修改 | 特许迁移命令；完整计划经用户整批确认后才允许直接改新设计内的 schema 或目录 drift。 |
| `/init` | 不改主流程 | 初始化流程不受模型变化影响。 |
| `/knowledgebase create <path-or-url>` | 修改 | 创建最小 knowledgebase 后立即从 source-like input 生成 create 阶段字段，但不创建 source。 |
| `/knowledgebase list` | 字段同步 | 只读流程不变，展示内容随索引包含 `scope/outline`。 |
| `/knowledgebase map [knowledgebase-id]` | 修改 | 基于 `outline + bindto`，不再基于 knowledge 层级关系。 |
| `/lark server start/status/stop` | 不改主流程 | server 生命周期不受知识模型变化影响。 |
| `/note add/list/view/deprecate` | 不改主流程 | note 操作流程不受知识模型变化影响。 |
| `/source add <path>` | 修改 | candidate create 阶段先读 knowledgebase 定义，再生成 candidate。 |
| `/source deprecate <source-id>` | 不改主流程 | source 废弃流程不受模型变化影响。 |

## 1. `/candidate review [candidate-id]`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B{"(interface) 是否提供 candidate ID"}
  B -- 否 --> C["(api) kb.candidate.next_pending"]
  B -- 是 --> D["(api) kb.candidate.get"]
  C --> D
  D --> E["(interface) 用 Claude Code 展示 candidate Markdown"]
  E --> F["(LLM) 生成只读 review 辅助说明"]
  F --> G["(interface) 展示 candidate、evidence、bindto、outline 修改建议和处理选项"]
  G --> H{"(interface) 是否存在 outline_change_suggestions"}
  H -- 是 --> I["(user) 交互确认是否采纳或暂缓 outline 建议；不自动写 outline"]
  H -- 否 --> J["(interface) 进入处理选择"]
  I --> J
  J --> K["(user) 选择 accept/reject/defer/merge 并输入备注"]
  K --> L{"(interface) 处理方式"}
  L -- accept --> M["(interface) 在 Claude Code 展示包含 evidence 的 accept 草案"]
  M --> N["(user) 确认或回复修改后的 Markdown"]
  N --> O["(api) kb.knowledge.accept"]
  L -- merge --> P["(interface) 在 Claude Code 展示包含 evidence 的 merge 草案"]
  P --> Q["(user) 确认或回复修改后的 Markdown"]
  Q --> R["(api) kb.knowledge.merge"]
  L -- reject --> S["(api) kb.knowledge.reject"]
  L -- defer --> T["(api) kb.candidate.defer"]
  O --> U["(interface) 展示处理结果"]
  R --> U
  S --> U
  T --> U
```

## 2. `/check`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用索引重建"]
  B --> C["(api) kb.index.rebuild"]
  C --> D["(interface) 展示更新的索引路径、bindto/outline 问题和修复方案"]
```

## 3. `/clean`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用只读 clean inspection"]
  B --> C["(api) kb.clean.inspect"]
  C --> D{"(api) 是否存在迁移差异"}
  D -- 否 --> E["(interface) 展示无需迁移"]
  D -- 是 --> F["(LLM) 生成当前新设计内的 schema 或目录 drift 迁移计划"]
  F --> G["(user) 整批确认"]
  G --> H["(interface) /clean 特许迁移执行：确认后直接修改文件并调用 kb.index.rebuild"]
```

## 4. `/init`

```mermaid
flowchart TD
  A["(user) 在目标目录输入命令"] --> B["(interface) 以当前调用目录作为初始化目标"]
  B --> C["(api) kb.init"]
  C --> D{"(api) 是否成功"}
  D -- 是 --> E["(interface) 展示创建路径和下一步建议"]
  D -- 否 --> F["(interface) 展示冲突原因，不创建文件"]
```

## 5. `/knowledgebase create <path-or-url>`

```mermaid
flowchart TD
  A["(user) 输入命令和 source-like input"] --> B["(interface) 原样保留 input；URL 不自行下载或导出"]
  B --> C["(interface) 询问用户 title"]
  C --> D["(api) kb.knowledgebase.create"]
  D --> E["(api) kb.knowledgebase.init"]
  E --> F["(interface) 接管 needs_llm 并生成 description、tags、scope、outline 草案"]
  F --> G["(api) resume kb.knowledgebase.init 交回 llm_result 校验"]
  G --> H["(interface) 展示 API 返回的 needs_review 草案"]
  H --> I["(user) approve 或回复修改后的 Markdown/结构化字段"]
  I --> J["(api) 带 review 和 reviewed payload 再次 resume kb.knowledgebase.init"]
  J --> K["(interface) 展示 knowledgebase ID、create 阶段字段摘要和索引重建结果"]
```

## 6. `/knowledgebase list`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 定位 knowledgebase index"]
  B --> C["(interface) 用 Claude Code 展示 knowledgebase index"]
```

## 7. `/knowledgebase map [knowledgebase-id]`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(api) kb.knowledgebase.map"]
  B --> C["(interface) 展示基于 outline + bindto 的临时 Mermaid Markdown 文件"]
  C --> D{"(interface) VSCode 是否可用"}
  D -- 是 --> E["(interface) code --reuse-window 打开临时文件"]
  D -- 否 --> F["(interface) 展示临时文件路径和 Markdown 内容"]
```

## 8. `/knowledgebase outline archive [knowledgebase-id] [outline-id]`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 缺少 ID 时列出并要求选择"]
  B --> C["(api) kb.knowledgebase.outline.archive"]
  C --> D["(interface) 展示归档结果和索引重建结果"]
```

## 9. `/knowledgebase outline create [knowledgebase-id] <path-or-url>`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 缺少 KB ID 或输入时要求提供"]
  B --> C["(LLM) 基于临时输入生成 outline 草案"]
  C --> D["(user) review/approve"]
  D --> E["(api) kb.knowledgebase.outline.create"]
```

## 10. `/knowledgebase outline set-default [knowledgebase-id] [outline-id]`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 缺少 ID 时列出并要求选择"]
  B --> C["(user) 确认默认 outline 切换"]
  C --> D["(api) kb.knowledgebase.outline.set_default"]
```

## 8. `/lark server start`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用 daemon start"]
  B --> C["(daemon) 按 workspace 进程名停止旧 server"]
  C --> D["(daemon) 用当前 plugin/cache detached 启动 server"]
  D --> E["(interface) 展示 pid、进程名和日志路径"]
```

## 9. `/lark server status`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用 daemon status"]
  B --> C["(daemon) 按 workspace 进程名扫描进程"]
  C --> D["(interface) 展示 running、pid、日志和 settings 路径"]
```

## 10. `/lark server stop`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用 daemon stop"]
  B --> C["(daemon) 按 workspace 进程名停止 server"]
  C --> D["(interface) 展示停止的 pid 和日志路径"]
```

## 11. `/note add`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 请求用户在 Claude Code 回复 note Markdown"]
  B --> C["(user) 回复 note 内容"]
  C --> D["(interface) 提取 note 内容"]
  D --> E["(api) kb.note.add"]
  E --> F["(interface) 展示 note ID"]
```

## 12. `/note deprecate <note-id>`

```mermaid
flowchart TD
  A["(user) 输入 note ID 和原因"] --> B["(interface) 请求确认"]
  B --> C{"(user) 确认"}
  C -- 否 --> D["(interface) 取消"]
  C -- 是 --> E["(api) kb.note.deprecate"]
  E --> F["(interface) 展示结果"]
```

## 13. `/note list`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 定位 note index"]
  B --> C["(interface) 用 Claude Code 展示 note index"]
```

## 14. `/note view <note-id>`

```mermaid
flowchart TD
  A["(user) 输入 note ID"] --> B["(api) kb.note.get"]
  B --> C["(interface) 用 Claude Code 展示 note Markdown"]
```

## 15. `/source add <path>`

```mermaid
flowchart TD
  A["(user) 输入目录/文件/URL"] --> B["(interface) 原样传递输入；URL 不自行下载或导出"]
  B --> C["(api) kb.source.add"]
  C --> D["(interface) 接管 source ingest needs_llm 并 resume"]
  D --> E["(api) kb.candidate.create"]
  E --> F["(interface) 接管 candidate create needs_llm：先读 knowledgebase 定义再读 source 内容"]
  F --> G["(interface) resume 后展示 source summary/tags、candidate ID、bindto 和 outline 修改建议"]
```

## 16. `/source deprecate <source-id>`

```mermaid
flowchart TD
  A["(user) 输入 source ID 和原因"] --> B["(interface) 展示废弃影响确认"]
  B --> C{"(user) 确认"}
  C -- 否 --> D["(interface) 取消"]
  C -- 是 --> E["(api) kb.source.deprecate"]
  E --> F["(interface) 展示废弃结果"]
```
