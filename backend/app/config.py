import re
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Backend kök dizini ve .env dosyası yolu
BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Uygulama konfigürasyon ayarları."""
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    OMDB_API_KEY: Optional[str] = None
    TMDB_API_KEY: Optional[str] = None

    # PostgreSQL bağlantı dizesi (Varsayılan yerel geliştirme adresi)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/film_kesif_db"

    @property
    def async_database_url(self) -> str:
        """Tüm standart veya sağlayıcıya özel PostgreSQL bağlantı şemalarını (postgres://, postgresql://, postgresql+psycopg2:// vb.) SQLAlchemy asyncpg formatına uyarlar."""
        url = self.DATABASE_URL
        return re.sub(r"^(postgres|postgresql)(\+[a-zA-Z0-9_-]+)?://", "postgresql+asyncpg://", url, count=1)

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
