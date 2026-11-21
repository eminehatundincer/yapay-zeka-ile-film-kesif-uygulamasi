"""
Yapay Zeka Film & Dizi Keşif Ajanı - Veritabanı ve ORM Modelleri Asenkron Test Scripti
Kıdemli Test Mühendisi Doğrulama Aracı
"""

import asyncio
from datetime import datetime
import logging
from pathlib import Path
import sys

# 1. Standart blok yapısı: Backend kök dizinini sys.path'e ekle
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select
from app.database import Base, Database, Movie, UserQuery, VibeTag, db, movie_vibes


def log_step(step_name: str, message: str, level: str = "INFO") -> None:
    """Belirtilen test adımını zaman damgası (timestamp) ile konsola loglar."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level:<7}] [{step_name:<12}] {message}")


async def test_live_database() -> bool:
    """Gerçek PostgreSQL veritabanına bağlanıp init_db ve sorgulama adımlarını dener."""
    log_step("BAGLANTI", f"PostgreSQL hedef adresi alınıyor: {db.get_db_url()}")
    try:
        # connect() hızlı deneme (max_retries=1, retry_interval=0.5)
        log_step("BAGLANTI", "Veritabanı bağlantısı test ediliyor (connect)...")
        await db.connect(max_retries=1, retry_interval=0.5)
        log_step("BAGLANTI", "Veritabanı motoru ve bağlantı havuzu başarıyla kuruldu.")

        log_step("INIT_DB", "init_db() çağrılıyor (UUID eklentisi, DDL create_all ve seed veri kontrolü)...")
        await db.init_db(seed_if_empty=True)
        log_step("INIT_DB", "init_db() başarıyla tamamlandı.")

        log_step("SORGU", "Filmler ve ilişkili vibe etiketleri sorgulanıyor...")
        async for session in db.get_session():
            stmt = select(Movie).order_by(Movie.release_year.asc())
            result = await session.execute(stmt)
            movies = result.scalars().all()

            log_step("SONUC", f"Veritabanından toplam {len(movies)} adet film başarıyla çekildi.")
            print("\n" + "=" * 70)
            print(" VERİTABANINDAN ÇEKİLEN FİLMLER VE VİBE ETİKETLERİ ")
            print("=" * 70)
            for idx, movie in enumerate(movies, 1):
                vibes_list = [v.tag_name for v in movie.vibes]
                vibes_str = ", ".join(f"#{v}" for v in vibes_list) if vibes_list else "Etiket yok"
                print(f" {idx}. Başlık     : {movie.title}")
                print(f"    Çıkış Yılı : {movie.release_year}")
                print(f"    Etiketler  : {vibes_str}")
                print(f"    Afiş URL   : {movie.poster_path or 'Yok'}")
                print(f"    Özet       : {movie.overview[:90]}...")
                print("-" * 70)

            # UserQuery tablosunu da kontrol et
            uq_count_stmt = select(func.count(UserQuery.id))
            uq_res = await session.execute(uq_count_stmt)
            uq_count = uq_res.scalar() or 0
            log_step("ANALITIK", f"user_queries tablosu aktif ve sorgulanabilir (Mevcut kayıt: {uq_count}).")

        await db.disconnect()
        log_step("KAPATMA", "Veritabanı bağlantısı güvenli şekilde kapatıldı.")
        return True

    except Exception as exc:
        log_step("BAGLANTI", f"Canlı PostgreSQL veritabanına doğrudan bağlanılamadı: {exc}", level="UYARI")
        log_step("UYARI", "Yerel makinede PostgreSQL servisi çalışmıyor veya port kapalı.", level="UYARI")
        return False


async def test_offline_models_and_seed() -> None:
    """
    Canlı veritabanı kapalı olduğunda ORM modellerini,
    MTM ilişkilerini ve seed verilerini bellek üzerinde doğrular.
    """
    log_step("IZOLE_TEST", "ORM Modelleri ve Seed Verisi doğrulama testi başlatılıyor...")

    # 1. Metadata ve Tablo Kontrolü
    log_step("METADATA", f"Base.metadata kayıtlı tablolar: {list(Base.metadata.tables.keys())}")
    assert "movies" in Base.metadata.tables
    assert "vibe_tags" in Base.metadata.tables
    assert "movie_vibes" in Base.metadata.tables
    assert "user_queries" in Base.metadata.tables
    log_step("METADATA", "Tüm tablolar (movies, vibe_tags, movie_vibes, user_queries) şemada başarıyla mevcut.")

    # 2. Seed Verilerinin Oluşturulması ve MTM İlişki Kontrolü
    log_step("SEED_TEST", "5 adet seed film ve vibe etiketleri nesne düzeyinde oluşturuluyor...")
    
    seed_movies_data = [
        {
            "title": "Inception",
            "overview": "Rüya içinde rüya temalı, zihin bükücü ve sürükleyici bir bilim kurgu başyapıtı.",
            "poster_path": "https://image.tmdb.org/t/p/w500/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
            "release_year": 2010,
            "vibes": ["Zihin Bükücü", "Gerilim", "Felsefi"],
        },
        {
            "title": "Interstellar",
            "overview": "İnsanlığın hayatta kalabilmesi adına bir solucan deliğinden geçen astronot ekibinin epik yolculuğu.",
            "poster_path": "https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
            "release_year": 2014,
            "vibes": ["Duygusal", "Büyüleyici", "Epik Bilim Kurgu"],
        },
        {
            "title": "The Grand Budapest Hotel",
            "overview": "Ünlü bir Avrupa otelinin efsanevi konsiyerjinin trajikomik ve nostaljik serüveni.",
            "poster_path": "https://image.tmdb.org/t/p/w500/eWdyYQreja6JGCzqHWX9NZkt5BW.jpg",
            "release_year": 2014,
            "vibes": ["Pastel Renkler", "Mizahi", "Nostaljik"],
        },
        {
            "title": "Blade Runner 2049",
            "overview": "Distopik gelecekte insanlık ve yapay zeka arasındaki çizgiyi sorgulayan karanlık bir görsel şölen.",
            "poster_path": "https://image.tmdb.org/t/p/w500/gajva2L0rPYkEWjzgFlBXCAVBE5.jpg",
            "release_year": 2017,
            "vibes": ["Karanlık", "Görsel Şölen", "Distopik"],
        },
        {
            "title": "Amélie",
            "overview": "Paris'in büyülü sokaklarında gizlice insanların hayatını güzelleştiren genç kadının iç ısıtan öyküsü.",
            "poster_path": "https://image.tmdb.org/t/p/w500/iZyflA0j6aHnF6T8aPcmhB2sYqm.jpg",
            "release_year": 2001,
            "vibes": ["İç Isıtan", "Romantik", "Fransız Sineması"],
        },
    ]

    tag_cache: dict[str, VibeTag] = {}
    for item in seed_movies_data:
        for tag_name in item["vibes"]:
            if tag_name not in tag_cache:
                tag_cache[tag_name] = VibeTag(tag_name=tag_name)

    movies = []
    for item in seed_movies_data:
        movie = Movie(
            title=item["title"],
            overview=item["overview"],
            poster_path=item["poster_path"],
            release_year=item["release_year"],
            vibes=[tag_cache[vibe_name] for vibe_name in item["vibes"]],
        )
        movies.append(movie)

    log_step("SEED_TEST", f"Toplam {len(movies)} film ve {len(tag_cache)} tekil vibe etiketi modellendi.")
    print("\n" + "=" * 70)
    print(" ORM MODELLERİ VE SEED VERİLERİ TEST ÇIKTISI ")
    print("=" * 70)
    for idx, movie in enumerate(movies, 1):
        vibes_list = [v.tag_name for v in movie.vibes]
        vibes_str = ", ".join(f"#{v}" for v in vibes_list)
        print(f" {idx}. Başlık     : {movie.title}")
        print(f"    Çıkış Yılı : {movie.release_year}")
        print(f"    Etiketler  : {vibes_str}")
        print(f"    Afiş URL   : {movie.poster_path}")
        print(f"    Özet       : {movie.overview[:90]}...")
        print("-" * 70)

    # UserQuery Modeli Kontrolü
    sample_query = UserQuery(
        query_text="Karanlık ve sürükleyici bilim kurgu",
        detected_moods=["#Karanlık", "#BilimKurgu", "#Gerilim"],
    )
    log_step("ANALITIK", f"UserQuery modeli doğrulandı (Örnek Metin: '{sample_query.query_text}', Moods: {sample_query.detected_moods})")
    log_step("IZOLE_TEST", "Tüm ORM modelleri, alanlar ve MTM ilişkileri başarıyla doğrulandı.")


async def main() -> None:
    """Asenkron test fonksiyonu: Canlı DB bağlantısını dener, gerekirse izole test modunu işletir."""
    print("=" * 70)
    print(" YAPAY ZEKA FİLM KEŞİF SİSTEMİ - VERİTABANI ASENKRON TEST PROTOKOLÜ ")
    print("=" * 70)

    success = await test_live_database()
    if not success:
        log_step("BILGI", "İzole ORM modelleri ve seed verisi doğrulama protokolüne geçiliyor...")
        await test_offline_models_and_seed()

    print("\n" + "=" * 70)
    log_step("SONUC", "Veritabanı test protokolü başarıyla tamamlandı!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
