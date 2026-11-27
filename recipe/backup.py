"""State-aware backup and restore for Platypus modules (`platypus backup` / `restore`)."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import yaml

from . import lock as lock_mod
from .model import PLATYPUS_DIR as _DEFAULT_PLATYPUS_DIR, role_dir

PLATYPUS_DIR: Path = _DEFAULT_PLATYPUS_DIR
DEFAULT_BACKUP_DEST: Path = Path("/var/backups/platypus")


class BackupError(Exception):
    """Raised when a backup or restore operation fails."""


def _exec_shell(cmd: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)


def _load_mounted_set(platypus_dir: Path) -> set[str]:
    state_file = platypus_dir / "state.yml"
    if not state_file.is_file():
        return set()
    try:
        raw = yaml.safe_load(state_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return set()
    if not isinstance(raw, dict):
        return set()
    if isinstance(raw.get("mounted"), list):
        return {str(m) for m in raw["mounted"]}
    if raw.get("active"):
        return {str(raw["active"])}
    return set()


def _load_module_hooks(module_name: str) -> dict[str, list[str]]:
    try:
        tmpl_path = role_dir(module_name) / "template.yml"
    except FileNotFoundError:
        return {}
    data = yaml.safe_load(tmpl_path.read_text(encoding="utf-8")) or {}
    hooks = data.get("hooks") or {}
    return {k: list(v or []) for k, v in hooks.items() if isinstance(v, list)}


def _load_runtime_answers(roles_root: Path, module_name: str) -> dict[str, Any]:
    ans_path = roles_root / module_name / "answers.yml"
    if not ans_path.is_file():
        return {}
    raw = yaml.safe_load(ans_path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, dict) and isinstance(raw.get("answers"), dict):
        return raw["answers"]
    return raw if isinstance(raw, dict) else {}


def _run_hook_list(
    commands: list[str],
    answers: dict[str, Any],
    log: Callable[[str], None],
    cwd: Path | None = None,
) -> None:
    run_cwd = str(cwd) if cwd is not None and cwd.is_dir() else None
    for cmd in commands:
        rendered = cmd
        if answers:
            try:
                rendered = cmd.format_map({"answers": answers})
            except (KeyError, ValueError):
                pass
        log(f"  $ {rendered}")
        try:
            res = _exec_shell(rendered) if run_cwd is None else _exec_shell(rendered, cwd=run_cwd)
        except TypeError:
            # Test monkeypatches of _exec_shell accepting a single argument
            res = _exec_shell(rendered)
        if res.returncode != 0:
            log(f"  ! hook exited {res.returncode}: {(res.stderr or '').strip()}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_stream(stream: Any) -> str:
    h = hashlib.sha256()
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


def _write_tar_archive(
    archive_path: Path,
    files_to_pack: list[tuple[str, Path]],
    manifest: dict[str, Any],
) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tf:
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        tf.addfile(info, io.BytesIO(manifest_bytes))
        for arcname, src in files_to_pack:
            tf.add(str(src), arcname=arcname, recursive=False)


def _record_last_backup(record: dict[str, Any]) -> None:
    try:
        PLATYPUS_DIR.mkdir(parents=True, exist_ok=True)
        marker = PLATYPUS_DIR / "last_backup.json"
        marker.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _prune_old_archives(dest: Path, scope: str, keep: int, log: Callable[[str], None]) -> None:
    if keep <= 0 or not dest.is_dir():
        return
    pattern = f"platypus-backup-{scope}-*.tar.gz"
    archives = sorted(dest.glob(pattern), key=lambda p: p.stat().st_mtime)
    while len(archives) > keep:
        oldest = archives.pop(0)
        oldest.unlink(missing_ok=True)
        log(f"Pruned old archive: {oldest.name}")


def _run_external(cmd: list[str], tool_name: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise BackupError(
            f"{tool_name!r} CLI not found on PATH — install {tool_name} first."
        ) from exc


def create_backup(
    module: str | None = None,
    dest: Path | None = None,
    keep: int = 7,
    s3_bucket: str | None = None,
    force_unlock: bool = False,
    log: Callable[[str], None] = print,
) -> Path:
    """Create a state-aware `.tar.gz` backup with SHA-256 manifest."""
    dest_dir = dest if dest is not None else DEFAULT_BACKUP_DEST
    roles_root = PLATYPUS_DIR / "roles"

    try:
        lock_mod.acquire(f"backup:{module or 'all'}", force=force_unlock)
    except lock_mod.LockError as exc:
        raise BackupError(str(exc)) from exc

    try:
        mounted_set = _load_mounted_set(PLATYPUS_DIR)
        if module:
            mod_dir = roles_root / module
            if not mod_dir.is_dir():
                raise BackupError(f"Module runtime directory not found: {mod_dir}")
            target_modules = [module]
        else:
            target_modules = (
                sorted(d.name for d in roles_root.iterdir() if d.is_dir())
                if roles_root.is_dir()
                else []
            )

        hooked_mounted: list[tuple[str, dict[str, Any], list[str]]] = []
        for mod_name in target_modules:
            if mod_name in mounted_set:
                hooks = _load_module_hooks(mod_name)
                ans = _load_runtime_answers(roles_root, mod_name)
                pre = hooks.get("pre_backup") or []
                post = hooks.get("post_backup") or []
                if pre:
                    log(f"Running pre_backup hooks for {mod_name!r}...")
                    _run_hook_list(pre, ans, log, cwd=roles_root / mod_name)
                if post:
                    hooked_mounted.append((mod_name, ans, post))

        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d-%H%M%S")
        scope = module or "all"
        archive_path = dest_dir / f"platypus-backup-{scope}-{ts}.tar.gz"

        try:
            files_to_pack: list[tuple[str, Path]] = []
            checksums: dict[str, str] = {}

            state_file = PLATYPUS_DIR / "state.yml"
            if module is None and state_file.is_file():
                files_to_pack.append(("state.yml", state_file))
                checksums["state.yml"] = _sha256_file(state_file)

            for mod_name in target_modules:
                mod_dir = roles_root / mod_name
                for file_path in sorted(mod_dir.rglob("*")):
                    if file_path.is_file() and not file_path.is_symlink():
                        rel = file_path.relative_to(PLATYPUS_DIR).as_posix()
                        files_to_pack.append((rel, file_path))
                        checksums[rel] = _sha256_file(file_path)

            manifest = {
                "schema_version": "1",
                "created_at": now.isoformat(),
                "scope": scope,
                "modules": target_modules,
                "files": checksums,
            }
            _write_tar_archive(archive_path, files_to_pack, manifest)
        except OSError as exc:
            raise BackupError(f"Failed to write backup archive {archive_path}: {exc}") from exc
        finally:
            for mod_name, ans, post in reversed(hooked_mounted):
                log(f"Running post_backup hooks for {mod_name!r}...")
                _run_hook_list(post, ans, log, cwd=roles_root / mod_name)

        if s3_bucket:
            bucket = s3_bucket.rstrip("/")
            res = _run_external(
                ["aws", "s3", "cp", str(archive_path), f"s3://{bucket}/{archive_path.name}"],
                "aws",
            )
            if res.returncode != 0:
                raise BackupError(f"S3 upload failed: {(res.stderr or '').strip()}")
            log(f"Uploaded to s3://{bucket}/{archive_path.name}")

        _prune_old_archives(dest_dir, scope=scope, keep=keep, log=log)
        _record_last_backup(
            {
                "timestamp": now.timestamp(),
                "created_at": now.isoformat(),
                "backend": "tar",
                "archive": str(archive_path),
                "modules": target_modules,
            }
        )
        log(f"Backup complete: {archive_path}")
        return archive_path
    finally:
        lock_mod.release()


def create_restic_backup(
    repo: str,
    module: str | None = None,
    keep: int = 7,
    force_unlock: bool = False,
    log: Callable[[str], None] = print,
) -> None:
    """Snapshot runtime state into an encrypted Restic repository."""
    if not (os.environ.get("RESTIC_PASSWORD") or os.environ.get("RESTIC_PASSWORD_FILE")):
        raise BackupError("Set RESTIC_PASSWORD or RESTIC_PASSWORD_FILE for restic backups.")

    roles_root = PLATYPUS_DIR / "roles"
    target_path = (roles_root / module) if module else PLATYPUS_DIR
    if not target_path.exists():
        raise BackupError(f"Backup source path does not exist: {target_path}")

    try:
        lock_mod.acquire(f"backup:{module or 'all'}", force=force_unlock)
    except lock_mod.LockError as exc:
        raise BackupError(str(exc)) from exc

    try:
        mounted_set = _load_mounted_set(PLATYPUS_DIR)
        target_modules = (
            [module]
            if module
            else (
                sorted(d.name for d in roles_root.iterdir() if d.is_dir())
                if roles_root.is_dir()
                else []
            )
        )

        probe = _run_external(["restic", "-r", repo, "cat", "config"], "restic")
        if probe.returncode != 0:
            init_res = _run_external(["restic", "-r", repo, "init"], "restic")
            if init_res.returncode != 0:
                raise BackupError(f"restic init failed: {(init_res.stderr or '').strip()}")

        hooked_mounted: list[tuple[str, dict[str, Any], list[str]]] = []
        for mod_name in target_modules:
            if mod_name in mounted_set:
                hooks = _load_module_hooks(mod_name)
                ans = _load_runtime_answers(roles_root, mod_name)
                if hooks.get("pre_backup"):
                    _run_hook_list(hooks["pre_backup"], ans, log, cwd=roles_root / mod_name)
                if hooks.get("post_backup"):
                    hooked_mounted.append((mod_name, ans, hooks["post_backup"]))

        try:
            cmd = ["restic", "-r", repo, "backup", str(target_path), "--tag", "platypus"]
            for mod_name in target_modules:
                cmd.extend(["--tag", mod_name])
            res = _run_external(cmd, "restic")
            if res.returncode != 0:
                raise BackupError(f"restic backup failed: {(res.stderr or '').strip()}")
        finally:
            for mod_name, ans, post in reversed(hooked_mounted):
                _run_hook_list(post, ans, log, cwd=roles_root / mod_name)

        if keep > 0:
            forget_cmd = [
                "restic",
                "-r",
                repo,
                "forget",
                "--tag",
                "platypus",
                "--keep-last",
                str(keep),
                "--prune",
            ]
            f_res = _run_external(forget_cmd, "restic")
            if f_res.returncode != 0:
                raise BackupError(f"restic forget failed: {(f_res.stderr or '').strip()}")

        now = datetime.now(timezone.utc)
        _record_last_backup(
            {
                "timestamp": now.timestamp(),
                "created_at": now.isoformat(),
                "backend": "restic",
                "repository": repo,
                "modules": target_modules,
            }
        )
        log(f"Restic backup complete in {repo}")
    finally:
        lock_mod.release()


def _validate_safe_member_name(name: str) -> PurePosixPath:
    if "\\" in name or ":" in name:
        raise BackupError(f"Unsafe path in archive: {name!r}")
    posix = PurePosixPath(name)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise BackupError(f"Unsafe path in archive: {name!r}")
    return posix


def _safe_destination(root: Path, rel_path: str) -> Path:
    posix = _validate_safe_member_name(rel_path)
    resolved_root = root.resolve()
    current = root
    for part in posix.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise BackupError(f"Refusing to traverse symlink directory: {current}")
    out_path = root.joinpath(*posix.parts)
    if out_path.is_symlink():
        out_path.unlink()
    if not out_path.resolve().is_relative_to(resolved_root):
        raise BackupError(f"Unsafe destination outside PLATYPUS_DIR: {rel_path!r}")
    return out_path


def restore_backup(
    archive: Path,
    module: str | None = None,
    force_unlock: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Verify SHA-256 manifest in streaming chunks and safely extract into ``PLATYPUS_DIR``."""
    if not archive.is_file():
        raise BackupError(f"Archive not found: {archive}")

    try:
        lock_mod.acquire(f"restore:{module or 'all'}", force=force_unlock)
    except lock_mod.LockError as exc:
        raise BackupError(str(exc)) from exc

    try:
        # Pass 1: validate member names, load manifest, verify SHA-256 via streaming reads
        with tarfile.open(archive, "r:gz") as tf:
            by_name: dict[str, tarfile.TarInfo] = {}
            for m in tf.getmembers():
                _validate_safe_member_name(m.name)
                if m.issym() or m.islnk() or m.isdev():
                    raise BackupError(f"Unsupported special archive member: {m.name!r}")
                by_name[m.name] = m

            if "manifest.json" not in by_name:
                raise BackupError("Archive is missing manifest.json")

            m_fh = tf.extractfile(by_name["manifest.json"])
            assert m_fh is not None
            manifest = json.loads(m_fh.read().decode("utf-8"))
            expected_files: dict[str, str] = manifest.get("files") or {}

            selected_paths: list[str] = []
            for rel_path, expected_hash in expected_files.items():
                _validate_safe_member_name(rel_path)
                if module is not None and not rel_path.startswith(f"roles/{module}/"):
                    continue
                if rel_path not in by_name:
                    raise BackupError(f"Archive missing declared file {rel_path!r}")
                ef = tf.extractfile(by_name[rel_path])
                if ef is None:
                    raise BackupError(f"Cannot read {rel_path!r} from archive")
                actual_hash = _sha256_stream(ef)
                if actual_hash != expected_hash:
                    raise BackupError(
                        f"SHA-256 checksum mismatch for {rel_path!r}: "
                        f"expected {expected_hash}, got {actual_hash}"
                    )
                selected_paths.append(rel_path)

        # Pass 2: stream verified members to disk without buffering multi-GB files in RAM
        PLATYPUS_DIR.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tf:
            by_name = {m.name: m for m in tf.getmembers()}
            for rel_path in selected_paths:
                out_path = _safe_destination(PLATYPUS_DIR, rel_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                ef = tf.extractfile(by_name[rel_path])
                assert ef is not None
                with out_path.open("wb") as dst:
                    shutil.copyfileobj(ef, dst, length=65536)

        log(f"Restored {len(selected_paths)} file(s) into {PLATYPUS_DIR}")
        return manifest
    except (tarfile.TarError, ValueError) as exc:
        raise BackupError(f"Invalid backup archive {archive}: {exc}") from exc
    finally:
        lock_mod.release()


def main_backup(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="platypus backup",
        description="Create a state-aware backup of Platypus modules.",
    )
    parser.add_argument("module", nargs="?", help="Optional single module to back up")
    parser.add_argument(
        "--backend",
        choices=["tar", "restic"],
        default=os.environ.get("PLATYPUS_BACKUP_BACKEND", "tar"),
        help="Backup backend (default: tar)",
    )
    parser.add_argument(
        "--dest",
        default=os.environ.get("PLATYPUS_BACKUP_DIR"),
        help="Destination directory for tar archives (default: /var/backups/platypus)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("RESTIC_REPOSITORY"),
        help="Restic repository path/URL when --backend=restic",
    )
    parser.add_argument("--keep", type=int, default=7, help="Snapshots/archives to retain")
    parser.add_argument("--s3", default=os.environ.get("S3_BUCKET"), help="Optional S3 bucket")
    parser.add_argument("--force-unlock", action="store_true", help="Steal a stale transition lock")
    args = parser.parse_args(argv)

    try:
        if args.backend == "restic":
            if not args.repo:
                raise BackupError("--repo (or RESTIC_REPOSITORY) is required for restic backend.")
            create_restic_backup(
                repo=args.repo,
                module=args.module,
                keep=args.keep,
                force_unlock=args.force_unlock,
            )
        else:
            dest_path = Path(args.dest) if args.dest else DEFAULT_BACKUP_DEST
            create_backup(
                module=args.module,
                dest=dest_path,
                keep=args.keep,
                s3_bucket=args.s3 or None,
                force_unlock=args.force_unlock,
            )
        return 0
    except BackupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def main_restore(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="platypus restore",
        description="Verify and restore a Platypus backup archive.",
    )
    parser.add_argument("archive", help="Path to platypus-backup-*.tar.gz")
    parser.add_argument("--module", help="Restore only a single module from the archive")
    parser.add_argument("--force-unlock", action="store_true", help="Steal a stale transition lock")
    args = parser.parse_args(argv)

    try:
        restore_backup(Path(args.archive), module=args.module, force_unlock=args.force_unlock)
        return 0
    except BackupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
