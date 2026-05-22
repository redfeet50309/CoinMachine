// Main Alpine component. Non-module so Alpine.data() is registered before
// Alpine boots on DOMContentLoaded. Pulls helpers from window.{Api,Rules,ChartLib}
// (set up by rules.js / api.js / chart.js loaded earlier in <head>).

(function () {
  const POLL_MS = 30_000;

  function appComponent() {
    const { fetchWatchlist, fetchMeta, fetchStock,
            getPat, writeWatchlist, readLocalWatchlist, writeLocalWatchlist } = window.Api;
    const { trendClass, zoneClass, histClass, bbClass, formatPrice, formatNum, formatPercent, formatTime } = window.Rules;
    const { drawCharts, destroyCharts } = window.ChartLib;

    return {
      watchlist: { stocks: [] },
      cards: [],
      meta: null,
      expanded: null,
      addId: '',
      busy: false,
      error: '',
      loading: true,
      hasPat: false,
      trendClass, zoneClass, histClass, bbClass, formatPrice, formatNum, formatPercent, formatTime,

      get displayed() {
        const ids = (this.watchlist.stocks || []).map(s => s.id);
        return ids.map(id => this.cards.find(c => c.id === id)).filter(Boolean);
      },

      async init() {
        this.hasPat = !!getPat();
        await this.refresh();
        this.loading = false;
        setInterval(() => this.refresh().catch(() => {}), POLL_MS);
      },

      async refresh() {
        let wl;
        try {
          wl = await fetchWatchlist();
        } catch (e) {
          wl = readLocalWatchlist() || { version: 1, stocks: [] };
        }
        this.watchlist = wl;
        writeLocalWatchlist(wl);

        this.meta = await fetchMeta();

        const stockData = await Promise.all(
          (wl.stocks || []).map(async s => ({
            id: s.id,
            name: s.name,
            market: s.market || '?',
            data: await fetchStock(s.id),
          })),
        );
        this.cards = stockData;

        if (this.expanded) {
          const card = this.cards.find(c => c.id === this.expanded);
          if (card?.data) await this._renderCharts(card);
        }
      },

      toggle(id) {
        if (this.expanded === id) {
          destroyCharts(id);
          this.expanded = null;
          return;
        }
        if (this.expanded) destroyCharts(this.expanded);
        this.expanded = id;
        const card = this.cards.find(c => c.id === id);
        if (card?.data) queueMicrotask(() => this._renderCharts(card));
      },

      async _renderCharts(card) {
        await new Promise(r => requestAnimationFrame(r));
        try {
          drawCharts(card.id, card.data.history || []);
        } catch (e) {
          console.error('chart error', e);
        }
      },

      async addStock() {
        this.error = '';
        const id = (this.addId || '').trim();
        if (!/^\d{4,6}[A-Z]?$/.test(id)) {
          this.error = '股票代號應為 4-6 位數字 (如 2330)';
          return;
        }
        const MAX_STOCKS = 30;
        const currentCount = (this.watchlist.stocks || []).length;
        if (currentCount >= MAX_STOCKS) {
          this.error = `自選清單已達上限 ${MAX_STOCKS} 檔（目前 ${currentCount}）`;
          return;
        }
        if (this.watchlist.stocks?.some(s => s.id === id)) {
          this.error = `${id} 已在追蹤清單`;
          return;
        }
        this.busy = true;
        try {
          const next = {
            version: this.watchlist.version || 1,
            stocks: [
              ...(this.watchlist.stocks || []),
              { id, name: id, market: null, added_at: new Date().toISOString().slice(0, 10) },
            ],
          };
          if (this.hasPat) {
            await writeWatchlist(next, `watchlist: add ${id}`);
          } else {
            writeLocalWatchlist(next);
          }
          this.watchlist = next;
          this.cards.push({ id, name: id, market: '?', data: null });
          this.addId = '';
        } catch (e) {
          this.error = `新增失敗：${e.message}`;
        } finally {
          this.busy = false;
        }
      },

      async removeStock(id) {
        if (!confirm(`移除 ${id}？(歷史資料保留在 repo，可重新加入)`)) return;
        this.busy = true;
        try {
          const next = {
            version: this.watchlist.version || 1,
            stocks: (this.watchlist.stocks || []).filter(s => s.id !== id),
          };
          if (this.hasPat) {
            await writeWatchlist(next, `watchlist: remove ${id}`);
          } else {
            writeLocalWatchlist(next);
          }
          this.watchlist = next;
          this.cards = this.cards.filter(c => c.id !== id);
          if (this.expanded === id) {
            destroyCharts(id);
            this.expanded = null;
          }
        } catch (e) {
          this.error = `移除失敗：${e.message}`;
        } finally {
          this.busy = false;
        }
      },
    };
  }

  // Register globally so Alpine can find it via x-data="appComponent()".
  // Also register with Alpine.data() at init time for resilience.
  window.appComponent = appComponent;
  document.addEventListener('alpine:init', () => {
    if (window.Alpine) window.Alpine.data('app', appComponent);
  });
})();
