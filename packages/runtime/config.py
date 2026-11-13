"""Fail-closed deployment settings. Secrets are read only by workers."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    public_url: str
    database: Path | str
    auth_database: Path
    jobs_database: Path
    secure: bool = True
    llm_provider: str = "disabled"
    llm_model: str = ""
    search_enabled: bool = False
    daily_jobs: int = 20
    max_output_tokens: int = 2000
    session_hours: int = 8
    search_provider: str = "disabled"

    @property
    def cookie_name(self):
        return "__Host-sponsor" if self.secure else "sponsor_local"

    @classmethod
    def from_env(cls):
        url = os.environ.get("SPONSOR_PUBLIC_URL", "").rstrip("/")
        parts = urlsplit(url)
        if not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
            raise ValueError("SPONSOR_PUBLIC_URL: нужен origin без пути, пароля и параметров")
        secure = parts.scheme == "https"
        if not secure and not (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")
                               and os.environ.get("SPONSOR_ALLOW_INSECURE_LOCAL") == "1"):
            raise ValueError("Нужен HTTPS; HTTP разрешён только для явно включённой локальной проверки")
        provider = os.environ.get("SPONSOR_LLM_PROVIDER", "disabled")
        model = os.environ.get("SPONSOR_LLM_MODEL", "").strip()
        if provider not in ("disabled", "openai", "anthropic") or (provider != "disabled" and not model):
            raise ValueError("Выберите disabled/openai/anthropic и задайте доступный API model ID")
        def bounded(name, default, low, high):
            value = int(os.environ.get(name, default))
            if not low <= value <= high:
                raise ValueError(f"{name}: вне допустимого диапазона")
            return value
        search_enabled = os.environ.get("SPONSOR_SEARCH_ENABLED", "0") == "1"
        search_provider = os.environ.get("SPONSOR_SEARCH_PROVIDER", "exa" if search_enabled else "disabled")
        if search_provider not in ("disabled", "exa", "stub"):
            raise ValueError("SPONSOR_SEARCH_PROVIDER: disabled/exa/stub")
        database = os.environ.get("SPONSOR_DATABASE", "/data/research/workspace.sqlite3")
        return cls(url, database if database.startswith('firestore://') else Path(database),
                   Path(os.environ.get("SPONSOR_AUTH_DATABASE", "/data/auth/auth.sqlite3")),
                   Path(os.environ.get("SPONSOR_JOBS_DATABASE", "/data/jobs/jobs.sqlite3")), secure, provider, model,
                   search_provider != "disabled",
                   bounded("SPONSOR_DAILY_JOBS", "20", 1, 500), bounded("SPONSOR_MAX_OUTPUT_TOKENS", "2000", 128, 16000),
                   bounded("SPONSOR_SESSION_HOURS", "8", 1, 24), search_provider)


def secret(name):
    path = os.environ.get(name + "_FILE", "")
    if not path:
        raise ValueError(f"Не задан {name}_FILE")
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value or len(value) > 4096 or "\n" in value or "\r" in value:
        raise ValueError(f"Пустой или неверный файл {name}_FILE")
    return value
