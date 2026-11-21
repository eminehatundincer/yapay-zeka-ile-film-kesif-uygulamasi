import { useEffect, useRef } from 'react';
import { Radio, Terminal, Trash2, WifiOff } from 'lucide-react';

export default function AgentLogs({ logs = [], onClear, connectionMode = 'idle', isLoading = false }) {
  const scrollContainerRef = useRef(null);

  // Yeni log satırı geldikçe otomatik aşağı kaydır
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs]);

  const modeBadge = (() => {
    if (connectionMode === 'websocket') {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-[11px] font-medium text-emerald-300">
          <Radio className={`h-3 w-3 ${isLoading ? 'animate-pulse' : ''}`} />
          WebSocket Canlı
        </span>
      );
    }
    if (connectionMode === 'http-fallback') {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 px-2.5 py-0.5 text-[11px] font-medium text-amber-300">
          <WifiOff className="h-3 w-3" />
          HTTP Fallback
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-700/80 px-2.5 py-0.5 text-[11px] font-medium text-slate-300">
        Hazır
      </span>
    );
  })();

  const renderLogLine = (entry, idx) => {
    const match = String(entry).match(/^(\[\d{2}:\d{2}:\d{2}\])\s*(.*)$/);
    const timestamp = match ? match[1] : null;
    const message = match ? match[2] : String(entry);
    const isWarning = /fallback|hata|uyarı|kullanılamıyor/i.test(message);
    const isSuccess = /tamamlandı|bulundu|eklendi|sentezlendi|hazırlandı/i.test(message);

    return (
      <div
        key={`${idx}-${entry.slice(0, 24)}`}
        className="animate-fade-slide flex items-start gap-2.5 border-b border-slate-800/60 py-1.5 last:border-b-0"
      >
        <span className="select-none text-[11px] text-slate-500">
          {String(idx + 1).padStart(2, '0')}
        </span>
        {timestamp && (
          <span className="shrink-0 text-[11px] font-medium text-sky-400/90">
            {timestamp}
          </span>
        )}
        <span
          className={`break-words text-xs leading-relaxed ${
            isWarning
              ? 'text-amber-300'
              : isSuccess
                ? 'text-emerald-300'
                : 'text-slate-200'
          }`}
        >
          {message}
        </span>
      </div>
    );
  };

  return (
    <section className="flex flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-[#1e293b] shadow-sm">
      {/* Terminal Üst Çubuğu */}
      <div className="flex items-center justify-between gap-2 border-b border-slate-700/80 bg-[#0f172a] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-rose-400/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-400/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
          </div>
          <div className="ml-1 flex items-center gap-1.5 text-xs font-semibold text-slate-200">
            <Terminal className="h-3.5 w-3.5 text-sky-400" />
            <span>Ajan Canlı Log Terminali</span>
          </div>
          {modeBadge}
        </div>

        <button
          type="button"
          onClick={onClear}
          disabled={logs.length === 0}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-2.5 py-1 text-xs font-medium text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-700 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Trash2 className="h-3.5 w-3.5" />
          <span>Temizle</span>
        </button>
      </div>

      {/* Log Çıktı Alanı */}
      <div
        ref={scrollContainerRef}
        className="terminal-scrollbar h-56 overflow-y-auto bg-[#0f172a]/90 px-4 py-3 font-mono sm:h-64"
      >
        {logs.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-slate-500">
            <Terminal className="h-6 w-6 opacity-50" />
            <p className="text-xs">
              Arama başlattığınızda yapay zeka ajanının tüm adımları burada canlı akacaktır.
            </p>
          </div>
        ) : (
          <div>
            {logs.map((entry, idx) => renderLogLine(entry, idx))}
            {isLoading && (
              <div className="mt-2 flex items-center gap-2 text-xs text-sky-400">
                <span className="inline-block h-2 w-2 animate-ping rounded-full bg-sky-400" />
                <span>Ajan çalışıyor...</span>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
