import logging
import urllib.parse
from contextvars import ContextVar
from datetime import datetime
from typing import List, Optional
import httpx

# Standart logger yapılandırması
logger = logging.getLogger("agent.tools")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# İstek/oturum bazlı logları saklamak için ContextVar
active_logs: ContextVar[List[str]] = ContextVar("active_logs", default=[])

# Yüksek kaliteli varsayılan mock afiş görseli
DEFAULT_POSTER_URL = "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?q=80&w=600&auto=format&fit=crop"


def log_agent(message: str) -> None:
    """Ajan işlemlerini standart logger'a ve active_logs ContextVar listesine saat damgalı olarak ekler."""
    timestamp = datetime.now().strftime("[%H:%M:%S]")
    formatted_entry = f"{timestamp} {message}"
    
    # Standart logging
    logger.info(message)
    
    # ContextVar listesine coroutine-güvenli ekleme (ObservableList alt sınıfını koruyarak)
    try:
        existing_logs = active_logs.get()
    except LookupError:
        existing_logs = None

    if existing_logs is not None and type(existing_logs) is not list and isinstance(existing_logs, list):
        existing_logs.append(formatted_entry)
    else:
        current_logs = list(existing_logs) if existing_logs is not None else []
        current_logs.append(formatted_entry)
        active_logs.set(current_logs)


async def fetch_movie_poster_url(movie_title: str, client: Optional[httpx.AsyncClient] = None) -> str:
    """Wikipedia API kullanarak verilen film başlığına ait afiş (thumbnail) adresini asenkron çeker.
    
    Bulunamazsa veya hata oluşursa yüksek kaliteli bir mock görsel URL'i döndürür.
    """
    clean_title = movie_title.strip()
    log_agent(f"Wikipedia afiş sorgusu başlatılıyor: '{clean_title}'")
    
    # Wikipedia REST Summary API
    encoded_title = urllib.parse.quote(clean_title.replace(" ", "_"))
    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"
    
    headers = {
        "User-Agent": "YapayZekaFilmKesifBot/1.0 (contact@example.com) httpx"
    }
    
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=6.0, follow_redirects=True, headers=headers)
        close_client = True

    try:
        # 1. Aşama: Sayfa özet API'sinden thumbnail kontrolü
        response = await client.get(summary_url)
        if response.status_code == 200:
            data = response.json()
            thumbnail = data.get("thumbnail", {}).get("source")
            if thumbnail:
                log_agent(f"Afiş başarıyla bulundu (Wikipedia Summary): '{clean_title}'")
                return thumbnail
        
        # 2. Aşama: Sayfa adı tam uyuşmadıysa Wikipedia Arama API'si ile dene
        search_query = urllib.parse.quote(f"{clean_title} film")
        search_url = (
            f"https://en.wikipedia.org/w/api.php?action=query&generator=search"
            f"&gsrsearch={search_query}&gsrlimit=1&prop=pageimages&pithumbsize=600&format=json"
        )
        search_res = await client.get(search_url)
        if search_res.status_code == 200:
            pages = search_res.json().get("query", {}).get("pages", {})
            for _, page_info in pages.items():
                thumbnail = page_info.get("thumbnail", {}).get("source")
                if thumbnail:
                    log_agent(f"Afiş arama ile bulundu (Wikipedia Search): '{clean_title}'")
                    return thumbnail
        
        log_agent(f"Wikipedia afişi bulunamadı, mock görsel kullanılıyor: '{clean_title}'")
        return DEFAULT_POSTER_URL

    except Exception as e:
        log_agent(f"Wikipedia afiş sorgusunda hata oluştu ('{clean_title}'): {e}. Mock görsel atanıyor.")
        return DEFAULT_POSTER_URL
    finally:
        if close_client:
            await client.aclose()


