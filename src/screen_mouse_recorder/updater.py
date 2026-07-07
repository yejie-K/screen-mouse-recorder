from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Any


@dataclass(slots=True)
class UpdateStatus:
    available: bool
    git_root: Path | None = None
    current_branch: str = ""
    target_ref: str = ""
    local_commit: str = ""
    remote_commit: str = ""
    behind_count: int = 0
    ahead_count: int = 0
    dirty: bool = False
    message: str = ""


def check_for_updates(base_dir: Path, *, remote: str = "origin", timeout_seconds: int = 30) -> UpdateStatus:
    git_root = _git_root(base_dir, timeout_seconds=timeout_seconds)
    if git_root is None:
        return UpdateStatus(False, message="当前目录不是 Git 仓库")

    branch = _git_text(git_root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout_seconds=timeout_seconds)
    if not branch or branch == "HEAD":
        return UpdateStatus(False, git_root=git_root, message="当前不是普通分支，无法自动更新")

    target_ref = _tracking_ref(git_root, branch, remote, timeout_seconds=timeout_seconds)
    if not target_ref:
        return UpdateStatus(False, git_root=git_root, current_branch=branch, message="未找到可检查的远端分支")

    fetch = _run_git(git_root, ["fetch", "--quiet", remote], timeout_seconds=timeout_seconds)
    if fetch.returncode != 0:
        return UpdateStatus(
            False,
            git_root=git_root,
            current_branch=branch,
            target_ref=target_ref,
            message=_compact_process_error(fetch, "检查更新失败"),
        )

    local_commit = _git_text(git_root, ["rev-parse", "HEAD"], timeout_seconds=timeout_seconds)
    remote_commit = _git_text(git_root, ["rev-parse", target_ref], timeout_seconds=timeout_seconds)
    if not local_commit or not remote_commit:
        return UpdateStatus(
            False,
            git_root=git_root,
            current_branch=branch,
            target_ref=target_ref,
            message="无法读取本地或远端版本",
        )

    behind_count = _git_int(git_root, ["rev-list", "--count", f"HEAD..{target_ref}"], timeout_seconds=timeout_seconds)
    ahead_count = _git_int(git_root, ["rev-list", "--count", f"{target_ref}..HEAD"], timeout_seconds=timeout_seconds)
    dirty = _is_dirty(git_root, timeout_seconds=timeout_seconds)
    return UpdateStatus(
        available=behind_count > 0,
        git_root=git_root,
        current_branch=branch,
        target_ref=target_ref,
        local_commit=local_commit[:12],
        remote_commit=remote_commit[:12],
        behind_count=behind_count,
        ahead_count=ahead_count,
        dirty=dirty,
        message="发现新版本" if behind_count > 0 else "已是最新版本",
    )


def apply_update(status: UpdateStatus, *, timeout_seconds: int = 180) -> UpdateStatus:
    if status.git_root is None:
        return UpdateStatus(False, message="未找到 Git 仓库，无法更新")
    if not status.available:
        return UpdateStatus(False, git_root=status.git_root, message="当前已是最新版本")
    if status.dirty:
        return UpdateStatus(
            False,
            git_root=status.git_root,
            current_branch=status.current_branch,
            target_ref=status.target_ref,
            local_commit=status.local_commit,
            remote_commit=status.remote_commit,
            behind_count=status.behind_count,
            ahead_count=status.ahead_count,
            dirty=True,
            message="检测到本地代码改动，已取消自动更新",
        )

    fetch = _run_git(status.git_root, ["fetch", "--quiet", "origin"], timeout_seconds=timeout_seconds)
    if fetch.returncode != 0:
        return UpdateStatus(
            False,
            git_root=status.git_root,
            current_branch=status.current_branch,
            target_ref=status.target_ref,
            local_commit=status.local_commit,
            remote_commit=status.remote_commit,
            behind_count=status.behind_count,
            ahead_count=status.ahead_count,
            dirty=_is_dirty(status.git_root, timeout_seconds=30),
            message=_compact_process_error(fetch, "更新失败"),
        )

    merge = _run_git(status.git_root, ["merge", "--ff-only", status.target_ref], timeout_seconds=timeout_seconds)
    if merge.returncode != 0:
        return UpdateStatus(
            False,
            git_root=status.git_root,
            current_branch=status.current_branch,
            target_ref=status.target_ref,
            local_commit=status.local_commit,
            remote_commit=status.remote_commit,
            behind_count=status.behind_count,
            ahead_count=status.ahead_count,
            dirty=_is_dirty(status.git_root, timeout_seconds=30),
            message=_compact_process_error(merge, "更新失败"),
        )

    refreshed = check_for_updates(status.git_root, timeout_seconds=30)
    refreshed.message = "更新完成"
    return refreshed


def _git_root(base_dir: Path, *, timeout_seconds: int) -> Path | None:
    if shutil.which("git") is None:
        return None
    result = _run_git(base_dir, ["rev-parse", "--show-toplevel"], timeout_seconds=timeout_seconds)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return Path(text).resolve() if text else None


def _tracking_ref(git_root: Path, branch: str, remote: str, *, timeout_seconds: int) -> str:
    upstream = _git_text(
        git_root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        timeout_seconds=timeout_seconds,
    )
    if upstream:
        return upstream

    for candidate in (f"{remote}/{branch}", f"{remote}/main", f"{remote}/master"):
        result = _run_git(git_root, ["rev-parse", "--verify", "--quiet", candidate], timeout_seconds=timeout_seconds)
        if result.returncode == 0:
            return candidate
    return ""


def _is_dirty(git_root: Path, *, timeout_seconds: int) -> bool:
    result = _run_git(
        git_root,
        ["status", "--porcelain", "--untracked-files=no"],
        timeout_seconds=timeout_seconds,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def _git_text(git_root: Path, args: list[str], *, timeout_seconds: int) -> str:
    result = _run_git(git_root, args, timeout_seconds=timeout_seconds)
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_int(git_root: Path, args: list[str], *, timeout_seconds: int) -> int:
    text = _git_text(git_root, args, timeout_seconds=timeout_seconds)
    try:
        return int(text)
    except ValueError:
        return 0


def _run_git(cwd: Path, args: list[str], *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(cwd), *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", str(exc))


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": creationflags} if creationflags else {}


def _compact_process_error(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    text = (result.stderr or result.stdout or fallback).strip()
    text = " ".join(text.split())
    return text[:160] + "..." if len(text) > 160 else text
