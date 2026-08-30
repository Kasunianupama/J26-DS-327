from backend.app.database.connection import database_url


def test_sql_server_url_uses_dbeaver_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_HOST", raising=False)
    monkeypatch.delenv("DATABASE_PORT", raising=False)
    monkeypatch.delenv("DATABASE_NAME", raising=False)
    from backend.app.core.config import get_settings
    get_settings.cache_clear()
    url = database_url()
    assert url.drivername == "mssql+pyodbc"
    assert url.host == "localhost"
    assert url.port == 1433
    assert url.database == "master"
    get_settings.cache_clear()
