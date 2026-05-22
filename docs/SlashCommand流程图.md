# Slash Command 流程图

本文描述第一层 slash command 的交互流程。流程只展开到调用第二层 `kb.*` API 为止，不描述 API 内部读写细节。

标记含义：

- `(user)`：用户输入、回复、选择或确认。
- `(interface)`：Claude Code / slash command 编排；review 草案和用户补充内容都通过 Claude Code 交互。
- `(LLM)`：第一层用于意图解析、结果整理、问题展示或问答范围判断。
- `(api)`：第二层 `kb.*` API 调用。
## 1. `/candidate review [candidate-id]`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B{"(interface) 是否提供 candidate ID"}
  B -- 否 --> C["(api) kb.candidate.next_pending"]
  B -- 是 --> D["(api) kb.candidate.get"]
  C --> D
  D --> E["(interface) 用 Claude Code 展示 candidate Markdown"]
  E --> F["(LLM) 生成只读 review 辅助说明"]
  F --> G["(interface) 展示 candidate、辅助说明和处理选项"]
  G --> H["(user) 选择 accept/reject/defer/merge 并输入备注"]
  H --> I{"(interface) 处理方式"}
  I -- accept --> J["(interface) 在 Claude Code 展示 accept 草案"]
  J --> K["(user) 确认或回复修改后的 Markdown"]
  K --> L["(api) kb.knowledge.accept"]
  I -- merge --> M["(interface) 在 Claude Code 展示 merge 草案"]
  M --> N["(user) 确认或回复修改后的 Markdown"]
  N --> O["(api) kb.knowledge.merge"]
  I -- reject --> Q["(api) kb.knowledge.reject"]
  I -- defer --> R["(api) kb.candidate.defer"]
  L --> P["(interface) 展示处理结果"]
  O --> P
  Q --> P
  R --> P
```

## 2. `/check`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用索引重建"]
  B --> C["(api) kb.index.rebuild"]
  C --> D["(interface) 展示更新的索引路径、问题和修复方案"]
```

## 3. `/init`

```mermaid
flowchart TD
  A["(user) 在目标目录输入命令"] --> B["(interface) 以当前调用目录作为初始化目标"]
  B --> C["(api) kb.init"]
  C --> D{"(api) 是否成功"}
  D -- 是 --> E["(interface) 展示创建路径和下一步建议"]
  D -- 否 --> F["(interface) 展示冲突原因，不创建文件"]
```

## 4. `/knowledgebase create`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 收集名称、描述、准入规则和标签"]
  B --> C["(LLM) 生成 knowledgebase Markdown 草案"]
  C --> D["(interface) 在 Claude Code 展示 Markdown 草案"]
  D --> E["(user) 确认或回复修改后的 Markdown"]
  E --> F["(api) kb.knowledgebase.create"]
  F --> G["(interface) 展示 knowledgebase ID 和路径"]
```

## 5. `/knowledgebase list`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 定位 knowledgebase index"]
  B --> C["(interface) 用 Claude Code 展示 knowledgebase index"]
```

## 6. `/lark server start`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用 daemon start"]
  B --> C["(daemon) 按 workspace 进程名停止旧 server"]
  C --> D["(daemon) 用当前 plugin/cache detached 启动 server"]
  D --> E["(interface) 展示 pid、进程名和日志路径"]
```

## 7. `/lark server status`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用 daemon status"]
  B --> C["(daemon) 按 workspace 进程名扫描进程"]
  C --> D["(interface) 展示 running、pid、日志和 settings 路径"]
```

## 8. `/lark server stop`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 调用 daemon stop"]
  B --> C["(daemon) 按 workspace 进程名停止 server"]
  C --> D["(interface) 展示停止的 pid 和日志路径"]
```

## 9. `/note add`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 请求用户在 Claude Code 回复 note Markdown"]
  B --> C["(user) 回复 note 内容"]
  C --> D["(interface) 提取 note 内容"]
  D --> E["(api) kb.note.add"]
  E --> F["(interface) 展示 note ID"]
```

## 10. `/note deprecate <note-id>`

```mermaid
flowchart TD
  A["(user) 输入 note ID 和原因"] --> B["(interface) 请求确认"]
  B --> C{"(user) 确认"}
  C -- 否 --> D["(interface) 取消"]
  C -- 是 --> E["(api) kb.note.deprecate"]
  E --> F["(interface) 展示结果"]
```

## 11. `/note list`

```mermaid
flowchart TD
  A["(user) 输入命令"] --> B["(interface) 定位 note index"]
  B --> C["(interface) 用 Claude Code 展示 note index"]
```

## 12. `/note view <note-id>`

```mermaid
flowchart TD
  A["(user) 输入 note ID"] --> B["(api) kb.note.get"]
  B --> C["(interface) 用 Claude Code 展示 note Markdown"]
```

## 13. `/source add <path>`

```mermaid
flowchart TD
  A["(user) 输入目录/文件/URL"] --> B["(interface) 原样传递输入；URL 不自行下载或导出"]
  B --> C["(api) kb.source.add"]
  C --> D["(interface) 接管 source ingest needs_llm 并 resume"]
  D --> E["(api) kb.candidate.create"]
  E --> F["(interface) 接管 candidate create needs_llm 并 resume"]
  F --> G["(interface) 展示 source 和 candidate ID"]
```

## 14. `/source deprecate <source-id>`

```mermaid
flowchart TD
  A["(user) 输入 source ID 和原因"] --> B["(interface) 展示废弃影响确认"]
  B --> C{"(user) 确认"}
  C -- 否 --> D["(interface) 取消"]
  C -- 是 --> E["(api) kb.source.deprecate"]
  E --> F["(interface) 展示废弃结果"]
```
