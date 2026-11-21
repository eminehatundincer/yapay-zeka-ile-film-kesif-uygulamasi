"""
Arama Trendleri ve Analitik Özet Servisi (AnalysisService).
PostgreSQL unnest fonksiyonu ile en popüler mod etiketlerini hesaplar ve
Gemini modeliyle kısa Türkçe analitik özetler üretir.
"""

import asyncio
import os
from typing import List

from google import genai
from google.genai import types
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import log_agent
from app.config import settings
from app.database import UserQuery
from app.schemas import AnalyticsResponse, TrendItem


class AnalysisService:
    """Kullanıcı arama trendlerini ve yapay zeka tabanlı özetleri yöneten asenkron servis."""

    SUMMARY_MODEL = "gemini-3.5-flash"
    _summary_cache: dict[tuple, str] = {}

    @staticmethod
    def _get_gemini_client() -> genai.Client:
        """Gemini API istemcisini ortam/ayar anahtarıyla başlatır."""
        api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY bulunamadı! Lütfen backend/.env dosyasında tanımlayın."
            )
        return genai.Client(api_key=api_key)

    @staticmethod
    async def get_analytics_report(session: AsyncSession) -> AnalyticsResponse:
        """Toplam sorgu sayısını ve PostgreSQL unnest ile en popüler 10 mod etiketini hesaplar.

        Ardından generate_ai_summary çağrısıyla 1-2 cümlelik Türkçe özet ekleyerek
        AnalyticsResponse döndürür.
        """
        log_agent("Analitik raporu hazırlanıyor: toplam sorgu sayısı ve popüler modlar sorgulanıyor...")

        # 1. Toplam sorgu sayısını hesapla
        total_stmt = select(func.count(UserQuery.id))
        total_result = await session.execute(total_stmt)
        total_queries = int(total_result.scalar() or 0)

        # 2. PostgreSQL unnest ile ARRAY içindeki en popüler 10 mod etiketini azalan sırada listele
        unnested_mood = func.unnest(UserQuery.detected_moods).label("mood")
        unnest_subq = select(unnested_mood).subquery()

        trends_stmt = (
            select(
                unnest_subq.c.mood.label("mood"),
                func.count().label("count"),
            )
            .where(unnest_subq.c.mood.is_not(None))
            .where(unnest_subq.c.mood != "")
            .group_by(unnest_subq.c.mood)
            .order_by(desc(func.count()), unnest_subq.c.mood.asc())
            .limit(10)
        )
        trends_result = await session.execute(trends_stmt)
        rows = trends_result.all()

        top_moods: List[TrendItem] = [
            TrendItem(mood=str(row[0]), count=int(row[1]))
            for row in rows
            if row and row[0] is not None
        ]

        log_agent(
            f"Analitik sorgusu tamamlandı: toplam {total_queries} sorgu, "
            f"{len(top_moods)} popüler mod etiketi bulundu."
        )

        # 3. Yapay zeka özetini üret (aynı istatistik snapshot'ı için önbellekten anlık dön)
        cache_key = (total_queries, tuple((m.mood, m.count) for m in top_moods))
        if cache_key in AnalysisService._summary_cache:
            ai_summary = AnalysisService._summary_cache[cache_key]
            log_agent("Analitik AI özeti önbellekten anlık olarak yüklendi.")
        else:
            ai_summary = await AnalysisService.generate_ai_summary(
                total_queries=total_queries,
                top_moods=top_moods,
            )
            if total_queries > 0:
                AnalysisService._summary_cache[cache_key] = ai_summary

        return AnalyticsResponse(
            total_queries=total_queries,
            top_moods=top_moods,
            ai_summary=ai_summary,
        )

    @staticmethod
    async def generate_ai_summary(
        total_queries: int,
        top_moods: List[TrendItem],
        model: str = SUMMARY_MODEL,
    ) -> str:
        """gemini-3.5-flash modeliyle arama trendlerine dair 1-2 cümlelik Türkçe özet üretir.

        Model 404/NOT_FOUND hatası verirse otomatik olarak settings.GEMINI_MODEL değerine
        (gemini-2.5-flash) düşer; API erişilemezse deterministik bir özet döner.
        """
        if total_queries == 0:
            log_agent("Henüz kullanıcı sorgusu bulunmadığı için varsayılan analitik özeti dönülüyor.")
            return (
                "Henüz kaydedilmiş bir kullanıcı araması bulunmuyor. "
                "Kullanıcılar film keşfetmeye başladıkça popüler ruh halleri ve trendler burada özetlenecektir."
            )

        moods_text = (
            ", ".join(f"{item.mood} ({item.count} kez)" for item in top_moods)
            if top_moods
            else "henüz sınıflandırılmış mod etiketi yok"
        )

        prompt = (
            "Sen bir film keşif platformunun veri analitiği asistanısın. "
            "Aşağıdaki arama verilerine bakarak kullanıcıların izleme eğilimlerini anlatan, "
            "samimi ve net, YALNIZCA 1-2 cümlelik Türkçe bir özet yaz.\n\n"
            f"- Toplam Sorgu Sayısı: {total_queries}\n"
            f"- En Popüler Mod Etiketleri: {moods_text}\n"
        )

        fallback_summary = (
            f"Platformda bugüne kadar toplam {total_queries} arama gerçekleştirildi"
            + (
                f" ve kullanıcıların en çok yöneldiği atmosferler arasında {top_moods[0].mood} "
                f"({top_moods[0].count} arama) öne çıkıyor."
                if top_moods
                else "."
            )
        )

        try:
            client = AnalysisService._get_gemini_client()
        except ValueError as err:
            log_agent(f"Gemini istemcisi başlatılamadı ({err}), varsayılan özet kullanılıyor.")
            return fallback_summary

        selected_model = model or AnalysisService.SUMMARY_MODEL
        fallback_model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
        max_retries = 3

        config = types.GenerateContentConfig(temperature=0.5)

        log_agent(f"Analitik AI özeti üretiliyor (Model: '{selected_model}')...")

        for attempt in range(1, max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=selected_model,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=5.0,
                )
                text_out = (response.text or "").strip()
                if text_out:
                    log_agent("Analitik AI özeti başarıyla oluşturuldu.")
                    return text_out
                break
            except Exception as err:
                err_str = str(err)
                if (
                    isinstance(err, asyncio.TimeoutError)
                    or "404" in err_str
                    or "NOT_FOUND" in err_str
                    or "no longer available" in err_str
                    or "503" in err_str
                    or "UNAVAILABLE" in err_str
                ) and selected_model != fallback_model:
                    log_agent(
                        f"'{selected_model}' yavaş/kullanılamıyor, hızlı '{fallback_model}' modeline geçiliyor..."
                    )
                    selected_model = fallback_model
                    continue
                if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str) and attempt < max_retries:
                    log_agent(
                        f"Gemini API yoğunluk bildirdi (Deneme {attempt}/{max_retries}), kısa süre bekleniyor..."
                    )
                    await asyncio.sleep(1.0)
                    continue
                log_agent(f"Analitik AI özeti üretiminde hata oluştu: {err}. Varsayılan özet dönülüyor.")
                return fallback_summary

        return fallback_summary
