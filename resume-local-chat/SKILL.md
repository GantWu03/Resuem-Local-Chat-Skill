---
name: resume-local-chat
description: Recover local Codex Desktop chat history when resume fails, session paths are stale, session_index.jsonl is missing/outdated, or switching API providers, models, login methods, or subscription accounts hides older chats from the sidebar.
---

# Resume Local Chat

Use this skill when Codex Desktop local chat logs still exist but the sidebar or resume flow cannot find them. Common triggers include switching API keys, third-party providers, models, login methods, or subscription accounts.

## Workflow

1. Inspect the Codex home directory. Default to `%USERPROFILE%\.codex` on Windows, or `$CODEX_HOME` when set.
2. Check `config.toml`, `state_5.sqlite`, `session_index.jsonl`, `sessions\`, and `archived_sessions\`.
3. Diagnose whether the issue is:
   - a stale session path
   - a missing or outdated `session_index.jsonl`
   - an unindexed but present session log
   - old threads assigned to a previous `model_provider` / `model`
4. Prefer recovery over rewriting history. Do not touch unrelated files.
5. Before modifying local Codex state, make a restorable backup of:
   - `state_5.sqlite` using SQLite backup so WAL contents are included
   - `session_index.jsonl`
   - the first `session_meta` line from every session `.jsonl`
6. Rebuild `session_index.jsonl` from session metadata and the `threads` table when the index is incomplete.
7. Preserve the real `id`, `thread_name` or title, `updated_at`, archived state, and message contents.
8. After repair, verify index count, session file count, newest thread IDs, and provider/model counts.
9. Tell the user to restart Codex Desktop so the sidebar reloads local history.

## Provider / Account Switch Recovery

Codex Desktop may hide older local chats after the user switches from a third-party API provider to an OpenAI subscription account, changes `model_provider`, changes model, or changes login mode. The local chat logs are usually still present, but sidebar filtering may follow provider/model values in local SQLite state and session metadata.

Use this checklist:

1. Read the current model from `config.toml`. Newer Codex configs may have `model = "..."` but no `model_provider`.
2. Infer the target provider from the newest active/current thread in `state_5.sqlite` when `config.toml` has no provider.
3. Query provider/model distribution:
   - `select model_provider, model, count(*) from threads group by model_provider, model order by count(*) desc`
   - `select archived, count(*) from threads group by archived`
4. Count session files in `sessions` plus `archived_sessions`, then compare with `session_index.jsonl`.
5. If provider/model counts are split and the user wants old chats restored to the current sidebar, synchronize old rows to the target provider/model.
6. Update only the first `session_meta` line in each session `.jsonl`; do not alter message contents after that line.
7. Keep archived state unchanged unless the user explicitly asks to unarchive chats.

## Scripted Repair

Prefer the bundled script for repeatable status checks and provider/account switch repairs:

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py status --json
python .\resume-local-chat\scripts\repair_codex_history.py sync --json
```

Use explicit target values only when inference is wrong or ambiguous:

```powershell
python .\resume-local-chat\scripts\repair_codex_history.py sync --provider openai --model gpt-5.5 --json
```

The script writes backups to `history_sync_backups`, updates `threads.model_provider` and `threads.model` when needed, updates session first-line metadata, and rebuilds `session_index.jsonl`.

## Manual Commands

Use these commands when inspecting state by hand:

```powershell
Get-Content "$env:USERPROFILE\.codex\session_index.jsonl"
Get-ChildItem -Recurse -File "$env:USERPROFILE\.codex\sessions","$env:USERPROFILE\.codex\archived_sessions" -Filter *.jsonl
@'
import os, sqlite3
db = os.path.expanduser(r'~\.codex\state_5.sqlite')
con = sqlite3.connect(db)
print(con.execute('select model_provider, model, count(*) from threads group by model_provider, model').fetchall())
print(con.execute('select archived, count(*) from threads group by archived').fetchall())
con.close()
'@ | python -
```

## Recovery Notes

- If a thread cannot resume because the stored path is stale, treat the log file as the source of truth.
- If API keys or login accounts changed, assume local logs are recoverable unless files are missing.
- If a file exists in `sessions` but not in `session_index.jsonl`, it is usually safe to add it back.
- If `config.toml` has no `model_provider`, infer the provider from the newest active/current thread instead of failing.
- Always keep a backup before changing `state_5.sqlite`, `session_index.jsonl`, or session first-line metadata.