async def fetch_omdb_movie_details(
    movie_title: str,
    release_year: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """OMDb API üzerinden filmin IMDb ID, IMDb puanı ve yüksek kaliteli afiş URL'ini asenkron çeker.

    OMDB_API_KEY tanımlı değilse veya film bulunamazsa None değerler içeren sözlük döner.
    """
    empty_result = {"imdb_id": None, "imdb_rating": None, "poster_url": None}
    clean_title = (movie_title or "").strip()
    if not clean_title:
        return empty_result

    api_key = settings.OMDB_API_KEY or os.environ.get("OMDB_API_KEY")
    if not api_key:
        return empty_result

    log_agent(f"OMDb (IMDb) sorgusu başlatılıyor: '{clean_title}'")

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=8.0, follow_redirects=True)
        close_client = True

    try:
        param_variants = []
        if release_year:
            param_variants.append({"apikey": api_key, "t": clean_title, "y": str(release_year), "type": "movie"})
        param_variants.append({"apikey": api_key, "t": clean_title, "type": "movie"})
        param_variants.append({"apikey": api_key, "t": clean_title})

        data = None
        for params in param_variants:
            resp = await client.get("https://www.omdbapi.com/", params=params)
            if resp.status_code == 200:
                candidate = resp.json()
                if candidate.get("Response") == "True":
                    data = candidate
                    break

        if not data:
            log_agent(f"OMDb (IMDb) kaydı bulunamadı: '{clean_title}'")
            return empty_result

        raw_imdb_id = data.get("imdbID")
        imdb_id = raw_imdb_id if raw_imdb_id and raw_imdb_id != "N/A" else None

        raw_rating = data.get("imdbRating")
        imdb_rating: Optional[float] = None
        if raw_rating and raw_rating != "N/A":
            try:
                imdb_rating = float(raw_rating)
            except ValueError:
                imdb_rating = None

        raw_poster = data.get("Poster")
        poster_url = (
            raw_poster
            if raw_poster and raw_poster != "N/A" and str(raw_poster).startswith("http")
            else None
        )

        log_agent(
            f"OMDb (IMDb) verisi alındı: '{clean_title}' "
            f"(IMDb: {imdb_rating if imdb_rating is not None else 'N/A'}, ID: {imdb_id or 'N/A'})"
        )
        return {
            "imdb_id": imdb_id,
            "imdb_rating": imdb_rating,
            "poster_url": poster_url,
        }
    except Exception as exc:
        log_agent(f"OMDb (IMDb) sorgusunda hata oluştu ('{clean_title}'): {exc}")
        return empty_result
    finally:
        if close_client:
            await client.aclose()


# ==============================================================================
# SQLAlchemy Asenkron ORM Tabanlı Ajan Araçları
# ==============================================================================

import asyncio
import os
import re
import uuid
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import Movie, VibeTag


class _DiscoveredMovieItem(BaseModel):
    """Gemini tarafından keşfedilen tekil film çıktısı şeması."""

    title: str = Field(..., description="Filmin orijinal veya uluslararası yaygın adı (Wikipedia araması için).")
    overview: str = Field(..., description="Filmin 2-3 cümlelik Türkçe özeti.")
    release_year: int = Field(..., description="Filmin vizyon yılı (tam sayı).")
    vibes: List[str] = Field(default_factory=list, description="2-4 adet Türkçe atmosfer/mod etiketi ('#' olmadan).")


class _DiscoveredMoviesPayload(BaseModel):
    """Gemini web keşif yanıtı kök şeması."""

    movies: List[_DiscoveredMovieItem] = Field(default_factory=list)


