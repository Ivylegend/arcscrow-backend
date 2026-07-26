from app.core.config import Settings


def test_normalizes_postgres_url_for_async_driver() -> None:
    settings = Settings.model_validate({"database_url": "postgresql://user:pass@db/app"})

    assert settings.database_url == "postgresql+asyncpg://user:pass@db/app"


def test_parses_json_allowed_origins() -> None:
    settings = Settings.model_validate(
        {"allowed_origins": '["https://app.example.com", "http://localhost:5173"]'}
    )

    assert settings.allowed_origins == ["https://app.example.com", "http://localhost:5173"]
