import asyncio
from datetime import datetime, timezone
import logging
import re
from typing import AsyncGenerator, Optional
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings

logger = logging.getLogger(__name__)


# 1. SQLAlchemy ORM Modellerinin Türeyeceği Deklaratif Taban Sınıfı
class Base(DeclarativeBase):
    """Tüm veritabanı ORM modellerinin türeyeceği taban sınıf."""
    pass


# 2. Çoktan Çoğa İlişki Ara Tablosu (Junction Table: movie_vibes)
movie_vibes = Table(
    "movie_vibes",
    Base.metadata,
    Column(
        "movie_id",
        UUID(as_uuid=True),
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        Integer,
        ForeignKey("vibe_tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# 3. ORM Tablo Modelleri
class Movie(Base):
    """Film verilerini temsil eden ORM modeli."""

    __tablename__ = "movies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    overview: Mapped[str] = mapped_column(Text, nullable=False)
    poster_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    release_year: Mapped[int] = mapped_column(Integer, nullable=False)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    imdb_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Çoktan-çoğa ilişki: Movies <-> VibeTags
    vibes: Mapped[list["VibeTag"]] = relationship(
        "VibeTag",
        secondary=movie_vibes,
        back_populates="movies",
        lazy="selectin",
    )


class VibeTag(Base):
    """Filmlerin duygu, tema ve atmosfer etiketlerini temsil eden ORM modeli."""

    __tablename__ = "vibe_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    # Geriye dönük ilişki: VibeTags <-> Movies
    movies: Mapped[list["Movie"]] = relationship(
        "Movie",
        secondary=movie_vibes,
        back_populates="vibes",
        lazy="selectin",
    )


class UserQuery(Base):
    """Kullanıcı arama analitiği ve ruh hali takibi için ORM modeli."""

    __tablename__ = "user_queries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_moods: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String),
        nullable=True,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


def normalize_to_asyncpg_url(url: str) -> str:
    """
    Tüm olası PostgreSQL bağlantı dizesi prefixlerini (postgres://, postgresql://,
    postgresql+psycopg2://, postgresql+psycopg://, postgresql+pg8000:// vb.)
    asenkron 'postgresql+asyncpg://' protokolüne dönüştürür.
    """
    return re.sub(r"^(postgres|postgresql)(\+[a-zA-Z0-9_-]+)?://", "postgresql+asyncpg://", url, count=1)


# 2. Database Sınıfı: Bağlantı yönetimi, havuz ayarları ve retry mekanizması
class Database:
    """SQLAlchemy asenkron motorunu, havuzunu ve oturum yöneticisini sarmallayan sınıf."""

    def __init__(self) -> None:
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    def get_db_url(self) -> str:
        """
        Ortam ayarlarından DATABASE_URL değerini alır ve asenkron asyncpg
        protokolü ile uyumlu hale getirir.
        """
        raw_url = settings.DATABASE_URL
        return normalize_to_asyncpg_url(raw_url)

    def _is_database_not_found_error(self, exc: Exception) -> bool:
        """Verilen hatanın veritabanının mevcut olmamasından kaynaklanıp kaynaklanmadığını denetler."""
        err_str = str(exc).lower()
        if "invalidcatalognameerror" in err_str or "does not exist" in err_str:
            return True

        orig = getattr(exc, "orig", None)
        if orig and ("invalidcatalogname" in type(orig).__name__.lower() or "does not exist" in str(orig).lower()):
            return True

        return False

    async def _create_database(self, url: str) -> None:
        """
        Hedef veritabanı mevcut değilse, geçici olarak 'postgres' varsayılan
        veritabanına AUTOCOMMIT modunda bağlanarak hedef veritabanını oluşturur.
        """
        parsed_url = make_url(url)
        target_db = parsed_url.database

        if not target_db:
            return

        # SQL Injection önlemek adına veritabanı adının geçerli bir identifier olduğunu doğrula
        if not re.match(r"^[a-zA-Z0-9_]+$", target_db):
            raise ValueError(f"Geçersiz veritabanı adı formatı: {target_db}")

        postgres_url = parsed_url.set(database="postgres")
        temp_engine = create_async_engine(
            postgres_url,
            isolation_level="AUTOCOMMIT",
        )

        try:
            async with temp_engine.connect() as conn:
                check_query = text("SELECT 1 FROM pg_database WHERE datname = :dbname")
                result = await conn.execute(check_query, {"dbname": target_db})
                exists = result.scalar() is not None

                if not exists:
                    logger.info("'%s' veritabanı bulunamadı. Otomatik olarak oluşturuluyor...", target_db)
                    await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                    logger.info("'%s' veritabanı başarıyla oluşturuldu.", target_db)
        finally:
            await temp_engine.dispose()

    async def connect(self, max_retries: int = 5, retry_interval: float = 2.0) -> None:
        """
        PostgreSQL veritabanına asenkron bağlantı kurar.
        Bağlantı havuzu parametrelerini ayarlar, hedef veritabanı yoksa oluşturur
        ve servislerin hazır olmaması durumunda retry döngüsü işletir.
        """
        db_url = self.get_db_url()

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("Veritabanına bağlanılıyor (Deneme %d/%d)...", attempt, max_retries)

                engine = create_async_engine(
                    db_url,
                    pool_size=5,
                    max_overflow=15,
                    pool_timeout=60,
                    pool_pre_ping=True,
                )
                session_factory = async_sessionmaker(
                    bind=engine,
                    expire_on_commit=False,
                    class_=AsyncSession,
                )

                # Bağlantıyı ve veritabanının varlığını doğrula
                try:
                    async with engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                except Exception as test_err:
                    if self._is_database_not_found_error(test_err):
                        logger.warning("Hedef veritabanı mevcut değil. Otomatik oluşturma başlatılıyor...")
                        await engine.dispose()
                        await self._create_database(db_url)

                        # Veritabanı oluşturulduktan sonra motoru yeniden başlat ve doğrula
                        engine = create_async_engine(
                            db_url,
                            pool_size=5,
                            max_overflow=15,
                            pool_timeout=60,
                            pool_pre_ping=True,
                        )
                        session_factory = async_sessionmaker(
                            bind=engine,
                            expire_on_commit=False,
                            class_=AsyncSession,
                        )
                        async with engine.connect() as conn:
                            await conn.execute(text("SELECT 1"))
                    else:
                        await engine.dispose()
                        raise test_err

                self.engine = engine
                self.session_factory = session_factory
                logger.info("Veritabanı bağlantısı ve havuzu başarıyla kuruldu.")
                return

            except Exception as e:
                logger.warning("Veritabanı bağlantı denemesi %d başarısız oldu: %s", attempt, e)
                if attempt < max_retries:
                    logger.info("%s saniye sonra yeniden denenecek...", retry_interval)
                    await asyncio.sleep(retry_interval)
                else:
                    logger.error("Veritabanına %d denemeden sonra bağlanılamadı.", max_retries)
                    raise ConnectionError(
                        f"Veritabanına {max_retries} deneme sonrasında bağlanılamadı: {e}"
                    ) from e

    async def disconnect(self) -> None:
        """Veritabanı motorunu ve havuzunu güvenli şekilde kapatır (dispose)."""
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None
            logger.info("Veritabanı bağlantısı güvenli şekilde kapatıldı.")

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        FastAPI dependency enjeksiyonu ve servis katmanı için asenkron oturum üreteci.
        Kullanım sonrasında oturumu otomatik kapatır ve hata anında rollback işletir.
        """
        if self.session_factory is None:
            raise RuntimeError(
                "Veritabanı bağlantısı henüz başlatılmadı. Önce connect() çağrılmalıdır."
            )
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def init_db(self, seed_if_empty: bool = True) -> None:
        """
        Veritabanını asenkron olarak ilklendirir.
        Önce connect() metodunu dener, PostgreSQL'in UUID oluşturması için
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' komutunu çalıştırır,
        tabloların asenkron olarak oluşturulmasını sağlar ve boşsa 5 adet seed veriyi yükler.
        """
        if self.engine is None or self.session_factory is None:
            await self.connect()

        # 1. UUID eklentisi ve Tablo Oluşturma
        async with self.engine.begin() as conn:
            try:
                await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
            except Exception as ext_err:
                logger.warning("uuid-ossp eklentisi oluşturulamadı veya atlandı: %s", ext_err)

            await conn.run_sync(Base.metadata.create_all)
            # Mevcut veritabanları için IMDb alanlarının varlığını garanti altına al
            await conn.execute(
                text("ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_id VARCHAR(20);")
            )
            await conn.execute(
                text("ALTER TABLE movies ADD COLUMN IF NOT EXISTS imdb_rating DOUBLE PRECISION;")
            )
            logger.info("Tüm veritabanı tabloları başarıyla oluşturuldu / doğrulandı.")

        # 2. Seed Veri Yükleme
        if seed_if_empty:
            await self._seed_initial_data()

    async def _seed_initial_data(self) -> None:
        """Veritabanında henüz film yoksa 5 adet kaliteli seed film ve vibe etiketlerini yükler."""
        if self.session_factory is None:
            raise RuntimeError("Veritabanı oturum fabrikası (session_factory) başlatılmadı.")

        async with self.session_factory() as session:
            # Tabloda veri var mı kontrol et
            count_stmt = select(func.count(Movie.id))
            result = await session.execute(count_stmt)
            movie_count = result.scalar() or 0

            if movie_count > 0:
                logger.info("Veritabanında halihazırda %d film mevcut. Seed verisi yüklenmeyecek.", movie_count)
                return

            logger.info("Veritabanı ilk kez açıldı. 5 adet zengin seed filmi ve vibe etiketleri yükleniyor...")

            seed_movies = [
                {
                    "title": "Inception",
                    "overview": "Rüya içinde rüya temalı, insan zihninin derinliklerine inen zihin bükücü ve sürükleyici bir bilim kurgu başyapıtı.",
                    "poster_path": "https://image.tmdb.org/t/p/w500/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
                    "release_year": 2010,
                    "imdb_id": "tt1375666",
                    "imdb_rating": 8.8,
                    "vibes": ["Zihin Bükücü", "Gerilim", "Felsefi"],
                },
                {
                    "title": "Interstellar",
                    "overview": "İnsanlığın hayatta kalabilmesi adına bir solucan deliğinden geçerek yeni bir yuva arayan astronot ekibinin epik ve duygusal yolculuğu.",
                    "poster_path": "https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
                    "release_year": 2014,
                    "imdb_id": "tt0816692",
                    "imdb_rating": 8.7,
                    "vibes": ["Duygusal", "Büyüleyici", "Epik Bilim Kurgu"],
                },
                {
                    "title": "The Grand Budapest Hotel",
                    "overview": "Büyük Buhran ile İkinci Dünya Savaşı arasındaki dönemde ünlü bir Avrupa otelinin efsanevi konsiyerjinin trajikomik ve nostaljik serüveni.",
                    "poster_path": "https://image.tmdb.org/t/p/w500/eWdyYQreja6JGCzqHWX9NZkt5BW.jpg",
                    "release_year": 2014,
                    "imdb_id": "tt2278388",
                    "imdb_rating": 8.1,
                    "vibes": ["Pastel Renkler", "Mizahi", "Nostaljik"],
                },
                {
                    "title": "Blade Runner 2049",
                    "overview": "Toplumun derinliklerine gömülmüş bir sırrı keşfeden yeni bir Blade Runner memurunun distopik ve karanlık gelecekteki arayışı.",
                    "poster_path": "https://image.tmdb.org/t/p/w500/gajva2L0rPYkEWjzgFlBXCAVBE5.jpg",
                    "release_year": 2017,
                    "imdb_id": "tt1856101",
                    "imdb_rating": 8.0,
                    "vibes": ["Karanlık", "Görsel Şölen", "Distopik"],
                },
                {
                    "title": "Amélie",
                    "overview": "Paris'in büyülü sokaklarında kendi yalnız dünyasında yaşarken etrafındaki insanların mutluluğu için gizli iyilikler yapan genç kadının iç ısıtan öyküsü.",
                    "poster_path": "https://image.tmdb.org/t/p/w500/iZyflA0j6aHnF6T8aPcmhB2sYqm.jpg",
                    "release_year": 2001,
                    "imdb_id": "tt0211915",
                    "imdb_rating": 8.3,
                    "vibes": ["İç Isıtan", "Romantik", "Fransız Sineması"],
                },
            ]

            # VibeTag'leri tekilleştirerek oluştur
            tag_cache: dict[str, VibeTag] = {}
            for item in seed_movies:
                for tag_name in item["vibes"]:
                    if tag_name not in tag_cache:
                        tag_cache[tag_name] = VibeTag(tag_name=tag_name)

            # Filmleri oluştur ve etiketlerle bağla
            for item in seed_movies:
                movie = Movie(
                    title=item["title"],
                    overview=item["overview"],
                    poster_path=item["poster_path"],
                    release_year=item["release_year"],
                    imdb_id=item["imdb_id"],
                    imdb_rating=item["imdb_rating"],
                    vibes=[tag_cache[vibe_name] for vibe_name in item["vibes"]],
                )
                session.add(movie)

            await session.commit()
            logger.info("5 adet seed film ve ilişkili vibe etiketleri başarıyla kaydedildi.")


# Global Database nesnesi
db = Database()

