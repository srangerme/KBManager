# KBManager UI API 目录

此目录用于 Claude Code UI 调用。

## 全局 Payload 字段

每个 `kb.*` API payload 都需要以下两个字段：

```yaml
entrypoint: claude_code
dry_run: false
```

- `dry_run: true` 会验证 payload shape、entrypoint permission、object existence、
  state preconditions 和 review gate requirements。
- Dry run 永远不会写入 object files、移动文件或 resume LLM output。

## 需要 Review Gate 的操作

以下操作需要明确的 Claude Code UI review：

- `kb.source.deprecate`
- `kb.candidate.defer`
- `kb.knowledge.accept`
- `kb.knowledge.reject`
- `kb.knowledge.merge`
- `kb.knowledge.deprecate`
- `kb.knowledgebase.create`
- `kb.knowledgebase.outline.create`
- `kb.knowledgebase.outline.set_default`
- `kb.knowledgebase.outline.archive`
- `kb.note.deprecate`
- clean migration execution after `kb.clean.inspect`

## 不需要 Review Gate 的操作

以下操作不需要 review gates：

- `kb.init`
- `kb.source.add`
- `kb.candidate.create`
- `kb.candidate.get`
- `kb.candidate.next_pending`
- `kb.knowledgebase.map`
- `kb.note.add`
- `kb.note.get`
- `kb.index.rebuild`
- `kb.clean.inspect`
- list/view read-only display workflows

## 操作

- `kb.init`: 初始化 workspace structure。
- `kb.source.add`: 添加 file、directory 或 URL source；可能返回 `needs_llm`。
- `kb.candidate.create`: 从 source IDs 创建 pending candidates；可能返回 `needs_llm`；无 review gate。
- `kb.candidate.get`: 读取一个 candidate。
- `kb.candidate.next_pending`: 读取下一个 pending candidate。
- `kb.candidate.defer`: 带 review gate 的 candidate decision。
- `kb.knowledge.accept`: 带 review gate 的 candidate acceptance。
- `kb.knowledge.reject`: 带 review gate 的 candidate rejection。
- `kb.knowledge.merge`: 带 review gate 的 merge into existing knowledge。
- `kb.knowledge.deprecate`: 带 review gate 的 knowledge deprecation。
- `kb.knowledgebase.create`: 从 reviewed content 创建 knowledgebase，带 review gate；不创建 source，不写入 `data/raw` 或 `data/cleaned`，不创建 candidate。
- `kb.knowledgebase.outline.create`: 创建 outline，带 review gate。
- `kb.knowledgebase.outline.set_default`: 更新 default outline，带 review gate。
- `kb.knowledgebase.outline.archive`: archive outline，带 review gate。
- `kb.knowledgebase.map`: 生成或返回 knowledgebase map。
- `kb.note.add`: 添加 note；可能请求 LLM title generation。
- `kb.note.get`: 读取一个 note。
- `kb.note.deprecate`: deprecate note，带 review gate。
- `kb.index.rebuild`: 重建 derived indexes 并报告 consistency issues。
- `kb.clean.inspect`: 检查 layout/schema drift，并可选择请求 LLM migration plan。

## 结果处理

报告 `status`、`operation`、created/updated/deprecated objects、diffs、warnings、
errors、review options 和 next actions。对于已经报告 automatic rebuild output 的写入 API，
不要额外运行 index rebuild。
