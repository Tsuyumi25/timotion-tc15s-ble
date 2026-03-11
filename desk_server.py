"""升降桌 HTTP 服務 (ATM Dongle serial transport)

HTTP API：
  GET  /status        查詢高度
  POST /to/{height}   移到指定高度 (mm)
  POST /stop          緊急停止
"""

import asyncio
import logging
import os
from pathlib import Path

import yaml
from aiohttp import web
import aiohttp_cors

from timotion.protocol import CMD_IDLE, CMD_INIT, CMD_STOP, cmd_move_to, parse_latest
from timotion.transport import ATMTransport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("desk")

# --- Config ---

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    defaults = {"server": {"port": 8741, "serial_port": None}}
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
HTTP_PORT: int = _cfg["server"]["port"]
SERIAL_PORT: str | None = os.environ.get("SERIAL_PORT") or _cfg["server"]["serial_port"]


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

    # -- Data callback (called from reader thread) --

    def _on_data(self, data: bytes):
        parsed = parse_latest(data)
        if not parsed:
            return
        if not self.last_status:
            self.last_status = parsed
        elif "limit" in parsed:
            # Type 02 (idle): height 永遠是 P1 preset，不可信
            # 保留 type 01 追蹤到的 height，只更新 metadata
            prev_height = self.last_status["height"]
            self.last_status = parsed
            self.last_status["height"] = prev_height
        else:
            # Type 01 (移動中): height 正確
            self.last_status["height"] = parsed["height"]
        if self._loop:
            self._loop.call_soon_threadsafe(self._status_event.set)

    # -- Connection lifecycle --

    async def connection_loop(self):
        """開啟 serial → probe/scan → init → heartbeat，斷線則重連。"""
        self._loop = asyncio.get_running_loop()

        while True:
            try:
                await self._connect()
                await self._heartbeat_until_disconnect()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("連線異常: %s", e)

            self._connected = False
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
            while not self.transport.connected:
                self.transport.write_raw(CMD_IDLE)
                await asyncio.sleep(0.5)

        self._connected = True
        self.last_status = None
        self.transport.write(CMD_INIT)
        self.transport.write(CMD_IDLE)

        # 等第一次狀態回傳
        self._status_event.clear()
        try:
            await asyncio.wait_for(self._status_event.wait(), 2.0)
        except asyncio.TimeoutError:
            pass

        if self.last_status:
            h = self.last_status["height"]
            log.info("已連線！高度 %dmm (%.1fcm)", h, h / 10)

    async def _heartbeat_until_disconnect(self):
        """每秒發 IDLE 心跳。Lock 被佔時跳過。"""
        while self._connected and self.transport.connected:
            if not self._lock.locked():
                self.transport.write(CMD_IDLE)
            await asyncio.sleep(1.0)

    # -- Commands --

    async def _send_stop(self):
        if not self._connected:
            return
        for _ in range(3):
            self.transport.write(CMD_STOP)
            await asyncio.sleep(0.02)
        self.transport.write(CMD_IDLE)

    async def move_to(self, height_mm: int) -> dict:
        if not self._connected:
            return {"error": "未連線"}

        async with self._lock:
            self._cancel.clear()
            cmd = cmd_move_to(height_mm)
            log.info("移動到 %dmm...", height_mm)

            WARMUP = 4

            try:
                for i in range(200):
                    if self._cancel.is_set():
                        log.info("移動被取消")
                        break
                    self.transport.write(cmd)
                    await asyncio.sleep(0.05)
                    if i >= WARMUP and self.last_status:
                        h = self.last_status["height"]
                        if abs(h - height_mm) <= 2:
                            break
            except Exception as e:
                log.error("移動異常: %s", e)
            finally:
                await self._send_stop()

            h = self.last_status["height"] if self.last_status else None
            log.info("到達 %smm", h)
            return {"ok": True, "height": h}

    async def stop(self) -> dict:
        self._cancel.set()
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

    # 檢查是否已執行 setup
    desk_name = (_cfg.get("desk") or {}).get("name")
    if not desk_name:
        log.warning("⚠ config.yaml 未設定 desk.name，請先執行: python setup_dongle.py")

    log.info("啟動 HTTP API on :%d", HTTP_PORT)
    log.info("  GET  /status")
    log.info("  POST /to/{mm}  /stop")
    try:
        web.run_app(app, host="0.0.0.0", port=HTTP_PORT, print=None)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
