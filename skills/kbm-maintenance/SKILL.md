---
name: kbm-maintenance
description: 初始化、检查、重建索引、检查 layout/schema drift，或执行已批准的 clean migration。仅覆盖 workspace 维护，不处理普通对象内容编辑。
---

# KBManager Maintenance 工作流

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-maintenance`。

执行具体 workflow 时，只读取该小节列出的 API reference。

API 调用硬规则：调用任何 `kb.*` API 前，必须先把 payload 写成 JSON object 文件，再把该文件路径传给 `scripts/kbmanager_plugin.py`；不得在命令行直接传 JSON 字符串。

此 skill 覆盖 init、check/index rebuild、clean inspect 和 clean migration execution。

普通用户 workflow 中，不得修改 plugin 提供的 `SKILL.md`、`references/`、
`system-prompts/`、`src/kbmanager/`、`scripts/kbmanager_plugin.py` 或其他版本化资源。
只有用户明确要求进行 plugin 开发或维护时，才允许修改这些资源。

## 初始化

本流程引用：

- `references/kb.init.md`

硬规则：调用任何 API 前，必须先读取本流程引用中对应的 references/ 文件确认输入载荷字段名，不得使用 result 输出字段名反推 payload。

### 意图流程图

```mermaid
flowchart TD
  B --> C["(api) kb.init"]
  C --> D{"(api) status"}
  D -- failed --> E["(ask) 展示 structured errors 并停止"]
  D -- success --> F["(ask) 汇报 created paths 和 next actions"]
```

- 使用 `kb.init` 初始化 workspace structure。
- 没有 review gate。
- 实际执行不得覆盖已有用户文件；初始化必须幂等。
- 报告 created structure、existing paths、conflicts、warnings 和 next actions。

## Check 和 Index Rebuild

本流程引用：

- `references/kb.index.rebuild.md`

硬规则：调用任何 API 前，必须先读取本流程引用中对应的 references/ 文件确认输入载荷字段名，不得使用 result 输出字段名反推 payload。

### 意图流程图

```mermaid
flowchart TD
  A["(user) check/rebuild indexes"] --> B["(api) kb.index.rebuild"]
  B --> C["(ask) 汇报 updated index paths"]
  C --> D["(ask) 汇报 consistency issues，包括 invalid bindto 和 missing outline nodes"]
  D --> E["(ask) 不写 object files"]
```

- 使用 `kb.index.rebuild`。
- 将该操作视为 consistency checking 和 derived index rebuilding。
- 可使用 `scope` 和 `object_id` 限定范围。
- 除非用户请求单独 reviewed workflow，否则不要自动修复 object files。

## Clean Inspect 和 Migration

本流程引用：

- `references/kb.clean.inspect.md`
- `references/kb.index.rebuild.md`

硬规则：调用任何 API 前，必须先读取本流程引用中对应的 references/ 文件确认输入载荷字段名，不得使用 result 输出字段名反推 payload。

### 意图流程图

```mermaid
flowchart TD
  A["(user) clean/migrate"] --> B["(api) kb.clean.inspect"]
  B --> C{"(api) status"}
  C -- success --> D["(ask) 汇报无需迁移"]
  C -- needs_llm --> E["(LLM) 按 API llm_request 生成 structured migration plan"]
  E --> F["(ask) 展示完整 migration plan"]
  F --> G{"(user) 是否整批确认"}
  G -- 否 --> H["(ask) 停止，不修改文件"]
  G -- 是 --> I["(ask) 按批准 plan 直接执行 clean migration"]
  I --> J["(api) kb.index.rebuild"]
  J --> K["(ask) 汇报 updated indexes 和 remaining issues"]
```

- 使用 `kb.clean.inspect` 执行只读 layout/schema inspection。
- 没有 review gate。
- 不直接修改 object files。
- 如果无差异，报告不需要 migration plan。
- 如果有差异，API 可返回 `needs_llm` 生成 clean migration plan。
- 报告 differences、warnings、migration_required 和 next actions。
- 只有在完整 migration plan 已展示在 Claude Code UI 且用户明确批准后，才可以执行。
- Clean migration execution 是受控 direct-edit exception。
- 执行时严格按 approved plan 修改，不夹带无关重构。
- 不物理删除业务对象，除非 approved plan 明确处理非对象临时/派生产物且不会破坏引用链。
- 执行后运行 `kb.index.rebuild` 或等价 check，报告 changed paths、remaining issues 和 warnings。

## 边界

- Maintenance workflows 负责结构、一致性、索引和迁移，不负责普通 source/candidate/knowledge/note/KB 内容编辑。
- Indexes 是派生文件；不要把 index 内容作为事实写回 objects。
- Clean inspect 的 LLM plan 不是用户批准；必须再收集明确 approval。
