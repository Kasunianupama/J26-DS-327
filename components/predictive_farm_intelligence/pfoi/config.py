"""Settings for PFOI.

Database settings use the same variables and root `.env` file as the backend (see the
root `.env.example`): APP_DB_HOST, APP_DB_PORT, APP_DB_NAME and the Component 1 login
APP_DB_PFOI_USER / APP_DB_PFOI_PASSWORD (role farmx_model). PFOI_DATABASE_URL, if set,
overrides them. Values are read at run time on the user's machine and never printed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

REPO_ROOT = Path(__file__).resolve().parents[3]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineConfig:
    """Modelling choices for the herd engine. Defaults follow docs/forecast_design.md."""

    window_months: int | None = 24  # None = expanding window
    # A conception counts as "recorded" only once this many days have passed
    # (typical pregnancy-diagnosis delay). Conceptions newer than this at the
    # origin are not known and are projected by the conception hazard instead.
    pregnancy_check_lag_days: int = 35
    # Pseudo-exposure used for shrinkage when the method-of-moments estimate fails.
    default_prior_days: float = 3650.0
    # Where external entries go when the transition table does not say.
    default_entry_state: str = "heifer_open"
    entry_dim: int = 100
    entry_gestation: int = 150


class _EnvSettings(BaseSettings):
    pfoi_database_url: str = ""
    app_db_host: str = "localhost"
    app_db_port: int = 5433
    app_db_name: str = "farmx_app"
    app_db_pfoi_user: str = "farmx_model"
    app_db_pfoi_password: str = ""
    pfoi_core_schema: str = "core"
    pfoi_model_input_schema: str = "model_input"
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")


@dataclass(frozen=True)
class DatabaseSettings:
    url: URL
    core_schema: str = "core"
    model_input_schema: str = "model_input"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "DatabaseSettings":
        """Read the environment and root `.env`; with ``environ``, use only that dict."""
        if environ is None:
            env = _EnvSettings()
        else:
            fields = _EnvSettings.model_fields
            env = _EnvSettings(
                _env_file=None,
                **{k.lower(): v for k, v in environ.items() if k.lower() in fields},
            )
        if env.pfoi_database_url.strip():
            url = make_url(env.pfoi_database_url.strip())
        else:
            if not env.app_db_pfoi_user.strip():
                raise ConfigError("Set APP_DB_PFOI_USER (and APP_DB_PFOI_PASSWORD) in .env.")
            url = URL.create(
                "postgresql+psycopg",
                username=env.app_db_pfoi_user.strip(),
                password=env.app_db_pfoi_password or None,
                host=env.app_db_host,
                port=env.app_db_port,
                database=env.app_db_name,
            )
        if url.get_backend_name() != "postgresql":
            raise ConfigError("PFOI reads only the PostgreSQL farmx_app database.")
        return cls(
            url=url,
            core_schema=env.pfoi_core_schema,
            model_input_schema=env.pfoi_model_input_schema,
        )
