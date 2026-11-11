#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "========================================================"
echo " 🌀  天贝 (TianBei) MACO 实时风扇控制中心 - 安装程序"
echo "========================================================"
echo "项目路径: ${REPO_DIR}"

echo "[1/4] 检查运行依赖..."
if ! command -v python3 &>/dev/null; then
    echo "❌ 错误: 未检测到 python3。"
    exit 1
fi
if ! python3 -c "import PyQt6, PyQt6.QtSvg" &>/dev/null; then
    echo "⚠️ 警告: 未检测到 PyQt6 / QtSvg，请执行: sudo pacman -S python-pyqt6"
fi

echo "[2/4] 设置可执行权限并校验内核驱动..."
chmod +x "${REPO_DIR}/main.py" "${REPO_DIR}/bin/tianbei-fan-daemon" "${REPO_DIR}/bin/tianbei-fan-ctl"
KVER="$(uname -r)"
BUILT_FILE="${REPO_DIR}/driver/it87/BUILT_FOR_KERNEL"
if [[ ! -f "${REPO_DIR}/driver/it87/it87.ko" || "$(cat "$BUILT_FILE" 2>/dev/null || true)" != "$KVER" ]]; then
    echo "正在为内核 ${KVER} 编译 it87 (IT8613E) 驱动..."
    make -C "${REPO_DIR}/driver/it87" clean modules
    echo "$KVER" > "$BUILT_FILE"
fi

echo "[3/4] 安装全局命令到 ~/.local/bin/tianbei-fan-control ..."
mkdir -p "${BIN_DIR}"
cat << INNER_EOF > "${BIN_DIR}/tianbei-fan-control"
#!/usr/bin/env bash
exec python3 "${REPO_DIR}/main.py" "\$@"
INNER_EOF
chmod +x "${BIN_DIR}/tianbei-fan-control"

echo "[4/4] 创建桌面应用图标..."
mkdir -p "${DESKTOP_DIR}"
cat << INNER_EOF > "${DESKTOP_DIR}/tianbei-fan-control-gui.desktop"
[Desktop Entry]
Name=天贝风扇控制中心
Name[zh_CN]=天贝风扇控制中心
GenericName=Live Fan Control Manager
Comment=Control TianBei MACO IT8613E Fan Speed Live Without Rebooting
Exec=${BIN_DIR}/tianbei-fan-control
Icon=utilities-system-monitor
Terminal=false
Type=Application
Categories=Settings;System;HardwareSettings;
Keywords=fan;pwm;cooling;tianbei;it8613;hwmon;curve;
INNER_EOF

if [[ "${1:-}" == "--with-service" ]]; then
    echo "[附加] 通过 GUI pkexec 安装系统持久化驱动与开机自启服务..."
    pkexec python3 "${REPO_DIR}/bin/tianbei-fan-ctl" install-system --uid "$(id -u)"
fi

echo ""
echo "========================================================"
echo "🎉 安装完成！"
echo "👉 启动图形界面: tianbei-fan-control"
echo "👉 查看实时状态: tianbei-fan-control --status"
echo "👉 快速切档命令: tianbei-fan-control --mode auto|full|curve"
echo "========================================================"
