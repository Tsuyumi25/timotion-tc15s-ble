#!/usr/bin/env bash
# timotion-ble 環境檢查與安裝腳本
# 用法：./install.sh [--setup]
#   --setup  安裝後直接執行 setup_dongle.py

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

# --- Serial port 權限（Linux） ---

if [ "$(uname)" = "Linux" ]; then
    info "檢查 dialout 群組..."
    if id -nG | grep -qw dialout; then
        ok "使用者已在 dialout 群組"
    else
        fail "使用者不在 dialout 群組（無法存取 serial port）"
        hint "sudo usermod -aG dialout $(whoami) && 重新登入"
        errors=$((errors + 1))
    fi
fi

# --- Docker（選用） ---

info "檢查 Docker..."
if command -v docker &>/dev/null; then
    ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
else
    warn "Docker 未安裝（不影響直接執行，僅 Docker 部署需要）"
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

info "安裝依賴..."
pip install -q ".[setup]"
ok "已安裝（含 bleak 掃描支援）"

# --- config.yaml ---

if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
    ok "已建立 config.yaml（從 config.example.yaml）"
else
    ok "config.yaml 已存在"
fi

# --- Dongle 偵測 → .env（Linux Docker 用） ---

if [ "$(uname)" = "Linux" ]; then
    info "偵測 ATM dongle..."
    DONGLE_PATH=$(ls /dev/serial/by-id/*nRF52* 2>/dev/null | head -1)
    if [ -n "$DONGLE_PATH" ]; then
        ok "找到 dongle: $DONGLE_PATH"
        echo "DONGLE_DEVICE=$DONGLE_PATH" > .env
        ok "已寫入 .env（docker-compose 會讀取）"
    else
        warn "未偵測到 dongle（未插入或非 nRF52 裝置）"
        hint "插入 dongle 後重跑 ./install.sh，或手動建立 .env："
        hint "echo 'DONGLE_DEVICE=/dev/serial/by-id/你的裝置路徑' > .env"
    fi
fi

# --- 完成 ---

echo ""
echo -e "${GREEN}安裝完成！${NC}"
echo ""
echo "下一步："
echo "  1. 插入 ATM dongle（如尚未插入）"
echo "  2. source .venv/bin/activate"
echo "  3. python setup_dongle.py        # 設定 dongle（只需一次）"
echo "  4. python desk_server.py          # 直接執行"
echo "  或"
echo "  4. docker compose up -d --build   # Docker 部署"

# --- --setup 快捷 ---

if [[ "${1:-}" == "--setup" ]]; then
    echo ""
    exec python setup_dongle.py
fi
