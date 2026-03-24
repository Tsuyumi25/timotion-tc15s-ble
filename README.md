# timotion-tc15s-ble — TiMOTION TC15S 升降桌 BLE 控制器

透過 ATM Dongle (Raytac MDBT50Q-RX-ATM) + Nordic UART Service (NUS) 控制升降桌高度。

適用於搭載 TiMOTION TC15S 控制盒（內建 BLE）的升降桌，桌腳型號不限。

### 為什麼用 Dongle 而不是主機藍牙？

升降桌需要持續 BLE 心跳維持連線。直接用 Linux BlueZ 藍牙堆疊常駐，實測很快就記憶體耗盡（OOM）——BlueZ / D-Bus 在持續 BLE notification 下有多個已知的 memory leak。ATM Dongle 走 USB serial 透傳，完全繞過 OS 藍牙堆疊，從根本上隔離問題。

## 需求

- Python 3.11+
- Raytac MDBT50Q-RX-ATM dongle
- Linux：需 Docker（生產部署）或直接 pip 執行

## 部署

### 共通步驟

所有平台都需要先配對 dongle：

```bash
git clone https://github.com/Tsuyumi25/timotion-tc15s-ble.git
cd timotion-tc15s-ble
./install.sh    # 環境檢查 + 安裝 + 配對 dongle（一條龍）
```

`install.sh` 會自動：
- 檢查 Python 版本、venv 支援、dialout 群組
- 建立 `.venv` 並安裝所有依賴（含 bleak 掃描）
- 建立 `config.yaml`
- 檢查 `/dev/ttyDONGLE`，若不存在則偵測 dongle VID:PID 並提示 udev rule 設定指令
- 執行 `setup_dongle.py` 配對 dongle

### Linux — Docker（推薦）

```bash
./install.sh          # 配對 dongle + 環境設定
# 按提示設定 udev rule（如果還沒有）
docker compose up -d  # 啟動（image 從 GHCR 拉取）
python3 cleanup.py    # （可選）清理原始碼，只留部署所需檔案
```

> Docker 部署需要 `/dev/ttyDONGLE` symlink（由 udev rule 建立）。`install.sh` 會偵測 dongle 並提示對應的 udev 指令。

查看日誌：

```bash
docker compose logs -f
```

### Linux — NixOS

```bash
./install.sh    # 配對 dongle，記下 DESK_NAME 和 VID:PID
```

然後在 NixOS 設定中加入（不需要 config.yaml 和 docker-compose.yml）：

```nix
# udev rule（tty symlink + USB 權限，後者讓 container 能 reset dongle）
services.udev.extraRules = ''
  SUBSYSTEM=="tty", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="521a", SYMLINK+="ttyDONGLE", MODE="0666"
  SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="521a", MODE="0666"
'';

# Container
virtualisation.oci-containers.containers.desk = {
  image = "ghcr.io/tsuyumi25/timotion-tc15s-ble:latest";
  ports = [ "8741:8741" ];
  environment = {
    DESK_NAME = "HC-  XXXX";  # install.sh 配對時顯示的名稱
  };
  volumes = [
    "/dev/bus/usb:/dev/bus/usb"  # USB reset 用
  ];
  extraOptions = [
    "--name=desk"
    "--device=/dev/ttyDONGLE:/dev/ttyDONGLE"
  ];
};
```

```bash
sudo nixos-rebuild switch
```

### Linux — 直接執行

```bash
./install.sh            # 配對 dongle + 環境設定
source .venv/bin/activate
python desk_server.py
```

### Windows / macOS

Docker Desktop 不支援 USB 裝置透傳，直接用 pip 執行：

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS
pip install .
python setup_dongle.py        # 配對 dongle（只需一次）
python desk_server.py
```

Windows 長期運行可考慮 Task Scheduler 或 [NSSM](https://nssm.cc/)。

### 設定 Dongle

`setup_dongle.py`（由 `install.sh` 自動執行）互動式引導：掃描附近 NUS 裝置 → 選擇 → 寫入 dongle flash → 儲存到 `config.yaml`。只需執行一次。

```
掃描附近的 BLE 裝置（5 秒）...

找到 1 個 NUS 裝置：

  [1] HC-  XXXX   (-64 dBm)  AA:BB:CC:DD:EE:FF

選擇裝置編號: 1

✅ 設定成功！Dongle 會自動連線 'HC-  XXXX'。
```

> 掃描需要 PC 內建藍牙網卡（與 dongle 無關）。若無藍牙網卡，會退回手動輸入模式——可用手機安裝 [nRF Connect](https://play.google.com/store/apps/details?id=no.nordicsemi.android.mcp) 查看桌子的 BLE 裝置名稱。

```bash
python setup_dongle.py --reset   # 恢復 dongle 出廠設定
```

### 設定優先順序

所有設定支援環境變數覆蓋 config.yaml，方便 NixOS 等宣告式系統使用：

| 設定 | 環境變數 | config.yaml | 預設值 |
|------|---------|-------------|--------|
| Serial port | `SERIAL_PORT` | — | `/dev/ttyDONGLE` |
| HTTP port | `HTTP_PORT` | `server.port` | `8741` |
| 桌子名稱 | `DESK_NAME` | `desk.name` | — |

### 疑難排解

- **容器啟動後卡在「探測連線狀態」或「開始掃描」**：server 會自動在掃描超時（30 秒）後重試，連續失敗 3 次會嘗試透過 sysfs 重設 USB dongle。如果自動重設無效，手動拔插 USB dongle 再重啟容器。
- **連線正常但偶爾斷線**：dongle 的 BLE 信號範圍有限（RSSI threshold 預設 -65dBm），確保 dongle 與桌子距離在 2 公尺內。server 內建 watchdog，超過 10 秒無回應會自動觸發重連。

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

`panel.html` 是一個簡易的測試 UI，瀏覽器直接開啟即可。頂部的輸入框可修改 API 位址（預設 `http://localhost:8741`）。

## 協議文檔

見 [docs/protocol.md](docs/protocol.md)

## 免責聲明

本專案透過 BLE 封包分析獨立完成逆向工程，目的是實現第三方軟體與 TiMOTION 升降桌的互操作性（interoperability）。本專案與 TiMOTION Technology Co., Ltd. 無任何關聯。

TiMOTION、TC15S 等為 TiMOTION Technology Co., Ltd. 的商標。

本軟體按「現狀」（AS IS）提供，不附帶任何保證。對因使用本軟體造成的硬體損壞或保固失效，作者不承擔責任。
