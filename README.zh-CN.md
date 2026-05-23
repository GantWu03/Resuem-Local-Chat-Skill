# Resume Local Chat Skill

恢复 Codex Desktop 本地聊天记录：当旧对话明明还在磁盘上，却因为切换 API Key、第三方 Provider、模型、登录方式或订阅账户后，从左侧历史列表里消失时，可以使用这个 skill 进行检查和修复。

本仓库打包了一个 Codex skill：`resume-local-chat`。它主要面向 Windows 上的 Codex Desktop，本地状态通常位于：

```text
%USERPROFILE%\.codex
```

## 能解决什么问题

- `session_index.jsonl` 丢失、过期或不完整。
- 本地 session `.jsonl` 日志还在，但左侧列表不显示。
- 旧线程在 `state_5.sqlite` 里仍然绑定到旧的 `model_provider` / `model`。
- `config.toml` 里有当前模型，但没有显式的 `model_provider`。
- 从第三方 API Provider 切换到 OpenAI 订阅账户后，本地历史记录看起来像丢失了。

这个 skill 会把本地聊天日志当作事实来源，尽量避免改动真实对话内容。对于 Provider / 账户切换导致的问题，它只会改每个 session 文件第一行的 `session_meta`，以及 SQLite 里 `threads` 表对应的 Provider / Model 字段。

## 安装

克隆或下载本仓库，然后把 skill 文件夹复制到 Codex 的 skills 目录：

```powershell
Copy-Item -Recurse .\resume-local-chat "$env:USERPROFILE\.codex\skills\resume-local-chat" -Force
```

复制完成后，重启 Codex Desktop，让 Codex 重新发现这个 skill。

## 使用方式

在 Codex 中直接调用：

```text
$resume-local-chat restore my local chats after switching providers
```

或者：

```text
Use $resume-local-chat to recover chats missing from the Codex left sidebar.
```

调用后，Codex 会检查本地状态，在修改任何文件之前创建备份；如果发现 Provider / Model 不一致，会修复对应元数据，重建 `session_index.jsonl`，最后提示你重启 Codex Desktop 来刷新左侧历史列表。

## 内置脚本

这个 skill 附带了 `scripts/repair_codex_history.py`，用于可重复执行的状态检查和修复。

只检查状态，不修改任何文件：

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py status --json
```

把旧线程同步到推断出的当前 Provider / Model：

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py sync --json
```

如果需要手动指定目标 Provider / Model：

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py sync --provider openai --model gpt-5.5 --json
```

## 安全机制

执行 `sync` 前，脚本会在下面的目录创建带时间戳的备份：

```text
%USERPROFILE%\.codex\history_sync_backups
```

备份内容包括：

- `state_5.sqlite` 的 SQLite 备份
- `session_index.jsonl` 的副本
- 每个 session 文件原始第一行的 JSON 快照

脚本会保留 archived 状态，不会自动把归档对话恢复成未归档。除非你之后手动修改数据库，否则归档状态不会改变。

## 仓库说明

仓库名沿用了远程仓库名 `Resuem-Local-Chat-Skill`，但 Codex skill 本身的名称是正确的：`resume-local-chat`。
