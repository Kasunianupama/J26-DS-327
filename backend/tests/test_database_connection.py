from backend.app.core.config import Settings
from backend.app.database.connection import database_url

APP_DB_VARS = (
    "APP_DB_HOST",
    "APP_DB_PORT",
    "APP_DB_NAME",
    "APP_DB_API_USER",
    "APP_DB_API_PASSWORD",
)


def test_app_db_url_uses_farmx_app_defaults(monkeypatch):
    for var in APP_DB_VARS:
        monkeypatch.delenv(var, raising=False)
    # _env_file=None: never read the local .env in tests.
    url = database_url(Settings(_env_file=None))
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "localhost"
    assert url.port == 5433
    assert url.database == "farmx_app"
    assert url.username == "farmx_api"
    assert url.password is None


def test_app_db_url_reads_env_vars(monkeypatch):
    monkeypatch.setenv("APP_DB_HOST", "db.example.test")
    monkeypatch.setenv("APP_DB_PORT", "6543")
    monkeypatch.setenv("APP_DB_NAME", "synthetic_db")
    monkeypatch.setenv("APP_DB_API_USER", "synthetic_user")
    monkeypatch.setenv("APP_DB_API_PASSWORD", "synthetic-not-a-secret")
    url = database_url(Settings(_env_file=None))
    assert url.host == "db.example.test"
    assert url.port == 6543
    assert url.database == "synthetic_db"
    assert url.username == "synthetic_user"
    assert url.password == "synthetic-not-a-secret"
