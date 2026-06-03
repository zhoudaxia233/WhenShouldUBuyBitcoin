import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends

from dca_service.auth.dependencies import get_current_admin_user
from dca_service.config import settings
from dca_service.models import User
from dca_service.services.static_generator import get_static_generation_log_path
from dca_service.services.distribution_scraper import (
    fetch_distribution_with_status,
    get_distribution_diagnostics,
)


router = APIRouter(prefix="/admin", tags=["admin"])


_SENSITIVE_LOG_PATTERNS = [
    (
        re.compile(
            r"(?i)\bhttps?connectionpool\(host='[^']+',\s*port=\d+\):\s*"
            r"(?:read timed out\.?(?:\s*\(read timeout=[^)]+\))?|[^\n\"']*)"
        ),
        "External HTTP request timed out.",
    ),
    (re.compile(r"(?i)\braw socket details\b"), "request details redacted"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|api[_-]?secret|authorization|bearer|password|secret|token)"
            r"(\s*[:=]\s*)(?:Bearer\s+)?([^\s,;]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]+=*"), "Bearer [REDACTED]"),
]


def _utc_iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _resolve_log_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _sanitize_log_line(line: str) -> str:
    sanitized = line.rstrip("\n")
    for pattern, replacement in _SENSITIVE_LOG_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _tail_text_file(path: Path, *, max_lines: int = 80, max_bytes: int = 128_000) -> dict:
    snapshot = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": None,
        "modified_at": None,
        "line_count": 0,
        "tail": [],
        "read_error": None,
    }
    if not path.exists():
        return snapshot

    try:
        stat = path.stat()
        snapshot["size_bytes"] = stat.st_size
        snapshot["modified_at"] = _utc_iso_from_timestamp(stat.st_mtime)
        with path.open("rb") as fh:
            if stat.st_size > max_bytes:
                fh.seek(-max_bytes, 2)
                fh.readline()
            content = fh.read().decode("utf-8", errors="replace")
        lines = content.splitlines()
        snapshot["line_count"] = len(lines)
        snapshot["tail"] = [_sanitize_log_line(line) for line in lines[-max_lines:]]
    except Exception as exc:
        snapshot["read_error"] = f"{type(exc).__name__}: {exc}"
    return snapshot


def _build_runtime_diagnostics() -> dict:
    service_log_path = _resolve_log_path(settings.LOG_FILE_PATH)
    static_generation_log_path = get_static_generation_log_path()
    return {
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "app_version": settings.APP_VERSION,
        "app_commit_sha": settings.APP_COMMIT_SHA,
        "log_level": settings.LOG_LEVEL,
        "service_log": _tail_text_file(service_log_path),
        "static_generation_log": _tail_text_file(static_generation_log_path),
    }


def _build_debug_summary(diagnostics: dict, runtime: dict) -> list[str]:
    summary = [
        f"BitInfoCharts status: {diagnostics.get('last_status') or 'unknown'}",
        f"Last attempt: {diagnostics.get('last_attempt_at') or 'never'}",
        f"Last success: {diagnostics.get('last_success_at') or 'never'}",
    ]
    if diagnostics.get("last_error_type"):
        summary.append(
            f"Last error: {diagnostics.get('last_error_type')} - "
            f"{diagnostics.get('last_error_message_sanitized') or 'no sanitized message'}"
        )
    if diagnostics.get("last_http_status"):
        summary.append(f"HTTP status: {diagnostics.get('last_http_status')}")
    if diagnostics.get("cache_age_seconds") is not None:
        summary.append(f"Cache age seconds: {diagnostics.get('cache_age_seconds')}")

    service_log = runtime.get("service_log", {})
    if service_log.get("exists"):
        summary.append(
            f"Service log: {service_log.get('path')} "
            f"({service_log.get('line_count')} sampled lines, modified {service_log.get('modified_at')})"
        )
    else:
        summary.append(f"Service log missing: {service_log.get('path')}")
    return summary


@router.get("/data-sources/bitinfocharts")
def get_bitinfocharts_diagnostics(
    current_user: User = Depends(get_current_admin_user),
):
    diagnostics = get_distribution_diagnostics()
    runtime = _build_runtime_diagnostics()
    return {
        "name": "BitInfoCharts Bitcoin wealth distribution",
        "diagnostics": diagnostics,
        "runtime": runtime,
        "debug_summary": _build_debug_summary(diagnostics, runtime),
    }


@router.post("/data-sources/bitinfocharts/refresh")
def refresh_bitinfocharts_distribution(
    current_user: User = Depends(get_current_admin_user),
):
    try:
        snapshot = fetch_distribution_with_status(
            use_cache=False,
            allow_static_fallback=False,
            allow_stale_cache=False,
        )
        data = snapshot.get("data") or []
        return {
            "success": True,
            "message": "BitInfoCharts live refresh completed.",
            "tier_count": len(data),
            "data_status": snapshot.get("data_status", "live"),
            "diagnostics": get_distribution_diagnostics(),
            "runtime": _build_runtime_diagnostics(),
        }
    except ValueError:
        return {
            "success": False,
            "message": "BitInfoCharts live refresh failed. See diagnostics.",
            "tier_count": 0,
            "data_status": "unavailable",
            "diagnostics": get_distribution_diagnostics(),
            "runtime": _build_runtime_diagnostics(),
        }
