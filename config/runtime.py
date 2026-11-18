"""Atomic application .env edits and live configuration snapshots (no Docker configuration)."""

import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from dotenv import dotenv_values
from pydantic import SecretStr

from config import get_global_config
from config.descriptions import DESCRIPTIONS, LEGACY_DEFAULTS
from dao.db import get_db_path

lock = threading.RLock()
revision = 0


def touch():
    """Invalidate call bindings after shared manager changes (without editing .env)."""
    global revision
    with lock:
        revision += 1


def env_path() -> Path:
    from config.config import find_config_file

    return find_config_file(".env") or get_db_path().parent / ".env"


def secret_name(name):
    return any(part in name.upper() for part in ("KEY", "SECRET", "PASSWORD")) or name.upper().endswith(
        ("AUTH_TOKEN", "ACCESS_TOKEN", "API_TOKEN")
    )


def plain(value):
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, bool):
        return str(value).lower()
    return "" if value is None else str(value)


def redact(value):
    """Redact exact configured secrets, including custom environment values."""
    text = str(value)
    cfg = get_global_config()
    values = {k: plain(v) for k, v in cfg.model_dump().items() if secret_name(k)}
    values.update({k: v for k, v in dotenv_values(env_path()).items() if v and k not in type(cfg).model_fields})
    for v in sorted(values.values(), key=len, reverse=True):
        if v:
            text = text.replace(v, "[REDACTED]")
    return text


def etag():
    path = env_path()
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def settings():
    cfg = get_global_config()
    raw = dotenv_values(env_path())
    fields = []
    for name, field in type(cfg).model_fields.items():
        value = getattr(cfg, name)
        default = LEGACY_DEFAULTS.get(name, field.default)
        sensitive = secret_name(name) or isinstance(value, SecretStr)
        fields.append(
            dict(
                name=name,
                value=None if sensitive else value,
                default=None if sensitive and plain(default) else ("" if sensitive else default),
                configured=bool(plain(value)),
                sensitive=sensitive,
                type="boolean"
                if isinstance(value, bool)
                else "number"
                if isinstance(value, (int, float))
                else "string",
                group=name.split("_")[0],
                description=DESCRIPTIONS.get(name, {"en": name, "zh-CN": name}),
            )
        )
    custom = [
        dict(name=k, value=None, configured=bool(v), sensitive=True)
        for k, v in raw.items()
        if k not in type(cfg).model_fields
    ]
    return dict(revision=etag(), fields=fields, custom=custom)


def save(changes: dict, expected=None, *, custom=False):
    global revision
    if not isinstance(changes, dict) or len(changes) > 200:
        raise ValueError("Invalid configuration update")
    with lock:
        if expected is not None and expected != etag():
            raise ValueError("Configuration changed; refresh before saving")
        cfg = get_global_config()
        fields = type(cfg).model_fields
        for name, value in changes.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError("Invalid variable name")
            if custom == (name in fields):
                raise ValueError("Use the correct configuration section")
            if custom and (
                name.startswith(("LARK_CHANNEL", "LARKSUITE_CLI_"))
                or name in {"PATH", "HOME", "PYTHONPATH", "LD_PRELOAD", "NODE_OPTIONS"}
            ):
                raise ValueError("Reserved runtime environment variable")
            if value is not None and (not isinstance(value, (str, int, float, bool)) or len(str(value)) > 100000):
                raise ValueError("Invalid configuration value")
        data = cfg.model_dump()
        for name, value in changes.items():
            if name in fields:
                data[name] = LEGACY_DEFAULTS.get(name, fields[name].default) if value is None else value
        candidate = type(cfg).model_validate(data)
        import math

        for value in candidate.model_dump().values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Numeric configuration must be finite")
        if not 1 <= candidate.WEBUI_PORT <= 65535 or not 1 <= candidate.WEBHOOK_PORT <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        if candidate.ENABLE_WEBUI and candidate.ENABLE_WEBHOOK and candidate.WEBUI_PORT == candidate.WEBHOOK_PORT:
            raise ValueError("WebUI and webhook must use independent ports")
        if candidate.ENABLE_WEBUI and (candidate.WEBUI_HOST, candidate.WEBUI_PORT) != (cfg.WEBUI_HOST, cfg.WEBUI_PORT):
            import socket

            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    listener.bind((candidate.WEBUI_HOST, candidate.WEBUI_PORT))
            except OSError as exc:
                raise ValueError("WebUI address is unavailable") from exc
        path = env_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        from dotenv.parser import parse_stream
        import io

        lines = [
            binding.original.string for binding in parse_stream(io.StringIO(original)) if binding.key not in changes
        ]
        text = "".join(lines).rstrip("\n") + "\n"
        for name, value in changes.items():
            if (custom and value is None) or (name in fields and getattr(candidate, name) is None):
                continue
            value = plain(getattr(candidate, name)) if name in fields else plain(value)
            # python-dotenv quoted strings preserve literal newlines and special characters.
            text += name + "='" + value.replace("\\", "\\\\").replace("'", "\\'") + "'\n"
        fd, tmp = tempfile.mkstemp(prefix=".env-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        # Preserve references held by existing tools; calls already in progress retain their arguments.
        for name in changes.keys() & fields.keys():
            setattr(cfg, name, getattr(candidate, name))
        for name, value in changes.items():
            if (custom and value is None) or (name in fields and getattr(candidate, name) is None):
                os.environ.pop(name, None)
            else:
                os.environ[name] = plain(getattr(candidate, name)) if name in fields else plain(value)
        if any(name != "ENABLE_WEBUI" and not name.startswith("WEBUI_") for name in changes):
            revision += 1
        return settings()
