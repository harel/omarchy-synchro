from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


class SynchroError(RuntimeError):
    pass


CONFIG_NAME = "omarchy-synchro.json"
MANAGED_DIRS = ("portable", "device", "manifests", "metadata")
COMMIT_PATHS = (*MANAGED_DIRS, "policy", "README.md", ".gitignore")
SECRET_PARTS = {
    ".ssh", ".gnupg", ".password-store", "keyring", "keyrings", "credentials",
    "secrets", "tokens", "cookies", "browser", "browsers", "cache", "caches",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
DEVICE_MARKERS = ("monitor", "display", "gpu", "nvidia", "amd", "power", "hostname")
CONTENT_SECRET = re.compile(
    rb"-----BEGIN (?:OPENSSH |PGP |RSA |EC )?PRIVATE KEY-----|"
    rb"^\s*(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)\s*[:=]\s*[^\s#]{4,}|"
    rb"https://[^\s/@:]+:[^\s/@]+@",
    re.IGNORECASE | re.MULTILINE,
)
MAX_CAPTURE_FILE_BYTES = 2 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def user_config_path(home: Path) -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return base / "omarchy" / CONFIG_NAME


def canonical(path: Path, *, strict: bool = False) -> Path:
    return path.expanduser().resolve(strict=strict)


def overlaps(a: Path, b: Path) -> bool:
    a, b = canonical(a), canonical(b)
    return a == b or a in b.parents or b in a.parents


def validate_repo_path(repo: Path, plugin_root: Path, home: Path) -> Path:
    repo = canonical(repo)
    plugin_root = canonical(plugin_root)
    forbidden = [plugin_root, Path("/usr/share/omarchy")]
    for candidate in (
        home / ".config/omarchy/plugins",
        home / ".local/share/omarchy/plugins",
        home / "plugins",
        home / ".codex/plugins",
    ):
        if candidate.exists():
            forbidden.append(candidate)
    for path in forbidden:
        if overlaps(repo, path):
            raise SynchroError(f"configuration repository overlaps a forbidden plugin/system path: {path}")
    if repo == home:
        raise SynchroError("configuration repository may not contain the home directory")
    return repo


def load_selection(home: Path, plugin_root: Path) -> Path:
    path = user_config_path(home)
    if not path.is_file():
        raise SynchroError(f"no configuration repository selected; run: omarchy-synchro config select PATH")
    try:
        data = json.loads(path.read_text())
        raw = data["repository"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SynchroError(f"invalid user configuration: {path}") from exc
    return validate_repo_path(Path(os.path.expandvars(os.path.expanduser(raw))), plugin_root, home)


def save_selection(repo: Path, home: Path, plugin_root: Path) -> Path:
    repo = validate_repo_path(repo, plugin_root, home)
    path = user_config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"version": 1, "repository": str(repo)}, stream, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return repo


def validate_remote(url: str) -> str:
    if not url or any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise SynchroError("remote URL cannot be empty or contain whitespace/control characters")
    if re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9_./~+-]+", url):
        return url
    parsed = urlsplit(url)
    if parsed.scheme not in {"ssh", "https"} or not parsed.hostname or not parsed.path:
        raise SynchroError("remote must be an SSH or HTTPS Git URL")
    if parsed.scheme == "https" and (parsed.username is not None or parsed.password is not None):
        raise SynchroError("credentials or usernames embedded in HTTPS remotes are forbidden")
    if parsed.password is not None:
        raise SynchroError("credentials embedded in remotes are forbidden")
    if parsed.query or parsed.fragment:
        raise SynchroError("remote URL queries and fragments are forbidden")
    return url


