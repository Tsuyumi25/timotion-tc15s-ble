# timotion-ble

TiMOTION TC15S 升降桌 BLE 控制器。透過 ATM Dongle (Raytac MDBT50Q-RX-ATM) + Nordic UART Service (NUS) 控制升降桌高度。

適用於搭載 TiMOTION TC15S 控制盒（內建 BLE）的升降桌，桌腳型號不限。

## 需求

- Python 3.11+
- Raytac MDBT50Q-RX-ATM dongle

## 設定 Dongle

```bash
cp config.example.yaml config.yaml
pip install ".[setup]"
python setup_dongle.py
```

互動式引導：自動掃描附近的 NUS 裝置 → 選擇 → 寫入 dongle flash → 儲存到 `config.yaml`。只需執行一次。

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

## 啟動 Server

```bash
pip install .
python desk_server.py
```

API：
- `GET  /status` — 查詢高度與連線狀態
- `POST /to/{height_mm}` — 移到指定高度 (mm)
- `POST /stop` — 緊急停止

## Docker（僅 Linux）

Docker Desktop（macOS / Windows）不支援 USB 裝置透傳，非 Linux 請直接用 pip 安裝。

```bash
# 1. 先在 host 完成 dongle 設定（見上方）
# 2. 查詢 dongle 的穩定路徑
ls -l /dev/serial/by-id/

# 3. 編輯 docker-compose.yml，將 devices 改為實際路徑
# 4. config.yaml 設定 serial_port: /dev/ttyDONGLE
docker compose up -d
```

## 協議文檔

見 [docs/protocol.md](docs/protocol.md)

## 免責聲明

本專案透過 BLE 封包分析獨立完成逆向工程，目的是實現第三方軟體與 TiMOTION 升降桌的互操作性（interoperability）。本專案與 TiMOTION Technology Co., Ltd. 無任何關聯。

TiMOTION、TC15S 等為 TiMOTION Technology Co., Ltd. 的商標。

本軟體按「現狀」（AS IS）提供，不附帶任何保證。對因使用本軟體造成的硬體損壞或保固失效，作者不承擔責任。
