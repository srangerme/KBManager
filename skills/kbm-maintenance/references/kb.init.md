# `kb.init`

## 用途

初始化 KBManager workspace structure。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.init '{}' --pretty
```

## 载荷

```json
{}
```

## Result 字段

报告 `objects.created`、existing paths、conflicts、`warnings`、`errors`、`diffs` 和 `next_actions`。

## 硬规则

- 没有 review gate。
- 不要直接创建或编辑 KBManager object files。
- 初始化不得覆盖已有用户文件。