def _normalize_vibe_keywords(vibe_tags: list) -> List[str]:
    """Hashtag ve CamelCase formatındaki mod etiketlerini esnek DB aramasına uygun terimlere dönüştürür.

    Örn: '#ZihinBükücü' -> ['ZihinBükücü', 'Zihin Bükücü', 'Zihin', 'Bükücü']
    """
    terms: List[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        cleaned = term.strip()
        key = cleaned.lower()
        if len(cleaned) >= 3 and key not in seen:
            seen.add(key)
            terms.append(cleaned)

    for raw_tag in vibe_tags:
        if not raw_tag:
            continue
        no_hash = str(raw_tag).strip().lstrip("#").strip()
        if not no_hash:
            continue

        # Hem orijinal (hash'siz) hem CamelCase ayrılmış versiyonu ekle
        spaced = re.sub(r"(?<=[a-zçğıöşü0-9])(?=[A-ZÇĞİÖŞÜ])", " ", no_hash)
        spaced = re.sub(r"[_\-]+", " ", spaced).strip()

        _add(no_hash)
        _add(spaced)

        # Anlamlı alt kelimeleri de ekle (örn. '#KaranlıkAtmosfer' -> 'Karanlık')
        for part in spaced.split():
            if len(part) >= 4:
                _add(part)

    return terms


async def get_movies_by_vibe(session: AsyncSession, vibe_tags: list) -> List[Movie]:
    """Sorguda geçen mod etiketleriyle eşleşen filmleri asenkron olarak veritabanından getirir."""
    if not vibe_tags:
        log_agent("Mod etiketi listesi boş; veritabanı film araması atlandı.")
        return []

    search_terms = _normalize_vibe_keywords(vibe_tags)
    if not search_terms:
        log_agent("Geçerli arama terimi üretilemedi; veritabanından film getirilemedi.")
        return []

    log_agent(f"Veritabanında mod etiketlerine göre film aranıyor: {vibe_tags}")

    conditions = []
    for term in search_terms:
        conditions.append(VibeTag.tag_name.ilike(f"%{term}%"))
        compact = term.replace(" ", "").lower()
        conditions.append(func.replace(func.lower(VibeTag.tag_name), " ", "") == compact)

    stmt = (
        select(Movie)
        .join(Movie.vibes)
        .options(selectinload(Movie.vibes))
        .where(or_(*conditions))
        .group_by(Movie.id)
        .order_by(
            func.count(func.distinct(VibeTag.id)).desc(),
            Movie.imdb_rating.desc().nulls_last(),
        )
        .limit(15)
    )

    result = await session.execute(stmt)
    movies = list(result.scalars().unique().all())

    if movies:
        titles = ", ".join(m.title for m in movies)
        log_agent(f"Veritabanında {len(movies)} uyumlu film bulundu: {titles}")
    else:
        log_agent("Veritabanında verilen mod etiketleriyle eşleşen film bulunamadı.")

    return movies


def _clean_json_block(text: str) -> str:
    """Markdown ```json ... ``` sarmalayıcılarını temizler."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


async def discover_new_movies_from_web(
    session: AsyncSession,
    user_mood: str,
    model: Optional[str] = None,
) -> List[Movie]:
    """Gemini API kullanarak kullanıcının moduna uygun 3 adet yeni ve gerçek film keşfeder.

    Her filmin afişini Wikipedia üzerinden asenkron çeker, veritabanında mükerrer kayıt
    kontrolü yaparak yalnızca özgün filmleri ilişkili VibeTag kayıtlarıyla birlikte ekler.
    """
    clean_mood = (user_mood or "").strip()
    log_agent(f"Web/AI film keşfi başlatılıyor. Hedef ruh hali: '{clean_mood}'")

    api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY bulunamadı! Lütfen backend/.env dosyasında tanımlayın."
        )

    client = genai.Client(api_key=api_key)
    selected_model = model or getattr(settings, "GEMINI_MODEL", "gemini-3.5-flash-lite")
    candidate_models: List[str] = []
    for candidate in [
        selected_model,
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
    ]:
        if candidate and candidate not in candidate_models:
            candidate_models.append(candidate)

    prompt = (
        "Sen sinema tarihi ve güncel dünya sineması konusunda uzman bir film küratörüsün.\n"
        f"Kullanıcının ruh hali / talebi: \"{clean_mood}\"\n\n"
        "Bu ruh haline mükemmel uyan, GERÇEK ve var olan TAM 3 ADET film öner.\n"
        "Kurallar:\n"
        "- Her filmin 'title' alanı Wikipedia'da kolayca bulunabilmesi için filmin orijinal veya uluslararası İngilizce adı olsun.\n"
        "- 'overview' alanı 2-3 cümlelik akıcı Türkçe özet olsun.\n"
        "- 'release_year' geçerli bir tam sayı yapım yılı olsun.\n"
        "- 'vibes' alanı 2 ile 4 adet kısa Türkçe atmosfer etiketi içersin ('#' işareti olmadan, örn: ['Karanlık', 'Gerilim', 'Zihin Bükücü']).\n"
        "- Yalnızca belirtilen JSON şemasına uygun yanıt üret."
    )

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_DiscoveredMoviesPayload,
        temperature=0.7,
    )

    response = None
    last_error: Optional[Exception] = None
    for idx, current_model in enumerate(candidate_models):
        try:
            response = await client.aio.models.generate_content(
                model=current_model,
                contents=prompt,
                config=config,
            )
            break
        except Exception as err:
            last_error = err
            err_str = str(err)
            is_retryable = any(
                code in err_str
                for code in ("404", "NOT_FOUND", "no longer available", "503", "UNAVAILABLE", "429", "disconnected")
            )
            if is_retryable and idx < len(candidate_models) - 1:
                next_model = candidate_models[idx + 1]
                log_agent(
                    f"'{current_model}' kullanılamıyor veya yoğun ({err_str[:80]}), "
                    f"'{next_model}' modeline geçiliyor..."
                )
                continue
            log_agent(f"Web keşfi sırasında Gemini API hatası oluştu: {err}")
            raise

    if response is None and last_error is not None:
        raise last_error

    raw_text = (response.text if response else "") or "{}"
    try:
        payload = _DiscoveredMoviesPayload.model_validate_json(_clean_json_block(raw_text))
        discovered_items = payload.movies[:3]
    except Exception as parse_err:
        log_agent(f"Keşfedilen film JSON yanıtı doğrulanamadı: {parse_err}")
        return []

    if not discovered_items:
        log_agent("Gemini yeni film önerisi döndürmedi.")
        return []

    log_agent(
        f"Gemini {len(discovered_items)} adet film keşfetti: "
        f"{', '.join(item.title for item in discovered_items)}. OMDb (IMDb) ve afiş verileri çekiliyor..."
    )

    async def _enrich_item(item: _DiscoveredMovieItem) -> dict:
        omdb_info = await fetch_omdb_movie_details(item.title, release_year=item.release_year)
        poster_url = omdb_info.get("poster_url")
        if not poster_url:
            poster_url = await fetch_movie_poster_url(item.title)
        return {
            "imdb_id": omdb_info.get("imdb_id"),
            "imdb_rating": omdb_info.get("imdb_rating"),
            "poster_url": poster_url or DEFAULT_POSTER_URL,
        }

    # OMDb (IMDb puanı + afiş) ve gerekirse Wikipedia afişlerini paralel olarak çek
    enrichments = await asyncio.gather(*(_enrich_item(item) for item in discovered_items))

    saved_movies: List[Movie] = []
    tag_cache: dict[str, VibeTag] = {}
    seen_titles: set[str] = set()
    has_new_records = False

    for item, enriched in zip(discovered_items, enrichments):
        poster_url = enriched["poster_url"]
        imdb_id = enriched["imdb_id"]
        imdb_rating = enriched["imdb_rating"]
        clean_title = item.title.strip()
        if not clean_title:
            continue

        title_key = clean_title.lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        # Mükerrer kayıt kontrolü (case-insensitive başlık eşleşmesi)
        existing_stmt = (
            select(Movie)
            .options(selectinload(Movie.vibes))
            .where(func.lower(Movie.title) == title_key)
        )
        existing_res = await session.execute(existing_stmt)
        existing_movie = existing_res.scalars().first()

        if existing_movie is not None:
            log_agent(f"Mükerrer kayıt tespit edildi, mevcut veritabanı kaydı kullanılıyor: '{existing_movie.title}'")
            saved_movies.append(existing_movie)
            continue

        # İlişkili VibeTag kayıtlarını bul veya tekilleştirerek oluştur
        movie_vibes_objs: List[VibeTag] = []
        movie_tag_keys: set[str] = set()

        for raw_tag in item.vibes:
            clean_tag = str(raw_tag).strip().lstrip("#").strip()
            if not clean_tag:
                continue
            tag_key = clean_tag.lower()
            if tag_key in movie_tag_keys:
                continue
            movie_tag_keys.add(tag_key)

            if tag_key in tag_cache:
                vibe_obj = tag_cache[tag_key]
            else:
                tag_stmt = select(VibeTag).where(func.lower(VibeTag.tag_name) == tag_key)
                tag_res = await session.execute(tag_stmt)
                vibe_obj = tag_res.scalars().first()
                if vibe_obj is None:
                    vibe_obj = VibeTag(tag_name=clean_tag)
                tag_cache[tag_key] = vibe_obj

            movie_vibes_objs.append(vibe_obj)

        new_movie = Movie(
            id=uuid.uuid4(),
            title=clean_title,
            overview=item.overview.strip(),
            poster_path=poster_url or DEFAULT_POSTER_URL,
            release_year=int(item.release_year),
            imdb_id=imdb_id,
            imdb_rating=imdb_rating,
            vibes=movie_vibes_objs,
        )
        session.add(new_movie)
        saved_movies.append(new_movie)
        has_new_records = True
        log_agent(f"Yeni film veritabanına eklendi: '{new_movie.title}' ({new_movie.release_year})")

    if has_new_records:
        await session.commit()
        log_agent("Keşfedilen yeni filmler veritabanına kalıcı olarak kaydedildi.")

    return saved_movies
