import os
import sys
from pathlib import Path
import pytest

# Backend kök dizinini sys.path'e ekle
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings, settings


def test_settings_default_or_loaded():
    """Settings sınıfının başarıyla başlatıldığını ve GEMINI_API_KEY alanının varlığını test eder."""
    assert hasattr(settings, "GEMINI_API_KEY")


def test_settings_extra_ignore():
    """Settings sınıfının 'extra=ignore' yapılandırması sayesinde bilinmeyen argümanları tolere ettiğini test eder."""
    custom_settings = Settings(GEMINI_API_KEY="test_key_123", extra_unknown_field="ignored_value")
    assert custom_settings.GEMINI_API_KEY == "test_key_123"


def test_settings_env_override(monkeypatch):
    """Ortam değişkenleri (os.environ) üzerinden GEMINI_API_KEY yüklenebildiğini test eder."""
    monkeypatch.setenv("GEMINI_API_KEY", "env_override_key")
    custom_settings = Settings()
    assert custom_settings.GEMINI_API_KEY == "env_override_key"


def test_settings_database_url_loaded():
    """Settings sınıfının DATABASE_URL alanını başarıyla yüklediğini test eder."""
    assert hasattr(settings, "DATABASE_URL")
    assert "postgresql" in settings.DATABASE_URL


def test_settings_database_url_env_override(monkeypatch):
    """Ortam değişkenleri üzerinden DATABASE_URL değerinin ezilebildiğini test eder."""
    custom_url = "postgresql+asyncpg://custom_user:custom_pass@custom_host:5432/custom_db"
    monkeypatch.setenv("DATABASE_URL", custom_url)
    custom_settings = Settings()
    assert custom_settings.DATABASE_URL == custom_url
    assert custom_settings.async_database_url == custom_url


def test_settings_async_database_url_railway_compatibility(monkeypatch):
    """Railway tarafından sağlanan standart 'postgresql://' dizesinin 'postgresql+asyncpg://' formatına dönüştürüldüğünü test eder."""
    railway_url = "postgresql://postgres:secretpassword@containers-us-west-1.railway.app:7182/railway"
    monkeypatch.setenv("DATABASE_URL", railway_url)
    custom_settings = Settings()
    assert custom_settings.DATABASE_URL == railway_url
    assert custom_settings.async_database_url.startswith("postgresql+asyncpg://")
    assert "secretpassword@containers-us-west-1.railway.app:7182/railway" in custom_settings.async_database_url


@pytest.mark.parametrize(
    "prefix, expected_prefix",
    [
        ("postgres://", "postgresql+asyncpg://"),
        ("postgresql://", "postgresql+asyncpg://"),
        ("postgresql+psycopg2://", "postgresql+asyncpg://"),
        ("postgresql+psycopg://", "postgresql+asyncpg://"),
        ("postgresql+pg8000://", "postgresql+asyncpg://"),
        ("postgresql+asyncpg://", "postgresql+asyncpg://"),
    ],
)
def test_settings_async_database_url_all_prefixes(monkeypatch, prefix, expected_prefix):
    """Farklı PostgreSQL bağlantı şemalarının Settings.async_database_url tarafından başarıyla asenkrona uyarlandığını test eder."""
    url = f"{prefix}user:pass@host:5432/testdb"
    monkeypatch.setenv("DATABASE_URL", url)
    custom_settings = Settings()
    assert custom_settings.async_database_url == f"{expected_prefix}user:pass@host:5432/testdb"

