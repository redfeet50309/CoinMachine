// Lightweight Charts wrapper. Draws price candles + MA overlays and a MACD subchart.
// Exposed via window.ChartLib for non-module load order.
//
// Colors are pulled from CSS custom properties at draw time so the entire chart
// theme follows :root tokens in styles.css. Only the color string literals were
// swapped — all data flow, setData, time-sync, and resize logic is unchanged.

window.ChartLib = (function () {
  const charts = new Map(); // id -> { priceChart, macdChart, rsiChart, bbChart, bandwidthChart, resize }

  // Read a CSS custom property from :root. Called once per drawCharts() so the
  // chart re-themes if styles.css ever swaps tokens (e.g. light mode later).
  const cssVar = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function drawCharts(stockId, history) {
    destroyCharts(stockId);
    const priceEl = document.getElementById(`chart-price-${stockId}`);
    const macdEl = document.getElementById(`chart-macd-${stockId}`);
    const rsiEl = document.getElementById(`chart-rsi-${stockId}`);
    const bbEl = document.getElementById(`chart-bb-${stockId}`);
    const bwEl = document.getElementById(`chart-bandwidth-${stockId}`);
    if (!priceEl || !macdEl) return;

    const recent = history.slice(-90);
    if (recent.length === 0) return;

    // Resolve all theme colors once per draw
    const C = {
      bg:         cssVar('--bg'),
      text:       cssVar('--text'),
      border:     cssVar('--border'),
      bull:       cssVar('--bull'),
      bear:       cssVar('--bear'),
      warn:       cssVar('--warn'),
      accent:     cssVar('--accent'),
      diverge:    cssVar('--diverge'),
      neutral:    cssVar('--neutral'),
      neutralDim: cssVar('--neutral-dim'),
    };

    const baseOptions = {
      layout: {
        background: { color: C.bg },
        textColor: C.text,
      },
      grid: {
        vertLines: { color: C.border },
        horzLines: { color: C.border },
      },
      rightPriceScale: { borderColor: C.border },
      timeScale: { borderColor: C.border, timeVisible: true },
      crosshair: { mode: 1 },
      width: priceEl.clientWidth || 600,
    };

    const priceChart = LightweightCharts.createChart(priceEl, {
      ...baseOptions,
      height: 320,
    });

    const candles = priceChart.addCandlestickSeries({
      upColor: C.bull,           // 台股紅漲 — Morandi 磚玫紅
      downColor: C.bear,         // 台股綠跌 — Morandi 苔綠
      borderUpColor: C.bull,
      borderDownColor: C.bear,
      wickUpColor: C.bull,
      wickDownColor: C.bear,
    });
    candles.setData(recent.map(d => ({
      time: d.date, open: d.o, high: d.h, low: d.l, close: d.c,
    })));

    const maColors = { ma5: C.warn, ma20: C.accent, ma60: C.diverge };
    for (const [key, color] of Object.entries(maColors)) {
      const series = priceChart.addLineSeries({
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: key.toUpperCase(),
      });
      series.setData(recent.filter(d => d[key] != null).map(d => ({ time: d.date, value: d[key] })));
    }

    // Bollinger upper/lower as dotted overlays. Middle band is skipped — it
    // coincides with ma20 which is already drawn above. Uses neutralDim (a step
    // darker than --neutral) so the bands recede behind the MA palette.
    const bbStyle = {
      color: C.neutralDim,
      lineWidth: 1,
      lineStyle: 2, // LineStyle.Dashed
      priceLineVisible: false,
      lastValueVisible: false,
    };
    const bbUpper = priceChart.addLineSeries({ ...bbStyle, title: 'BB Upper' });
    bbUpper.setData(recent.filter(d => d.bb_upper != null).map(d => ({ time: d.date, value: d.bb_upper })));
    const bbLower = priceChart.addLineSeries({ ...bbStyle, title: 'BB Lower' });
    bbLower.setData(recent.filter(d => d.bb_lower != null).map(d => ({ time: d.date, value: d.bb_lower })));

    priceChart.timeScale().fitContent();

    const macdChart = LightweightCharts.createChart(macdEl, {
      ...baseOptions,
      height: 180,
    });

    const histogram = macdChart.addHistogramSeries({
      priceLineVisible: false,
      title: 'OSC',
    });
    histogram.setData(recent.filter(d => d.osc != null).map(d => ({
      time: d.date,
      value: d.osc,
      color: d.osc >= 0 ? C.bull : C.bear,
    })));

    const difLine = macdChart.addLineSeries({ color: C.warn, lineWidth: 1, title: 'DIF' });
    difLine.setData(recent.filter(d => d.dif != null).map(d => ({ time: d.date, value: d.dif })));

    const macdLine = macdChart.addLineSeries({ color: C.accent, lineWidth: 1, title: 'MACD' });
    macdLine.setData(recent.filter(d => d.macd != null).map(d => ({ time: d.date, value: d.macd })));

    macdChart.timeScale().fitContent();

    let rsiChart = null;
    if (rsiEl) {
      rsiChart = LightweightCharts.createChart(rsiEl, {
        ...baseOptions,
        height: 160,
      });
      const rsiLine = rsiChart.addLineSeries({
        color: C.accent, lineWidth: 1, title: 'RSI(14)',
      });
      rsiLine.setData(recent.filter(d => d.rsi != null).map(d => ({
        time: d.date, value: d.rsi,
      })));
      // 70 / 30 reference lines
      rsiLine.createPriceLine({
        price: 70, color: C.bull, lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: '70',
      });
      rsiLine.createPriceLine({
        price: 30, color: C.bear, lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: '30',
      });
      rsiChart.timeScale().fitContent();
    }

    let bbChart = null;
    if (bbEl) {
      bbChart = LightweightCharts.createChart(bbEl, {
        ...baseOptions,
        height: 140,
      });
      const pbLine = bbChart.addLineSeries({
        color: C.accent, lineWidth: 1, title: '%B',
      });
      pbLine.setData(recent.filter(d => d.percent_b != null).map(d => ({
        time: d.date, value: d.percent_b,
      })));
      // %B reference lines: 0 / 0.2 / 0.5 / 0.8 / 1.0
      const refLines = [
        { p: 1.0, c: C.bull,    t: '1.0' },
        { p: 0.8, c: C.warn,    t: '0.8' },
        { p: 0.5, c: C.neutral, t: '0.5' },
        { p: 0.2, c: C.warn,    t: '0.2' },
        { p: 0.0, c: C.bear,    t: '0.0' },
      ];
      for (const r of refLines) {
        pbLine.createPriceLine({
          price: r.p, color: r.c, lineWidth: 1, lineStyle: 2,
          axisLabelVisible: true, title: r.t,
        });
      }
      bbChart.timeScale().fitContent();
    }

    let bandwidthChart = null;
    if (bwEl) {
      bandwidthChart = LightweightCharts.createChart(bwEl, {
        ...baseOptions,
        height: 110,
      });
      const bwHist = bandwidthChart.addHistogramSeries({
        color: C.neutral, priceLineVisible: false, title: 'Bandwidth',
      });
      bwHist.setData(recent.filter(d => d.bandwidth != null).map(d => ({
        time: d.date, value: d.bandwidth,
      })));
      // Global squeeze line + per-stock p20 line (drawn from latest available value)
      bwHist.createPriceLine({
        price: 0.10, color: C.warn, lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: '0.10 squeeze',
      });
      const lastP20 = [...recent].reverse().find(d => d.bandwidth_pct20 != null);
      if (lastP20) {
        bwHist.createPriceLine({
          price: lastP20.bandwidth_pct20, color: C.accent, lineWidth: 1, lineStyle: 1,
          axisLabelVisible: true, title: 'p20',
        });
      }
      bandwidthChart.timeScale().fitContent();
    }

    const subscribers = [];
    const syncTimes = (src, dst) => {
      const handler = r => { if (r) dst.timeScale().setVisibleLogicalRange(r); };
      src.timeScale().subscribeVisibleLogicalRangeChange(handler);
      subscribers.push({ src, handler });
    };
    const otherCharts = [macdChart, rsiChart, bbChart, bandwidthChart].filter(Boolean);
    for (const c of otherCharts) {
      syncTimes(priceChart, c);
      syncTimes(c, priceChart);
    }
    // Cross-sync between non-price charts too, so dragging any moves all
    for (let i = 0; i < otherCharts.length; i++) {
      for (let j = i + 1; j < otherCharts.length; j++) {
        syncTimes(otherCharts[i], otherCharts[j]);
        syncTimes(otherCharts[j], otherCharts[i]);
      }
    }

    const resize = () => {
      priceChart.applyOptions({ width: priceEl.clientWidth });
      macdChart.applyOptions({ width: macdEl.clientWidth });
      if (rsiChart && rsiEl) rsiChart.applyOptions({ width: rsiEl.clientWidth });
      if (bbChart && bbEl) bbChart.applyOptions({ width: bbEl.clientWidth });
      if (bandwidthChart && bwEl) bandwidthChart.applyOptions({ width: bwEl.clientWidth });
    };
    window.addEventListener('resize', resize);

    charts.set(stockId, { priceChart, macdChart, rsiChart, bbChart, bandwidthChart, resize });
  }

  function destroyCharts(stockId) {
    const entry = charts.get(stockId);
    if (!entry) return;
    window.removeEventListener('resize', entry.resize);
    try {
      entry.priceChart.remove();
      entry.macdChart.remove();
      if (entry.rsiChart) entry.rsiChart.remove();
      if (entry.bbChart) entry.bbChart.remove();
      if (entry.bandwidthChart) entry.bandwidthChart.remove();
    } catch {}
    charts.delete(stockId);
  }

  return { drawCharts, destroyCharts };
})();
