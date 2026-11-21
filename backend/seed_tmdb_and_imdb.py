"""
TMDB API + IMDb Resmi Açık Veri Seti Toplu Film İçe Aktarma Scripti.

Tek çalıştırmada 3 büyük koleksiyonu PostgreSQL veritabanına (mükerrer kayıt kontrolü ile) yükler:
1. IMDb Top 250 & Yüksek Puanlı Klasikler (TMDB top_rated + IMDb resmi puan eşleşmesi)
2. TMDB Popüler & Tür Dengeli 500+ Film (Türkçe özet + HD afiş + otomatik vibe etiketleri)
3. Türk Sineması Koleksiyonu (Yeşilçam klasikleri ve çağdaş Türk filmleri)

Kullanım:
    backend\.venv\Scripts\python.exe backend/seed_tmdb_and_imdb.py
"""

import asyncio
import gzip
import io
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import DEFAULT_POSTER_URL
from app.config import settings
from app.database import Movie, VibeTag, db

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"

# TMDB Tür ID -> Zengin Türkçe Vibe Etiketleri Eşlemesi
GENRE_ID_TO_VIBES: Dict[int, List[str]] = {
    28: ["Aksiyon", "Adrenalin", "Sürükleyici"],
    12: ["Macera", "Epik"],
    16: ["Animasyon", "Büyüleyici"],
    35: ["Komedi", "Kafa Dağıtmalık", "Eğlenceli"],
    80: ["Suç", "Polisiye", "Karanlık"],
    99: ["Belgesel", "Öğretici", "Gerçek Hikaye"],
    18: ["Dram", "Duygusal"],
    10751: ["Aile", "İç Isıtan"],
    14: ["Fantastik", "Büyüleyici"],
    36: ["Tarih", "Dönem", "Öğretici"],
    27: ["Korku", "Gerilim", "Karanlık"],
    10402: ["Müzik", "Duygusal"],
    9648: ["Gizem", "Zihin Bükücü", "Gerilim"],
    10749: ["Romantik", "Duygusal", "İç Isıtan"],
    878: ["Bilim Kurgu", "Zihin Bükücü", "Felsefi"],
    53: ["Gerilim", "Sürükleyici", "Psikolojik"],
    10752: ["Savaş", "Tarih", "Epik"],
    37: ["Western", "Klasik", "Macera"],
}

GENRE_ID_TO_TR_NAME: Dict[int, str] = {
    28: "Aksiyon",
    12: "Macera",
    16: "Animasyon",
    35: "Komedi",
    80: "Suç",
    99: "Belgesel",
    18: "Dram",
    10751: "Aile",
    14: "Fantastik",
    36: "Tarih",
    27: "Korku",
    10402: "Müzik",
    9648: "Gizem",
    10749: "Romantik",
    878: "Bilim Kurgu",
    53: "Gerilim",
    10752: "Savaş",
    37: "Western",
}


def _build_tmdb_auth() -> Tuple[Dict[str, str], Dict[str, str]]:
    """TMDB_API_KEY değerinin v3 API Key mi yoksa Bearer Read Access Token mı olduğunu otomatik algılar."""
    token = (settings.TMDB_API_KEY or os.environ.get("TMDB_API_KEY") or "").strip()
    if not token:
        raise ValueError("TMDB_API_KEY bulunamadı! Lütfen backend/.env dosyasına ekleyin.")

    if token.startswith("eyJ") or len(token) > 60:
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}, {}
    return {"Accept": "application/json"}, {"api_key": token}


async def _download_imdb_ratings(client: httpx.AsyncClient) -> Dict[str, Tuple[float, int]]:
    """IMDb resmi açık veri setinden (title.ratings.tsv.gz) gerçek IMDb puanlarını ve oy sayılarını indirir."""
    print("[1/4] IMDb resmi puan veri seti (title.ratings.tsv.gz) indiriliyor...")
    try:
        resp = await client.get(IMDB_RATINGS_URL, timeout=45.0)
        resp.raise_for_status()
        ratings: Dict[str, Tuple[float, int]] = {}
        with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as gz:
            next(gz, None)  # Header satırını atla
            for raw_line in gz:
                parts = raw_line.decode("utf-8", errors="ignore").strip().split("\t")
                if len(parts) == 3:
                    tconst, avg_str, votes_str = parts
                    try:
                        ratings[tconst] = (float(avg_str), int(votes_str))
                    except ValueError:
                        continue
        print(f"      -> {len(ratings):,} adet resmi IMDb puanı belleğe yüklendi.")
        return ratings
    except Exception as exc:
        print(f"      [!] IMDb resmi veri seti indirilemedi ({exc}); TMDB puanları yedek kullanılacak.")
        return {}


