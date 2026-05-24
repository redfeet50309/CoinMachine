# TWSE / TPEx OpenAPI 資料源參考

開發新功能時用來查「哪個資料拿哪支 endpoint」。所有路徑都從官方 Swagger 文件提取，但**只有標記 `[已驗證]` 的真的打過 API 確認 schema**——新增使用前要先實打一次。

---

## 0. Quick Reference

| 來源 | Swagger UI | OpenAPI Spec | 總端點數 |
|---|---|---|---|
| TWSE | https://openapi.twse.com.tw/ | https://openapi.twse.com.tw/v1/swagger.json | **143** |
| TPEx | https://www.tpex.org.tw/openapi/ | https://www.tpex.org.tw/openapi/swagger.json | **225** |

兩邊 Swagger UI 都可以在瀏覽器直接 `Try it out`。

---

## 1. 目前已使用的端點

| Endpoint | 程式碼位置 | 用途 / 注意 |
|---|---|---|
| TWSE `/exchangeReport/STOCK_DAY` (legacy) | `fetch_twse.fetch_month` | 個股單月 OHLCV；ROC 民國年（`115/03/02`） |
| TWSE `/exchangeReport/STOCK_DAY_ALL` (OpenAPI) | `fetch_twse.fetch_twse_latest_all` | 全市場最新日批次；legacy 404 時 fallback |
| TPEx `/www/zh-tw/afterTrading/tradingStock` (legacy) | `fetch_twse.fetch_month` | 個股單月 OHLCV；**量單位是「張」需 ×1000** |
| TPEx `/openapi/v1/tpex_mainboard_daily_close_quotes` | `fetch_twse.fetch_tpex_latest_all` | 全市場最新日批次；**量單位是「股」不用 ×1000** |

---

## A. 除權息 / 還原權值

| 用途 | TWSE | TPEx |
|---|---|---|
| 股利分派基本資料 | `/opendata/t187ap45_L` | — |
| 除權息日資訊（個股） | — | `/tpex_exright_daily` |
| 除權息前後參考價 | — | `/tpex_exright_prepost` |

**Use case**：歷史價格還原權值，修正跨除權息日的 MA / MACD 跳空。README「Phase 3 計畫」已列。業界主流做法是同時存 `close` + `adj_close` 兩套（K 線顯示原始、指標計算用還原）。

---

## B. 三大法人 / 籌碼面

| 用途 | TWSE | TPEx |
|---|---|---|
| 全市場法人總表（日） | `/exchangeReport/BFI84U` | `/tpex_3insti_summary` |
| 個股法人買賣超（日） | `/exchangeReport/TWT38U` 附近（驗證前先打一次）| `/tpex_3insti_daily_trading` |
| 外資 / 陸資持股 | `/fund/MI_QFIIS_cat`、`/fund/MI_QFIIS_sort_20` | `/tpex_3insti_qfii`、`/tpex_3insti_qfii_industry`、`/tpex_3insti_qfii_trading` |
| 自營商 | （含在 BFI84U）| `/tpex_3insti_dealer_trading` |
| 法人個股交易明細 | — | `/tpex_3insti_trading` |

**可衍生訊號**：連 N 日法人買超 / 外資轉買轉賣 / 三大法人合計買賣超金額排行

**注意**：法人資料**常延後 1 個交易日**，22:00 跑批不一定能拿到當日。

---

## C. 融資融券 / 借券

| 用途 | TWSE | TPEx |
|---|---|---|
| 融資融券餘額 | `/exchangeReport/MI_MARGN` | `/tpex_mainboard_margin_balance` |
| 信用交易明細 | `/exchangeReport/BFT41U` | `/tpex_margin_trading_marginspot`、`/tpex_margin_trading_lend`、`/tpex_margin_trading_short_sell`、`/tpex_margin_trading_margin_used`、`/tpex_margin_trading_margin_mark`、`/tpex_margin_trading_term`、`/tpex_margin_trading_adjust` |
| 借券賣出 / SBL | `/SBL/TWT96U`、`/exchangeReport/TWTBAU1`、`/exchangeReport/TWTBAU2` | `/tpex_short_sell`、`/tpex_margin_sbl` |

