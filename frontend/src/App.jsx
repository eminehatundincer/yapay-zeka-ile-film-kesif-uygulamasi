import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, BarChart3, Clapperboard, Compass, Server } from 'lucide-react';
import PromptBar from './components/PromptBar.jsx';
import AgentLogs from './components/AgentLogs.jsx';
import MovieGrid from './components/MovieGrid.jsx';
import Dashboard from './components/Dashboard.jsx';

/**
 * Railway ve yerel geliştirme ortamları için dinamik HTTP / WebSocket URL çözümleyicisi.
 * Kod içinde hiçbir adres sabit (hardcoded) tutulmaz.
 */
function resolveBackendUrls() {
  const envSecure = import.meta.env.VITE_SECURE;
  const isSecure =
    envSecure !== undefined && String(envSecure).trim() !== ''
      ? String(envSecure).toLowerCase() === 'true'
      : window.location.protocol === 'https:';

  const host = (import.meta.env.VITE_BACKEND_HOST || window.location.hostname).trim();
  const port = (import.meta.env.VITE_BACKEND_PORT || '').trim();
  const hostWithPort = port ? `${host}:${port}` : host;

  const httpProtocol = isSecure ? 'https' : 'http';
  const wsProtocol = isSecure ? 'wss' : 'ws';

  return {
    httpBaseUrl: `${httpProtocol}://${hostWithPort}`,
    wsSearchUrl: `${wsProtocol}://${hostWithPort}/ws/search/`,
  };
}

function nowStamp() {
  return `[${new Date().toTimeString().slice(0, 8)}]`;
}

