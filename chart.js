// Lightweight Charts wrapper. Draws price candles + MA overlays and a MACD subchart.

const charts = new Map(); // id -> { price, macd }

export function drawCharts(stockId, history) {
  destroyCharts(stockId);
  const priceEl = document.getElementById(`chart-price-${stockId}`);
  const macdEl = document.getElementById(`chart-macd-${stockId}`);
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

  // Keep two charts' time axes synced
  const syncTimes = (src, dst) => src.timeScale().subscribeVisibleLogicalRangeChange(r => {
    if (r) dst.timeScale().setVisibleLogicalRange(r);
  });
  syncTimes(priceChart, macdChart);
  syncTimes(macdChart, priceChart);

  const resize = () => {
    priceChart.applyOptions({ width: priceEl.clientWidth });
    macdChart.applyOptions({ width: macdEl.clientWidth });
  };
  window.addEventListener('resize', resize);

  charts.set(stockId, { priceChart, macdChart, resize });
}

export function destroyCharts(stockId) {
  const entry = charts.get(stockId);
  if (!entry) return;
  window.removeEventListener('resize', entry.resize);
  try {
    entry.priceChart.remove();
    entry.macdChart.remove();
  } catch {}
  charts.delete(stockId);
}
