import { BarChart3, RefreshCw, SearchCheck, Sparkles, TrendingUp } from 'lucide-react';

export default function Dashboard({ analytics, isLoading = false, onRefresh }) {
  const totalQueries = analytics?.total_queries ?? 0;
  const topMoods = Array.isArray(analytics?.top_moods) ? analytics.top_moods : [];
  const aiSummary =
    analytics?.ai_summary ||
    'Analitik verileri yüklendiğinde yapay zeka trend özeti burada görünecektir.';

  const totalMoodHits = topMoods.reduce((sum, item) => sum + (Number(item.count) || 0), 0);
  const maxCount = topMoods.reduce((max, item) => Math.max(max, Number(item.count) || 0), 0);

  return (
    <section className="space-y-5">
      {/* Üst Başlık ve Yenileme */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#0f3b82]/10 text-[#0f3b82]">
            <BarChart3 className="h-5 w-5" />
          </span>
          <div>
            <h2 className="text-base font-bold text-[#1e293b] sm:text-lg">
              Arama Trendleri ve Analiz Paneli
            </h2>
            <p className="text-xs text-slate-500">
              PostgreSQL <code className="font-mono">unnest</code> analitiği &amp; Gemini özet raporu
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-[#1e293b] shadow-xs transition-all hover:border-[#0f3b82]/40 hover:text-[#0f3b82] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>Verileri Yenile</span>
        </button>
      </div>

      {/* Üst Kartlar: Toplam Arama Sayacı + Gemini AI Trend Özeti */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Toplam Arama Sayacı Kartı */}
        <div className="flex flex-col justify-between rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
              Toplam Arama Sayısı
            </span>
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#0f3b82]/10 text-[#0f3b82]">
              <SearchCheck className="h-5 w-5" />
            </span>
          </div>

          <div className="mt-4">
            {isLoading && !analytics ? (
              <div className="h-10 w-24 animate-pulse rounded-lg bg-slate-200" />
            ) : (
              <p className="text-4xl font-bold tracking-tight text-[#0f3b82]">
                {totalQueries.toLocaleString('tr-TR')}
              </p>
            )}
            <p className="mt-1.5 text-xs text-slate-500">
              {topMoods.length > 0
                ? `En popüler ${topMoods.length} mod etiketi takip ediliyor`
                : 'Henüz kaydedilmiş trend etiketi yok'}
            </p>
          </div>
        </div>

        {/* Gemini AI Trend Özeti Kartı */}
        <div className="flex flex-col justify-between rounded-2xl border border-[#0f3b82]/20 bg-white p-5 shadow-sm lg:col-span-2">
          <div className="flex items-center gap-2 text-xs font-semibold tracking-wide text-[#0f3b82] uppercase">
            <Sparkles className="h-4 w-4" />
            <span>Gemini AI Trend Özeti</span>
          </div>

          <div className="mt-3 flex-1">
            {isLoading && !analytics ? (
              <div className="space-y-2">
                <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
                <div className="h-4 w-4/5 animate-pulse rounded bg-slate-100" />
              </div>
            ) : (
              <p className="text-sm leading-relaxed text-[#1e293b] sm:text-[15px]">
                {aiSummary}
              </p>
            )}
          </div>

          <div className="mt-4 flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
            <TrendingUp className="h-3.5 w-3.5 text-[#0f3b82]" />
            <span>Her yeni arama sonrasında otomatik güncellenir</span>
          </div>
        </div>
      </div>

      {/* En Popüler 10 Mod Etiketi Bar Grafiği */}
      <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm sm:p-6">
        <div className="mb-5 flex items-center justify-between gap-2">
          <h3 className="text-sm font-bold text-[#1e293b] sm:text-base">
            En Popüler 10 Mod Etiketi Dağılımı
          </h3>
          <span className="text-xs font-medium text-slate-400">
            Toplam {totalMoodHits} etiket eşleşmesi
          </span>
        </div>

        {topMoods.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-[#f8fafc] py-10 text-center text-sm text-slate-500">
            Henüz trend grafiği oluşturacak kadar arama kaydı yok. Keşif sekmesinden ilk aramanızı yapın!
          </div>
        ) : (
          <div className="space-y-3.5">
            {topMoods.slice(0, 10).map((item, idx) => {
              const count = Number(item.count) || 0;
              const sharePercent = totalMoodHits > 0 ? Math.round((count / totalMoodHits) * 100) : 0;
              const barWidth = maxCount > 0 ? Math.max(8, Math.round((count / maxCount) * 100)) : 0;

              return (
                <div key={`${item.mood}-${idx}`} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs sm:text-sm">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-[#0f3b82]/10 text-[11px] font-bold text-[#0f3b82]">
                        {idx + 1}
                      </span>
                      <span className="font-semibold text-[#1e293b]">{item.mood}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-semibold text-[#0f3b82]">%{sharePercent}</span>
                      <span className="text-slate-400">({count} kez)</span>
                    </div>
                  </div>

                  <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                    <div
                      style={{ width: `${barWidth}%` }}
                      className="h-full rounded-full bg-gradient-to-r from-[#0f3b82] to-blue-600 transition-all duration-500 ease-out"
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
