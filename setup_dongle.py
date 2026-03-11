"""ATM Dongle 互動式設定 — 掃描附近 BLE 裝置，選擇後寫入 dongle flash + config.yaml

流程：
  1. bleak 掃描附近的 NUS 裝置（用 PC 內建藍牙，與 dongle 無關）
  2. 列出結果讓用戶選擇
  3. 將選中的名稱寫入 dongle flash（AT+NAME + AT+RESET）
  4. 儲存到 config.yaml

如果 bleak 未安裝，退回手動輸入模式。
設定完成後 dongle 每次插入會自動掃描並連線。

用法：
  python setup_dongle.py              # 互動式設定
  python setup_dongle.py --reset      # 恢復出廠設定
"""

import sys
import io
import time
import asyncio
from pathlib import Path

import serial
import serial.tools.list_ports
import yaml

from timotion.transport import find_dongle_port, DEFAULT_RSSI_THRESHOLD

CONFIG_PATH = Path(__file__).parent / "config.yaml"

def _init_stdout():
    """Windows 終端 UTF-8 相容（避免 UnicodeEncodeError）"""
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RSSI_THRESHOLD = DEFAULT_RSSI_THRESHOLD


# --- BLE Scan ---

async def _scan_nus(timeout: float = 5.0) -> list[dict]:
    from bleak import BleakScanner

    print(f"掃描附近的 BLE 裝置（{timeout:.0f} 秒）...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = []
    for device, adv in devices.values():
        uuids = [str(u).lower() for u in (adv.service_uuids or [])]
        if NUS_SERVICE_UUID in uuids and device.name:
            results.append({
                "name": device.name,
                "address": device.address,
                "rssi": adv.rssi,
            })
    results.sort(key=lambda d: d["rssi"], reverse=True)
    return results


def scan_and_pick() -> str | None:
    """掃描 NUS 裝置並讓用戶選擇。返回裝置名稱或 None。"""
    try:
        devices = asyncio.run(_scan_nus())
    except Exception as e:
        print(f"掃描失敗: {e}")
        return None

    if not devices:
        print("未找到任何 NUS 裝置。確認桌子已開啟電源。")
        return None

    print(f"\n找到 {len(devices)} 個 NUS 裝置：\n")
    for i, d in enumerate(devices, 1):
        print(f"  [{i}] {d['name']:<20s} ({d['rssi']} dBm)  {d['address']}")

    print()
    while True:
        ans = input(f"選擇裝置編號，或 Enter 取消: ").strip()
        if not ans:
            return None
        try:
            idx = int(ans) - 1
            if 0 <= idx < len(devices):
                return devices[idx]["name"]
        except ValueError:
            pass
        print("輸入無效，請重試。")


def manual_input() -> str | None:
    """手動輸入 BLE 裝置名稱。"""
    print("請用 nRF Connect 等 app 查看桌子的 BLE 裝置名稱，然後輸入。")
    name = input("BLE 裝置名稱: ").strip()
    return name or None


# --- Config ---

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_desk_name(name: str):
    config = load_config()
    if "desk" not in config:
        config["desk"] = {}
    config["desk"]["name"] = name
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_config_name() -> str | None:
    return (load_config().get("desk") or {}).get("name")


# --- Dongle Serial ---

find_dongle = find_dongle_port


def at_cmd(ser: serial.Serial, cmd: str, delay: float = 0.3) -> bytes:
    ser.reset_input_buffer()
    ser.write(cmd.encode())
    time.sleep(delay)
    return ser.read(500)


def flash_name(ser: serial.Serial) -> str:
    return at_cmd(ser, "AT?NAME").decode(errors="replace").strip()


def flash_rssi(ser: serial.Serial) -> str:
    return at_cmd(ser, "AT?RSSITHRESHOLD").decode(errors="replace").strip()


def write_to_dongle(ser: serial.Serial, desk_name: str, port: str) -> bool:
    """寫入名稱和 RSSI 到 dongle flash。成功返回 True。"""
    current_name = flash_name(ser)
    current_rssi = flash_rssi(ser)
    needs_save = False

    if desk_name not in current_name:
        print(f"\n設定名稱: '{desk_name}'...")
        resp = at_cmd(ser, f"AT+NAME{desk_name}")
        print(f"  回應: {resp.decode(errors='replace').strip()}")
        needs_save = True

    if str(RSSI_THRESHOLD) not in current_rssi:
        print(f"設定 RSSI threshold: {RSSI_THRESHOLD}...")
        resp = at_cmd(ser, f"AT+RSSITHRESHOLD{RSSI_THRESHOLD}")
        resp_text = resp.decode(errors="replace").strip()
        if "Canceled" in resp_text:
            print(f"  ❌ RSSI 被拒絕: {resp_text}")
            return False
        print(f"  回應: {resp_text}")
        needs_save = True

    if not needs_save:
        print("\nFlash 設定已正確，無需變更。")
        return True

    print("\n儲存到 flash (AT+RESET)... dongle 將重啟")
    try:
        ser.write(b"AT+RESET")
    except Exception:
        pass
    try:
        ser.close()
    except Exception:
        pass

    print("等待 dongle 重啟...")
    time.sleep(5)
    ser_new = serial.Serial(port, baudrate=115200, timeout=1)
    time.sleep(1)
    ser_new.reset_input_buffer()

    # 驗證
    print(f"\n--- 驗證 Flash ---")
    name_v = flash_name(ser_new)
    rssi_v = flash_rssi(ser_new)
    print(f"  Name: [{name_v}]")
    print(f"  RSSI: [{rssi_v}]")
    ser_new.close()

    return desk_name in name_v and str(RSSI_THRESHOLD) in rssi_v


def factory_reset(ser: serial.Serial):
    """恢復出廠設定 (AT+DEFAULT)。"""
    print("恢復出廠設定...")
    resp = at_cmd(ser, "AT+DEFAULT", delay=1.0)
    print(f"  回應: {resp.decode(errors='replace').strip()}")
    ser.close()

    # 清除 config.yaml 中的 desk.name
    config = load_config()
    if "desk" in config:
        config["desk"]["name"] = None
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print("已清除 config.yaml 中的 desk.name。")
    print("✅ 已恢復出廠設定。")


# --- Main ---

def main():
    _init_stdout()

    # --reset: 恢復出廠設定
    if "--reset" in sys.argv:
        port = find_dongle()
        if not port:
            print("找不到 dongle。")
            return
        ser = serial.Serial(port, baudrate=115200, timeout=1)
        time.sleep(1)
        ser.reset_input_buffer()
        factory_reset(ser)
        return

    # 檢查 config 現有設定
    config_name = get_config_name()
    desk_name = None

    if config_name:
        print(f"config.yaml 已設定: '{config_name}'")
        ans = input("要重新設定嗎？(y/N): ").strip().lower()
        if ans != "y":
            return

    # 掃描或手動輸入
    try:
        import bleak  # noqa: F401
        has_bleak = True
    except ImportError:
        has_bleak = False

    if has_bleak:
        desk_name = scan_and_pick()
        if not desk_name:
            ans = input("要手動輸入名稱嗎？(y/N): ").strip().lower()
            if ans == "y":
                desk_name = manual_input()
    else:
        print("提示: 安裝 bleak 可自動掃描裝置 (pip install bleak)")
        desk_name = manual_input()

    if not desk_name:
        print("取消。")
        return

    # 開啟 dongle
    port = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else find_dongle()
    if not port:
        print("找不到 dongle。手動指定: python setup_dongle.py COM6")
        return

    print(f"\n開啟 {port}...")
    ser = serial.Serial(port, baudrate=115200, timeout=1)
    time.sleep(1)
    ser.reset_input_buffer()

    # 寫入 flash
    if write_to_dongle(ser, desk_name, port):
        save_desk_name(desk_name)
        print(f"\n✅ 設定成功！Dongle 會自動連線 '{desk_name}'。")
        print(f"   已寫入 config.yaml。")
    else:
        print(f"\n❌ 設定失敗，未更新 config.yaml。")

    try:
        ser.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
