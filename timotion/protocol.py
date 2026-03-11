"""TiMOTION TC15S BLE 協議編碼/解碼

指令格式（App → 桌子）：8 bytes
  dd [flags] [cmd_hi] [cmd_lo] [param_hi] [param_lo] [00] [checksum]
  checksum = sum(bytes[2:7]) & 0x7F

回應格式（桌子 → App）：
  type 02 (19B): 9d 02 [flags] [status] [b4] [b5] [height_hi] [height_lo]
                 [limit_hi] [limit_lo] [P1-P4 各 2 bytes] [checksum]
  type 00 (11B), type 01 (14B): 也帶高度，但資訊較少
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


def cmd_set_preset(n: int, height_mm: int) -> bytes:
    """設定預設 N（1-4）的高度"""
    return make_cmd(0x40, 0x30 + n, (height_mm >> 8) & 0xFF, height_mm & 0xFF)


# --- 回應解析 ---


def parse_notify(data: bytes) -> dict | None:
    """解析桌子回傳的通知資料。

    Returns:
        dict with at least "height" key, or None if unrecognized.
    """
    if len(data) < 8 or data[0] != 0x9D:
        return None
    height = (data[6] << 8) | data[7]
    if data[1] == 0x02 and len(data) >= 19:
        return {
            "height": height,
            "limit": (data[8] << 8) | data[9],
            "P1": (data[10] << 8) | data[11],
            "P2": (data[12] << 8) | data[13],
            "P3": (data[14] << 8) | data[15],
            "P4": (data[16] << 8) | data[17],
            "status": data[3],
        }
    return {"height": height}


def parse_latest(data: bytes) -> dict | None:
    """Parse the last complete 0x9D packet from a data chunk.

    Serial reads often contain multiple concatenated 19-byte packets.
    We want the most recent status for real-time control.
    """
    last_idx = -1
    for i in range(len(data) - 1, -1, -1):
        if data[i] == 0x9D and len(data) - i >= 8:
            last_idx = i
            break
    if last_idx < 0:
        return None
    return parse_notify(data[last_idx:])
