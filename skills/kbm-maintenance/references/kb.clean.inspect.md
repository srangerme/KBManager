# `kb.clean.inspect`

## 用途

只读检查 workspace layout/schema drift，并在需要时返回 LLM migration plan 请求。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.clean.inspect '{}' --pretty
```

## 载荷

```json
{}
```

## needs_llm

返回 `needs_llm` 时，按 API 的 `llm_request` 生成 structured migration plan。该 plan 不是用户批准。

## Result 字段

报告 differences、migration_required、warnings、errors、migration plan、remaining issues 和 `next_actions`。

## 硬规则

- `kb.clean.inspect` 是只读操作。
- 执行 migration 前必须完整展示 plan 并获得用户明确批准。
- Clean migration execution 只能按 approved plan 直接编辑 workspace files。
- Migration 后运行 `kb.index.rebuild`。
