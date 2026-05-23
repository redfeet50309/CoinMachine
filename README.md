# CoinMachine

個人自用的台股技術指標追蹤網站。每晚 22:00 自動從 TWSE / TPEx 官方資料抓取自選股，計算 MA / MACD / RSI / 布林通道 / 量價關係，給出文字化判讀,並 push 一則 LINE 訊息彙整當日訊號。

**所有數據來自官方一手來源，公式透明可驗證。**

## 線上版

部署在 GitHub Pages（push 後 Actions 自動部署）：

- 主頁：`https://redfeet50309.github.io/CoinMachine/`
- 設定（PAT）：`https://redfeet50309.github.io/CoinMachine/settings.html`

## 功能

- **自選清單**：在頁面上直接新增/移除（最多 30 檔），同步到 repo
- **指標**：MA (5/10/20/60/120/240)、MACD (DIF/MACD/OSC, 12/26/9)
- **判讀**：
  - MA 多頭排列 / 空頭排列 / 盤整
  - 黃金交叉 / 死亡交叉（5/20 + 20-MA 斜率過濾）
  - 均線糾結 / 發散 / 向上發散 / 向下發散
  - MACD 零軸位置（多 / 空 / 分歧）
  - MACD 交叉強弱（零軸上下訊號強度不同）
  - 紅綠柱加速 / 減弱（連續 3 根趨勢）
  - 頂背離 / 底背離（近 60 日峰谷比對）
- **K 線圖**：點卡片展開後顯示近 90 日 K 線 + MA 5/20/60 + MACD 副圖
- **自動排程**：Windows Task Scheduler,週一到週五每晚 22:00 跑批(從本地電腦抓資料,自動 push 到 repo)
- **LINE 通知**:跑完後自動推一則彙整訊息(分注意 / 進場 / 空頭 / 無事件 4 類,連續日標「連N日」)

## 資料來源

