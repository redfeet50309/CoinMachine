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
    if (s?.includes('多頭')) return 'bull';
    if (s?.includes('空頭')) return 'bear';
    return 'neutral';
  }

  function histClass(s) {
    if (!s) return '';
    if (s.startsWith('紅柱')) return 'bull';
    if (s.startsWith('綠柱')) return 'bear';
    return '';
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

  return { trendClass, zoneClass, histClass, formatPrice, formatNum, formatTime };
})();
