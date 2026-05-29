# `kb.candidate.get`

## 用途

读取指定 candidate 的对象内容和 review state，用于只读展示或 review 前置加载。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.get '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>"
}
```

必填字段：`candidate_id`。

## Result 字段

报告 `candidate`、`candidate.path`、`candidate.content`、`candidate.references`、`warnings` 和 `errors`。

## 硬规则

- 只读操作。
- Candidate object 是事实来源；不要把 index content 当作 candidate fact。
- Review display 在 Claude Code 中展示，不使用 VSCode。
