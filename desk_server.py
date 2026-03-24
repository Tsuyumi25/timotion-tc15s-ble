"""升降桌 HTTP 服務 (ATM Dongle serial transport)

HTTP API：
  GET  /status        查詢高度
  POST /to/{height}   移到指定高度 (mm)
  POST /stop          緊急停止
"""

import asyncio
import logging
import os
import time
from pathlib import Path

import yaml
from aiohttp import web
import aiohttp_cors

from timotion.protocol import CMD_IDLE, CMD_INIT, CMD_STOP, cmd_move_to, parse_latest
from timotion.transport import ATMTransport, reset_usb_device

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("desk")

# --- Config ---

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    defaults = {"server": {"port": 8741}}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return defaults
    if "server" in user and isinstance(user["server"], dict):
        defaults["server"].update(user["server"])
    # 保留非 server 的區塊（如 desk.name）
    for k, v in user.items():
        if k != "server":
            defaults[k] = v
    return defaults


_cfg = _load_config()
SERIAL_PORT: str = os.environ.get("SERIAL_PORT", "/dev/ttyDONGLE")
HTTP_PORT: int = int(os.environ.get("HTTP_PORT", _cfg["server"]["port"]))
DESK_NAME: str | None = os.environ.get("DESK_NAME") or (_cfg.get("desk") or {}).get("name")

BLE_TIMEOUT = 10       # 秒，heartbeat 無回應視為斷線
SCAN_TIMEOUT = 30      # 秒，BLE 掃描超時
MAX_SCAN_RETRIES = 3   # 連續掃描失敗後觸發 USB reset


# --- Desk Controller (async, serial transport in thread) ---

