# `kb.candidate.next_pending`

## 用途

查找下一个 pending candidate，用于 review queue 或“继续审核”场景。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.next_pending '{}' --pretty
```

## 载荷

```json
{}
```

## Result 字段

报告 `candidate_id`、candidate summary/path、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 只读操作。
- 获取 ID 后通常继续调用 `kb.candidate.get` 展示完整 candidate。
