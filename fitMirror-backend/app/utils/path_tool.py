"""项目路径配置：支持 .env 配置存储根目录，DB 存相对路径（相对 fitMirror-backend 根）。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# fitMirror-backend 根目录（main.py 所在目录）
BACKEND_ROOT = Path(__file__).resolve().parents[2]
# 项目根目录（fitMirror，fitMirror-backend 的上一级）
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", str(BACKEND_ROOT.parent))).resolve()


def _resolve_dir(env_key: str, default: Path) -> Path:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default.resolve()
    p = Path(raw)
    if not p.is_absolute():
        p = BACKEND_ROOT / p
    return p.resolve()


STORAGE_ROOT = _resolve_dir("STORAGE_ROOT", BACKEND_ROOT / "storage")
UPLOADS_DIR = STORAGE_ROOT / "uploads"
WORKSPACES_DIR = STORAGE_ROOT / "workspaces"
GENERATED_DIR = STORAGE_ROOT / "generated"
KNOWLEDGE_DIR = STORAGE_ROOT / "knowledge"


def ensure_storage_dirs() -> None:
    for d in (UPLOADS_DIR, WORKSPACES_DIR, GENERATED_DIR, KNOWLEDGE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def sku_upload_dir(sku_id: str) -> Path:
    p = UPLOADS_DIR / sku_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def sku_workspace_dir(sku_id: str) -> Path:
    p = WORKSPACES_DIR / sku_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def job_output_dir(job_id: str) -> Path:
    p = GENERATED_DIR / job_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def normalize_stored_path(path: str | Path | None) -> str:
    """将任意路径规范为 DB 存储用的相对路径（相对 fitMirror-backend 根，如 storage/uploads/...）。"""
    if not path:
        return ""
    s = str(path).strip().replace("\\", "/")
    if not s:
        return ""

    # 已是相对路径
    p = Path(s)
    if not p.is_absolute():
        return s.lstrip("./")

    resolved = p.resolve()
    try:
        return resolved.relative_to(BACKEND_ROOT.resolve()).as_posix()
    except ValueError:
        pass

    # 从路径中提取 storage/ 段
    parts = resolved.parts
    for i, part in enumerate(parts):
        if part.lower() == "storage":
            return "/".join(parts[i:]).replace("\\", "/")
    return s


def _legacy_backend_path(candidate: Path) -> Path | None:
    """兼容目录从 backend 重命名为 fitMirror-backend 后的历史绝对路径。"""
    s = str(candidate)
    replacements = (
        (f"{PROJECT_ROOT / 'backend'}", f"{BACKEND_ROOT}"),
        (str(PROJECT_ROOT / "backend"), str(BACKEND_ROOT)),
    )
    for old, new in replacements:
        if old in s:
            alt = Path(s.replace(old, new, 1)).resolve()
            if alt.is_file():
                return alt
    return None


def resolve_storage_path(path: str | Path | None) -> Path | None:
    """将 DB 中的相对路径或历史绝对路径解析为本地绝对 Path。"""
    if not path:
        return None
    s = str(path).strip()
    if not s:
        return None

    p = Path(s)
    if p.is_absolute():
        resolved = p.resolve()
        if resolved.is_file():
            return resolved
        legacy = _legacy_backend_path(resolved)
        if legacy:
            return legacy
        return resolved

    # 相对 backend 根
    candidate = (BACKEND_ROOT / p).resolve()
    if candidate.exists():
        return candidate

    # 兼容仅 storage/... 形式
    if not s.startswith("storage/") and not s.startswith("storage\\"):
        alt = (BACKEND_ROOT / "storage" / p).resolve()
        if alt.exists():
            return alt

    return candidate


def path_exists(path: str | Path | None) -> bool:
    resolved = resolve_storage_path(path)
    return bool(resolved and resolved.is_file())


def safe_filename(name: str, default: str = "file") -> str:
    """Strip directory components from user-supplied filenames."""
    base = Path(name or "").name
    if not base or base in (".", ".."):
        return default
    return base


def safe_resolve_under(base_dir: Path, *parts: str) -> Path | None:
    """Resolve a path and ensure it stays within base_dir."""
    if not parts:
        return None
    try:
        candidate = base_dir.joinpath(*parts).resolve()
        candidate.relative_to(base_dir.resolve())
        return candidate
    except (ValueError, OSError):
        return None


def storage_url(path: str | Path | None) -> str | None:
    """将存储路径转为 /storage/... 静态 URL。"""
    resolved = resolve_storage_path(path)
    if not resolved or not resolved.is_file():
        return None
    try:
        rel = resolved.relative_to(STORAGE_ROOT.resolve()).as_posix()
        return f"/storage/{rel}"
    except ValueError:
        return None