async def _tmdb_get(
    client: httpx.AsyncClient,
    path: str,
    base_params: Dict[str, str],
    extra_params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    params = dict(base_params)
    if extra_params:
        params.update(extra_params)

    for attempt in range(3):
        try:
            resp = await client.get(f"{TMDB_BASE_URL}{path}", params=params, timeout=15.0)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.8)
    return None


def _derive_vibes(movie_data: Dict[str, Any], source_tag: str, imdb_rating: Optional[float]) -> List[str]:
    """TMDB türleri, dil, yıl, puan ve koleksiyon kaynağından zengin Türkçe vibe etiketleri üretir."""
    vibes: List[str] = []
    seen: set[str] = set()

    def _add(tag: str) -> None:
        key = tag.strip().lower()
        if key and key not in seen:
            seen.add(key)
            vibes.append(tag.strip())

    genre_ids = movie_data.get("genre_ids") or []
    for gid in genre_ids:
        for v in GENRE_ID_TO_VIBES.get(gid, []):
            _add(v)

    orig_lang = (movie_data.get("original_language") or "").lower()
    release_date = str(movie_data.get("release_date") or "")
    year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else 0

    if orig_lang == "tr":
        _add("Türk Sineması")
        if 1950 <= year <= 1990:
            _add("Yeşilçam")
            _add("Nostaljik")
    elif orig_lang == "ja" and 16 in genre_ids:
        _add("Anime")
    elif orig_lang == "fr":
        _add("Fransız Sineması")
    elif orig_lang == "ko":
        _add("Kore Sineması")

    if source_tag == "top_rated":
        _add("IMDb Top 250")
    if imdb_rating is not None and imdb_rating >= 8.2:
        _add("Başyapıt")
    if 1920 <= year <= 1995:
        _add("Klasik")
        _add("Nostaljik")

    if not vibes:
        _add("Popüler")

    return vibes[:7]


async def collect_tmdb_movies(
    client: httpx.AsyncClient,
    base_params: Dict[str, str],
) -> Dict[int, Dict[str, Any]]:
    """3 farklı koleksiyondan ~750+ benzersiz film toplar (Top 250 + TMDB 500 + Türk Sineması)."""
    print("[2/4] TMDB'den koleksiyonlar toplanıyor (IMDb Top 250 + TMDB 500 + Türk Sineması)...")
    semaphore = asyncio.Semaphore(12)
    movies_by_id: Dict[int, Dict[str, Any]] = {}

    tasks_spec: List[Tuple[str, Dict[str, Any], str]] = []

    # 1. IMDb Top 250 & Klasikler (13 sayfa * 20 = ~260 film)
    for page in range(1, 14):
        tasks_spec.append(("/movie/top_rated", {"language": "tr-TR", "page": page}, "top_rated"))

    # 2. TMDB Popüler & Keşif (~500 hedefi: 16 sayfa popüler + tür bazlı kaliteli filmler)
    for page in range(1, 17):
        tasks_spec.append(("/movie/popular", {"language": "tr-TR", "page": page}, "popular"))

    # Tür çeşitliliğini garanti altına al (Belgesel, Bilim Kurgu, Komedi, Korku, Animasyon, Romantik)
    for gid in [99, 878, 35, 27, 16, 10749, 9648]:
        for page in range(1, 3):
            tasks_spec.append(
                (
                    "/discover/movie",
                    {
                        "language": "tr-TR",
                        "with_genres": str(gid),
                        "sort_by": "vote_count.desc",
                        "vote_average.gte": "6.8",
                        "page": page,
                    },
                    "discover",
                )
            )

    # 3. Türk Sineması (Yeşilçam + Çağdaş Türk Filmleri: 6 sayfa = ~120 film)
    for page in range(1, 7):
        tasks_spec.append(
            (
                "/discover/movie",
                {
                    "language": "tr-TR",
                    "with_original_language": "tr",
                    "sort_by": "vote_count.desc",
                    "vote_count.gte": "25",
                    "page": page,
                },
                "turkish",
            )
        )

    async def _fetch_page(path: str, params: Dict[str, Any], source_tag: str):
        async with semaphore:
            data = await _tmdb_get(client, path, base_params, params)
            return source_tag, (data.get("results") or [] if data else [])

    page_results = await asyncio.gather(
        *(_fetch_page(path, params, tag) for path, params, tag in tasks_spec)
    )

    counts = {"top_rated": 0, "popular": 0, "discover": 0, "turkish": 0}
    for source_tag, items in page_results:
        for item in items:
            tmdb_id = item.get("id")
            title = (item.get("title") or item.get("original_title") or "").strip()
            release_date = str(item.get("release_date") or "")
            if not tmdb_id or not title or len(release_date) < 4 or not release_date[:4].isdigit():
                continue

            if tmdb_id not in movies_by_id:
                item["_source"] = source_tag
                movies_by_id[tmdb_id] = item
                counts[source_tag] += 1
            elif source_tag == "top_rated":
                movies_by_id[tmdb_id]["_source"] = "top_rated"

    print(
        f"      -> Toplam {len(movies_by_id)} benzersiz film toplandı "
        f"(Top Rated: {counts['top_rated']}, Popüler: {counts['popular']}, "
        f"Tür Keşfi: {counts['discover']}, Türk Sineması: {counts['turkish']})."
    )
    return movies_by_id


