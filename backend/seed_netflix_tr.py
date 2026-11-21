"""
Netflix Türkiye Kataloğu İçe Aktarma Scripti (TMDB Watch Providers + IMDb Resmi Puanlar).

TMDB'nin resmi Watch Providers API'si (with_watch_providers=8, watch_region=TR)
üzerinden Netflix Türkiye'de yayında olan popüler ve yüksek puanlı filmleri çeker:
- Veritabanında zaten bulunan filmlere 'Netflix' vibe etiketini ekler (mükerrer kayıt oluşturmaz).
- Yeni filmleri Türkçe özet, HD TMDB afişi, gerçek IMDb puanı ve 'Netflix' etiketiyle kaydeder.

Kullanım:
    python seed_netflix_tr.py
"""

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Movie, VibeTag, db
from seed_tmdb_and_imdb import (
    _build_tmdb_auth,
    _download_imdb_ratings,
    _tmdb_get,
    enrich_with_imdb_ids,
)

NETFLIX_PROVIDER_ID = "8"
WATCH_REGION = "TR"


async def collect_netflix_tr_movies(
    client: httpx.AsyncClient,
    base_params: Dict[str, str],
    pages: int = 10,
) -> Dict[int, Dict[str, Any]]:
    """TMDB Watch Providers API ile Netflix Türkiye'deki popüler/yüksek puanlı filmleri toplar."""
    print(f"[*] TMDB üzerinden Netflix Türkiye kataloğu taranıyor ({pages} sayfa)...")
    semaphore = asyncio.Semaphore(10)
    movies_by_id: Dict[int, Dict[str, Any]] = {}

    async def _fetch(page: int, sort_by: str):
        async with semaphore:
            data = await _tmdb_get(
                client,
                "/discover/movie",
                base_params,
                {
                    "language": "tr-TR",
                    "watch_region": WATCH_REGION,
                    "with_watch_providers": NETFLIX_PROVIDER_ID,
                    "sort_by": sort_by,
                    "vote_count.gte": "50",
                    "page": page,
                },
            )
            return data.get("results") or [] if data else []

    tasks = []
    # Popüler Netflix filmleri + yüksek puanlı Netflix filmleri
    for p in range(1, pages + 1):
        tasks.append(_fetch(p, "popularity.desc"))
    for p in range(1, 5):
        tasks.append(_fetch(p, "vote_average.desc"))

    results = await asyncio.gather(*tasks)
    for items in results:
        for item in items:
            tid = item.get("id")
            title = (item.get("title") or item.get("original_title") or "").strip()
            rdate = str(item.get("release_date") or "")
            if not tid or not title or len(rdate) < 4 or not rdate[:4].isdigit():
                continue
            if tid not in movies_by_id:
                item["_source"] = "netflix_tr"
                movies_by_id[tid] = item

    print(f"    -> Netflix Türkiye'de {len(movies_by_id)} benzersiz film bulundu.")
    return movies_by_id


async def run_netflix_import() -> None:
    headers, base_params = _build_tmdb_auth()
    await db.init_db()

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        imdb_ratings, movies_by_id = await asyncio.gather(
            _download_imdb_ratings(client),
            collect_netflix_tr_movies(client, base_params, pages=10),
        )
        if not movies_by_id:
            print("[!] Netflix Türkiye kataloğu alınamadı.")
            await db.disconnect()
            return

        enriched = await enrich_with_imdb_ids(client, base_params, movies_by_id, imdb_ratings)

    added_new = 0
    tagged_existing = 0

    async for session in db.get_session():
        existing_res = await session.execute(select(Movie).options(selectinload(Movie.vibes)))
        existing_movies = list(existing_res.scalars().all())
        by_title = {m.title.strip().lower(): m for m in existing_movies}
        by_imdb = {m.imdb_id.strip().lower(): m for m in existing_movies if m.imdb_id}

        tags_res = await session.execute(select(VibeTag))
        tag_cache: Dict[str, VibeTag] = {
            t.tag_name.strip().lower(): t for t in tags_res.scalars().all()
        }

        if "netflix" not in tag_cache:
            tag_cache["netflix"] = VibeTag(tag_name="Netflix")
        netflix_tag = tag_cache["netflix"]

        for item in enriched:
            tkey = item["title"].strip().lower()
            ikey = item["imdb_id"].strip().lower() if item["imdb_id"] else None

            existing = by_title.get(tkey) or (by_imdb.get(ikey) if ikey else None)
            if existing is not None:
                # Zaten DB'de varsa 'Netflix' etiketini iliştir
                existing_tag_keys = {v.tag_name.strip().lower() for v in existing.vibes}
                if "netflix" not in existing_tag_keys:
                    existing.vibes.append(netflix_tag)
                    tagged_existing += 1
                continue

            vibe_objs: List[VibeTag] = [netflix_tag]
            seen_tags = {"netflix"}
            for raw_tag in item["vibes"]:
                key = raw_tag.strip().lower()
                if not key or key in seen_tags:
                    continue
                seen_tags.add(key)
                if key not in tag_cache:
                    tag_cache[key] = VibeTag(tag_name=raw_tag.strip())
                vibe_objs.append(tag_cache[key])

            new_movie = Movie(
                id=uuid.uuid4(),
                title=item["title"],
                overview=item["overview"],
                poster_path=item["poster_path"],
                release_year=item["release_year"],
                imdb_id=item["imdb_id"],
                imdb_rating=item["imdb_rating"],
                vibes=vibe_objs,
            )
            session.add(new_movie)
            by_title[tkey] = new_movie
            if ikey:
                by_imdb[ikey] = new_movie
            added_new += 1

        if added_new > 0 or tagged_existing > 0:
            await session.commit()

        total_movies = (await session.execute(select(func.count(Movie.id)))).scalar() or 0
        netflix_count = (
            await session.execute(
                select(func.count(Movie.id))
                .join(Movie.vibes)
                .where(func.lower(VibeTag.tag_name) == "netflix")
            )
        ).scalar() or 0

        print("\n========================================================")
        print("[+] NETFLIX TÜRKİYE KATALOĞU BAŞARIYLA EKLENDİ!")
        print(f"    - Yeni eklenen Netflix filmi   : {added_new}")
        print(f"    - Mevcut filme #Netflix etiketi: {tagged_existing}")
        print(f"    - Toplam #Netflix filmi        : {netflix_count}")
        print(f"    - Veritabanı toplam film sayısı: {total_movies}")
        print("========================================================")
        break

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(run_netflix_import())
