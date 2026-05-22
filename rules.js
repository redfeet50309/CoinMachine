// Signal → CSS class mapping. Pure presentation, no logic.
// Exposed via window.Rules so app.js can use it without ES modules
// (ES module imports load too late and miss Alpine's init event).

window.Rules = (function () {
  function trendClass(s) {
    if (s === '多頭排列') return 'bull';
    if (s === '空頭排列') return 'bear';
    return 'neutral';
  }

  function zoneClass(s) {
    // 台股配色：紅 = 多 (bull)、綠 = 空 (bear)
    // RSI: 超賣 = 反彈機會 → bull 色；超買 = 回檔風險 → bear 色
    if (s?.includes('多頭') || s?.includes('超賣') || s?.includes('做多')) return 'bull';
    if (s?.includes('空頭') || s?.includes('超買') || s?.includes('做空')) return 'bear';
    return 'neutral';
  }

  function histClass(s) {
    if (!s) return '';
    if (s.startsWith('紅柱')) return 'bull';
    if (s.startsWith('綠柱')) return 'bear';
    return '';
  }

  function bbClass(s) {
    if (!s) return '';
    // 強訊號交叉先判斷,避免 startsWith 比對被附註裡的「空頭/多頭」搶走
    if (s.startsWith('突破上軌') || s.startsWith('上穿中軌') || s.startsWith('上穿下軌')) return 'bull';
    if (s.startsWith('跌破下軌') || s.startsWith('下穿中軌') || s.startsWith('下穿上軌')) return 'bear';
    if (s === '上軌之上') return 'bull';
    if (s === '下軌之下') return 'bear';
    // %B / 位置標籤
    if (s.includes('超強多') || s.includes('多頭')) return 'bull';
    if (s.includes('超強空') || s.includes('空頭')) return 'bear';
    // Bandwidth 收斂 — 借用 .badge.cross 的 warn 色
    if (s.includes('收斂')) return 'cross';
    return '';
  }

  function formatPercent(v) {
    if (v == null || Number.isNaN(v)) return '—';
    return (Number(v) * 100).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
  }

  function formatPrice(v) {
    if (v == null || Number.isNaN(v)) return '—';
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatNum(v) {
    if (v == null || Number.isNaN(v)) return '—';
    const n = Number(v);
    return n.toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  }

  function formatTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('zh-TW', { hour12: false });
  }

  return { trendClass, zoneClass, histClass, bbClass, formatPrice, formatNum, formatPercent, formatTime };
})();
