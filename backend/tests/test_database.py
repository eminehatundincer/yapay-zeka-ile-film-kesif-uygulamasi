import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import DeclarativeBase

# Backend kök dizinini sys.path'e ekle
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import (
    Base,
    Database,
    Movie,
    UserQuery,
    VibeTag,
    db,
    movie_vibes,
    normalize_to_asyncpg_url,
)


def test_base_declarative():
    """Base sınıfının SQLAlchemy DeclarativeBase tabanından türediğini doğrular."""
    assert issubclass(Base, DeclarativeBase)
    assert hasattr(Base, "metadata")


@pytest.mark.parametrize(
    "input_url, expected_url",
    [
        ("postgres://user:pass@localhost:5432/film_db", "postgresql+asyncpg://user:pass@localhost:5432/film_db"),
        ("postgresql://user:pass@localhost:5432/film_db", "postgresql+asyncpg://user:pass@localhost:5432/film_db"),
        ("postgresql+psycopg2://user:pass@localhost:5432/film_db", "postgresql+asyncpg://user:pass@localhost:5432/film_db"),
        ("postgresql+psycopg://user:pass@localhost:5432/film_db", "postgresql+asyncpg://user:pass@localhost:5432/film_db"),
        ("postgresql+pg8000://user:pass@localhost:5432/film_db", "postgresql+asyncpg://user:pass@localhost:5432/film_db"),
        ("postgresql+asyncpg://user:pass@localhost:5432/film_db", "postgresql+asyncpg://user:pass@localhost:5432/film_db"),
    ],
)
def test_normalize_to_asyncpg_url(input_url, expected_url):
    """Tüm olası PostgreSQL bağlantı dizesi prefixlerinin postgresql+asyncpg:// formatına dönüştürüldüğünü test eder."""
    assert normalize_to_asyncpg_url(input_url) == expected_url


def test_database_get_db_url(monkeypatch):
    """Database.get_db_url() metodunun settings.DATABASE_URL değerini asenkron formata çevirdiğini test eder."""
    test_db = Database()
    monkeypatch.setattr("app.database.settings.DATABASE_URL", "postgresql://dbuser:dbpass@dbhost:5432/testdb")
    assert test_db.get_db_url() == "postgresql+asyncpg://dbuser:dbpass@dbhost:5432/testdb"


@pytest.mark.asyncio
async def test_connect_success():
    """connect() metodunun motoru havuz parametreleriyle doğru başlattığını ve bağlantıyı doğruladığını test eder."""
    test_db = Database()

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = MagicMock()

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_conn
    mock_conn_ctx.__aexit__.return_value = None

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn_ctx

    with patch("app.database.create_async_engine", return_value=mock_engine) as mock_create_engine:
        await test_db.connect(max_retries=1, retry_interval=0.01)

        assert test_db.engine is not None
        assert test_db.session_factory is not None

        mock_create_engine.assert_called_once()
        _, kwargs = mock_create_engine.call_args
        assert kwargs.get("pool_size") == 5
        assert kwargs.get("max_overflow") == 15
        assert kwargs.get("pool_timeout") == 60
        assert kwargs.get("pool_pre_ping") is True


@pytest.mark.asyncio
async def test_connect_retry_and_eventual_success():
    """connect() metodunun başarısız bağlantı durumunda retry yapıp ardından başarılı olduğunu test eder."""
    test_db = Database()

    mock_conn = AsyncMock()
    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_conn

    # 1. ve 2. denemede hata verip 3. denemede başarılı olan motor kurgusu
    mock_engine_fail = MagicMock()
    mock_engine_fail.connect.side_effect = RuntimeError("Postgres henüz hazır değil")
    mock_engine_fail.dispose = AsyncMock()

    mock_engine_success = MagicMock()
    mock_engine_success.connect.return_value = mock_conn_ctx

    with patch("app.database.create_async_engine", side_effect=[mock_engine_fail, mock_engine_fail, mock_engine_success]), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        await test_db.connect(max_retries=5, retry_interval=2.0)

        assert test_db.engine is mock_engine_success
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(2.0)


