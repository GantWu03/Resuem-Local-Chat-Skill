#!/usr/bin/env python3
"""Repair Codex Desktop local chat index/provider metadata."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Paths:
    home: Path
    db: Path
    config: Path
    index: Path
    sessions: Path
    archived_sessions: Path
    backups: Path


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def paths_for(home: Path) -> Paths:
    return Paths(
        home=home,
        db=home / "state_5.sqlite",
        config=home / "config.toml",
        index=home / "session_index.jsonl",
        sessions=home / "sessions",
        archived_sessions=home / "archived_sessions",
        backups=home / "history_sync_backups",
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def parse_config_value(config: str, key: str) -> str | None:
    match = re.search(rf'(?m)^\s*{re.escape(key)}\s*=\s*"([^"]+)"', config)
    return match.group(1) if match else None


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"pragma table_info({table})")}


def session_paths(paths: Paths) -> list[Path]:
    files: list[Path] = []
    for directory in (paths.sessions, paths.archived_sessions):
        if directory.exists():
            files.extend(sorted(directory.rglob("*.jsonl")))
    return files


def read_session_meta(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            first = handle.readline().rstrip("\r\n")
        item = json.loads(first)
    except Exception:
        return None
    if item.get("type") != "session_meta" or not isinstance(item.get("payload"), dict):
        return None
    return item


def provider_model_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select model_provider, model, count(*) as count
        from threads
        group by model_provider, model
        order by count(*) desc, model_provider asc, model asc
        """
    ).fetchall()
    return [
        {"provider": row["model_provider"], "model": row["model"], "count": int(row["count"])}
        for row in rows
    ]


def archived_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if "archived" not in table_columns(conn, "threads"):
        return []
    rows = conn.execute("select archived, count(*) as count from threads group by archived").fetchall()
    return [{"archived": int(row["archived"]), "count": int(row["count"])} for row in rows]


def infer_target(paths: Paths, explicit_provider: str | None, explicit_model: str | None) -> tuple[str, str | None]:
    config = read_text(paths.config)
    provider = explicit_provider or parse_config_value(config, "model_provider")
    model = explicit_model if explicit_model is not None else parse_config_value(config, "model")

    if provider:
        return provider, model

    with connect(paths.db) as conn:
        columns = table_columns(conn, "threads")
        order_col = "updated_at_ms" if "updated_at_ms" in columns else "updated_at"
        where = "where archived = 0" if "archived" in columns else ""
        row = conn.execute(
            f"""
            select model_provider, model
            from threads
            {where}
            order by {order_col} desc
            limit 1
            """
        ).fetchone()
        if row and row["model_provider"]:
            return str(row["model_provider"]), model or row["model"]

        row = conn.execute(
            f"""
            select model_provider, model
            from threads
            order by {order_col} desc
            limit 1
            """
        ).fetchone()
        if row and row["model_provider"]:
            return str(row["model_provider"]), model or row["model"]

    raise RuntimeError("Could not infer target model_provider. Pass --provider explicitly.")


def iso_utc_from_unix(value: int | None) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def index_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def session_counts(paths: Paths) -> tuple[int, dict[str, int], int]:
    counts: dict[str, int] = {}
    bad = 0
    files = session_paths(paths)
    for path in files:
        meta = read_session_meta(path)
        if not meta:
            bad += 1
            continue
        payload = meta["payload"]
        key = f"{payload.get('model_provider') or ''}/{payload.get('model') or ''}"
        counts[key] = counts.get(key, 0) + 1
    return len(files), counts, bad


def status(paths: Paths, provider: str | None, model: str | None) -> dict[str, Any]:
    target_provider, target_model = infer_target(paths, provider, model)
    with connect(paths.db) as conn:
        db_counts = provider_model_counts(conn)
        archive_counts = archived_counts(conn)
        total_threads = int(conn.execute("select count(*) from threads").fetchone()[0])
    session_file_count, session_provider_counts, bad_session_meta = session_counts(paths)
    return {
        "codex_home": str(paths.home),
        "target_provider": target_provider,
        "target_model": target_model,
        "db_threads": total_threads,
        "db_provider_model_counts": db_counts,
        "db_archived_counts": archive_counts,
        "session_files": session_file_count,
        "session_provider_model_counts": session_provider_counts,
        "bad_session_meta_files": bad_session_meta,
        "session_index_entries": index_line_count(paths.index),
    }


def snapshot(paths: Paths) -> dict[str, str]:
    paths.backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = paths.backups / f"state_5.sqlite.resume-local-chat.{stamp}.bak"
    with connect(paths.db) as source, sqlite3.connect(prefix) as target:
        source.backup(target)

    index_backup = prefix.with_name(f"{prefix.name}.session_index.jsonl")
    if paths.index.exists():
        shutil.copy2(paths.index, index_backup)

    meta_backup = prefix.with_name(f"{prefix.name}.session_meta.json")
    items: list[dict[str, str]] = []
    for file in session_paths(paths):
        with file.open("r", encoding="utf-8", newline="") as handle:
            first = handle.readline().rstrip("\r\n")
        if not first:
            continue
        try:
            rel = str(file.relative_to(paths.home))
        except ValueError:
            rel = str(file)
        items.append({"path": rel, "first_line": first})
    meta_backup.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"db": str(prefix), "index": str(index_backup), "session_meta": str(meta_backup)}


