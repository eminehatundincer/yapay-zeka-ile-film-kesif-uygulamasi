import { useState } from 'react';
import { Loader2, Search, Sparkles } from 'lucide-react';

const QUICK_PROMPTS = [
  {
    label: 'Kafa dağıtmalık komedi',
    query: 'Bugün çok yorgunum, kafa dağıtacak eğlenceli ve komik filmler öner.',
  },
  {
    label: 'Zihin bükücü bilim kurgu',
    query: 'Zihin bükücü, karanlık ve felsefi bir bilim kurgu filmi izlemek istiyorum.',
  },
  {
    label: 'Yeşilçam nostaljisi',
    query: 'İçimi ısıtacak nostaljik Yeşilçam ve Türk sineması klasikleri öner.',
  },
  {
    label: 'Öğretici belgesel',
    query: 'Boş vaktimi verimli geçirmek için öğretici belgesel ve gerçek hayat hikayeleri öner.',
  },
  {
    label: 'Trend raporu (Analitik)',
    query: 'Kullanıcılar en çok hangi ruh hallerinde arama yaptı? Trend analizi ver.',
  },
];

export default function PromptBar({ onSearch, isLoading }) {
  const [query, setQuery] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length < 2 || isLoading) return;
    onSearch(trimmed);
  };

  const handleQuickSelect = (presetQuery) => {
    if (isLoading) return;
    setQuery(presetQuery);
    onSearch(presetQuery);
  };

  return (
    <section className="w-full rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm sm:p-6">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#0f3b82]/10 text-[#0f3b82]">
            <Sparkles className="h-4 w-4" />
          </span>
          <h2 className="text-sm font-semibold tracking-tight text-[#1e293b] sm:text-base">
            Ruh Halini Anlat, Sana Özel Filmleri Keşfedelim
          </h2>
        </div>
        <span className="hidden text-xs font-medium text-slate-400 sm:inline">
          Doğal dil arama &amp; analitik sorgu destekli
        </span>
      </div>

      <form onSubmit={handleSubmit} className="relative flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-4 h-5 w-5 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={isLoading}
            placeholder="Örn: Yağmurlu bir akşam için melankolik ama iç ısıtan filmler..."
            maxLength={1000}
            className="w-full rounded-xl border border-slate-200 bg-[#f8fafc] py-3.5 pr-4 pl-12 text-sm text-[#1e293b] placeholder-slate-400 transition-all focus:border-[#0f3b82] focus:bg-white focus:ring-4 focus:ring-[#0f3b82]/10 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 sm:text-[15px]"
          />
        </div>

        <button
          type="submit"
          disabled={isLoading || query.trim().length < 2}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#0f3b82] px-6 py-3.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#0a2a5e] active:scale-[0.99] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 sm:min-w-[144px]"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Aranıyor...</span>
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              <span>Keşfet</span>
            </>
          )}
        </button>
      </form>

      {/* Hızlı test için hazır öneri butonları */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="mr-1 text-xs font-medium text-slate-400">Hızlı dene:</span>
        {QUICK_PROMPTS.map((item) => (
          <button
            key={item.label}
            type="button"
            disabled={isLoading}
            onClick={() => handleQuickSelect(item.query)}
            className="rounded-full border border-slate-200 bg-[#f8fafc] px-3 py-1.5 text-xs font-medium text-slate-600 transition-all hover:border-[#0f3b82]/40 hover:bg-[#0f3b82]/5 hover:text-[#0f3b82] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {item.label}
          </button>
        ))}
      </div>
    </section>
  );
}