@pytest.mark.asyncio
async def test_connect_max_retries_exceeded():
    """Tüm retry denemeleri tükendiğinde ConnectionError fırlatıldığını test eder."""
    test_db = Database()

    mock_engine = MagicMock()
    mock_engine.connect.side_effect = ConnectionRefusedError("Bağlantı reddedildi")
    mock_engine.dispose = AsyncMock()

    with patch("app.database.create_async_engine", return_value=mock_engine), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        with pytest.raises(ConnectionError) as exc_info:
            await test_db.connect(max_retries=3, retry_interval=1.0)

        assert "3 deneme sonrasında bağlanılamadı" in str(exc_info.value)
        assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_connect_auto_creates_database():
    """Hedef veritabanı bulunamadığında (InvalidCatalogNameError) otomatik oluşturulduğunu test eder."""
    test_db = Database()

    mock_conn = AsyncMock()
    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_conn

    mock_engine_missing_db = MagicMock()
    mock_engine_missing_db.connect.side_effect = Exception("InvalidCatalogNameError: database does not exist")
    mock_engine_missing_db.dispose = AsyncMock()

    mock_engine_success = MagicMock()
    mock_engine_success.connect.return_value = mock_conn_ctx

    with patch("app.database.create_async_engine", side_effect=[mock_engine_missing_db, mock_engine_success]), \
         patch.object(test_db, "_create_database", new_callable=AsyncMock) as mock_create_db:
        
        await test_db.connect(max_retries=1)

        mock_create_db.assert_called_once()
        assert test_db.engine is mock_engine_success


@pytest.mark.asyncio
async def test_create_database_helper():
    """_create_database metodunun postgres veritabanına bağlanıp CREATE DATABASE sorgusu çalıştırdığını test eder."""
    test_db = Database()

    mock_result = MagicMock()
    mock_result.scalar.return_value = None  # Veritabanı yok

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = mock_result
    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_conn

    mock_temp_engine = MagicMock()
    mock_temp_engine.connect.return_value = mock_conn_ctx
    mock_temp_engine.dispose = AsyncMock()

    with patch("app.database.create_async_engine", return_value=mock_temp_engine) as mock_create_engine:
        await test_db._create_database("postgresql+asyncpg://postgres:pass@localhost:5432/my_new_film_db")

        mock_create_engine.assert_called_once()
        _, kwargs = mock_create_engine.call_args
        assert kwargs.get("isolation_level") == "AUTOCOMMIT"
        mock_temp_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect():
    """disconnect() metodunun motoru güvenle kapattığını test eder."""
    test_db = Database()
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    test_db.engine = mock_engine
    test_db.session_factory = MagicMock()

    await test_db.disconnect()

    mock_engine.dispose.assert_awaited_once()
    assert test_db.engine is None
    assert test_db.session_factory is None


@pytest.mark.asyncio
async def test_get_session_lifecycle():
    """get_session() metodunun oturum oluşturma ve sonlandırma yaşam döngüsünü test eder."""
    test_db = Database()

    # Bağlantı kurulmamışken get_session hata fırlatmalı
    with pytest.raises(RuntimeError):
        async for _ in test_db.get_session():
            pass

    # Oturum fabrikası tanımlı iken
    mock_session = AsyncMock()
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_session_factory = MagicMock(return_value=mock_session_ctx)

    test_db.session_factory = mock_session_factory

    sessions = []
    async for session in test_db.get_session():
        sessions.append(session)

    assert len(sessions) == 1
    assert sessions[0] is mock_session
    mock_session.close.assert_awaited_once()


def test_global_db_instance():
    """app.database modülündeki global db nesnesinin varlığını ve tipini test eder."""
    assert isinstance(db, Database)
    assert db.engine is None


# ==============================================================================
# Model ve Şema Testleri (Prompt 3.4)
# ==============================================================================

def test_models_tables_registered():
    """Tüm model tablolarının Base.metadata içinde kayıtlı olduğunu doğrular."""
    table_names = Base.metadata.tables.keys()
    assert "movies" in table_names
    assert "vibe_tags" in table_names
    assert "movie_vibes" in table_names
    assert "user_queries" in table_names


def test_movie_vibes_junction_table():
    """movie_vibes ara tablosunun sütunlarını, composite PK ve cascade delete FK kısıtlarını doğrular."""
    assert movie_vibes.name == "movie_vibes"

    cols = {col.name: col for col in movie_vibes.columns}
    assert "movie_id" in cols
    assert "tag_id" in cols

    # Composite Primary Key denetimi
    assert cols["movie_id"].primary_key is True
    assert cols["tag_id"].primary_key is True

    # Foreign Key ve Cascade Delete denetimi
    movie_fk = list(cols["movie_id"].foreign_keys)[0]
    assert movie_fk.target_fullname == "movies.id"
    assert movie_fk.ondelete.upper() == "CASCADE"

    tag_fk = list(cols["tag_id"].foreign_keys)[0]
    assert tag_fk.target_fullname == "vibe_tags.id"
    assert tag_fk.ondelete.upper() == "CASCADE"


