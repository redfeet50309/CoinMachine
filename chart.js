// Lightweight Charts wrapper. Draws price candles + MA overlays and a MACD subchart.
// Exposed via window.ChartLib for non-module load order.

window.ChartLib = (function () {
  const charts = new Map(); // id -> { priceChart, macdChart, rsiChart, resize }

  function drawCharts(stockId, history) {
    destroyCharts(stockId);
    const priceEl = document.getElementById(`chart-price-${stockId}`);
    const macdEl = document.getElementById(`chart-macd-${stockId}`);
    const rsiEl = document.getElementById(`chart-rsi-${stockId}`);
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

    const syncTimes = (src, dst) => src.timeScale().subscribeVisibleLogicalRangeChange(r => {
      if (r) dst.timeScale().setVisibleLogicalRange(r);
    });
    syncTimes(priceChart, macdChart);
    syncTimes(macdChart, priceChart);
    if (rsiChart) {
      syncTimes(priceChart, rsiChart);
      syncTimes(rsiChart, priceChart);
      syncTimes(macdChart, rsiChart);
    }

    const resize = () => {
      priceChart.applyOptions({ width: priceEl.clientWidth });
      macdChart.applyOptions({ width: macdEl.clientWidth });
      if (rsiChart && rsiEl) rsiChart.applyOptions({ width: rsiEl.clientWidth });
    };
    window.addEventListener('resize', resize);

    charts.set(stockId, { priceChart, macdChart, rsiChart, resize });
  }

  function destroyCharts(stockId) {
    const entry = charts.get(stockId);
    if (!entry) return;
    window.removeEventListener('resize', entry.resize);
    try {
      entry.priceChart.remove();
      entry.macdChart.remove();
      if (entry.rsiChart) entry.rsiChart.remove();
    } catch {}
    charts.delete(stockId);
  }

  return { drawCharts, destroyCharts };
})();
