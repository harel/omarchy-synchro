from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from .core import (
    SynchroError, apply_restore, commit_snapshot, init_repo, load_selection, repository_status,
    restore_plan, run_git, save_selection, snapshot, test_remote, user_config_path,
    plugin_seed_plan, push_snapshot, seed_stage_plan,
    validate_remote, validate_repo_path,
)

QML_OUTPUT_LIMIT = 64 * 1024
QML_STRING_LIMIT = 4096
QML_LIST_LIMIT = 200


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="omarchy-synchro", description="Safe Omarchy configuration snapshots")
    result.add_argument("--json", action="store_true", help="machine-readable output")
    result.add_argument("--qml", action="store_true", help=argparse.SUPPRESS)
    commands = result.add_subparsers(dest="command", required=True)
    config = commands.add_parser("config")
    config_sub = config.add_subparsers(dest="action", required=True)
    select = config_sub.add_parser("select"); select.add_argument("path")
    config_sub.add_parser("show"); config_sub.add_parser("remove")
    repo = commands.add_parser("repo")
    repo_sub = repo.add_subparsers(dest="action", required=True)
    repo_sub.add_parser("init")
    commit = repo_sub.add_parser("commit"); commit.add_argument("--message", "-m", required=True)
    repo_sub.add_parser("push")
    origin = repo_sub.add_parser("origin")
    origin_sub = origin.add_subparsers(dest="origin_action", required=True)
    for name in ("set", "test"):
        item = origin_sub.add_parser(name); item.add_argument("url", nargs="?" if name == "test" else None)
    origin_sub.add_parser("show"); origin_sub.add_parser("remove")
    repo_sub.add_parser("open")
    status = commands.add_parser("status"); status.add_argument("--fetch", action="store_true")
    snap = commands.add_parser("snapshot"); snap.add_argument("--apply", action="store_true")
    restore = commands.add_parser("restore"); restore.add_argument("--apply", action="store_true"); restore.add_argument("--include-device", action="store_true")
    seed = commands.add_parser("seed"); seed.add_argument("--stage", choices=["check", "restore", "packages", "plugins", "mime", "reload", "report"], default="check")
    return result


def qml_safe_payload(value):
    if isinstance(value, str):
        return value[:QML_STRING_LIMIT] + ("\n[truncated]" if len(value) > QML_STRING_LIMIT else "")
    if isinstance(value, list):
        items = [qml_safe_payload(item) for item in value[:QML_LIST_LIMIT]]
        if len(value) > QML_LIST_LIMIT:
            items.append(f"[{len(value) - QML_LIST_LIMIT} more items omitted]")
        return items
    if isinstance(value, dict):
        return {str(key)[:256]: qml_safe_payload(item) for key, item in list(value.items())[:QML_LIST_LIMIT]}
    return value


def encode_qml_payload(data) -> str:
    encoded = json.dumps(qml_safe_payload(data), separators=(",", ":"))
    if len(encoded.encode("utf-8")) > QML_OUTPUT_LIMIT:
        return json.dumps({"error": "Output exceeded the safe UI limit. Use the CLI or narrow the configuration before retrying."}, separators=(",", ":"))
    return encoded


def emit(data, as_json: bool, qml_safe: bool = False) -> None:
    if qml_safe:
        print(encode_qml_payload(data))
        return
    if as_json:
        print(json.dumps(data, indent=2))
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2))


def main(plugin_root: Path | None = None, argv=None) -> int:
    plugin_root = (plugin_root or Path(__file__).resolve().parents[2]).resolve()
    home = Path.home().resolve()
    args = parser().parse_args(argv)
    output = lambda data: emit(data, args.json, args.qml)
    try:
        if args.command == "config":
            if args.action == "select":
                repo = save_selection(Path(args.path), home, plugin_root)
                output({"selected": str(repo)})
            elif args.action == "show":
                repo = load_selection(home, plugin_root)
                output({"selected": str(repo), "settings": str(user_config_path(home))})
            else:
                path = user_config_path(home)
                if path.exists(): path.unlink()
                output("Repository selection removed; configuration repository was not deleted.")
            return 0
        repo = load_selection(home, plugin_root)
        if args.command == "repo":
            if args.action == "init":
                init_repo(repo, plugin_root / "templates/allowlist.tsv")
                output({"initialized": str(repo)})
            elif args.action == "commit":
                output(commit_snapshot(repo, args.message))
            elif args.action == "push":
                output(push_snapshot(repo))
            elif args.action == "open":
                subprocess.Popen(["xdg-terminal-exec", f"--dir={repo}"], start_new_session=True)
                output("Configuration repository opened.")
            elif args.action == "origin":
                action = args.origin_action
                if action == "show":
                    current = run_git(repo, "remote", "get-url", "origin", check=False)
                    output({"origin": current.stdout.strip() or None})
                elif action == "remove":
                    run_git(repo, "remote", "remove", "origin", check=False)
                    output("Origin removed; no files or commits were changed.")
                elif action == "test":
                    url = args.url
                    if not url:
                        current = run_git(repo, "remote", "get-url", "origin", check=False)
                        url = current.stdout.strip()
                    test_remote(url); output("Remote access succeeded.")
                else:
                    url = validate_remote(args.url)
                    exists = run_git(repo, "remote", "get-url", "origin", check=False).returncode == 0
                    run_git(repo, "remote", "set-url" if exists else "add", *( ["origin", url] if exists else ["origin", url] ))
                    output({"origin": url})
            return 0
        if args.command == "status":
            if args.fetch:
                run_git(repo, "fetch", "--prune", "origin")
            output(repository_status(repo)); return 0
        if args.command == "snapshot":
            summary, changes = snapshot(repo, home, args.apply)
            output({"mode": "applied" if args.apply else "preview", "summary": summary, "changes": changes, "repositoryStatus": repository_status(repo), "next": "Review with git diff; Synchro never commits or pushes."}); return 0
        if args.command == "restore":
            plan = restore_plan(repo, home, args.include_device)
            backup = str(apply_restore(plan, home, repo)) if args.apply and plan else None
            output({"mode": "applied" if args.apply else "dry-run", "changes": [{"source": str(s), "destination": str(d), "scope": scope} for s,d,scope in plan], "backup": backup}); return 0
        if args.command == "seed":
            output(seed_stage_plan(repo, home, args.stage)); return 0
    except (SynchroError, OSError, ValueError) as exc:
        output({"error": str(exc)} if args.json else f"Error: {exc}")
        return 2
    return 0
