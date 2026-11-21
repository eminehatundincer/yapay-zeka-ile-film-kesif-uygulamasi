"""
Yapay Zeka ile Film Keşif Uygulaması - FastAPI Ana Sunucu Modülü.

Veritabanı yaşam döngüsü (lifespan), CORS yapılandırması, gerçek zamanlı
WebSocket log akışı için ObservableList, REST API uç noktaları ve
canlı ajan logu akıtan WebSocket rotasını içerir.
"""

import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Any, Callable, Iterable, Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.router import route_and_execute
from app.agents.tools import active_logs
from app.analysis_service import AnalysisService
from app.database import db
from app.schemas import AnalyticsResponse, SearchRequest, SearchResponse

logger = logging.getLogger("app.main")


# ==============================================================================
# 1. Dinamik Log Akışı İçin ObservableList Sınıfı
# ==============================================================================

class ObservableList(list):
    """Eleman eklendiğinde verilen callback fonksiyonunu anlık olarak tetikleyen liste sınıfı."""

    def __init__(
        self,
        iterable: Iterable[Any] = (),
        callback: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        super().__init__(iterable)
        self._callback = callback

    def append(self, item: Any) -> None:
        """Elemanı listeye ekler ve tanımlıysa callback fonksiyonunu çağırır."""
        super().append(item)
        if self._callback is not None:
            try:
                self._callback(item)
            except Exception as exc:
                logger.warning("ObservableList callback çalıştırılırken hata oluştu: %s", exc)


# ==============================================================================
# 2. Veritabanı Lifespan Yönetimi
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama başlangıcında veritabanı bağlantısını/tabloları hazırlar, kapanışta güvenle kapatır."""
    logger.info("FastAPI uygulaması başlatılıyor: veritabanı bağlantısı ve tablolar hazırlanıyor...")
    await db.connect()
    await db.init_db()
    logger.info("Veritabanı bağlantısı, tablolar ve seed verileri hazır.")
    try:
        yield
    finally:
        logger.info("FastAPI uygulaması kapatılıyor: veritabanı bağlantı havuzu kapatılıyor...")
        await db.disconnect()
        logger.info("Veritabanı bağlantısı başarıyla kapatıldı.")


# ==============================================================================
# 3. Sunucu Tanımlama ve CORS Yapılandırması
# ==============================================================================

app = FastAPI(
    title="Yapay Zeka ile Film Keşif API",
    description="Asenkron PostgreSQL ORM, Gemini yapay zeka ajanları ve canlı WebSocket log akışı sunan API.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# 4. HTTP API Uç Noktaları (REST)
# ==============================================================================

@app.get("/api/health", tags=["Sistem"])
async def health_check(session: AsyncSession = Depends(db.get_session)):
    """Asenkron SQL sorgusu ile PostgreSQL veritabanı bağlantısını test eder."""
    try:
        await session.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "connected",
        }
    except Exception as exc:
        logger.error("Veritabanı sağlık kontrolü başarısız oldu: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "detail": str(exc),
            },
        )


@app.post("/api/search", response_model=SearchResponse, tags=["Keşif"])
async def search_movies(
    request: SearchRequest,
    session: AsyncSession = Depends(db.get_session),
) -> SearchResponse:
    """Doğal dilde film/dizi keşif veya analitik sorgusunu ajan orkestrasyonuyla çalıştırır."""
    try:
        result = await route_and_execute(
            session=session,
            query_text=request.query,
            model=request.model,
        )
        return SearchResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Arama orkestrasyonu sırasında beklenmeyen hata oluştu.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Arama işlemi sırasında bir hata oluştu: {exc}",
        ) from exc


@app.get("/api/analytics", response_model=AnalyticsResponse, tags=["Analitik"])
async def get_analytics(
    session: AsyncSession = Depends(db.get_session),
) -> AnalyticsResponse:
    """AnalysisService üzerinden toplam sorgu sayısı, popüler mod etiketleri ve AI özetini döner."""
    try:
        return await AnalysisService.get_analytics_report(session)
    except Exception as exc:
        logger.exception("Analitik raporu hazırlanırken beklenmeyen hata oluştu.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analitik raporu oluşturulurken bir hata oluştu: {exc}",
        ) from exc


# ==============================================================================
# 5. Canlı Ajan Logu Akıtan WebSocket Rotası (WEBSOCKET /ws/search/)
# ==============================================================================

async def _handle_websocket_search(websocket: WebSocket) -> None:
    """Gelen WebSocket bağlantısını kabul eder, JSON arama sorgularını dinler,
    ajan loglarını ObservableList üzerinden gerçek zamanlı akıtır ve nihai sonucu döner.
    """
    await websocket.accept()
    logger.info("Yeni WebSocket bağlantısı kabul edildi.")

    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except WebSocketDisconnect:
                logger.info("WebSocket istemcisi bağlantıyı kapattı.")
                break
            except Exception:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Geçersiz JSON formatı. Lütfen {'query': '...'} biçiminde gönderin.",
                    }
                )
                continue

            if not isinstance(payload, dict):
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Beklenen istek gövdesi JSON nesnesi olmalıdır.",
                    }
                )
                continue

            query_text = str(payload.get("query") or "").strip()
            model_name = payload.get("model")

            if len(query_text) < 2:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Arama sorgusu en az 2 karakter olmalıdır.",
                    }
                )
                continue

            # Gerçek zamanlı log akışı için sıralı asyncio.Queue ve gönderici coroutine
            log_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            async def _log_sender() -> None:
                try:
                    while True:
                        entry = await log_queue.get()
                        try:
                            if entry is None:
                                break
                            await websocket.send_json({"type": "log", "message": entry})
                        finally:
                            log_queue.task_done()
                except Exception as send_err:
                    logger.warning("WebSocket log gönderimi kesildi: %s", send_err)
                    while not log_queue.empty():
                        try:
                            log_queue.get_nowait()
                            log_queue.task_done()
                        except asyncio.QueueEmpty:
                            break

            sender_task = asyncio.create_task(_log_sender())

            def _on_agent_log(entry: str) -> None:
                log_queue.put_nowait(entry)

            observable_logs = ObservableList(callback=_on_agent_log)
            context_token = active_logs.set(observable_logs)

            try:
                result: Optional[dict[str, Any]] = None
                async for session in db.get_session():
                    result = await route_and_execute(
                        session=session,
                        query_text=query_text,
                        model=model_name,
                    )
                    break

                # Kuyruktaki tüm gerçek zamanlı logların istemciye ulaşmasını bekle
                await log_queue.put(None)
                await sender_task

                if result is None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Veritabanı oturumu açılamadı.",
                        }
                    )
                    continue

                # UUID ve datetime alanlarını JSON uyumlu hale getir
                validated_payload = SearchResponse(**result).model_dump(mode="json")
                await websocket.send_json(
                    {
                        "type": "result",
                        "data": validated_payload,
                    }
                )
            except WebSocketDisconnect:
                logger.info("Arama sırasında WebSocket bağlantısı kapandı.")
                break
            except Exception as exc:
                logger.exception("WebSocket arama işlenirken hata oluştu.")
                if not sender_task.done():
                    await log_queue.put(None)
                    await sender_task
                try:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Arama sırasında bir hata oluştu: {exc}",
                        }
                    )
                except Exception:
                    break
            finally:
                active_logs.reset(context_token)
                if not sender_task.done():
                    sender_task.cancel()
                    try:
                        await sender_task
                    except asyncio.CancelledError:
                        pass
    except WebSocketDisconnect:
        logger.info("WebSocket bağlantısı sonlandırıldı.")


@app.websocket("/ws/search/")
async def websocket_search_trailing_slash(websocket: WebSocket) -> None:
    """Canlı ajan logu akıtan ana WebSocket uç noktası (/ws/search/)."""
    await _handle_websocket_search(websocket)


@app.websocket("/ws/search")
async def websocket_search_no_trailing_slash(websocket: WebSocket) -> None:
    """Trailing slash olmadan bağlanan istemciler için WebSocket uyumluluk uç noktası (/ws/search)."""
    await _handle_websocket_search(websocket)
