import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Proje/backend kök dizinini sys.path listesine ekle
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import Movie, UserQuery
from app.analysis_service import AnalysisService
from app.schemas import (
    ContentType,
    IntentAnalysisResponse,
    IntentType,
    MovieResponse,
    MovieSchema,
    SearchRequest,
    SearchResponse,
)
from app.agents.tools import (
    DEFAULT_POSTER_URL,
    active_logs,
    discover_new_movies_from_web,
    fetch_movie_poster_url,
    get_movies_by_vibe,
    log_agent,
)

# Varsayılan Hızlı Gemini Modeli ve Yedek Model Zinciri
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
FALLBACK_GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
]


def _build_candidate_models(primary_model: str) -> List[str]:
    """Birincil modelden başlayarak yinelenmeyen yedek model sırasını oluşturur."""
    candidates: List[str] = []
    for candidate in [primary_model, *FALLBACK_GEMINI_MODELS]:
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates

# Yapay Zeka Film Keşif Asistanı Sistem Talimatı
SYSTEM_INSTRUCTION = """
Sen sinema ve dizi alanında derin uzmanlığa sahip, kullanıcı psikolojisini ve sinematik atmosferleri mükemmel analiz eden yapay zeka tabanlı bir Film & Dizi Keşif Asistanısın.

Görevin, kullanıcının doğal dilde girdiği serbest metni (günlük ruh hali, duygusal durumu, yorgunluğu, izleme tercihi, tür talepleri vb.) derinlemesine analiz ederek aşağıdaki yapılandırılmış alanları kesin doğrulukla çıkarmaktır:

1. intent:
   - Kullanıcı film veya dizi tavsiyesi, arama, keşif ya da ruh haline uygun yapım istiyorsa: "search"
   - Kullanıcı istatistiksel veri, trend analizleri, geçmiş izleme raporları veya veri tabanı analitiği soruyorsa: "analytics"

2. mood:
   - Kullanıcının cümlelerinden süzülen duygusal durum, zihinsel ihtiyaç veya aranan atmosfer (Örn: "Yoğun bir günün ardından kafa dağıtmak, gülmek ve rahatlamak isteyen neşeli bir ruh hali").

3. content_type:
   - Kullanıcı dizi istiyorsa "series", film istiyorsa "movie", ayrım belirtmemişse veya her ikisi de uygunsa "all" ya da "movie".

4. tags:
   - Ruh haline, temaya, platforma (örn: Netflix istiyorsa "#Netflix", Türk filmi istiyorsa "#TürkSineması", Yeşilçam istiyorsa "#Yeşilçam") ve atmosfere uygun 2 ile 4 adet temiz CamelCase hashtag üret. Her biri '#' ile başlamalı ve sonunda fazladan kelime/boşluk bulunmamalıdır (Örn: ["#Distopik", "#HayattaKalma", "#BilimKurgu"]).

5. genres:
   - Bu ruh haline en iyi yanıt verecek 1-3 sinema/dizi türü (Örn: ["Komedi", "Macera"]).

6. explanation:
   - Kullanıcıya yönelik empatik, samimi ve öneri mantığını 1-2 cümlede açıklayan kısa bir değerlendirme.

7. needs_web_discovery:
   - Kullanıcı vizyondaki/çok yeni (2024-2026) yapımlar, belirli bir filme/diziye doğrudan benzer yapımlar (örn: "Açlık Oyunları benzeri", "Interstellar gibi") veya çok spesifik niş temalar istiyorsa true; genel ruh hali/tür aramaları için false.

Yanıtını kesinlikle belirtilen JSON şemasına uygun olarak üret.
"""


def get_gemini_client() -> genai.Client:
    """Gemini API istemcisini yapılandırır ve döndürür.
    
    API anahtarı config (settings.GEMINI_API_KEY) veya ortam değişkenlerinden
    (os.environ['GEMINI_API_KEY']) okunur. Bulunamazsa ValueError fırlatılır.
    """
    api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY bulunamadı! Lütfen backend/.env dosyasında 'GEMINI_API_KEY' "
            "değişkenini tanımlayın veya ortam değişkeni olarak ayarlayın."
        )
    return genai.Client(api_key=api_key)