export default function App() {
  const { httpBaseUrl, wsSearchUrl } = useMemo(() => resolveBackendUrls(), []);

  const [activeTab, setActiveTab] = useState('discover');
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // Arama sonucu state'leri
  const [movies, setMovies] = useState([]);
  const [responseText, setResponseText] = useState('');
  const [detectedMood, setDetectedMood] = useState([]);
  const [matchedTool, setMatchedTool] = useState('');

  // Canlı ajan logları & bağlantı modu
  const [logs, setLogs] = useState([]);
  const [connectionMode, setConnectionMode] = useState('idle');

  // Analitik & sağlık durumu
  const [analytics, setAnalytics] = useState(null);
  const [isAnalyticsLoading, setIsAnalyticsLoading] = useState(false);
  const [backendHealthy, setBackendHealthy] = useState(null);

  const activeWsRef = useRef(null);

  const appendLog = useCallback((entry) => {
    setLogs((prev) => [...prev, entry]);
  }, []);

  const fetchAnalytics = useCallback(async () => {
    setIsAnalyticsLoading(true);
    try {
      const res = await fetch(`${httpBaseUrl}/api/analytics`);
      if (!res.ok) {
        throw new Error(`Analitik isteği başarısız oldu (HTTP ${res.status})`);
      }
      const data = await res.json();
      setAnalytics(data);
    } catch (err) {
      console.error('Analitik verisi alınamadı:', err);
    } finally {
      setIsAnalyticsLoading(false);
    }
  }, [httpBaseUrl]);

  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch(`${httpBaseUrl}/api/health`);
      setBackendHealthy(res.ok);
    } catch {
      setBackendHealthy(false);
    }
  }, [httpBaseUrl]);

  // İlk yükleme: güncel analitikleri ve backend sağlık durumunu çek
  useEffect(() => {
    fetchAnalytics();
    checkHealth();
    return () => {
      if (activeWsRef.current) {
        activeWsRef.current.close();
      }
    };
  }, [fetchAnalytics, checkHealth]);

  const applySearchResult = useCallback(
    (payload, mergeLogs = false) => {
      setMovies(Array.isArray(payload.movies) ? payload.movies : []);
      setResponseText(payload.response_text || '');
      setDetectedMood(Array.isArray(payload.detected_mood) ? payload.detected_mood : []);
      setMatchedTool(payload.matched_tool || '');
      setHasSearched(true);

      if (mergeLogs && Array.isArray(payload.logs) && payload.logs.length > 0) {
        setLogs((prev) => [...prev, ...payload.logs]);
      }

      // Her başarılı aramadan sonra analitik panelini güncel tut
      fetchAnalytics();
    },
    [fetchAnalytics]
  );

  const executeHttpFallback = useCallback(
    async (queryText) => {
      setConnectionMode('http-fallback');
      appendLog(
        `${nowStamp()} [Fallback] WebSocket kullanılamadı; HTTP POST (/api/search) üzerinden devam ediliyor...`
      );

      const res = await fetch(`${httpBaseUrl}/api/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: queryText }),
      });

      if (!res.ok) {
        let detail = `Sunucu hatası (HTTP ${res.status})`;
        try {
          const errJson = await res.json();
          if (errJson?.detail) {
            detail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
          }
        } catch {
          // JSON parse edilemezse varsayılan mesaj kalır
        }
        throw new Error(detail);
      }

      const data = await res.json();
      applySearchResult(data, true);
      appendLog(`${nowStamp()} [Fallback] HTTP POST sonucu başarıyla alındı.`);
    },
    [httpBaseUrl, appendLog, applySearchResult]
  );

  const executeViaWebSocket = useCallback(
    (queryText) =>
      new Promise((resolve, reject) => {
        let settled = false;
        let receivedResult = false;
        let ws;

        try {
          ws = new WebSocket(wsSearchUrl);
          activeWsRef.current = ws;
        } catch (err) {
          reject(err);
          return;
        }

        // Bağlantı 4 saniye içinde açılamazsa hızlıca HTTP Fallback'e düş
        const connectTimer = setTimeout(() => {
          if (!settled && ws.readyState !== WebSocket.OPEN) {
            settled = true;
            try {
              ws.close();
            } catch {
              // ignore
            }
            reject(new Error('WebSocket bağlantı zaman aşımı'));
          }
        }, 4000);

        ws.onopen = () => {
          clearTimeout(connectTimer);
          setConnectionMode('websocket');
          appendLog(`${nowStamp()} WebSocket bağlantısı kuruldu. Sorgu ajana iletiliyor...`);
          ws.send(JSON.stringify({ query: queryText }));
        };

        ws.onmessage = (event) => {
          try {
            const frame = JSON.parse(event.data);
            if (frame.type === 'log' && frame.message) {
              appendLog(frame.message);
            } else if (frame.type === 'result' && frame.data) {
              receivedResult = true;
              applySearchResult(frame.data, false);
              if (!settled) {
                settled = true;
                ws.close();
                resolve(frame.data);
              }
            } else if (frame.type === 'error') {
              const msg = frame.message || 'WebSocket arama sırasında hata oluştu.';
              appendLog(`${nowStamp()} [Hata] ${msg}`);
              if (!settled) {
                settled = true;
                ws.close();
                reject(new Error(msg));
              }
            }
          } catch (parseErr) {
            console.warn('WebSocket mesajı ayrıştırılamadı:', parseErr);
          }
        };

        ws.onerror = () => {
          clearTimeout(connectTimer);
          if (!settled) {
            settled = true;
            reject(new Error('WebSocket bağlantı hatası'));
          }
        };

        ws.onclose = () => {
          clearTimeout(connectTimer);
          if (activeWsRef.current === ws) {
            activeWsRef.current = null;
          }
          if (!settled && !receivedResult) {
            settled = true;
            reject(new Error('WebSocket bağlantısı sonuç alınmadan kapandı'));
          }
        };
      }),
    [wsSearchUrl, appendLog, applySearchResult]
  );

  const handleSearch = useCallback(
    async (queryText) => {
      if (activeWsRef.current) {
        try {
          activeWsRef.current.close();
        } catch {
          // ignore
        }
      }

      setActiveTab('discover');
      setIsLoading(true);
      setErrorMessage('');
      setLogs([`${nowStamp()} Yeni arama başlatılıyor: "${queryText}"`]);

      try {
        // 1. Önce WebSocket üzerinden canlı log akışı dene
        await executeViaWebSocket(queryText);
      } catch (wsErr) {
        // 2. WebSocket başarısız olursa otomatik HTTP POST Fallback kullan
        try {
          await executeHttpFallback(queryText);
        } catch (httpErr) {
          const finalMsg =
            httpErr?.message || wsErr?.message || 'Arama sırasında beklenmeyen bir hata oluştu.';
          setErrorMessage(finalMsg);
          appendLog(`${nowStamp()} [Hata] ${finalMsg}`);
        }
      } finally {
        setIsLoading(false);
      }
    },
    [executeViaWebSocket, executeHttpFallback, appendLog]
  );

  return (
    <div className="min-h-screen bg-[#f8fafc] text-[#1e293b]">
      {/* Üst Navigasyon Çubuğu */}
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#0f3b82] text-white shadow-sm">
              <Clapperboard className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight text-[#1e293b] sm:text-lg">
                Sine<span className="text-[#0f3b82]">AI</span>
              </h1>
              <p className="hidden text-xs text-slate-500 sm:block">
                Yapay Zeka Destekli Film Keşif &amp; Trend Analitiği
              </p>
            </div>
          </div>

          {/* Sekme Geçişi */}
          <nav className="flex items-center gap-1 rounded-xl border border-slate-200 bg-[#f8fafc] p-1">
            <button
              type="button"
              onClick={() => setActiveTab('discover')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all sm:text-sm ${
                activeTab === 'discover'
                  ? 'bg-[#0f3b82] text-white shadow-xs'
                  : 'text-slate-600 hover:text-[#1e293b]'
              }`}
            >
              <Compass className="h-4 w-4" />
              <span>Keşif</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('analytics')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all sm:text-sm ${
                activeTab === 'analytics'
                  ? 'bg-[#0f3b82] text-white shadow-xs'
                  : 'text-slate-600 hover:text-[#1e293b]'
              }`}
            >
              <BarChart3 className="h-4 w-4" />
              <span>Analiz Paneli</span>
              {analytics?.total_queries > 0 && (
                <span
                  className={`rounded-full px-1.5 py-0.2 text-[11px] ${
                    activeTab === 'analytics'
                      ? 'bg-white/20 text-white'
                      : 'bg-[#0f3b82]/10 text-[#0f3b82]'
                  }`}
                >
                  {analytics.total_queries}
                </span>
              )}
            </button>
          </nav>

          {/* Canlı Sunucu Durumu */}
          <div className="hidden items-center gap-2 md:flex">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
                backendHealthy === true
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : backendHealthy === false
                    ? 'border-rose-200 bg-rose-50 text-rose-700'
                    : 'border-slate-200 bg-slate-50 text-slate-500'
              }`}
            >
              <Server className="h-3.5 w-3.5" />
              {backendHealthy === true
                ? 'API Bağlı'
                : backendHealthy === false
                  ? 'API Çevrimdışı'
                  : 'Kontrol Ediliyor...'}
            </span>
          </div>
        </div>
      </header>

      {/* Ana İçerik */}
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        {errorMessage && (
          <div className="animate-fade-slide flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3.5 text-sm text-rose-800">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
            <div>
              <p className="font-semibold">İstek tamamlanamadı</p>
              <p className="mt-0.5 text-xs text-rose-700 sm:text-sm">{errorMessage}</p>
            </div>
          </div>
        )}

        {activeTab === 'discover' ? (
          <>
            <PromptBar onSearch={handleSearch} isLoading={isLoading} />

            <AgentLogs
              logs={logs}
              onClear={() => setLogs([])}
              connectionMode={connectionMode}
              isLoading={isLoading}
            />

            <MovieGrid
              movies={movies}
              responseText={responseText}
              detectedMood={detectedMood}
              matchedTool={matchedTool}
              isLoading={isLoading}
              hasSearched={hasSearched}
            />
          </>
        ) : (
          <Dashboard
            analytics={analytics}
            isLoading={isAnalyticsLoading}
            onRefresh={fetchAnalytics}
          />
        )}
      </main>
    </div>
  );
}
