"""All thresholds, paths, endpoints in one place."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
STOCKS_DIR = DATA_DIR / "stocks"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
INDEX_FILE = DATA_DIR / "index.json"
META_FILE = DATA_DIR / "meta.json"

RULE_VERSION = "v1.3.0"
SCHEMA_VERSION = 1

TWSE_ENDPOINT = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TWSE_OPENAPI_STOCK_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
REQUEST_DELAY_SEC = 3.0
RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 5
RETRY_MAX_WAIT = 60

WARMUP_MONTHS = 18
# Must be >= longest MA window (240) + buffer, otherwise re-runs that read
# JSON back as the starting point will lose enough warmup to compute MA240.
HISTORY_KEEP_DAYS = 280

MA_PERIODS = [5, 10, 20, 60, 120, 240]
EMA_FAST = 12
EMA_SLOW = 26
MACD_SIGNAL = 9

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_NUMB_BARS = 3              # min consecutive bars in OB/OS zone to count as 鈍化
RSI_NUMB_PRICE_LOOKBACK = 5    # close must be new high/low across this window
RSI_PULLBACK_LOW = 50          # long-entry RSI upper bound (30 <= rsi <= 50)
RSI_BOUNCE_HIGH = 50           # short-entry RSI lower bound (50 <= rsi <= 70)

# Bollinger Bands (see plan: bollinger-bands-expressive-lynx.md)
BB_PERIOD = 20
BB_STD_MULT = 2.0
BB_STD_DDOF = 0                # population std — matches TradingView / 多數券商
BB_PERCENT_B_HIGH = 0.80
BB_PERCENT_B_LOW = 0.20
BB_BANDWIDTH_SQUEEZE = 0.10
BB_BANDWIDTH_EXTREME = 0.03

# Price-Volume relationship (see plan: bollinger-bands-expressive-lynx.md Part C)
PV_FLAT_PRICE_PCT = 0.005      # |Δprice%| < 0.5% → 價平
PV_FLAT_VOLUME_PCT = 0.20      # |Δvolume%| < 20% → 量平
PV_HOLIDAY_SPIKE_PCT = 2.0     # volume > +200% 且當日近價平 → 視為長假效應,壓制 alert
MARKET_PHASE_RETURN_LOOKBACK = 20    # 階段判定用的累積報酬窗
MARKET_PHASE_BIG_MOVE_PCT = 0.15     # 20 日報酬 ≥ ±15% → 大漲後 / 大跌後
MARKET_PHASE_NEW_TREND_BARS = 5      # MA trend 翻轉後 N 個交易日內視為「初期」

WATCHLIST_MAX_STOCKS = 30      # frontend addStock guard; backend doesn't enforce

RETRY_MAX_PASSES = 2           # build_dataset retries failures up to N extra passes
RETRY_BACKOFF_SEC = 60

# Thresholds (see plan: ma-macd-deep-duckling.md)
MA_CLUSTER_PCT = 0.015        # 1.5%
MA_CLUSTER_DAYS = 5
MA_SPREAD_PCT = 0.030         # 3%
MA_SLOPE_LOOKBACK = 3
MA_CROSS_TREND_LOOKBACK = 5
OSC_TREND_BARS = 3
OSC_STRONG_BARS = 5
DIVERGENCE_LOOKBACK = 60
DIVERGENCE_MIN_PEAK_GAP = 10
DIVERGENCE_PRICE_PCT = 0.02   # 2%
PEAK_PROMINENCE_PCT = 0.01    # 1%

INACTIVE_AFTER_MISSING_DAYS = 5
