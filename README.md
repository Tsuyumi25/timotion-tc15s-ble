# timotion-tc15s-ble — TiMOTION TC15S 升降桌 BLE 控制器

透過 ATM Dongle (Raytac MDBT50Q-RX-ATM) + Nordic UART Service (NUS) 控制升降桌高度。

適用於搭載 TiMOTION TC15S 控制盒（內建 BLE）的升降桌，桌腳型號不限。

### 為什麼用 Dongle 而不是主機藍牙？

升降桌需要持續 BLE 心跳維持連線。直接用 Linux BlueZ 藍牙堆疊常駐，實測很快就記憶體耗盡（OOM）——BlueZ / D-Bus 在持續 BLE notification 下有多個已知的 memory leak。ATM Dongle 走 USB serial 透傳，完全繞過 OS 藍牙堆疊，從根本上隔離問題。

## 需求

- Python 3.11+
- Raytac MDBT50Q-RX-ATM dongle
- Linux：需 Docker（生產部署）或直接 pip 執行

## 快速開始（Linux）

```bash
git clone https://github.com/Tsuyumi25/timotion-tc15s-ble.git
cd timotion-tc15s-ble
chmod +x install.sh
./install.sh
```

`install.sh` 會自動：
- 檢查 Python 版本、venv 支援、dialout 群組
- 建立 `.venv` 並安裝所有依賴（含 bleak 掃描）
- 建立 `config.yaml`
- 偵測 dongle 並寫入 `.env`（Docker 用）

遇到需要 `sudo` 的問題（如 `python3.x-venv` 未安裝、使用者不在 `dialout` 群組），會印出修正指令，修正後重跑即可。

## 設定 Dongle

插入 dongle 後執行：

```bash
source .venv/bin/activate
python setup_dongle.py
```

互動式引導：掃描附近 NUS 裝置 → 選擇 → 寫入 dongle flash → 儲存到 `config.yaml`。只需執行一次。

```
掃描附近的 BLE 裝置（5 秒）...

找到 1 個 NUS 裝置：

  [1] HC-  XXXX   (-64 dBm)  AA:BB:CC:DD:EE:FF

選擇裝置編號: 1

✅ 設定成功！Dongle 會自動連線 'HC-  XXXX'。
```

> 掃描需要 PC 內建藍牙網卡（與 dongle 無關）。若無藍牙網卡，會退回手動輸入模式——可用手機安裝 [nRF Connect](https://play.google.com/store/apps/details?id=no.nordicsemi.android.mcp) 查看桌子的 BLE 裝置名稱。

其他操作：

```bash
python setup_dongle.py --reset   # 恢復 dongle 出廠設定
```

## 啟動

### 直接執行

```bash
source .venv/bin/activate
python desk_server.py
```

### Docker 部署（僅 Linux）

Docker Desktop（macOS / Windows）不支援 USB 裝置透傳。非 Linux 請直接用 pip 執行。

`install.sh` 會自動偵測 dongle 並寫入 `.env`，之後直接啟動：

```bash
docker compose up -d --build
```

> dongle 路徑透過 `.env` 的 `DONGLE_DEVICE` 變數傳入 docker-compose，serial port 由環境變數 `SERIAL_PORT` 自動覆蓋，不需手動改 config.yaml。

查看日誌：

```bash
docker compose logs -f
```

## API

| 端點 | 方法 | 說明 |
|------|------|------|
| `/status` | GET | 查詢高度 (mm) 與連線狀態 |
| `/to/{height_mm}` | POST | 移到指定高度，範圍 620–1300 mm |
| `/stop` | POST | 緊急停止 |

範例：

```bash
curl http://localhost:8741/status
curl -X POST http://localhost:8741/to/750
curl -X POST http://localhost:8741/stop
```

## 測試面板

`panel.html` 是一個簡易的本機測試 UI，瀏覽器直接開啟即可（API 寫死 `localhost:8741`）。

## Windows / macOS

Docker 不可用，直接用 pip 執行：

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS
pip install .
python desk_server.py
```

Windows 長期運行可考慮 Task Scheduler 或 [NSSM](https://nssm.cc/)。

## 協議文檔

見 [docs/protocol.md](docs/protocol.md)

## 免責聲明

本專案透過 BLE 封包分析獨立完成逆向工程，目的是實現第三方軟體與 TiMOTION 升降桌的互操作性（interoperability）。本專案與 TiMOTION Technology Co., Ltd. 無任何關聯。

TiMOTION、TC15S 等為 TiMOTION Technology Co., Ltd. 的商標。

本軟體按「現狀」（AS IS）提供，不附帶任何保證。對因使用本軟體造成的硬體損壞或保固失效，作者不承擔責任。
