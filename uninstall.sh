#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_PATH="$HOME/.local/bin/tianbei-fan-control"
DESKTOP_PATH="$HOME/.local/share/applications/tianbei-fan-control-gui.desktop"

echo "========================================================"
echo " 🗑️   天贝 (TianBei) MACO 实时风扇控制中心 - 卸载程序"
echo "========================================================"

if [[ -f /etc/systemd/system/tianbei-fan-daemon.service || -f /etc/modprobe.d/tianbei-it87.conf ]]; then
    echo "检测到系统级持久化服务/驱动配置，正在通过 GUI 提权清理..."
    pkexec python3 "${REPO_DIR}/bin/tianbei-fan-ctl" uninstall-system
fi

rm -f "$BIN_PATH" "$DESKTOP_PATH"
echo "✅ 已清理全局命令与桌面快捷方式。"
