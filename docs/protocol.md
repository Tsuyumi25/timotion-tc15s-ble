# TiMOTION TC15S BLE 協議

## 硬體資訊

- **控制盒：** TiMOTION TC15S（Z73Q = SPM-73Q 電源模組；BLE 由 Spec Code 控制板欄位決定：3 或 5 = 內建藍牙）
- **BLE 晶片：** Nordic Semiconductor nRF 系列
- **BLE 裝置名：** 因品牌而異（如 `HC-  XXXX`）
- **MAC：** 因裝置而異
- **Service：** Nordic UART Service (NUS)

## Nordic UART Service

| Characteristic | UUID | 用途 |
|----------------|------|------|
| RX（寫入） | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | 發指令給桌子 |
| TX（通知） | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | 桌子回傳資料 |

## 指令格式（App → 桌子）：8 bytes

```
dd [flags] [cmd_hi] [cmd_lo] [param_hi] [param_lo] [00] [checksum]
```

- Header 固定 `0xDD`
- Checksum = `sum(bytes[2:7]) & 0x7F`

### 指令表

| 指令 | Bytes | 說明 |
|------|-------|------|
| IDLE | `dd 00 40 20 00 00 00 60` | 心跳 / 查詢狀態 |
| MANUAL_DOWN | `dd 00 42 20 00 00 00 62` | 手動下降（按住重複發送） |
| MANUAL_UP | `dd 00 44 20 00 00 00 64` | 手動上升 |
| MOVE_TO | `dd 00 40 28 HH LL 00 CC` | 移動到指定高度 HHLL (mm) |
| SET_PRESET_N | `dd 00 40 3N HH LL 00 CC` | 設定預設 N (1-4) |
| STOP | `dd 00 c3 00 00 00 00 43` | 停止移動 |
| INIT | `dd 01 00 00 00 00 00 00` | 初始化（連線後發一次） |

## 回應格式（桌子 → App）

### Type 02（19 bytes，完整狀態）

```
9d 02 [flags] [status] [b4] [b5] [height_hi] [height_lo]
[limit_hi] [limit_lo] [P1_hi] [P1_lo] [P2_hi] [P2_lo]
[P3_hi] [P3_lo] [P4_hi] [P4_lo] [checksum]
```

- Header 固定 `0x9D`
- 桌子每 ~150ms 回傳一次
- 高度單位：mm（680 = 68cm）

### 高度範圍

| 邊界 | 高度 (mm) |
|------|-----------|
| 下限 | 620 |
| 上限 | 1300 |

## 通訊流程

1. 連線後發 `INIT`
2. 桌子開始持續回傳 STATUS
3. 移動：持續發 `MOVE_TO` 直到到達目標
4. 停止：發 `STOP`
5. 閒置：持續發 `IDLE` 心跳保持連線

## 相容硬體

本協議適用於 TiMOTION TC15S 系列控制盒（內建 BLE），桌腳型號不影響協議。