def test_movie_model_structure():
    """Movie modelinin sütunlarını, tiplerini ve lazy='selectin' MTM ilişkisini doğrular."""
    table = Movie.__table__
    cols = {col.name: col for col in table.columns}

    assert cols["id"].primary_key is True
    assert cols["title"].nullable is False
    assert cols["overview"].nullable is False
    assert cols["poster_path"].nullable is True
    assert cols["release_year"].nullable is False
    assert cols["imdb_id"].nullable is True
    assert cols["imdb_rating"].nullable is True
    assert cols["created_at"].nullable is False

    # Relationship denetimi
    rel = Movie.vibes.property
    assert rel.secondary is movie_vibes
    assert rel.lazy == "selectin"
    assert rel.back_populates == "movies"


def test_vibe_tag_model_structure():
    """VibeTag modelinin sütunlarını, unique kısıtını ve geri ilişkisini doğrular."""
    table = VibeTag.__table__
    cols = {col.name: col for col in table.columns}

    assert cols["id"].primary_key is True
    assert cols["id"].autoincrement is True or cols["id"].autoincrement == "auto"
    assert cols["tag_name"].unique is True
    assert cols["tag_name"].nullable is False

    # Relationship denetimi
    rel = VibeTag.movies.property
    assert rel.secondary is movie_vibes
    assert rel.lazy == "selectin"
    assert rel.back_populates == "vibes"


def test_user_query_model_structure():
    """UserQuery modelinin arama analitiği alanlarını ve ARRAY tipini doğrular."""
    table = UserQuery.__table__
    cols = {col.name: col for col in table.columns}

    assert cols["id"].primary_key is True
    assert cols["query_text"].nullable is False
    assert cols["created_at"].nullable is False
    assert "ARRAY" in str(cols["detected_moods"].type).upper()


@pytest.mark.asyncio
async def test_init_db_creates_extension_and_tables():
    """Database.init_db() metodunun uuid-ossp extension oluşturup create_all çalıştırdığını test eder."""
    test_db = Database()

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.run_sync = AsyncMock()

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_conn

    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_conn_ctx

    test_db.engine = mock_engine
    test_db.session_factory = MagicMock()

    with patch.object(test_db, "_seed_initial_data", new_callable=AsyncMock) as mock_seed:
        await test_db.init_db(seed_if_empty=True)

        # Extension komutu, create_all ve IMDb sütun güncellemeleri çağrıldı mı
        executed_queries = [str(call[0][0]) for call in mock_conn.execute.call_args_list]
        assert any('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' in q for q in executed_queries)
        assert any("imdb_id" in q for q in executed_queries)
        assert any("imdb_rating" in q for q in executed_queries)
        mock_conn.run_sync.assert_awaited_once_with(Base.metadata.create_all)
        mock_seed.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_initial_data_when_empty():
    """_seed_initial_data metodunun veritabanı boşken 5 film ve etiket eklediğini test eder."""
    test_db = Database()

    mock_scalar = MagicMock()
    mock_scalar.scalar.return_value = 0  # 0 film var

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_scalar
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_session_ctx.__aexit__.return_value = None

    mock_factory = MagicMock(return_value=mock_session_ctx)
    test_db.session_factory = mock_factory

    await test_db._seed_initial_data()

    # 5 adet Movie eklenmeli
    assert mock_session.add.call_count == 5
    added_movies = [call_args[0][0] for call_args in mock_session.add.call_args_list]
    movie_titles = [m.title for m in added_movies]

    assert "Inception" in movie_titles
    assert "Interstellar" in movie_titles
    assert "The Grand Budapest Hotel" in movie_titles
    assert "Blade Runner 2049" in movie_titles
    assert "Amélie" in movie_titles

    # Her film en az bir vibe etiketine sahip olmalı
    for movie in added_movies:
        assert len(movie.vibes) > 0

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_initial_data_skips_when_not_empty():
    """_seed_initial_data metodunun veritabanında zaten film varken seed yapmadığını test eder."""
    test_db = Database()

    mock_scalar = MagicMock()
    mock_scalar.scalar.return_value = 10  # Zaten 10 film var

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_scalar
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_session_ctx.__aexit__.return_value = None

    mock_factory = MagicMock(return_value=mock_session_ctx)
    test_db.session_factory = mock_factory

    await test_db._seed_initial_data()

    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()

