// Lightweight Charts wrapper. Draws price candles + MA overlays and a MACD subchart.
// Exposed via window.ChartLib for non-module load order.

window.ChartLib = (function () {
  const charts = new Map(); // id -> { priceChart, macdChart, rsiChart, bbChart, bandwidthChart, resize }

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

    const baseOptions = {
      layout: {
        background: { color: '#1a1d24' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#2a2e39' },
        horzLines: { color: '#2a2e39' },
      },
      rightPriceScale: { borderColor: '#2a2e39' },
      timeScale: { borderColor: '#2a2e39', timeVisible: true },
      crosshair: { mode: 1 },
      width: priceEl.clientWidth || 600,
    };

    const priceChart = LightweightCharts.createChart(priceEl, {
      ...baseOptions,
      height: 320,
    });

    const candles = priceChart.addCandlestickSeries({
      upColor: '#e34d4d',      // 台股紅漲
      downColor: '#26a69a',    // 台股綠跌
      borderUpColor: '#e34d4d',
      borderDownColor: '#26a69a',
      wickUpColor: '#e34d4d',
      wickDownColor: '#26a69a',
    });
    candles.setData(recent.map(d => ({
      time: d.date, open: d.o, high: d.h, low: d.l, close: d.c,
    })));

    const maColors = { ma5: '#ffb300', ma20: '#42a5f5', ma60: '#ab47bc' };
    for (const [key, color] of Object.entries(maColors)) {
      const series = priceChart.addLineSeries({
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: key.toUpperCase(),
      });
      series.setData(recent.filter(d => d[key] != null).map(d => ({ time: d.date, value: d[key] })));
    }

    // Bollinger upper/lower as dotted overlays. Middle band is skipped — it
    // coincides with ma20 which is already drawn above.
    const bbStyle = {
      color: '#90a4ae',
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
      color: d.osc >= 0 ? '#e34d4d' : '#26a69a',
    })));

    const difLine = macdChart.addLineSeries({ color: '#ffb300', lineWidth: 1, title: 'DIF' });
    difLine.setData(recent.filter(d => d.dif != null).map(d => ({ time: d.date, value: d.dif })));

    const macdLine = macdChart.addLineSeries({ color: '#42a5f5', lineWidth: 1, title: 'MACD' });
    macdLine.setData(recent.filter(d => d.macd != null).map(d => ({ time: d.date, value: d.macd })));

    macdChart.timeScale().fitContent();

    let rsiChart = null;
    if (rsiEl) {
      rsiChart = LightweightCharts.createChart(rsiEl, {
        ...baseOptions,
        height: 160,
      });
      const rsiLine = rsiChart.addLineSeries({
        color: '#42a5f5', lineWidth: 1, title: 'RSI(14)',
      });
      rsiLine.setData(recent.filter(d => d.rsi != null).map(d => ({
        time: d.date, value: d.rsi,
      })));
      // 70 / 30 reference lines
      rsiLine.createPriceLine({
        price: 70, color: '#e34d4d', lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: '70',
      });
      rsiLine.createPriceLine({
        price: 30, color: '#26a69a', lineWidth: 1, lineStyle: 2,
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
        color: '#42a5f5', lineWidth: 1, title: '%B',
      });
      pbLine.setData(recent.filter(d => d.percent_b != null).map(d => ({
        time: d.date, value: d.percent_b,
      })));
      // %B reference lines: 0 / 0.2 / 0.5 / 0.8 / 1.0
      const refLines = [
        { p: 1.0, c: '#e34d4d', t: '1.0' },
        { p: 0.8, c: '#ffb84d', t: '0.8' },
        { p: 0.5, c: '#7e8a9a', t: '0.5' },
        { p: 0.2, c: '#ffb84d', t: '0.2' },
        { p: 0.0, c: '#26a69a', t: '0.0' },
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
        color: '#90a4ae', priceLineVisible: false, title: 'Bandwidth',
      });
      bwHist.setData(recent.filter(d => d.bandwidth != null).map(d => ({
        time: d.date, value: d.bandwidth,
      })));
      // Global squeeze line + per-stock p20 line (drawn from latest available value)
      bwHist.createPriceLine({
        price: 0.10, color: '#ffb84d', lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: '0.10 squeeze',
      });
      const lastP20 = [...recent].reverse().find(d => d.bandwidth_pct20 != null);
      if (lastP20) {
        bwHist.createPriceLine({
          price: lastP20.bandwidth_pct20, color: '#5fa8ff', lineWidth: 1, lineStyle: 1,
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
