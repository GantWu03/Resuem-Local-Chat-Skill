# Resume Local Chat Skill

[中文说明](README.md)

Recover local Codex Desktop chat history when older conversations still exist on disk but disappear from the left sidebar after switching API keys, third-party providers, models, login methods, or subscription accounts.

This repository packages a Codex skill named `resume-local-chat`. It is designed for Windows Codex Desktop installations where local state usually lives under:

```text
%USERPROFILE%\.codex
```

## What It Fixes

- `session_index.jsonl` is missing, stale, or incomplete.
- Session `.jsonl` logs exist but are not shown in the sidebar.
- Old threads are still assigned to a previous `model_provider` / `model` in `state_5.sqlite`.
- `config.toml` has a current model but no explicit `model_provider`.
- Switching between a third-party API provider and an OpenAI subscription account makes local chats look lost.

The skill treats local chat logs as the source of truth and avoids changing message contents. For provider/account switch repairs, it only rewrites the first `session_meta` line in each session file and the relevant `threads` rows in SQLite.

## Install

Clone or download this repository, then copy the skill folder into your Codex skills directory:

```powershell
Copy-Item -Recurse .\resume-local-chat "$env:USERPROFILE\.codex\skills\resume-local-chat" -Force
```

Restart Codex Desktop so the skill metadata is discovered.

## Use

In Codex, call the skill directly:

```text
$resume-local-chat restore my local chats after switching providers
```

or:

```text
Use $resume-local-chat to recover chats missing from the Codex left sidebar.
```

The skill will inspect local Codex state, make backups before any mutation, repair provider/model mismatches when appropriate, rebuild `session_index.jsonl`, and ask you to restart Codex Desktop so the sidebar reloads.

## Included Script

The skill includes `scripts/repair_codex_history.py` for repeatable repairs.

Check status without modifying anything:

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py status --json
```

Synchronize old threads to the inferred current provider/model:

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py sync --json
```

Override the target provider/model if needed:

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py sync --provider openai --model gpt-5.5 --json
```

## Safety

Before `sync`, the script writes a timestamped backup under:

```text
%USERPROFILE%\.codex\history_sync_backups
```

The backup includes:

- a SQLite backup of `state_5.sqlite`
- a copy of `session_index.jsonl`
- a JSON snapshot of every session file's original first line

Archived state is preserved. The script does not unarchive chats unless you manually change the database afterward.

## Repository Note

The repository name intentionally follows the remote name `Resuem-Local-Chat-Skill`, while the Codex skill itself is correctly named `resume-local-chat`.
