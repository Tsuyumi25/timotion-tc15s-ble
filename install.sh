#!/usr/bin/env bash
# timotion-ble 環境檢查 + 安裝 + 配對腳本

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}▸${NC} $*"; }
ok()    { echo -e "${GREEN}✔${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "${RED}✘${NC} $*"; }
hint()  { echo -e "  ${YELLOW}→${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IS_NIXOS=false
[ -f /etc/NIXOS ] && IS_NIXOS=true

errors=0

# --- Python 版本 ---

info "檢查 Python..."
if ! command -v python3 &>/dev/null; then
    fail "找不到 python3"
    hint "sudo apt install python3"
    errors=$((errors + 1))
else
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_MINOR" -lt 11 ]; then
        fail "Python $PY_VER 太舊（需要 3.11+）"
        errors=$((errors + 1))
    else
        ok "Python $PY_VER"
    fi
fi

# --- venv 支援 ---

info "檢查 venv 支援..."
if python3 -m venv --help &>/dev/null; then
    ok "venv 可用"
else
    fail "python3-venv 未安裝"
    hint "sudo apt install python${PY_VER}-venv"
    errors=$((errors + 1))
fi

# --- Serial port 權限（Linux，非 NixOS） ---

if [ "$(uname)" = "Linux" ] && ! $IS_NIXOS; then
    info "檢查 dialout 群組..."
    if id -nG | grep -qw dialout; then
        ok "使用者已在 dialout 群組"
    else
        fail "使用者不在 dialout 群組（無法存取 serial port）"
        hint "sudo usermod -aG dialout $(whoami) && 重新登入"
        errors=$((errors + 1))
    fi
fi

# --- 前置檢查結果 ---

echo ""
if [ "$errors" -gt 0 ]; then
    fail "有 $errors 個問題需先修正，修正後重新執行 ./install.sh"
    exit 1
fi

# --- 建立 venv + 安裝 ---

if [ ! -d ".venv" ]; then
    info "建立 venv..."
    python3 -m venv .venv
    ok "已建立 .venv"
else
    ok ".venv 已存在"
fi

source .venv/bin/activate

# 確保 pip 存在（uv 建的 venv 不含 pip）
if ! command -v pip &>/dev/null; then
    python3 -m ensurepip --upgrade 2>/dev/null
fi

info "安裝依賴..."
python3 -m pip install -q ".[setup]"
ok "已安裝（含 bleak 掃描支援）"

# --- config.yaml ---

if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
    ok "已建立 config.yaml（從 config.example.yaml）"
else
    ok "config.yaml 已存在"
fi

# --- udev rule 檢查（Linux，非 NixOS） ---
# NixOS 用戶的 udev rule 由 nixosModule 自動處理，不需手動設定。

if [ "$(uname)" = "Linux" ] && ! $IS_NIXOS; then
    info "檢查 /dev/ttyDONGLE..."
    if [ -e /dev/ttyDONGLE ]; then
        ok "/dev/ttyDONGLE 存在（udev rule 已生效）"
    else
        # 偵測 dongle，讀取 VID:PID
        DONGLE_PATH=$(ls /dev/serial/by-id/*nRF52* 2>/dev/null | head -1)
        if [ -n "$DONGLE_PATH" ]; then
            REAL_DEV=$(readlink -f "$DONGLE_PATH")
            TTY_NAME=$(basename "$REAL_DEV")
            VID=$(cat "/sys/class/tty/$TTY_NAME/device/../idVendor" 2>/dev/null || true)
            PID=$(cat "/sys/class/tty/$TTY_NAME/device/../idProduct" 2>/dev/null || true)
            if [ -n "$VID" ] && [ -n "$PID" ]; then
                ok "找到 dongle: $DONGLE_PATH (VID:$VID PID:$PID)"
                TTY_RULE="SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"$VID\", ATTRS{idProduct}==\"$PID\", SYMLINK+=\"ttyDONGLE\", MODE=\"0666\""
                USB_RULE="SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$VID\", ATTR{idProduct}==\"$PID\", MODE=\"0666\""
                warn "/dev/ttyDONGLE 不存在，需要建立 udev rule"
                echo ""
                echo -e "  ${CYAN}執行以下指令：${NC}"
                echo "  sudo bash -c 'printf \"$TTY_RULE\n$USB_RULE\n\" > /etc/udev/rules.d/99-atm-dongle.rules && udevadm control --reload-rules && udevadm trigger'"
                echo ""
            else
                warn "找到 dongle 但無法讀取 VID:PID"
                hint "手動查看: udevadm info -a $REAL_DEV | grep -E 'idVendor|idProduct'"
            fi
        else
            warn "/dev/ttyDONGLE 不存在且未偵測到 dongle"
            hint "插入 ATM dongle 後重跑 ./install.sh"
        fi
    fi
fi

# --- 配對 Dongle ---

echo ""
info "開始配對 dongle..."
echo ""
python setup_dongle.py

# --- 完成 ---

DESK_NAME=$(python3 -c "
import yaml
try:
    with open('config.yaml') as f:
        cfg = yaml.safe_load(f) or {}
    print((cfg.get('desk') or {}).get('name') or '')
except: pass
" 2>/dev/null)

echo ""
echo -e "${GREEN}安裝完成！${NC}"
echo ""

if $IS_NIXOS; then
    echo "NixOS 用戶下一步："
    echo "  在 flake.nix inputs 加入 timotion，啟用 nixosModule："
    echo ""
    echo "    services.timotion = {"
    echo "      enable = true;"
    echo "      deskName = \"$DESK_NAME\";"
    echo "    };"
    echo ""
    echo "  然後 nixos-rebuild switch"
else
    echo "下一步："
    echo ""
    echo "  # 安裝 systemd service（推薦）"
    echo "  sudo cp timotion-desk.service /etc/systemd/system/"
    echo "  sudo sed -i 's|__INSTALL_DIR__|$SCRIPT_DIR|g; s|__USER__|$(whoami)|g' /etc/systemd/system/timotion-desk.service"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now timotion-desk"
    echo ""
    echo "  # 或直接執行"
    echo "  source .venv/bin/activate"
    echo "  python desk_server.py"
fi