| 來源 | 用途 |
|---|---|
| [TWSE 證交所](https://www.twse.com.tw/) — `/exchangeReport/STOCK_DAY` | 上市股票每日 OHLCV |
| [TPEx 櫃買中心](https://www.tpex.org.tw/) — `/www/zh-tw/afterTrading/tradingStock` | 上櫃股票每日 OHLCV |

公式都用台灣券商常見算法：
- MA = simple moving average (N 日)
- DIF = EMA(close, 12) − EMA(close, 26)，EMA 用 `adjust=False` 遞迴
- MACD = EMA(DIF, 9)
- OSC = DIF − MACD

## 量化閾值

| 概念 | 定義 |
|---|---|
| 均線糾結 | MA5/20/60 最大差距 < 收盤價 × 1.5%，持續 ≥ 5 交易日 |
| 均線發散 | 最大差距 > 收盤價 × 3% |
| 向上 / 向下發散 | 發散 + MA5 連續 3 日斜率為正 / 負 |
| MA 黃金交叉 | MA5 由下穿越 MA20，且 MA20 比 5 日前高 |
| MACD 強訊號 | DIF 上穿 MACD 且兩者 > 0（強多頭）；下穿且兩者 < 0（強空頭） |
| MACD 弱訊號 | 上述條件不在零軸正確側時 → 反彈 / 回檔 |
| 柱狀體加速 | OSC 連續 3 根同向遞增；連續 5 根標記強加速 |
| 頂 / 底背離 | 近 60 日內找峰谷，價差 ≥ 2%，峰間距 ≥ 10 交易日，DIF 反向變化 |

詳見 [scripts/config.py](scripts/config.py)。要調整閾值改這個檔。

## 專案結構

```
CoinMachine/
├── index.html              # 主頁
├── settings.html           # PAT 設定頁
├── styles.css
├── app.js                  # Alpine 主邏輯
├── api.js                  # fetch + GitHub Contents API
├── chart.js                # Lightweight Charts K 線
├── rules.js                # signal → CSS class
├── data/                   # Actions 產出，commit 回 repo
│   ├── watchlist.json      # 自選清單（前端會寫）
│   ├── index.json          # 全檔索引
│   ├── meta.json           # 跑批時間 / 失敗清單
│   └── stocks/{id}.json    # 每檔的最新指標 + 近 180 日歷史
├── scripts/                # Python 後端
│   ├── requirements.txt
│   ├── config.py           # 所有閾值集中
│   ├── fetch_twse.py       # TWSE / TPEx 抓取
│   ├── indicators.py       # MA / EMA / MACD / 背離
│   ├── analyze.py          # 規則判讀
│   └── build_dataset.py    # 主編排
├── tests/
│   └── test_indicators.py
└── .github/workflows/
    └── pages.yml                # GitHub Pages 部署 (網頁更新)
```

每晚 22:00 的資料抓取由本機 Windows Task Scheduler 觸發（GitHub Actions runner 在美國，TWSE / TPEx 對非台灣 IP 會 geo-block）。

## 本機開發

```bash
# 安裝依賴
pip install -r scripts/requirements.txt

# 跑跑看
python scripts/build_dataset.py            # 全清單
python scripts/build_dataset.py 2330 8299  # 指定股票

# 跑測試
pytest tests/

# 啟動本地網頁（從 repo root）
python -m http.server 8000
# 開 http://localhost:8000/
```

## 設定每晚 22:00 自動跑批 (Windows Task Scheduler)

TWSE 和 TPEx 都會把美國 IP 的請求 reject (HTTP 404 / Cloudflare 530),所以 cron 沒辦法跑在 GitHub Actions,要跑在台灣 IP — 也就是你的電腦。

一次性設定:

```powershell
# 從 PowerShell 在 repo 根目錄執行
.\scripts\register_task.ps1
```

這會註冊一個 Windows 排程任務 `CoinMachine-daily`,每週一到五 22:00 自動跑:
- 喚醒睡眠中的電腦
- 跑 `python scripts/build_dataset.py`
- 自動 `git push` 結果到 repo
- 推一則 LINE 訊息(若已設定 token,見下節)

驗證：

```powershell
# 立即測試一次
Start-ScheduledTask -TaskName 'CoinMachine-daily'

# 查看執行紀錄
Get-Content data\last_run.log -Tail 30
```

新增股票後想立刻看到資料（不等到 23:30），手動跑一次：

```powershell
.\scripts\run_local.ps1
```

要取消排程：

```powershell
Unregister-ScheduledTask -TaskName 'CoinMachine-daily' -Confirm:$false
```

> **電腦關機時跑不到**：23:30 時電腦如果是完全關機，當天不會跑。睡眠/休眠都可以被喚醒。如果想跨平台真正 always-on 的方案，可以考慮 self-hosted GitHub Actions runner（架在台灣的 VPS / Raspberry Pi）。

## 自選清單同步（PAT 流程）

純看資料不需要 PAT。要新增 / 移除股票才需要：

1. 到 [GitHub Settings → Fine-grained PAT](https://github.com/settings/tokens?type=beta)
2. Resource owner 選自己；Repository access 只勾 `CoinMachine`
3. Permissions → Contents: **Read and write**（其他保持 No access）
4. 複製 token，到 `settings.html` 貼上
5. 回主頁，新增 / 移除按鈕會 commit `data/watchlist.json` 進 repo
6. 新代號的資料會在下次 23:30 排程跑批時被抓進來；想立刻看就在本地跑 `.\scripts\run_local.ps1`

PAT 只存在你瀏覽器的 localStorage，沒有送任何伺服器。

## LINE 通知設定(可選)

每天 22:00 跑批完會 push 一則 LINE 訊息彙整全 watchlist 訊號。預設**未設定 token 時自動跳過**(不影響其他流程)。

### 一次性申請

1. 進 [LINE Developers Console](https://developers.line.biz/console/)
2. **Create Provider** → 取個人名稱即可
3. **Create Channel** → 選 **Messaging API**
4. **Basic settings** → 取得 **Channel access token (long-lived)**
5. **Messaging API tab** → 用手機 LINE 掃 QR code 把 bot 加為朋友
6. PowerShell 設使用者層級環境變數(persistent,所有 process 都能讀到):
   ```powershell
   [System.Environment]::SetEnvironmentVariable('LINE_CHANNEL_ACCESS_TOKEN', '貼上 token', 'User')
   ```
7. 開新 PowerShell session 驗證:
   ```powershell
   $env:LINE_CHANNEL_ACCESS_TOKEN  # 應顯示 token
   ```

### 預覽訊息 / dry-run

```powershell
py scripts/notify.py --dry-run
```
會把訊息印到 console、不真的推 LINE。可用 `--date=2026-05-22` 指定日期。

### 訊息格式

```
📊 CoinMachine 5/22(五) 收盤

━━━ ⚠ 注意 (2) ━━━
🔴 8299 群聯  +4.1%
   頂部警訊(連2日)
...

━━━ 📈 進場 (1) ━━━
🟢 8039 台虹  +8.6%
   布林 突破上軌 (強多)
...

🔗 詳情
https://redfeet50309.github.io/CoinMachine
```

採用 LINE Messaging API broadcast endpoint(推給 bot 所有 friends,個人 = 只有你)。
免費額度 200 則/月,個人用每天 1 則綽綽有餘。

連續日同訊號用 `data/notify_state.json` 追蹤(會 commit 進 repo),訊息會標「連N日」。
若某日 build 失敗、隔日重跑,連續計數會 reset 重新從 1 開始。

## 已知限制 / Phase 3 計畫

- **未還原除權息**:跨除權息日均線會有跳空(Phase 3 整合 MOPS 除權息資料)
- **僅支援台股**(TWSE + TPEx 上市上櫃)

## 免責聲明

本服務僅供研究參考，不構成投資建議。所有指標判讀都是程式機械化計算結果，不保證準確性或時效性。投資決策請自行判斷並承擔風險。