def _clean_json_text(text: str) -> str:
    """Markdown kod bloklarını (```json ... ```) temizleyerek ham JSON metnini döner."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


async def analyze_intent(
    query_text: str,
    model: Optional[str] = None
) -> IntentAnalysisResponse:
    """Kullanıcının doğal dilde girdiği arama/ruh hali metnini gemini-2.5-flash ile analiz eder.
    
    Pydantic IntentAnalysisResponse şemasına tam uygun, kesin Structured JSON çıktısı döner.
    ContextVar kancası (active_logs) üzerinden her adımı loglar.
    """
    clean_query = query_text.strip()
    log_agent(f"Niyet analizi başlatıldı. Kullanıcı sorgusu: '{clean_query}'")

    selected_model = model or getattr(settings, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    log_agent(f"Gemini client hazırlanıyor (Model: '{selected_model}')...")
    client = get_gemini_client()

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=IntentAnalysisResponse,
        temperature=0.3,
    )

    log_agent("Gemini API'ye yapılandırılmış JSON niyet analizi sorgusu gönderiliyor...")

    candidate_models = _build_candidate_models(selected_model)
    response = None
    last_error: Optional[Exception] = None

    for idx, current_model in enumerate(candidate_models):
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=current_model,
                    contents=clean_query,
                    config=config,
                ),
                timeout=12.0,
            )
            break
        except Exception as err:
            last_error = err
            err_str = str(err)
            is_retryable = isinstance(err, asyncio.TimeoutError) or any(
                code in err_str
                for code in ("404", "NOT_FOUND", "no longer available", "503", "UNAVAILABLE", "429", "disconnected")
            )
            if is_retryable and idx < len(candidate_models) - 1:
                next_model = candidate_models[idx + 1]
                log_agent(
                    f"'{current_model}' kullanılamıyor veya yavaş ({err_str[:80] or 'timeout'}), "
                    f"'{next_model}' modeline geçiliyor..."
                )
                continue
            log_agent(f"Gemini API hatası oluştu: {err}")
            raise err

    if response is None and last_error is not None:
        raise last_error

    raw_response_text = response.text or "{}"
    log_agent("Gemini API yanıtı alındı, IntentAnalysisResponse şemasıyla doğrulanıyor...")

    try:
        cleaned_json = _clean_json_text(raw_response_text)
        analysis_result = IntentAnalysisResponse.model_validate_json(cleaned_json)
    except Exception as e:
        log_agent(f"Pydantic model doğrulama uyarısı ({e}), fallback yapılandırılıyor.")
        analysis_result = IntentAnalysisResponse(
            intent=IntentType.SEARCH,
            mood=f"Kullanıcı keşif talebi: {clean_query}",
            content_type=ContentType.MOVIE,
            tags=["#FilmKeşfi", "#Popüler"],
            genres=["Komedi", "Drama"],
            explanation="Kullanıcının sorgusu başarıyla analiz edildi.",
            needs_web_discovery=False,
        )

    log_agent(
        f"Analiz tamamlandı -> Niyet: '{analysis_result.intent.value}', "
        f"Ruh Hali: '{analysis_result.mood}', "
        f"Etiketler: {analysis_result.tags}, Türler: {analysis_result.genres}"
    )
    return analysis_result


async def route_and_execute_standalone(
    query_text: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """Kullanıcının sorgusunu niyet analizi, etiketleme ve öneri üretimi için Gemini modeline yönlendirir.
    
    Ajanın her adımını loglar, film önerilerinin afişlerini Wikipedia üzerinden çeker ve
    biriktirilen loglarla birlikte yapılandırılmış sonuç döner.
    """
    # 1. Oturum loglarını sıfırla / initialize et
    active_logs.set([])
    log_agent(f"Yeni istek başlatıldı. Kullanıcı sorgusu: '{query_text}'")

    selected_model = model or getattr(settings, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    log_agent(f"Gemini client hazırlanıyor (Model: '{selected_model}')...")
    client = get_gemini_client()

    # 2. Gemini için sistem ve niyet analizi talimatı
    prompt = f"""
