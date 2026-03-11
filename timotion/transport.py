"""ATM Dongle serial transport — 透過 USB serial 與 dongle 通訊

ATM dongle 連線後進入透傳模式：
- serial TX → NUS RX（桌子收指令）
- serial RX ← NUS TX（桌子回狀態）

實測發現：
- AT+DISCONNECT 在透傳模式下仍被 firmware 攔截，可正常斷線
- RSSI threshold 有效範圍約 -65 ~ -10，超出範圍靜默拒絕（回 "Parameter Change Canceled!!"）
- 設定存入 flash 後，重插 dongle 會自動掃描並連線
"""

import logging
import threading
import time

import serial
import serial.tools.list_ports

from timotion.protocol import CMD_IDLE

log = logging.getLogger("timotion")

# 桌子信號約 -64dBm，-65 是測試確認的有效最低值
DEFAULT_RSSI_THRESHOLD = -65


def find_dongle_port() -> str | None:
    """自動找 USB serial device（有 VID 的 = USB 裝置）"""
    for port in serial.tools.list_ports.comports():
        if port.vid is not None:
            return port.device
    return None


class ATMTransport:
    """ATM Dongle serial transport.

    States:
        IDLE       → dongle 閒置，可接受 AT 指令
        SCANNING   → 正在掃描 BLE 裝置
        CONNECTED  → 已連線，透傳模式（AT+ 指令仍被 firmware 攔截）
    """

    def __init__(self, port: str | None = None, baudrate: int = 115200):
        self.port_name = port or find_dongle_port()
        self.baudrate = baudrate
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self._connected = False
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._on_data: callable = None  # callback(data: bytes)

    @property
    def connected(self) -> bool:
        return self._connected

    def open(self):
        """Open serial port.

        Does not auto-detect connection state — use wait_auto_connect()
        or start_scan() after open.
        """
        if not self.port_name:
            raise RuntimeError("找不到 ATM dongle，請指定 port")
        log.info("開啟 %s (baud=%d)", self.port_name, self.baudrate)
        self._ser = serial.Serial(
            self.port_name, baudrate=self.baudrate, timeout=0.5
        )
        self._ser.reset_input_buffer()

    def probe_connection(self) -> bool:
        """Probe if dongle is already connected by sending IDLE command.

        If connected, the raw bytes pass through transparent mode to the desk,
        which responds with 0x9D status packets. If not connected, nothing happens.
        """
        if self._connected:
            return True
        log.info("探測連線狀態...")
        self._ser.reset_input_buffer()
        self._ser.write(CMD_IDLE)
        data = self._ser.read(512)
        if data and any(b == 0x9D for b in data):
            self._connected = True
            log.info("Dongle 已連線（桌子回應 IDLE）")
            self._start_reader()
            if self._on_data:
                self._on_data(data)
            return True
        log.info("未連線")
        return False

    def close(self):
        """Close serial port and stop all threads."""
        self._stop_reader()
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None
        self._connected = False

    def setup(self, rssi_threshold: int = DEFAULT_RSSI_THRESHOLD) -> bool:
        """Configure dongle AT settings. Only works when not connected."""
        if self._connected:
            log.warning("已連線狀態下無法設定 AT 參數")
            return False

        resp = self.at_cmd(f"AT+RSSITHRESHOLD{rssi_threshold}")
        resp_text = resp.decode(errors="replace")
        if "Canceled" in resp_text:
            log.warning(
                "RSSI %d 被拒絕（有效範圍約 -65 ~ -10）", rssi_threshold
            )
            return False

        actual = self.at_cmd("AT?RSSITHRESHOLD").decode(errors="replace").strip()
        log.info("RSSI threshold: %s", actual)
        return True

    def at_cmd(self, cmd: str, delay: float = 0.3) -> bytes:
        """Send AT command and read response.

        Works in IDLE/SCANNING state.
        AT+DISCONNECT also works in CONNECTED state (firmware intercepts).
        """
        with self._lock:
            self._ser.reset_input_buffer()
            self._ser.write(cmd.encode())
            time.sleep(delay)
            return self._ser.read(500)

    def start_scan(self):
        """Start scanning for the configured device.

        Dongle will auto-connect when it finds a name match,
        then enter transparent UART mode.
        """
        if self._connected:
            log.info("已連線，跳過掃描")
            return
        # probe 送的 raw bytes 會污染 AT parser，用一個 AT 命令重置
        self.at_cmd("AT", delay=0.1)
        log.info("開始掃描...")
        resp = self.at_cmd("AT+SCANNEWSTART")
        log.debug("scan: %s", resp.decode(errors="replace").strip())
        self._start_reader()

    def disconnect(self):
        """Disconnect BLE and return to AT command mode."""
        if not self._ser or not self._ser.is_open:
            return

        # Stop reader first so it doesn't consume the disconnect response
        self._stop_reader()

        try:
            self._ser.reset_input_buffer()
            self._ser.write(b"AT+DISCONNECT")
            time.sleep(0.5)
            resp = self._ser.read(200)
            text = resp.decode(errors="replace").strip()
            if text:
                log.info("斷線: %s", text)
        except Exception as e:
            log.error("斷線失敗: %s", e)

        self._connected = False

    def write(self, data: bytes):
        """Write raw bytes to BLE peripheral (transparent mode)."""
        if not self._connected or not self._ser:
            return
        with self._lock:
            try:
                self._ser.write(data)
            except Exception as e:
                log.error("寫入失敗: %s", e)
                self._connected = False

    def write_raw(self, data: bytes):
        """Write raw bytes regardless of connection state (for probing)."""
        if not self._ser:
            return
        with self._lock:
            try:
                self._ser.write(data)
            except Exception:
                pass

    # -- internal --

    def _start_reader(self):
        """Start background reader thread."""
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._running = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()

    def _stop_reader(self):
        """Stop background reader thread."""
        self._running = False
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None

    def _reader_loop(self):
        """Read loop: detect connection state and forward desk data."""
        while self._running and self._ser and self._ser.is_open:
            try:
                data = self._ser.read(512)
            except Exception:
                break
            if not data:
                continue

            if any(b == 0x9D for b in data):
                if not self._connected:
                    self._connected = True
                    log.info("BLE 已連線（收到桌子回應）")
                log.debug("RX [%d]: %s", len(data), data.hex(' '))
                if self._on_data:
                    self._on_data(data)