**可衍生訊號**：融資餘額連 N 日增 + 股價跌 → 散戶套牢；借券賣出激增 → 看空訊號

---

## D. 基本面

| 用途 | TWSE | TPEx |
|---|---|---|
| 本益比 / 殖利率 / 股價淨值比（日）| `/exchangeReport/BWIBBU_d`、`/exchangeReport/BWIBBU_ALL` | `/tpex_mainboard_peratio_analysis` |
| 月營收（單月 / 累計）| `/opendata/t187ap05_L`、`/opendata/t187ap05_P` | `/mopsfin_t187ap05_O`、`/mopsfin_t187ap05_OA`、`/mopsfin_t187ap05_OB` |
| 季財報：綜合損益 | `/opendata/t187ap06_L_*`、`/opendata/t187ap06_X_*` | `/mopsfin_t187ap06_O_*`、`/mopsfin_t187ap06_U_*` |
| 季財報：資產負債 | `/opendata/t187ap07_L_*`、`/opendata/t187ap07_X_*` | `/mopsfin_t187ap07_O_*`、`/mopsfin_t187ap07_U_*` |

財報路徑的 `_*` 後綴對應產業類別：

| 後綴 | 產業 |
|---|---|
| `ci` | 一般業 |
| `fh` | 金控 |
| `ins` | 保險 |
| `bd` | 證券期貨 |
| `basi` | 銀行 |
| `mim` | 其他特殊業（百貨、化學等）|

**可衍生訊號**：PE > 產業均值 → 估值警示；月營收 YoY 衰退 + 股價漲 → 背離；殖利率異常變動

---

## E. 警示 / 處置 / 風控

| 用途 | TWSE | TPEx |
|---|---|---|
| 處置股 | `/announcement/punish` | `/tpex_disposal_information`、`/tpex_esb_disposal_information` |
| 注意股 / 警示股 | `/announcement/notetrans` | `/tpex_trading_warning_information`、`/tpex_trading_warning_note` |
| 暫停交易 / 終止上市櫃 | `/announcement/notice`、`/company/suspendListingCsvAndHtml` | `/tpex_ceil_non_trading` |

**可衍生功能**：卡片紅標標示「處置中」；LINE 推播抑制（被處置的個股不算進場訊號）。

---

## F. 大盤 / 指數 / ETF（補充）

| 用途 | TWSE | TPEx |
|---|---|---|
| 大盤統計 / 加權指數 | `/exchangeReport/MI_INDEX`、`/exchangeReport/MI_INDEX20`、`/exchangeReport/MI_INDEX4`、`/exchangeReport/FMTQIK` | `/tpex_index`、`/tpex_index_consti`、`/tpex_daily_trading_index` |
| 5 分鐘指數 | `/exchangeReport/MI_5MINS`、`/indicesReport/MI_5MINS_HIST` | — |
| 成分股 | `/indicesReport/TAI50I` (台灣 50) | `/tpex50_constituents`、`/tpex200_constituents`、`/tphd_constituents` |
| ETF | `/ETFReport/ETFRank` | — |
| 警示 / 處置統計 | — | `/tpex_esb_latest_statistics` |
| 量價排行 | — | `/tpex_volume_rank`、`/tpex_amount_rank` |

---

## G. 開發優先序建議

依「實作成本 vs 訊號價值」排：

| 優先 | 功能 | 主要端點 | 估計工 |
|---|---|---|---|
| **P1** | 除權息還原（解 MA 跳空）| A 類 | 半天 |
| **P1** | 法人買賣超 + 連 N 日訊號 | B 類 | 1 天 |
| **P1** | 處置 / 警示股紅標 + 推播抑制 | E 類 | 半天 |
| **P2** | 估值欄位（PE / 殖利率 / PB）| D 類 / `BWIBBU_d` | 半天 |
| **P2** | 融資餘額 vs 股價背離訊號 | C 類 | 1 天 |
| **P3** | 月營收 YoY / MoM 卡片 | D 類 / `t187ap05_*` | 1 天 |
| **P3** | 大盤同步 + 個股相對強弱 | F 類 / `MI_INDEX` | 1 天 |