Sen sinema ve dizi alanında uzmanlaşmış, yapay zeka tabanlı bir Router ve Öneri Ajanısın.
Görevin, kullanıcının girdiği doğal dildeki sorguyu analiz etmek ve JSON formatında yapılandırılmış bir yanıt üretmektir.

KULLANICI SORGUSU: "{query_text}"

Lütfen aşağıdaki kurallara harfiyen uyarak YALNIZCA geçerli bir JSON nesnesi üret:

1. INTENT (Niyet Analizi):
   - Eğer kullanıcı istatistiksel, veri analizi, trendler, geçmiş izleme raporları gibi sorular soruyorsa: "intent": "analytics"
   - Eğer kullanıcı film/dizi tavsiyesi, keşif veya doğrudan arama yapıyorsa: "intent": "search"

2. TAGS (Etiketler):
   - Sorgunun temasına, ruh haline ve türüne uygun 1 ile 3 adet CamelCase etiket üret.
   - Her etiket '#' ile başlamalıdır (Örnek format: "#ZihinBükücü", "#KaranlıkAtmosfer", "#DistopikGelecek").

3. NEEDS_WEB_DISCOVERY (Ağ Keşif Bayrağı):
   - Sorgu vizyondaki, henüz çok yeni (2024-2026), güncel veya çok spesifik dış bilgi gerektiren durumları içeriyorsa: true
   - Genel klasik veya standart tavsiye aramaları için: false

