"""TiMOTION TC15S BLE 協議編碼/解碼

指令格式（App → 桌子）：8 bytes
  dd [flags] [cmd_hi] [cmd_lo] [param_hi] [param_lo] [00] [checksum]
  checksum = sum(bytes[2:7]) & 0x7F

回應格式（桌子 → App）：
  type 01 (14B): 帶即時高度 (mm)，移動中持續發送，INIT 後也會送一次
  type 02 (19B): idle 狀態，帶 limit/status
"""


def checksum(pkt: bytes) -> int:
    return sum(pkt[2:7]) & 0x7F


def make_cmd(
    cmd_hi: int,
    cmd_lo: int,
    param_hi: int = 0,
    param_lo: int = 0,
    flags: int = 0x00,
) -> bytes:
    pkt = bytes([0xDD, flags, cmd_hi, cmd_lo, param_hi, param_lo, 0x00, 0x00])
    return pkt[:7] + bytes([checksum(pkt)])


# --- 常用指令 ---

CMD_IDLE = make_cmd(0x40, 0x20)
CMD_STOP = make_cmd(0xC3, 0x00)
CMD_INIT = bytes([0xDD, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
CMD_UP = make_cmd(0x44, 0x20)
CMD_DOWN = make_cmd(0x42, 0x20)


def cmd_move_to(height_mm: int) -> bytes:
    return make_cmd(0x40, 0x28, (height_mm >> 8) & 0xFF, height_mm & 0xFF)


# --- 回應解析 ---

_TYPE01_LEN = 14
_TYPE02_LEN = 19


def parse_notify(data: bytes) -> dict | None:
    """解析桌子回傳的通知資料。

    Returns:
        Type 01: {"height": int}
        Type 02: {"limit": int, "status": int}
        None if unrecognized.
    """
    if len(data) < 8 or data[0] != 0x9D:
        return None
    if data[1] == 0x01 and len(data) >= _TYPE01_LEN:
        return {"height": (data[6] << 8) | data[7]}
    if data[1] == 0x02 and len(data) >= _TYPE02_LEN:
        return {
            "limit": (data[8] << 8) | data[9],
            "status": data[3],
        }
    return None


def parse_latest(data: bytes) -> dict | None:
    """Parse all 0x9D packets from a data chunk, merge results.

    Serial reads often contain multiple concatenated packets.
    Return merged dict: height from the latest Type 01,
    limit/status from the latest Type 02.
    """
    merged = {}
    i = 0
    while i < len(data):
        if data[i] == 0x9D and len(data) - i >= 8:
            parsed = parse_notify(data[i:])
            if parsed:
                merged.update(parsed)
            # skip past this packet to avoid re-matching
            if len(data) - i >= _TYPE02_LEN and data[i + 1] == 0x02:
                i += _TYPE02_LEN
            elif len(data) - i >= _TYPE01_LEN and data[i + 1] == 0x01:
                i += _TYPE01_LEN
            else:
                i += 8
        else:
            i += 1
    return merged or None