def run_git(repo: Path, *args: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], text=True, capture_output=True,
            check=check, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise SynchroError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise SynchroError("Git operation timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise SynchroError((exc.stderr or exc.stdout or "Git operation failed").strip()) from exc


def require_repo(repo: Path) -> None:
    if not (repo / ".git").is_dir():
        raise SynchroError(f"configuration repository is not initialized: {repo}")


def init_repo(repo: Path, template: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    if any(repo.iterdir()) and not (repo / ".git").is_dir():
        raise SynchroError("refusing to initialize a non-empty, non-Git directory")
    if not (repo / ".git").exists():
        run_git(repo, "init", "-b", "main")
    for directory in MANAGED_DIRS:
        (repo / directory).mkdir(exist_ok=True)
    policy = repo / "policy"
    policy.mkdir(exist_ok=True)
    allowlist = policy / "allowlist.tsv"
    if not allowlist.exists():
        shutil.copy2(template, allowlist)
    readme = repo / "README.md"
    if not readme.exists():
        readme.write_text("# Omarchy configuration\n\nPrivate data managed by Omarchy Synchro. Review every diff before committing.\n")
    ignore = repo / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*.tmp\n*.log\n.env\n.env.*\n*.pem\n*.key\n*.p12\n")


@dataclass(frozen=True)
class AllowEntry:
    scope: str
    relative: PurePosixPath


def secret_reason(relative: PurePosixPath) -> str | None:
    lowered = [part.lower() for part in relative.parts]
    name = lowered[-1] if lowered else ""
    if any(part in SECRET_PARTS for part in lowered):
        return "secret/cache/browser path"
    if name == ".env" or name.startswith(".env."):
        return "environment file"
    if Path(name).suffix.lower() in SECRET_SUFFIXES:
        return "secret-bearing file extension"
    if any(word in name for word in ("credential", "secret", "token", "cookie")):
        return "secret-bearing filename"
    if relative.as_posix().startswith(".config/omarchy/plugins/"):
        return "installed plugin working tree"
    if relative.as_posix() == ".config/omarchy/omarchy-synchro.json":
        return "machine-local repository selection"
    return None


def content_secret_reason(path: Path) -> str | None:
    try:
        if path.stat(follow_symlinks=False).st_size > MAX_CAPTURE_FILE_BYTES:
            return "file exceeds the 2 MiB inspected-capture limit"
        with path.open("rb") as stream:
            sample = stream.read(MAX_CAPTURE_FILE_BYTES + 1)
        if len(sample) > MAX_CAPTURE_FILE_BYTES:
            return "file exceeds the 2 MiB inspected-capture limit"
    except OSError:
        return "file could not be safely inspected"
    return "private-key or credential-like content" if CONTENT_SECRET.search(sample) else None


def require_contained_regular_file(path: Path, root: Path, *, label: str) -> Path:
    root = root.resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SynchroError(f"{label} escapes its approved root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SynchroError(f"{label} contains a symlink: {current}")
    try:
        resolved = path.resolve(strict=True)
        mode = path.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise SynchroError(f"{label} is not safely readable: {path}") from exc
    if not resolved.is_relative_to(root) or not stat.S_ISREG(mode):
        raise SynchroError(f"{label} is not a contained regular file: {path}")
    return resolved


def require_safe_destination(path: Path, home: Path) -> Path:
    home = home.resolve(strict=True)
    try:
        relative = path.relative_to(home)
    except ValueError as exc:
        raise SynchroError(f"restore destination escapes the home directory: {path}") from exc
    if not relative.parts:
        raise SynchroError("restore destination may not replace the home directory")
    current = home
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SynchroError(f"restore destination contains a symlink: {current}")
        if current.exists() and not current.resolve(strict=True).is_relative_to(home):
            raise SynchroError(f"restore destination escapes the home directory: {current}")
    return path


def parse_allowlist(path: Path) -> list[AllowEntry]:
    entries: list[AllowEntry] = []
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) != 2 or fields[0] not in {"portable", "device"}:
            raise SynchroError(f"invalid allowlist line {number}: expected SCOPE<TAB>HOME_RELATIVE_PATH")
        rel = PurePosixPath(fields[1])
        if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
            raise SynchroError(f"unsafe allowlist path on line {number}: {fields[1]}")
        reason = secret_reason(rel)
        if reason:
            raise SynchroError(f"unsafe allowlist path on line {number}: {fields[1]} ({reason})")
        lowered = rel.as_posix().lower()
        if fields[0] == "portable" and any(marker in lowered for marker in DEVICE_MARKERS):
            raise SynchroError(f"hardware-sensitive path must use device scope: {fields[1]}")
        entries.append(AllowEntry(fields[0], rel))
    if not entries:
        raise SynchroError("allowlist has no entries")
    return entries


def iter_source_files(source: Path, relative: PurePosixPath):
    if source.is_symlink():
        raise SynchroError(f"symlink sources are not captured: {relative}")
    if source.is_file():
        if stat.S_ISREG(source.stat(follow_symlinks=False).st_mode) and not secret_reason(relative) and not content_secret_reason(source):
            yield source, relative
        return
    if not source.exists():
        return
    for root, dirs, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        kept = []
        for name in dirs:
            candidate = root_path / name
            rel = PurePosixPath(candidate.relative_to(source).as_posix())
            full_rel = relative / rel
            if name == ".git" or (candidate / ".git").exists() or candidate.is_symlink() or secret_reason(full_rel):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            candidate = root_path / name
            rel = relative / PurePosixPath(candidate.relative_to(source).as_posix())
            if candidate.is_symlink() or not stat.S_ISREG(candidate.stat(follow_symlinks=False).st_mode) or secret_reason(rel) or content_secret_reason(candidate):
                continue
            yield candidate, rel


def build_snapshot(repo: Path, home: Path, stage: Path) -> dict:
    entries = parse_allowlist(repo / "policy/allowlist.tsv")
    device_id = socket.gethostname().split(".")[0] or "unknown-device"
    count = 0
    for entry in entries:
        source = home / Path(entry.relative.as_posix())
        if source.exists():
            current = home.resolve(strict=True)
            for part in source.relative_to(home).parts:
                current = current / part
                if current.is_symlink():
                    raise SynchroError(f"allowlisted source contains a symlink: {entry.relative}")
            resolved_source = source.resolve(strict=True)
            if not resolved_source.is_relative_to(home.resolve(strict=True)):
                raise SynchroError(f"allowlisted source escapes the home directory: {entry.relative}")
            if overlaps(resolved_source, repo):
                raise SynchroError(f"allowlisted source overlaps configuration repository: {entry.relative}")
        target_base = stage / ("portable" if entry.scope == "portable" else f"device/{device_id}") / "home"
        for candidate, relative in iter_source_files(source, entry.relative):
            target = target_base / Path(relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target, follow_symlinks=False)
            count += 1
    manifests = stage / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    if shutil.which("pacman"):
        for args, name in ((["pacman", "-Qqen"], "native.txt"), (["pacman", "-Qqem"], "aur.txt")):
            result = subprocess.run(args, text=True, capture_output=True, check=True)
            (manifests / name).write_text("".join(f"{line}\n" for line in sorted(result.stdout.splitlines())))
    shell_path = home / ".config/omarchy/shell.json"
    if shell_path.is_file():
        if content_secret_reason(shell_path):
            raise SynchroError("shell.json contains credential-like content and was not captured")
        shell_data = json.loads(shell_path.read_text())
        (manifests / "shell.json").write_text(json.dumps(shell_data, indent=2) + "\n")
    plugins = collect_plugins(home, shell_path)
    (manifests / "plugins.json").write_text(json.dumps({"schema": 1, "plugins": plugins}, indent=2) + "\n")
    metadata = stage / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    summary = {"schema": 1, "deviceId": device_id, "files": count}
    (metadata / "snapshot.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def _shell_locations(shell_data: dict) -> dict[str, dict]:
    locations: dict[str, dict] = {}
    layout = shell_data.get("bar", {}).get("layout", {})
    for section in ("left", "center", "right"):
        for index, raw in enumerate(layout.get(section, [])):
            entry = raw if isinstance(raw, dict) else {"id": str(raw)}
            plugin_id = str(entry.get("id", ""))
            if plugin_id:
                locations[plugin_id] = {
                    "kind": "bar", "section": section, "index": index,
                    "settings": {key: value for key, value in entry.items() if key != "id"},
                }
    for index, entry in enumerate(shell_data.get("plugins", [])):
        if isinstance(entry, dict) and entry.get("id"):
            locations[str(entry["id"])] = {
                "kind": "plugin", "index": index,
                "settings": {key: value for key, value in entry.items() if key != "id"},
            }
    return locations


def collect_plugins(home: Path, shell_path: Path | None = None) -> list[dict]:
    plugins_dir = home / ".config/omarchy/plugins"
    shell_path = shell_path or home / ".config/omarchy/shell.json"
    try:
        shell_data = json.loads(shell_path.read_text())
    except (OSError, ValueError):
        shell_data = {}
    locations = _shell_locations(shell_data)
    disabled = set(shell_data.get("disabledPlugins") or [])
    output: list[dict] = []
    if not plugins_dir.is_dir():
        return output
    for path in sorted(plugins_dir.iterdir(), key=lambda item: item.name):
        manifest_path = path / "manifest.json"
        if path.name == "harel.omarchy-synchro" or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            continue
        plugin_id = str(manifest.get("id", path.name))
        remote_result = run_git(path.resolve(), "remote", "get-url", "origin", check=False)
        raw_remote = remote_result.stdout.strip() if remote_result.returncode == 0 else ""
        portable_remote = None
        if raw_remote:
            try:
                portable_remote = validate_remote(raw_remote)
            except SynchroError:
                portable_remote = None
        revision_result = run_git(path.resolve(), "rev-parse", "HEAD", check=False)
        entry = {
            "id": plugin_id,
            "name": str(manifest.get("name", plugin_id)),
            "version": str(manifest.get("version", "")),
            "source": portable_remote,
            "sourceState": "portable" if portable_remote else "manual",
            "revision": revision_result.stdout.strip() if revision_result.returncode == 0 else None,
            "enabled": plugin_id in locations and plugin_id not in disabled,
            "placement": locations.get(plugin_id),
        }
        if not portable_remote:
            entry["manualStep"] = "Configure a portable SSH or HTTPS Git origin before seeding another machine."
        output.append(entry)
    return output


def plugin_seed_plan(repo: Path, home: Path) -> dict:
    manifest_path = repo / "manifests/plugins.json"
    if not manifest_path.is_file():
        return {"stage": "plugins", "mode": "preview", "summary": "No plugin manifest is present.", "actions": [], "manual": ["Apply a fresh snapshot first."]}
    data = json.loads(manifest_path.read_text())
    installed = home / ".config/omarchy/plugins"
    actions = []
    manual = []
    for plugin in data.get("plugins", []):
        plugin_id = str(plugin.get("id", ""))
        if not plugin_id:
            continue
        if (installed / plugin_id / "manifest.json").is_file():
            state = "installed"
        elif plugin.get("source"):
            state = "missing"
        else:
            state = "manual"
        actions.append({
            "id": plugin_id, "state": state, "source": plugin.get("source"),
            "enabled": bool(plugin.get("enabled")), "placement": plugin.get("placement"),
            "revision": plugin.get("revision"),
        })
        if state == "manual":
            manual.append(f"{plugin_id}: {plugin.get('manualStep', 'portable source required')}")
    installed_count = sum(action["state"] == "installed" for action in actions)
    missing_count = sum(action["state"] == "missing" for action in actions)
    summary = f"{installed_count} installed, {missing_count} missing, {len(manual)} manual."
    return {"stage": "plugins", "mode": "preview", "summary": summary, "actions": actions, "manual": manual}


def seed_stage_plan(repo: Path, home: Path, stage: str) -> dict:
    require_repo(repo)
    if stage == "plugins":
        return plugin_seed_plan(repo, home)

    if stage == "check":
        checks = []
        version = subprocess.run(["omarchy", "version"], text=True, capture_output=True, check=False) if shutil.which("omarchy") else None
        checks.append(("Base Omarchy", "ok" if version and version.returncode == 0 else "missing", version.stdout.strip() if version else "omarchy command not found"))
        checks.append(("Configuration repository", "ok", str(repo)))
        metadata_path = repo / "metadata/snapshot.json"
        try:
            schema = json.loads(metadata_path.read_text()).get("schema")
            checks.append(("Snapshot schema", "ok" if schema == 1 else "incompatible", str(schema)))
        except (OSError, ValueError):
            checks.append(("Snapshot schema", "missing", "apply a snapshot before seeding"))
        lines = [f"{state.upper()}  {name}\n  {detail}" for name, state, detail in checks]
        ready = all(state == "ok" for _name, state, _detail in checks)
        return {"stage": stage, "mode": "preview", "summary": "Compatible base detected." if ready else "Setup checks need attention.", "lines": lines, "ready": ready}

    if stage == "restore":
        plan = restore_plan(repo, home, include_device=False)
        lines = [f"{scope.upper()}  {destination}" for _source, destination, scope in plan]
        summary = f"{len(plan)} portable file change{'s' if len(plan) != 1 else ''} would be restored." if plan else "Portable configuration already matches this machine."
        return {"stage": stage, "mode": "dry-run", "summary": summary, "lines": lines or ["NOTHING TO DO\n  Portable configuration is already current."], "changes": len(plan)}

    if stage == "packages":
        if not shutil.which("pacman"):
            return {"stage": stage, "mode": "preview", "summary": "Package comparison unavailable.", "lines": ["MANUAL\n  pacman is not available on this base system."], "ready": False}
        installed_result = subprocess.run(["pacman", "-Qq"], text=True, capture_output=True, check=True)
        installed = set(installed_result.stdout.splitlines())
        sections = []
        total = 0
        for filename, label in (("native.txt", "NATIVE"), ("aur.txt", "AUR / FOREIGN")):
            path = repo / "manifests" / filename
            declared = set(path.read_text().splitlines()) if path.is_file() else set()
            missing = sorted(declared - installed)
            total += len(missing)
            sections.append(f"{label}\n  " + ("\n  ".join(missing) if missing else "Nothing missing."))
        summary = f"{total} package{'s' if total != 1 else ''} missing; installation requires approval." if total else "All declared packages are installed."
        return {"stage": stage, "mode": "preview", "summary": summary, "lines": sections, "missing": total}

    if stage == "mime":
        saved = repo / "portable/home/.config/mimeapps.list"
        current = home / ".config/mimeapps.list"
        if not saved.is_file():
            return {"stage": stage, "mode": "preview", "summary": "No MIME defaults were captured.", "lines": ["NOTHING TO APPLY\n  Add .config/mimeapps.list to the allowlist and snapshot first."]}
        matches = current.is_file() and filecmp.cmp(saved, current, shallow=False)
        return {"stage": stage, "mode": "preview", "summary": "MIME/application defaults already match." if matches else "MIME/application defaults would change.", "lines": ["CURRENT\n  " + str(current), "SAVED\n  " + str(saved), "RESULT\n  " + ("Nothing to do." if matches else "Preview restoration before applying.")]}

    if stage == "reload":
        plan = restore_plan(repo, home, include_device=False)
        destinations = [str(destination.relative_to(home)) for _source, destination, _scope in plan]
        components = []
        if any(path.startswith(".config/hypr/") for path in destinations): components.append("Hyprland — reload configuration")
        if any(path.startswith(".config/omarchy/") for path in destinations): components.append("Omarchy Shell — restart or reload")
        if any(path.startswith((".config/alacritty/", ".config/foot/", ".config/kitty/", ".config/ghostty/")) for path in destinations): components.append("Terminal — restart running terminal instances")
        return {"stage": stage, "mode": "preview", "summary": f"{len(components)} component reload{'s' if len(components) != 1 else ''} would be required." if components else "No component reloads are currently required.", "lines": components or ["NOTHING TO DO\n  Restored configuration already matches this machine."]}

    if stage == "report":
        device_root = repo / "device"
        device_files = sorted(str(path.relative_to(repo)) for path in device_root.rglob("*") if path.is_file()) if device_root.exists() else []
        plugin_plan = plugin_seed_plan(repo, home)
        manual = list(plugin_plan.get("manual", []))
        lines = ["DEVICE-SPECIFIC — never applied cross-device automatically\n  " + ("\n  ".join(device_files) if device_files else "None captured.")]
        lines.append("SECRETS\n  SSH/GPG keys, credentials, tokens, keyrings, password stores, cookies, and device secrets must be restored manually.")
        lines.append("MANUAL PLUGIN STEPS\n  " + ("\n  ".join(manual) if manual else "None."))
        return {"stage": stage, "mode": "preview", "summary": f"{len(device_files)} device-specific file{'s' if len(device_files) != 1 else ''}; {len(manual)} manual plugin step{'s' if len(manual) != 1 else ''}.", "lines": lines}

    raise SynchroError(f"unknown seed stage: {stage}")


def tree_changes(source: Path, destination: Path) -> list[str]:
    changes: list[str] = []
    source_files = {p.relative_to(source) for p in source.rglob("*") if p.is_file()} if source.exists() else set()
    dest_files = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()} if destination.exists() else set()
    for rel in sorted(source_files | dest_files, key=str):
        left, right = source / rel, destination / rel
        if rel not in dest_files:
            changes.append(f"A {rel}")
        elif rel not in source_files:
            changes.append(f"D {rel}")
        elif not filecmp.cmp(left, right, shallow=False):
            changes.append(f"M {rel}")
    return changes


def snapshot(repo: Path, home: Path, apply: bool) -> tuple[dict, list[str]]:
    require_repo(repo)
    with tempfile.TemporaryDirectory(prefix="omarchy-synchro-") as temp:
        stage = Path(temp)
        summary = build_snapshot(repo, home, stage)
        changes: list[str] = []
        for name in MANAGED_DIRS:
            changes.extend(f"{name}/{line}" for line in tree_changes(stage / name, repo / name))
        if apply:
            for name in MANAGED_DIRS:
                target = repo / name
                replacement = stage / name
                if target.exists():
                    shutil.rmtree(target)
                if replacement.exists():
                    shutil.copytree(replacement, target)
                else:
                    target.mkdir()
        return summary, changes


def restore_plan(repo: Path, home: Path, include_device: bool = False) -> list[tuple[Path, Path, str]]:
    require_repo(repo)
    repo = repo.resolve(strict=True)
    home = home.resolve(strict=True)
    roots = [(repo / "portable/home", "portable")]
    if include_device:
        device_id = socket.gethostname().split(".")[0] or "unknown-device"
        roots.append((repo / f"device/{device_id}/home", f"device:{device_id}"))
    plan = []
    for root, scope in roots:
        if not root.exists():
            continue
        current_root = repo
        for part in root.relative_to(repo).parts:
            current_root = current_root / part
            if current_root.is_symlink():
                raise SynchroError(f"restore root contains a symlink: {current_root}")
        if not root.resolve(strict=True).is_relative_to(repo):
            raise SynchroError(f"restore root is not safely contained in the configuration repository: {root}")
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in dirs:
                candidate = current_path / name
                if candidate.is_symlink():
                    raise SynchroError(f"restore snapshot contains a symlink: {candidate}")
            for name in sorted(files):
                source = current_path / name
                safe_source = require_contained_regular_file(source, root, label="restore source")
                rel = source.relative_to(root)
                destination = require_safe_destination(home / rel, home)
                state = "add" if not destination.exists() else ("same" if filecmp.cmp(safe_source, destination, shallow=False) else "modify")
                if state != "same":
                    plan.append((safe_source, destination, scope))
    return plan


def apply_restore(plan: list[tuple[Path, Path, str]], home: Path, repo: Path) -> Path:
    home = home.resolve(strict=True)
    repo = repo.resolve(strict=True)
    backup = home / ".local/state/omarchy-synchro/backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    for source, destination, _scope in plan:
        safe_source = require_contained_regular_file(source, repo, label="restore source")
        destination = require_safe_destination(destination, home)
        if destination.exists():
            saved = backup / destination.relative_to(home)
            require_safe_destination(saved, home)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
        destination.parent.mkdir(parents=True, exist_ok=True)
        require_safe_destination(destination, home)
        shutil.copy2(safe_source, destination)
    return backup


def repository_status(repo: Path) -> dict:
    if not (repo / ".git").is_dir():
        return {"state": "uninitialized", "repository": str(repo), "branch": None, "dirtyFiles": [], "ahead": 0, "behind": 0, "origin": None, "remoteState": "unconfigured"}
    branch = run_git(repo, "branch", "--show-current").stdout.strip() or "detached"
    dirty = run_git(repo, "status", "--porcelain=v1").stdout.splitlines()
    origin_result = run_git(repo, "remote", "get-url", "origin", check=False)
    origin = origin_result.stdout.strip() if origin_result.returncode == 0 else None
    ahead = behind = 0
    upstream = run_git(repo, "rev-parse", "--abbrev-ref", "@{upstream}", check=False)
    remote_state = "unconfigured" if not origin else "no-upstream"
    if upstream.returncode == 0:
        counts = run_git(repo, "rev-list", "--left-right", "--count", "@{upstream}...HEAD").stdout.split()
        behind, ahead = map(int, counts)
        remote_state = "tracked"
    return {"state": "dirty" if dirty else "clean", "repository": str(repo), "branch": branch, "dirtyFiles": dirty, "ahead": ahead, "behind": behind, "origin": origin, "remoteState": remote_state}


def _audit_commit_paths(repo: Path) -> None:
    for name in COMMIT_PATHS:
        root = repo / name
        candidates = [root] if root.is_file() else ([path for path in root.rglob("*") if path.is_file()] if root.is_dir() else [])
        for path in candidates:
            relative = PurePosixPath(path.relative_to(repo).as_posix())
            reason = secret_reason(relative) or content_secret_reason(path)
            if reason:
                raise SynchroError(f"refusing to stage suspicious file: {relative} ({reason})")


def commit_snapshot(repo: Path, message: str) -> dict:
    require_repo(repo)
    message = message.strip()
    if not message:
        raise SynchroError("commit message cannot be empty")
    if len(message) > 200 or any(ord(character) < 32 for character in message):
        raise SynchroError("commit message must be a single printable line of at most 200 characters")
    _audit_commit_paths(repo)
    existing = [name for name in COMMIT_PATHS if (repo / name).exists()]
    run_git(repo, "add", "--", *existing)
    staged = run_git(repo, "diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        raise SynchroError("no managed snapshot changes are staged for commit")
    if staged.returncode != 1:
        raise SynchroError("could not inspect staged snapshot changes")
    run_git(repo, "commit", "--message", message)
    revision = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    return {"commit": revision, "message": message, "repositoryStatus": repository_status(repo)}


def push_snapshot(repo: Path) -> dict:
    require_repo(repo)
    origin = run_git(repo, "remote", "get-url", "origin", check=False)
    if origin.returncode != 0:
        raise SynchroError("cannot push: origin is not configured")
    branch = run_git(repo, "branch", "--show-current").stdout.strip()
    if not branch:
        raise SynchroError("cannot push from a detached HEAD")
    upstream = run_git(repo, "rev-parse", "--abbrev-ref", "@{upstream}", check=False)
    if upstream.returncode == 0:
        run_git(repo, "push", timeout=120)
    else:
        run_git(repo, "push", "--set-upstream", "origin", branch, timeout=120)
    return {"pushed": branch, "origin": origin.stdout.strip(), "repositoryStatus": repository_status(repo)}


def test_remote(url: str) -> None:
    url = validate_remote(url)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if url.startswith("git@") or url.startswith("ssh://"):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=8"
    try:
        subprocess.run(["git", "ls-remote", url, "HEAD"], env=env, text=True, capture_output=True, check=True, timeout=20)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or "authentication, access, or network failure"
        raise SynchroError(f"remote test failed: {detail.strip()}") from exc