class DeskController:
    def __init__(self, port: str | None = None):
        self.transport = ATMTransport(port=port)
        self.last_status: dict | None = None
        self._status_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._cancel = asyncio.Event()
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_time: float = 0

    @property
    def height(self) -> int | None:
        return self.last_status.get("height") if self.last_status else None

    async def _write(self, data: bytes):
        await asyncio.to_thread(self.transport.write, data)

    async def _write_raw(self, data: bytes):
        await asyncio.to_thread(self.transport.write_raw, data)

    # -- Data callback (called from reader thread) --

    def _on_data(self, data: bytes):
        parsed = parse_latest(data)
        if not parsed:
            return
        if "height" in parsed:
            if not self.last_status:
                self.last_status = {}
            self.last_status["height"] = parsed["height"]
        else:
            # Type 02: limit/status
            if not self.last_status:
                self.last_status = parsed
            else:
                self.last_status.update(parsed)
        if self._loop:
            self._loop.call_soon_threadsafe(self._status_event.set)

    # -- Connection lifecycle --

    async def connection_loop(self):
        """開啟 serial → probe/scan → init → heartbeat，斷線則重連。"""
        self._loop = asyncio.get_running_loop()
        scan_failures = 0

        while True:
            try:
                await self._connect()
                scan_failures = 0
                await self._heartbeat_until_disconnect()
            except TimeoutError as e:
                scan_failures += 1
                log.warning("掃描失敗 (%d/%d): %s", scan_failures, MAX_SCAN_RETRIES, e)
                if scan_failures >= MAX_SCAN_RETRIES:
                    log.warning("連續掃描失敗，嘗試重設 USB dongle...")
                    try:
                        await asyncio.to_thread(self.transport.close)
                    except Exception:
                        pass
                    port = self.transport.port_name
                    if port and await asyncio.to_thread(reset_usb_device, port):
                        log.info("USB 重設完成，重試連線...")
                    else:
                        log.error("USB 重設失敗，等待後重試...")
                    scan_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("連線異常: %s", e)

            self._connected = False
            try:
                await asyncio.to_thread(self.transport.close)
            except Exception:
                pass
            log.info("斷線，5 秒後重連...")
            await asyncio.sleep(5)

    async def _connect(self):
        """Open serial, probe existing BLE, fallback to scan, init."""
        await asyncio.to_thread(self.transport.open)
        self.transport._on_data = self._on_data

        connected = await asyncio.to_thread(self.transport.probe_connection)
        if not connected:
            await asyncio.to_thread(self.transport.start_scan)
            # 主動送 IDLE 觸發桌子回應，reader thread 偵測 0x9D → _connected
            deadline = asyncio.get_event_loop().time() + SCAN_TIMEOUT
            while not self.transport.connected:
                if asyncio.get_event_loop().time() > deadline:
                    raise TimeoutError(f"BLE 掃描超時 ({SCAN_TIMEOUT}s)")
                await self._write_raw(CMD_IDLE)
                await asyncio.sleep(0.5)

        self._connected = True
        self.last_status = None
        await self._write(CMD_INIT)
        await self._write(CMD_IDLE)

        # INIT 後桌子會依序回 Type 02 → Type 01（帶高度），等高度到達
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 2.0
        while loop.time() < deadline:
            self._status_event.clear()
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._status_event.wait(), remaining)
            except asyncio.TimeoutError:
                break
            if self.height is not None:
                break

        h = self.height
        if h is not None:
            log.info("已連線！高度 %dmm (%.1fcm)", h, h / 10)
        else:
            log.info("已連線！（高度待移動後取得）")

    async def _heartbeat_until_disconnect(self):
        """每秒發 IDLE 心跳。Lock 被佔或剛停止時跳過。"""
        while self._connected and self.transport.connected:
            now = asyncio.get_event_loop().time()
            if not self._lock.locked() and now - self._stop_time > 0.5:
                await self._write(CMD_IDLE)
            # watchdog：超過 BLE_TIMEOUT 秒沒收到桌子資料 → 視為斷線
            ldt = self.transport.last_data_time
            if ldt is not None and time.monotonic() - ldt > BLE_TIMEOUT:
                log.warning("桌子超過 %ds 無回應，視為斷線", BLE_TIMEOUT)
                break
            await asyncio.sleep(1.0)

    # -- Commands --

    async def _send_stop(self):
        if not self._connected:
            return
        for _ in range(5):
            await self._write(CMD_STOP)
            await asyncio.sleep(0.03)

    async def move_to(self, height_mm: int) -> dict:
        if not self._connected:
            return {"error": "未連線"}

        async with self._lock:
            self._cancel.clear()
            # 讓 event loop 跑兩輪，給同時到達的 stop() 機會執行
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            if self._cancel.is_set():
                h = self.height
                return {"ok": True, "height": h, "cancelled": True}

            cmd = cmd_move_to(height_mm)
            log.info("移動到 %dmm...", height_mm)

            WARMUP = 4

            cancelled = False
            try:
                for i in range(200):
                    if self._cancel.is_set():
                        log.info("移動被取消")
                        cancelled = True
                        break
                    await self._write(cmd)
                    await asyncio.sleep(0.05)
                    if i >= WARMUP and self.last_status:
                        h = self.last_status.get("height")
                        if h is not None and abs(h - height_mm) <= 2:
                            break
            except Exception as e:
                log.error("移動異常: %s", e)
            finally:
                await self._send_stop()

            h = self.height
            log.info("到達 %smm", h)
            return {"ok": True, "height": h, "cancelled": cancelled}

    async def stop(self) -> dict:
        self._cancel.set()
        self._stop_time = asyncio.get_event_loop().time()
        await self._send_stop()
        return {"ok": True}

    def get_status(self) -> dict:
        if not self._connected:
            return {"connected": False}
        return {"connected": True, **(self.last_status or {})}

    async def shutdown(self):
        """斷開 BLE 並關閉 serial port。"""
        self._connected = False
        try:
            await asyncio.to_thread(self.transport.disconnect)
        except Exception:
            pass
        try:
            self.transport.close()
        except Exception:
            pass


# --- HTTP API ---

desk = DeskController(port=SERIAL_PORT)


async def handle_status(request):
    return web.json_response(desk.get_status())


async def handle_move_to(request):
    height = int(request.match_info["height"])
    if not 620 <= height <= 1300:
        return web.json_response({"error": "高度須介於 620–1300 mm"}, status=400)
    return web.json_response(await desk.move_to(height))


async def handle_stop(request):
    return web.json_response(await desk.stop())


async def on_startup(app):
    app["ble"] = asyncio.create_task(desk.connection_loop())


async def on_cleanup(app):
    app["ble"].cancel()
    await desk.shutdown()


def main():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(allow_methods="*", allow_headers="*"),
    })
    cors.add(app.router.add_get("/status", handle_status))
    cors.add(app.router.add_post("/to/{height}", handle_move_to))
    cors.add(app.router.add_post("/stop", handle_stop))
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    if not DESK_NAME:
        log.warning("⚠ 未設定 desk name，請先執行 setup_dongle.py 或設定 DESK_NAME 環境變數")

    log.info("啟動 HTTP API on :%d", HTTP_PORT)
    log.info("  GET  /status")
    log.info("  POST /to/{mm}  /stop")
    try:
        web.run_app(app, host="0.0.0.0", port=HTTP_PORT, print=None, access_log=None)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