4. FALLBACK_RECOMMENDATIONS (Öneriler):
   - Kullanıcının zevkine ve sorgusuna en uygun 3 film önerisini 'fallback_recommendations' listesi altında üret.
   - Her eleman şu alanları içermelidir:
     - "title": Filmin orijinal veya yaygın bilinen adı (Wikipedia'da bulunabilmesi için kesin adı, örn: "Inception")
     - "year": Yapım yılı (sayı veya metin, örn: 2010)
     - "genre": Türü (örn: "Bilim Kurgu / Gerilim")
     - "description": Kullanıcının arayışına neden uygun olduğunu açıklayan 1-2 cümlelik kısa açıklama

JSON ŞEMASI:
{{
  "intent": "search" | "analytics",
  "tags": ["#Etiket1", "#Etiket2"],
  "needs_web_discovery": false,
  "fallback_recommendations": [
    {{
      "title": "Film Adı",
      "year": 2020,
      "genre": "Tür",
      "description": "Açıklama"
    }}
  ]
}}
"""

    log_agent("Gemini API'ye yapılandırılmış JSON sorgusu gönderiliyor...")
    
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.7,
    )

    max_retries = 3
    response = None
    fallback_model = "gemini-3.8-flash"

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.aio.models.generate_content(
                model=selected_model,
                contents=prompt,
                config=config,
            )
            break
        except Exception as err:
            err_str = str(err)
            if ("404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str) and selected_model != fallback_model:
                log_agent(f"'{selected_model}' kullanılamıyor, güncel '{fallback_model}' modeline geçiliyor...")
                selected_model = fallback_model
                continue
            elif ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str) and attempt < max_retries:
                log_agent(f"Gemini API geçici yoğunluk bildirdi (Deneme {attempt}/{max_retries}). 2 saniye sonra tekrar deneniyor...")
                await asyncio.sleep(2.0)
            else:
                raise err

    raw_response_text = response.text or "{}"
    log_agent("Gemini API yanıtı alındı, JSON parse ediliyor...")

    try:
        parsed_data = json.loads(_clean_json_text(raw_response_text))
    except json.JSONDecodeError as e:
        log_agent(f"JSON parse hatası: {e}. Ham metin: {raw_response_text}")
        parsed_data = {
            "intent": "search",
            "tags": ["#FilmKeşfi"],
            "needs_web_discovery": False,
            "fallback_recommendations": [],
            "raw_response": raw_response_text,
        }

    recommendations = parsed_data.get("fallback_recommendations", [])
    log_agent(f"Niyet: '{parsed_data.get('intent')}', Etiketler: {parsed_data.get('tags')}, "
              f"Öneri sayısı: {len(recommendations)}")

    # 3. Film önerilerinin afişlerini Wikipedia üzerinden asenkron olarak çek
    if recommendations:
        log_agent(f"{len(recommendations)} adet film için Wikipedia üzerinden paralel afiş çekme başlatılıyor...")
        
        async def enrich_movie_with_poster(movie: dict) -> dict:
            title = movie.get("title", "").strip()
            if title:
                poster_url = await fetch_movie_poster_url(title)
                movie["poster_url"] = poster_url
            else:
                movie["poster_url"] = DEFAULT_POSTER_URL
            return movie

        enriched_recommendations = await asyncio.gather(
            *(enrich_movie_with_poster(m) for m in recommendations)
        )
        parsed_data["fallback_recommendations"] = list(enriched_recommendations)
        log_agent("Tüm film afişleri başarıyla zenginleştirildi.")

    # 4. Toplanan logları sonuca ekle ve döndür
    parsed_data["logs"] = active_logs.get()
    log_agent("İşlem tamamlandı, sonuç paketi hazırlandı.")
    return parsed_data


async def test_gemini_connection(model: Optional[str] = None) -> str:
    """Gemini modeline basit bir deneme sorgusu gönderir ve yanıtı yazdırır."""
    selected_model = model or getattr(settings, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    print(f"[*] Gemini client başlatılıyor...")
    client = get_gemini_client()
    
    prompt = "Merhaba! Sen bir film ve dizi keşif asistanısın. Bağlantının çalıştığını teyit eden tek cümlelik bir karşılama mesajı yaz."
    print(f"[*] '{selected_model}' modeline test isteği gönderiliyor: '{prompt}'")
    
    response = await client.aio.models.generate_content(
        model=selected_model,
        contents=prompt
    )
    
    print("\n[+] Gemini API Yanıtı:")
    print("----------------------------------------")
    print(response.text)
    print("----------------------------------------\n")
    return response.text


# ==============================================================================
# Asenkron ORM Destekli Ana Orkestrasyon Katmanı
# ==============================================================================

async def _synthesize_recommendation_text(
    query_text: str,
    mood: str,
    movies: List[Movie],
    model: Optional[str] = None,
) -> str:
    """Önerilen filmleri ve kullanıcının ruh halini Gemini'ye göndererek 2-3 cümlelik
    gündelik dilde, samimi ve sinematik bir Türkçe öneri metni sentezler.
    """
    if not movies:
        return (
            "Şu an aradığın ruh haline tam uyan bir film bulamadım ama atmosferini biraz daha "
            "detaylandırırsan sana harika sinematik öneriler çıkarabilirim."
        )

    movie_lines = "\n".join(
        f"- {m.title} ({m.release_year}): {m.overview}" for m in movies[:5]
    )
    movie_titles = ", ".join(m.title for m in movies[:3])

    fallback_text = (
        f"Şu anki ruh haline çok yakışacak özel bir seçki hazırladım: {movie_titles}. "
        f"Işıkları kıs, arkana yaslan ve bu atmosferin tadını çıkar!"
    )

    prompt = (
        "Sen sinemaya tutkulu, sıcak ve samimi bir film dostusun.\n"
        f"Kullanıcının sorgusu: \"{query_text}\"\n"
        f"Tespit edilen ruh hali: \"{mood}\"\n"
        f"Önerilen filmler:\n{movie_lines}\n\n"
        "Bu ruh haline ve seçilen filmlere göre YALNIZCA 2-3 cümlelik, gündelik dilde, "
        "samimi, empatik ve sinematik bir Türkçe öneri açıklaması yaz. "
        "Madde işareti veya markdown başlığı kullanma, tek akıcı paragraf olsun."
    )

    try:
        client = get_gemini_client()
    except ValueError as err:
        log_agent(f"Öneri metni sentezinde Gemini istemcisi başlatılamadı ({err}), varsayılan metin dönülüyor.")
        return fallback_text

    selected_model = model or getattr(settings, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    candidate_models = _build_candidate_models(selected_model)
    config = types.GenerateContentConfig(temperature=0.8)

    log_agent(f"Sinematik öneri açıklama metni sentezleniyor (Model: '{selected_model}')...")

    for idx, current_model in enumerate(candidate_models):
        try:
            response = await client.aio.models.generate_content(
                model=current_model,
                contents=prompt,
                config=config,
            )
            synthesized = (response.text or "").strip()
            if synthesized:
                log_agent("Sinematik öneri metni başarıyla sentezlendi.")
                return synthesized
            break
        except Exception as err:
            err_str = str(err)
            is_retryable = any(
                code in err_str
                for code in ("404", "NOT_FOUND", "no longer available", "503", "UNAVAILABLE", "429", "disconnected")
            )
            if is_retryable and idx < len(candidate_models) - 1:
                next_model = candidate_models[idx + 1]
                log_agent(
                    f"'{current_model}' kullanılamıyor veya yoğun, '{next_model}' modeline geçiliyor..."
                )
                continue
            log_agent(f"Öneri metni sentezi başarısız oldu ({err}), varsayılan metin kullanılıyor.")
            return fallback_text

    return fallback_text


class _MovieSelectionPayload(BaseModel):
    """Gemini anlamsal eleme ve yeniden sıralama (re-ranking) çıktı şeması."""

    selected_indices: List[int] = Field(
        default_factory=list,
        description="Kullanıcının isteğine gerçekten uyan aday filmlerin 0-tabanlı indeksleri (en alakalıdan başlayarak en fazla 6 adet). Hiçbiri gerçekten uymuyorsa boş liste [].",
    )


async def _filter_and_rank_movies(
    query_text: str,
    mood: str,
    candidates: List[Movie],
    model: Optional[str] = None,
) -> List[Movie]:
    """Veritabanından gelen aday filmleri kullanıcının asıl sorgusuna göre anlamsal olarak eler ve sıralar.

    Özellikle 'Açlık Oyunları benzeri' gibi belirli bir filme referans veren sorgularda
    yalnızca ortak genel etiketten (örn. 'Macera') gelen alakasız filmleri (örn. Western) eler.
    """
    if not candidates:
        return []

    candidate_lines = []
    for idx, m in enumerate(candidates):
        vibe_names = [
            v.tag_name if hasattr(v, "tag_name") else str(v)
            for v in (getattr(m, "vibes", None) or [])
        ]
        short_ov = (m.overview or "")[:160].replace("\n", " ")
        candidate_lines.append(
            f"[{idx}] {m.title} ({m.release_year}) | Etiketler: {', '.join(vibe_names)} | Özet: {short_ov}"
        )

    prompt = (
        "Sen titiz bir sinema küratörüsün.\n"
        f"Kullanıcının tam sorgusu: \"{query_text}\"\n"
        f"Tespit edilen ruh hali: \"{mood}\"\n\n"
        "Aşağıdaki aday filmleri incele:\n"
        + "\n".join(candidate_lines)
        + "\n\nKurallar:\n"
        "- Kullanıcının sorgusuna (özellikle belirli bir filme benzerlik, platform, dönem veya tema talebine) "
        "GERÇEKTEN uyan filmlerin indekslerini en alakalıdan başlayarak (en fazla 6 adet) 'selected_indices' listesine ekle.\n"
        "- Konusu veya türü açıkça alakasız olan filmleri (örneğin 'Açlık Oyunları benzeri' istenmişken Western, romantik komedi veya alakasız klasikleri) KESİNLİKLE ELE!\n"
        "- Eğer adayların HİÇBİRİ kullanıcının asıl isteğine gerçekten uymuyorsa 'selected_indices' için boş liste [] döndür."
    )

    try:
        client = get_gemini_client()
    except ValueError:
        return candidates[:6]

    selected_model = model or getattr(settings, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    candidate_models = _build_candidate_models(selected_model)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_MovieSelectionPayload,
        temperature=0.1,
    )

    log_agent(f"Veritabanı adayları ({len(candidates)} film) anlamsal olarak filtreleniyor ve sıralanıyor...")

    for idx, current_model in enumerate(candidate_models):
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=config,
                ),
                timeout=10.0,
            )
            parsed = _MovieSelectionPayload.model_validate_json(_clean_json_text(response.text or "{}"))
            picked: List[Movie] = []
            seen_idx: set[int] = set()
            for i in parsed.selected_indices:
                if isinstance(i, int) and 0 <= i < len(candidates) and i not in seen_idx:
                    seen_idx.add(i)
                    picked.append(candidates[i])
            log_agent(f"Anlamsal eleme tamamlandı: {len(candidates)} adaydan {len(picked)} alakalı film seçildi.")
            return picked[:6]
        except Exception as err:
            err_str = str(err)
            is_retryable = isinstance(err, asyncio.TimeoutError) or any(
                code in err_str
                for code in ("404", "NOT_FOUND", "no longer available", "503", "UNAVAILABLE", "429", "disconnected")
            )
            if is_retryable and idx < len(candidate_models) - 1:
                continue
            log_agent(f"Anlamsal eleme atlandı ({err}), skorlu DB sırası kullanılıyor.")
            return candidates[:6]

    return candidates[:6]


def _clean_hashtag(raw_tag: str) -> str:
    """Etiket sonundaki olası artık karakterleri ve boşlukları temizler."""
    cleaned = re.sub(r"\s+me$", "", raw_tag.strip(), flags=re.IGNORECASE).strip()
    if cleaned and not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    return cleaned


async def route_and_execute(
    session: AsyncSession,
    query_text: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Asenkron ORM destekli ana orkestrasyon fonksiyonu.

    Kullanıcının niyet analizini yapar:
    - Niyet 'analytics' ise sorguyu UserQuery tablosuna kaydeder ve AnalysisService.get_analytics_report çağrısını yürütür.
    - Niyet 'search' ise sorguyu kaydeder, önce yerel veritabanında mod etiketlerini skorlu olarak arar ve
      anlamsal elemeden geçirir; uygun film bulunmazsa veya web keşfi gerekiyorsa discover_new_movies_from_web
      aracını tetikler. Önerilen filmleri ve ruh halini Gemini'ye göndererek 2-3 cümlelik samimi, sinematik
      Türkçe öneri metni sentezler.

    Sonuçları kullanılan aracı, tespit edilen mod/etiketleri, film listesini ve active_logs üzerinden
    toplanan ajan loglarını içeren bir sözlük olarak döndürür.
    """
    existing_logs = active_logs.get()
    if existing_logs is None or type(existing_logs) is list:
        active_logs.set([])
    clean_query = (query_text or "").strip()
    log_agent(f"Orkestrasyon başlatıldı. Kullanıcı sorgusu: '{clean_query}'")

    # 1. Niyet ve ruh hali analizi
    analysis = await analyze_intent(clean_query, model=model)
    detected_tags = [_clean_hashtag(tag) for tag in analysis.tags if tag and tag.strip()]
    detected_mood = detected_tags if detected_tags else [analysis.mood]

    # 2. Kullanıcı sorgusunu analitik takibi için veritabanına kaydet
    user_query_record = UserQuery(
        query_text=clean_query,
        detected_moods=detected_tags,
    )
    session.add(user_query_record)
    await session.commit()
    log_agent("Kullanıcı sorgusu analitik veritabanına (user_queries) kaydedildi.")

    # 3. Niyet: ANALYTICS
    if analysis.intent == IntentType.ANALYTICS:
        log_agent("Niyet 'analytics' olarak belirlendi. AnalysisService.get_analytics_report çağrılıyor...")
        matched_tool = "AnalysisService.get_analytics_report"
        report = await AnalysisService.get_analytics_report(session)

        log_agent("Analitik orkestrasyonu başarıyla tamamlandı.")
        return {
            "response_text": report.ai_summary,
            "movies": [],
            "matched_tool": matched_tool,
            "detected_mood": detected_mood,
            "logs": list(active_logs.get()),
        }

    # 4. Niyet: SEARCH
    log_agent("Niyet 'search' olarak belirlendi. Yerel veritabanında mod etiketleri taranıyor...")
    db_candidates = await get_movies_by_vibe(session, detected_tags)
    filtered_db_movies = (
        await _filter_and_rank_movies(clean_query, analysis.mood, db_candidates, model=model)
        if db_candidates
        else []
    )

    final_movies: List[Movie] = []
    if not filtered_db_movies or analysis.needs_web_discovery:
        reason = (
            "referans film/web keşfi gerektiği için"
            if analysis.needs_web_discovery
            else "yerel veritabanında sorguya tam uyan film bulunamadığı için"
        )
        log_agent(f"Web keşif aracı tetikleniyor ({reason})...")
        matched_tool = "discover_new_movies_from_web"

        mood_context = (
            f"Kullanıcı isteği: {clean_query} | Ruh hali: {analysis.mood} "
            f"({', '.join(detected_tags)})"
            if detected_tags
            else f"Kullanıcı isteği: {clean_query} | Ruh hali: {analysis.mood}"
        )
        discovered_movies = await discover_new_movies_from_web(
            session,
            user_mood=mood_context,
            model=model,
        )

        # Keşfedilen filmleri öne alarak yalnızca anlamsal elemeden geçmiş yerel eşleşmelerle birleştir
        seen_titles: set[str] = set()
        for movie_obj in discovered_movies + filtered_db_movies:
            key = movie_obj.title.strip().lower()
            if key not in seen_titles:
                seen_titles.add(key)
                final_movies.append(movie_obj)
        final_movies = final_movies[:6]
    else:
        matched_tool = "get_movies_by_vibe"
        final_movies = filtered_db_movies

    # 5. Önerilen filmler ve ruh haliyle sinematik Türkçe açıklama metni sentezle
    response_text = await _synthesize_recommendation_text(
        query_text=clean_query,
        mood=analysis.mood,
        movies=final_movies,
        model=model,
    )

    serialized_movies = [
        MovieSchema.model_validate(movie_obj).model_dump()
        for movie_obj in final_movies
    ]

    log_agent(
        f"Arama orkestrasyonu tamamlandı. Kullanılan araç: '{matched_tool}', "
        f"dönen film sayısı: {len(serialized_movies)}."
    )

    return {
        "response_text": response_text,
        "movies": serialized_movies,
        "matched_tool": matched_tool,
        "detected_mood": detected_mood,
        "logs": list(active_logs.get()),
    }


if __name__ == "__main__":
    sample_query = "Bugün çok yorgunum, kafa dağıtacak komik bir şeyler izlemek istiyorum"
    print(f"\n==================================================")
    print(f"[*] Film & Dizi Ajanı Niyet Analizi Test Başlatılıyor")
    print(f"[*] Örnek Sorgu: \"{sample_query}\"")
    print(f"==================================================\n")

    try:
        intent_res = asyncio.run(analyze_intent(sample_query))
        print("\n--- [YAPILANDIRILMIŞ NİYET ANALİZİ (Pydantic)] ---")
        print(f"Niyet (Intent)        : {intent_res.intent.value}")
        print(f"Ruh Hali (Mood)       : {intent_res.mood}")
        print(f"İçerik Türü           : {intent_res.content_type.value}")
        print(f"Etiketler (Tags)      : {', '.join(intent_res.tags)}")
        print(f"Önerilen Türler       : {', '.join(intent_res.genres)}")
        print(f"Açıklama              : {intent_res.explanation}")
        print(f"Ağ Keşfi Gerekir mi?  : {intent_res.needs_web_discovery}")
        print("\n==================================================\n")

    except ValueError as e:
        print(f"[!] Doğrulama Hatası: {e}")
    except Exception as e:
        print(f"[!] Çalıştırma Hatası: {e}")