---

## H. 實作須知（踩過的坑）

1. **Geo-block**：TWSE + TPEx 都擋非台灣 IP（CDN 回 404 / Cloudflare 530）。本機 / 台灣 VPS / self-hosted runner 才能跑。已知 GitHub Actions 美國 runner 跑不起來
2. **編碼**：JSON 都是 UTF-8。Windows PowerShell console (cp950) `print` 中文會亂碼，但實際存進 dict / JSON 的 byte 是正確的（`群聯` = `e7bea4e881af`）
3. **`---` 佔位符**：TPEx OpenAPI 在 illiquid 商品（特別是 bond ETF 如 00791B/00834B）的 OHLC 欄位放 `'---'` 或 `' ---'`。`_to_float` 已支援轉為 NaN，新函式裡 close=NaN 的 row 直接跳過
4. **欄位命名不一致**：
   | 來源 | 代號欄位 | 收盤欄位 | 量欄位 | 量單位 |
   |---|---|---|---|---|
   | TWSE OpenAPI | `Code` | `ClosingPrice` | `TradeVolume` | 股 |
   | TPEx OpenAPI | `SecuritiesCompanyCode` | `Close` | `TradingShares` | **股** |
   | TWSE legacy | (row[0]) | (row[6]) | (row[1]) | 股 |
   | TPEx legacy | (row[0]) | (row[6]) | (row[1]) | **張** (×1000) |
5. **ROC 民國年格式**：legacy 是 `115/03/02`、OpenAPI 是 `1150302`（不分隔）。`_roc_to_iso` 處理前者，OpenAPI 函式內 inline 切片處理後者
6. **Rate limit**：官方無明文規定。社群經驗 2–3 秒/request 安全。目前用 `REQUEST_DELAY_SEC = 3.0`
7. **歷史回查限制**：絕大多數 endpoint 只給「最新一日」或「指定日期單日」。要建歷史就靠每日累積寫到 `data/stocks/{id}.json`
8. **資料更新時間**：盤後 OHLCV 通常 17:00–18:00 更新完，22:00 跑批可拿到當日。**但法人資料常延後 1 個交易日**，新接 B 類 endpoint 時要驗證 date 欄位
9. **欄位 schema 沒人類友善對照**：TWSE 路徑用 `TWT38U`、`BFI84U` 這種代號，新增使用前**先打 API 看實際回傳的 keys**

---

## I. 驗證狀態

| 已實測 | Endpoint |
|---|---|
| ✓ | TWSE `STOCK_DAY_ALL`、`STOCK_DAY` (legacy) |
| ✓ | TPEx `tpex_mainboard_daily_close_quotes`、`tradingStock` (legacy) |

**其他所有端點**皆來自官方 Swagger 路徑清單，**新增使用前先打一次 API 確認 schema**。建議的驗證指令：

```powershell
# TWSE
curl -s "https://openapi.twse.com.tw/v1/<endpoint_path>" | python -m json.tool | Select-Object -First 30

# TPEx
curl -s "https://www.tpex.org.tw/openapi/v1/<endpoint_path>" | python -m json.tool | Select-Object -First 30
```

---

## J. 相關來源 / 進一步閱讀

- TWSE Swagger JSON: https://openapi.twse.com.tw/v1/swagger.json
- TPEx Swagger JSON: https://www.tpex.org.tw/openapi/swagger.json
- 社群 endpoint 映射（含 TAIFEX 期交所）：https://github.com/twjackysu/TWSEMCPServer
- MOPS 公開資訊觀測站（互補資料源，部分 TWSE / TPEx 沒有的）：https://mops.twse.com.tw/