async def enrich_with_imdb_ids(
    client: httpx.AsyncClient,
    base_params: Dict[str, str],
    movies_by_id: Dict[int, Dict[str, Any]],
    imdb_ratings: Dict[str, Tuple[float, int]],
) -> List[Dict[str, Any]]:
    """Her film için TMDB external_ids (IMDb ID) ve eksikse İngilizce özeti paralel çeker, IMDb puanını bağlar."""
    print(f"[3/4] {len(movies_by_id)} film için IMDb ID ve resmi IMDb puanları eşleştiriliyor...")
    semaphore = asyncio.Semaphore(20)

    async def _enrich_one(tmdb_id: int, item: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            overview = (item.get("overview") or "").strip()
            need_en_overview = len(overview) < 15

            imdb_id: Optional[str] = None
            if need_en_overview:
                detail = await _tmdb_get(
                    client,
                    f"/movie/{tmdb_id}",
                    base_params,
                    {"language": "en-US", "append_to_response": "external_ids"},
                )
                if detail:
                    ext = detail.get("external_ids") or {}
                    imdb_id = ext.get("imdb_id") or detail.get("imdb_id")
                    en_ov = (detail.get("overview") or "").strip()
                    if en_ov:
                        overview = en_ov
            else:
                ext = await _tmdb_get(client, f"/movie/{tmdb_id}/external_ids", base_params)
                if ext:
                    imdb_id = ext.get("imdb_id")

            if not overview:
                gnames = [GENRE_ID_TO_TR_NAME[g] for g in (item.get("genre_ids") or []) if g in GENRE_ID_TO_TR_NAME]
                genre_label = ", ".join(gnames[:3]) if gnames else "Sinema"
                overview = f"{item.get('title')} ({str(item.get('release_date'))[:4]}), {genre_label} türünde öne çıkan bir yapımdır."

            # Gerçek resmi IMDb puanı varsa onu kullan, yoksa TMDB puanını 1 ondalıkla yedek kullan
            imdb_rating: Optional[float] = None
            if imdb_id and imdb_id in imdb_ratings:
                imdb_rating = imdb_ratings[imdb_id][0]
            elif item.get("vote_average"):
                try:
                    val = round(float(item["vote_average"]), 1)
                    if val > 0:
                        imdb_rating = val
                except (ValueError, TypeError):
                    pass

            poster_rel = item.get("poster_path")
            poster_url = f"{TMDB_IMAGE_BASE}{poster_rel}" if poster_rel else DEFAULT_POSTER_URL

            # Orijinal dil Türkçe ise Türkçe başlık, yabancı ise yaygın/orijinal başlığı tercih et
            orig_lang = (item.get("original_language") or "").lower()
            title = (
                (item.get("title") or item.get("original_title") or "").strip()
                if orig_lang == "tr"
                else (item.get("title") or item.get("original_title") or "").strip()
            )
            year = int(str(item["release_date"])[:4])
            vibes = _derive_vibes(item, item.get("_source", "popular"), imdb_rating)

            return {
                "title": title[:250],
                "overview": overview,
                "poster_path": poster_url,
                "release_year": year,
                "imdb_id": imdb_id[:20] if imdb_id else None,
                "imdb_rating": imdb_rating,
                "vibes": vibes,
            }

    enriched = await asyncio.gather(
        *(_enrich_one(tid, data) for tid, data in movies_by_id.items())
    )
    return list(enriched)


async def run_bulk_import() -> None:
    headers, base_params = _build_tmdb_auth()
    await db.init_db()

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        # IMDb resmi puan veri seti ve TMDB koleksiyonlarını paralel çek
        imdb_ratings, movies_by_id = await asyncio.gather(
            _download_imdb_ratings(client),
            collect_tmdb_movies(client, base_params),
        )

        if not movies_by_id:
            print("[!] TMDB'den film alınamadı. Lütfen TMDB_API_KEY değerinizi kontrol edin.")
            await db.disconnect()
            return

        enriched_movies = await enrich_with_imdb_ids(client, base_params, movies_by_id, imdb_ratings)

    print("[4/4] Veriler mükerrer kontrolü ile PostgreSQL veritabanına kaydediliyor...")
    added_count = 0
    skipped_count = 0

    async for session in db.get_session():
        existing_res = await session.execute(select(Movie))
        existing_movies = list(existing_res.scalars().all())
        existing_titles = {m.title.strip().lower() for m in existing_movies}
        existing_imdb_ids = {m.imdb_id.strip().lower() for m in existing_movies if m.imdb_id}

        existing_tags_res = await session.execute(select(VibeTag))
        tag_cache: Dict[str, VibeTag] = {
            t.tag_name.strip().lower(): t for t in existing_tags_res.scalars().all()
        }

        for item in enriched_movies:
            title_key = item["title"].strip().lower()
            imdb_key = item["imdb_id"].strip().lower() if item["imdb_id"] else None

            if title_key in existing_titles or (imdb_key and imdb_key in existing_imdb_ids):
                skipped_count += 1
                continue

            existing_titles.add(title_key)
            if imdb_key:
                existing_imdb_ids.add(imdb_key)

            movie_vibes: List[VibeTag] = []
            seen_tags: set[str] = set()
            for raw_tag in item["vibes"]:
                tkey = raw_tag.strip().lower()
                if not tkey or tkey in seen_tags:
                    continue
                seen_tags.add(tkey)
                if tkey not in tag_cache:
                    tag_cache[tkey] = VibeTag(tag_name=raw_tag.strip())
                movie_vibes.append(tag_cache[tkey])

            session.add(
                Movie(
                    id=uuid.uuid4(),
                    title=item["title"],
                    overview=item["overview"],
                    poster_path=item["poster_path"],
                    release_year=item["release_year"],
                    imdb_id=item["imdb_id"],
                    imdb_rating=item["imdb_rating"],
                    vibes=movie_vibes,
                )
            )
            added_count += 1

        if added_count > 0:
            await session.commit()

        total_movies = (await session.execute(select(func.count(Movie.id)))).scalar() or 0
        total_tags = (await session.execute(select(func.count(VibeTag.id)))).scalar() or 0

        print("\n========================================================")
        print("[+] TOPLU FİLM İÇE AKTARMA BAŞARIYLA TAMAMLANDI!")
        print(f"    - Yeni eklenen film     : {added_count}")
        print(f"    - Zaten mevcut (atlanan): {skipped_count}")
        print(f"    - Veritabanı toplam film: {total_movies}")
        print(f"    - Toplam vibe etiketi   : {total_tags}")
        print("========================================================")
        break

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(run_bulk_import())