def split_first_line(text: str) -> tuple[str, str, str]:
    if "\r\n" in text:
        first, rest = text.split("\r\n", 1)
        return first, "\r\n", rest
    if "\n" in text:
        first, rest = text.split("\n", 1)
        return first, "\n", rest
    return text, "", ""


def sync_sessions(paths: Paths, provider: str, model: str | None) -> int:
    updated = 0
    for file in session_paths(paths):
        text = file.read_text(encoding="utf-8")
        if not text:
            continue
        first, ending, rest = split_first_line(text)
        try:
            item = json.loads(first)
        except Exception:
            continue
        payload = item.get("payload")
        if item.get("type") != "session_meta" or not isinstance(payload, dict):
            continue
        changed = False
        if payload.get("model_provider") != provider:
            payload["model_provider"] = provider
            changed = True
        if model and payload.get("model") != model:
            payload["model"] = model
            changed = True
        if not changed:
            continue
        file.write_text(
            json.dumps(item, ensure_ascii=False, separators=(",", ":")) + ending + rest,
            encoding="utf-8",
            newline="",
        )
        updated += 1
    return updated


def parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def rebuild_index(paths: Paths) -> int:
    existing: dict[str, dict[str, str]] = {}
    if paths.index.exists():
        for line in paths.index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            thread_id = str(item.get("id") or "").strip()
            if thread_id:
                existing[thread_id] = {
                    "id": thread_id,
                    "thread_name": str(item.get("thread_name") or thread_id),
                    "updated_at": str(item.get("updated_at") or ""),
                }

    db_info: dict[str, dict[str, Any]] = {}
    with connect(paths.db) as conn:
        columns = table_columns(conn, "threads")
        title_col = "title" if "title" in columns else "id"
        rows = conn.execute(f"select id, {title_col} as title, updated_at from threads").fetchall()
        for row in rows:
            db_info[str(row["id"])] = {
                "title": row["title"] or str(row["id"]),
                "updated_at": iso_utc_from_unix(row["updated_at"]),
            }

    merged = dict(existing)
    for file in session_paths(paths):
        meta = read_session_meta(file)
        if not meta:
            continue
        payload = meta["payload"]
        thread_id = str(payload.get("id") or "").strip()
        if not thread_id:
            continue
        info = db_info.get(thread_id, {})
        merged[thread_id] = {
            "id": thread_id,
            "thread_name": str(info.get("title") or existing.get(thread_id, {}).get("thread_name") or thread_id),
            "updated_at": str(info.get("updated_at") or meta.get("timestamp") or payload.get("timestamp") or ""),
        }

    entries = sorted(merged.values(), key=lambda item: (parse_timestamp(item["updated_at"]), item["id"]))
    content = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in entries)
    temp = paths.index.with_name(f".{paths.index.name}.resume-local-chat.{time.time_ns()}.tmp")
    temp.write_text(content, encoding="utf-8", newline="")
    temp.replace(paths.index)
    return len(entries)


def sync(paths: Paths, provider: str | None, model: str | None) -> dict[str, Any]:
    target_provider, target_model = infer_target(paths, provider, model)
    before = status(paths, target_provider, target_model)
    backups = snapshot(paths)
    with connect(paths.db) as conn:
        if target_model:
            updated_db = conn.execute(
                """
                update threads
                set model_provider = ?, model = ?
                where model_provider <> ? or model is null or model <> ?
                """,
                (target_provider, target_model, target_provider, target_model),
            ).rowcount
        else:
            updated_db = conn.execute(
                "update threads set model_provider = ? where model_provider <> ?",
                (target_provider, target_provider),
            ).rowcount
        conn.commit()

    updated_sessions = sync_sessions(paths, target_provider, target_model)
    index_entries = rebuild_index(paths)
    after = status(paths, target_provider, target_model)
    return {
        "action": "sync",
        "target_provider": target_provider,
        "target_model": target_model,
        "backups": backups,
        "db_rows_updated": updated_db,
        "session_files_updated": updated_sessions,
        "index_entries_written": index_entries,
        "before": before,
        "after": after,
    }


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Repair Codex Desktop local chat history metadata.")
    parser.add_argument("--codex-home", default=str(default_codex_home()))
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    status_parser = sub.add_parser("status", help="Inspect local history state without changing files")
    sync_parser = sub.add_parser("sync", help="Backup and sync local history to the target provider/model")
    for child in (status_parser, sync_parser):
        child.add_argument("--codex-home", dest="codex_home_after")
        child.add_argument("--provider", dest="provider_after")
        child.add_argument("--model", dest="model_after")
        child.add_argument("--json", dest="json_after", action="store_true")
    args = parser.parse_args(argv)

    codex_home = args.codex_home_after or args.codex_home
    provider = args.provider_after or args.provider
    model = args.model_after if args.model_after is not None else args.model
    as_json = bool(args.json or args.json_after)

    paths = paths_for(Path(codex_home).expanduser())
    if not paths.db.exists():
        raise RuntimeError(f"Missing Codex state database: {paths.db}")

    if args.command == "status":
        payload = status(paths, provider, model)
    else:
        payload = sync(paths, provider, model)
    emit(payload, as_json)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
