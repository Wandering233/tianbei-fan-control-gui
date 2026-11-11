"""
Main Window for TianBei MACO Live Fan Control Center.
Provides real-time telemetry, 3-mode fan switching (Factory Auto / Full Speed /
Custom Fan Curve), interactive curve editing, and one-click GUI pkexec service control.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from core.client import DaemonClient
from core.config_store import load_config, save_config
from core.hwmon import read_telemetry
from core.models import (
    CURVE_PRESETS,
    CurvePoint,
    FACTORY_SMART_FAN,
    FanConfig,
    FanMode,
    TEMP_MAX_C,
    TEMP_MIN_C,
    factory_preview_points,
    validate_and_normalize_points,
)
from .curve_canvas import CurveCanvasWidget
from .icons import get_icon, get_pixmap
from .styles import DARK_THEME


class WorkerThread(QThread):
    """Run blocking pkexec/socket operations off the Qt UI thread."""

    finished_with_result = pyqtSignal(bool, object, str)

    def __init__(self, fn: Callable[[], Tuple[bool, Any, str]], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            ok, payload, msg = self._fn()
            self.finished_with_result.emit(ok, payload, msg)
        except Exception as exc:
            self.finished_with_result.emit(False, None, str(exc))


class ToastBanner(QFrame):
    """Sonner-inspired in-app notification banner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToastBanner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        self.icon_lbl = QLabel()
        self.text_lbl = QLabel()
        self.text_lbl.setWordWrap(True)
        layout.addWidget(self.icon_lbl)
        layout.addWidget(self.text_lbl, stretch=1)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, toast_type: str = "info", duration_ms: int = 4500) -> None:
        palette = {
            "success": ("check", "#3FB950", "rgba(63, 185, 80, 0.12)", "rgba(63, 185, 80, 0.4)"),
            "error": ("alert", "#F85149", "rgba(248, 81, 73, 0.12)", "rgba(248, 81, 73, 0.4)"),
            "info": ("chip", "#58A6FF", "rgba(56, 139, 253, 0.12)", "rgba(56, 139, 253, 0.4)"),
        }
        icon_name, fg, bg, border = palette.get(toast_type, palette["info"])
        self.icon_lbl.setPixmap(get_pixmap(icon_name, color=fg, size=18))
        self.text_lbl.setText(text)
        self.text_lbl.setStyleSheet(f"font-weight: 600; font-size: 12.5px; color: {fg};")
        self.setStyleSheet(
            f"QFrame#ToastBanner {{ background-color: {bg}; border: 1px solid {border}; border-radius: 8px; }}"
        )
        self.show()
        self.timer.start(duration_ms)


class ServiceDialog(QDialog):
    """Manage transient root daemon, kernel driver loading, and systemd boot persistence."""

    state_changed = pyqtSignal()

    def __init__(self, client: DaemonClient, parent=None):
        super().__init__(parent)
        self.client = client
        self._busy = False
        self._worker: Optional[WorkerThread] = None

        self.setWindowTitle("后台守护进程与系统持久化管理")
        self.resize(580, 390)
        self.setStyleSheet(DARK_THEME)
        self._build_ui()
        self._refresh_info()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        hdr = QHBoxLayout()
        ico = QLabel()
        ico.setPixmap(get_pixmap("server", color="#58A6FF", size=24))
        hdr.addWidget(ico)
        vbox = QVBoxLayout()
        t = QLabel("IT8613E 驱动与后台调速守护进程")
        t.setStyleSheet("font-size: 15px; font-weight: 700; color: #F0F6FC;")
        s = QLabel("无需重启电脑，所有特权操作均通过 GUI pkexec 弹窗授权执行。")
        s.setStyleSheet("color: #8B949E; font-size: 12px;")
        vbox.addWidget(t)
        vbox.addWidget(s)
        hdr.addLayout(vbox, stretch=1)
        layout.addLayout(hdr)

        grp = QGroupBox("当前状态")
        grid = QGridLayout(grp)
        grid.setVerticalSpacing(8)
        self.lbl_drv = QLabel("-")
        self.lbl_daemon = QLabel("-")
        self.lbl_service = QLabel("-")
        grid.addWidget(QLabel("IT8613E 内核驱动:"), 0, 0)
        grid.addWidget(self.lbl_drv, 0, 1)
        grid.addWidget(QLabel("控制守护进程:"), 1, 0)
        grid.addWidget(self.lbl_daemon, 1, 1)
        grid.addWidget(QLabel("开机自启服务:"), 2, 0)
        grid.addWidget(self.lbl_service, 2, 1)
        layout.addWidget(grp)

        hint = QLabel(
            "说明：\n"
            "• 【临时启动守护进程】不改动 /etc 或内核模块目录，关闭图形窗口后自定义曲线仍会在后台继续运行，"
            "直到你停止服务或重启。\n"
            "• 【安装开机自启】会把编译好的 it87.ko 放入 /lib/modules/<内核>/updates/ 并注册 systemd 服务，"
            "以后开机即自动按上次模式运行，打开本界面也无需再次输密码。"
        )
        hint.setObjectName("HintBox")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row1 = QHBoxLayout()
        self.btn_start = QPushButton(" 启动临时守护进程 (pkexec)")
        self.btn_start.setIcon(get_icon("zap", color="#58A6FF", size=16))
        self.btn_start.setObjectName("SecondaryAction")
        self.btn_start.clicked.connect(lambda: self._run_action("start"))

        self.btn_stop = QPushButton(" 停止守护并恢复原厂")
        self.btn_stop.setIcon(get_icon("power", color="#F85149", size=16))
        self.btn_stop.setObjectName("DangerButton")
        self.btn_stop.clicked.connect(lambda: self._run_action("stop"))
        row1.addWidget(self.btn_start)
        row1.addWidget(self.btn_stop)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_install = QPushButton(" 安装开机自启服务与驱动 (pkexec)")
        self.btn_install.setIcon(get_icon("save", color="#FFFFFF", size=16))
        self.btn_install.setObjectName("PrimaryButton")
        self.btn_install.clicked.connect(lambda: self._run_action("install"))

        self.btn_uninstall = QPushButton(" 卸载开机服务与驱动 (pkexec)")
        self.btn_uninstall.setIcon(get_icon("alert", color="#F85149", size=16))
        self.btn_uninstall.setObjectName("DangerButton")
        self.btn_uninstall.clicked.connect(lambda: self._run_action("uninstall"))
        row2.addWidget(self.btn_install)
        row2.addWidget(self.btn_uninstall)
        layout.addLayout(row2)

        btn_close_row = QHBoxLayout()
        btn_close_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_close_row.addWidget(btn_close)
        layout.addLayout(btn_close_row)

    def _refresh_info(self) -> None:
        tel = read_telemetry()
        running = self.client.is_daemon_running()
        installed = self.client.is_persistent_service_installed()
        enabled = self.client.is_persistent_service_enabled() if installed else False

        if tel["driver_loaded"]:
            self.lbl_drv.setText(f"已加载 ({tel['hwmon_path']})")
            self.lbl_drv.setStyleSheet("color: #3FB950; font-weight: 600;")
        else:
            self.lbl_drv.setText("未加载（连接守护进程时自动热加载）")
            self.lbl_drv.setStyleSheet("color: #D29922; font-weight: 600;")

        if running:
            self.lbl_daemon.setText("运行中（/run/tianbei-fan/control.sock 在线）")
            self.lbl_daemon.setStyleSheet("color: #3FB950; font-weight: 600;")
        else:
            self.lbl_daemon.setText("未启动")
            self.lbl_daemon.setStyleSheet("color: #8B949E; font-weight: 600;")

        if installed and enabled:
            self.lbl_service.setText("已安装并启用开机自启 (systemd)")
            self.lbl_service.setStyleSheet("color: #3FB950; font-weight: 600;")
        elif installed:
            self.lbl_service.setText("已安装但未启用")
            self.lbl_service.setStyleSheet("color: #D29922; font-weight: 600;")
        else:
            self.lbl_service.setText("未安装（仅按需临时运行）")
            self.lbl_service.setStyleSheet("color: #8B949E;")

        self.btn_stop.setEnabled(running)
        self.btn_uninstall.setEnabled(installed)

    def _run_action(self, kind: str) -> None:
        if self._busy:
            return
        self._busy = True
        for b in (self.btn_start, self.btn_stop, self.btn_install, self.btn_uninstall):
            b.setEnabled(False)

        def _task():
            if kind == "start":
                ok, msg = self.client.start_transient_daemon()
            elif kind == "stop":
                ok, msg = self.client.stop_daemon()
            elif kind == "install":
                ok, msg = self.client.install_system_service()
            else:
                ok, msg = self.client.uninstall_system_service()
            return ok, None, msg

        self._worker = WorkerThread(_task, self)
        self._worker.finished_with_result.connect(lambda ok, _, msg: self._on_action_done(ok, msg))
        self._worker.start()

    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)

    def _on_action_done(self, ok: bool, msg: str) -> None:
        self._busy = False
        for b in (self.btn_start, self.btn_stop, self.btn_install, self.btn_uninstall):
            b.setEnabled(True)
        self._refresh_info()
        self.state_changed.emit()
        if ok:
            QMessageBox.information(self, "操作成功", msg or "操作已完成。")
        else:
            QMessageBox.warning(self, "操作失败", msg or "操作未完成。")


class MainWindow(QMainWindow):
    """Primary PyQt6 desktop interface for TianBei MACO 3-mode live fan control."""

    def __init__(self):
        super().__init__()
        self.client = DaemonClient()
        self.config: FanConfig = load_config()
        self.active_mode: Optional[str] = None
        self.daemon_running: bool = False
        self._syncing_ui: bool = False
        self._busy: bool = False
        self._worker: Optional[WorkerThread] = None

        self._build_ui()
        self._load_config_into_ui(self.config)
        self.refresh_status()

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self.refresh_status)
        self.poll_timer.start()

    def _build_ui(self) -> None:
        self.setWindowTitle("天贝 MACO 实时风扇控制中心")
        self.resize(1040, 810)
        self.setStyleSheet(DARK_THEME)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 1. Header
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(get_pixmap("fan", color="#58A6FF", size=30))
        header.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("TianBei MACO 实时风扇控制中心")
        title.setObjectName("HeaderTitle")
        subtitle = QLabel("硬件: 天贝 MACO (Ryzen 7 255 / ITE IT8613E) | 标准 hwmon 接口 · 免重启即时生效")
        subtitle.setObjectName("HeaderSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.status_badge = QLabel("正在检测硬件...")
        self.status_badge.setObjectName("BadgeSafe")
        header.addWidget(self.status_badge)
        root.addLayout(header)

        # 2. Toast banner
        self.toast = ToastBanner(self)
        root.addWidget(self.toast)

        # 3. Telemetry strip
        tel_row = QHBoxLayout()
        tel_row.setSpacing(10)

        self.card_cpu_val, self.card_cpu_sub, c1 = self._make_metric_card("CPU 核心温度 (k10temp)", "thermometer", "#58A6FF")
        self.card_rpm_val, self.card_rpm_sub, c2 = self._make_metric_card("CPU 风扇实时转速", "fan", "#3FB950")
        self.card_board_val, self.card_board_sub, c3 = self._make_metric_card("主板传感器 (IT8613E)", "chip", "#8B949E")
        self.card_mode_val, self.card_mode_sub, c4 = self._make_metric_card("当前激活档位", "activity", "#D29922")

        for card in (c1, c2, c3, c4):
            tel_row.addWidget(card, stretch=1)
        root.addLayout(tel_row)

        # 4. Three-mode selector cards
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)

        self.mode_cards: Dict[str, QPushButton] = {}
        mode_defs = [
            (
                FanMode.AUTO,
                "1. 原厂默认自动",
                "SmartGuardian 芯片硬件闭环\n25°C停 / 35°C起转 / 95°C满速",
                "shield",
                "#58A6FF",
            ),
            (
                FanMode.FULL,
                "2. 全速运转 (100%)",
                "手动锁定 PWM = 255 满转输出\n高负载烤机与极速降温",
                "zap",
                "#F85149",
            ),
            (
                FanMode.CURVE,
                "3. 自定义温控曲线",
                "多节点温控折线 + 滞回防抽风\n支持后台持续闭环调速",
                "sliders",
                "#3FB950",
            ),
        ]

        for mode_id, m_title, m_desc, icon_name, accent in mode_defs:
            btn = self._make_mode_card(mode_id, m_title, m_desc, icon_name, accent)
            self.mode_cards[mode_id] = btn
            self.mode_group.addButton(btn)
            btn.clicked.connect(lambda _checked, m=mode_id: self._on_mode_card_selected(m))
            mode_row.addWidget(btn, stretch=1)
        root.addLayout(mode_row)

        # 5. Main workspace: interactive canvas (left) + mode detail/editor (right)
        body_row = QHBoxLayout()
        body_row.setSpacing(12)

        # Left panel
        left_frame = QFrame()
        left_frame.setObjectName("SurfaceCard")
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(12, 12, 12, 10)
        left_layout.setSpacing(8)

        self.canvas = CurveCanvasWidget()
        self.canvas.points_changed.connect(self._on_canvas_points_changed)
        left_layout.addWidget(self.canvas, stretch=1)

        legend = QLabel("提示：实线为目标温控曲线，蓝色光点为当前实时温/速，红色虚线为高温满转安全兜底。")
        legend.setObjectName("MetricSub")
        left_layout.addWidget(legend)
        body_row.addWidget(left_frame, stretch=6)

        # Right panel
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_auto_page())
        self.right_stack.addWidget(self._build_full_page())
        self.right_stack.addWidget(self._build_curve_page())
        body_row.addWidget(self.right_stack, stretch=5)

        root.addLayout(body_row, stretch=1)

        # 6. Bottom action bar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(10)

        self.btn_service = QPushButton(" 连接硬件与后台服务...")
        self.btn_service.setIcon(get_icon("server", color="#8B949E", size=16))
        self.btn_service.clicked.connect(self._open_service_dialog)
        action_bar.addWidget(self.btn_service)

        action_bar.addStretch()

        self.btn_refresh = QPushButton(" 刷新状态")
        self.btn_refresh.setIcon(get_icon("refresh", color="#58A6FF", size=16))
        self.btn_refresh.setObjectName("SecondaryAction")
        self.btn_refresh.clicked.connect(lambda: self.refresh_status(manual=True))
        action_bar.addWidget(self.btn_refresh)

        self.btn_apply = QPushButton(" 立即应用当前档位")
        self.btn_apply.setIcon(get_icon("check", color="#FFFFFF", size=16))
        self.btn_apply.setObjectName("PrimaryButton")
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        action_bar.addWidget(self.btn_apply)

        root.addLayout(action_bar)

    def _make_metric_card(self, title: str, icon_name: str, color: str) -> Tuple[QLabel, QLabel, QFrame]:
        frame = QFrame()
        frame.setObjectName("MetricCard")
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(4)

        top = QHBoxLayout()
        ico = QLabel()
        ico.setPixmap(get_pixmap(icon_name, color=color, size=15))
        lbl_t = QLabel(title)
        lbl_t.setObjectName("MetricTitle")
        top.addWidget(ico)
        top.addWidget(lbl_t)
        top.addStretch()

        lbl_val = QLabel("--")
        lbl_val.setObjectName("MetricValue")
        lbl_sub = QLabel("--")
        lbl_sub.setObjectName("MetricSub")

        v.addLayout(top)
        v.addWidget(lbl_val)
        v.addWidget(lbl_sub)
        return lbl_val, lbl_sub, frame

    def _make_mode_card(
        self,
        mode_id: str,
        title: str,
        desc: str,
        icon_name: str,
        accent: str,
    ) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("ModeCard")
        btn.setProperty("modeRole", mode_id)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(btn)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(10)

        ico = QLabel()
        ico.setPixmap(get_pixmap(icon_name, color=accent, size=22))
        lay.addWidget(ico, alignment=Qt.AlignmentFlag.AlignTop)

        tv = QVBoxLayout()
        tv.setSpacing(3)
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("font-size: 13.5px; font-weight: 700; color: #F0F6FC;")
        d_lbl = QLabel(desc)
        d_lbl.setStyleSheet("font-size: 11.5px; color: #8B949E;")
        tv.addWidget(t_lbl)
        tv.addWidget(d_lbl)
        lay.addLayout(tv, stretch=1)
        btn.setMinimumHeight(74)
        return btn

    def _build_auto_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        grp = QGroupBox("原厂默认自动参数 (SmartGuardian 硬件闭环)")
        grid = QGridLayout(grp)
        grid.setVerticalSpacing(8)
        rows = [
            ("温控传感器通道:", "temp3 (CPU SIO 温感)"),
            ("停转温度 (Off):", f"{FACTORY_SMART_FAN['point1_temp_mc'] // 1000} °C"),
            ("滞回温度 (Hyst):", f"{FACTORY_SMART_FAN['point1_hyst_mc'] // 1000} °C (温差 1 °C)"),
            ("起转温度 (Start):", f"{FACTORY_SMART_FAN['point2_temp_mc'] // 1000} °C"),
            ("起转 PWM (StartPWM):", f"{FACTORY_SMART_FAN['start_pwm']} / 255 (~27%)"),
            ("增速斜率 (Slope):", f"{FACTORY_SMART_FAN['slope']} ({FACTORY_SMART_FAN['slope'] / 8.0:.1f} PWM/°C)"),
            ("满速温度 (Full):", f"{FACTORY_SMART_FAN['point3_temp_mc'] // 1000} °C"),
        ]
        for idx, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet("color: #8B949E;")
            vl = QLabel(v)
            vl.setStyleSheet("color: #F0F6FC; font-weight: 600;")
            grid.addWidget(kl, idx, 0)
            grid.addWidget(vl, idx, 1)
        lay.addWidget(grp)

        hint = QLabel(
            "该模式会先复原 IT8613E 共用寄存器 pwm2_auto_start=70，再切换 pwm2_enable=2，"
            "交由主板芯片全权独立温控，无需用户态轮询，关闭本软件后依然生效。"
        )
        hint.setObjectName("HintBox")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()
        return page

    def _build_full_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        grp = QGroupBox("全速运转锁定参数 (100% PWM)")
        grid = QGridLayout(grp)
        grid.setVerticalSpacing(8)
        rows = [
            ("控制模式 (pwm2_enable):", "1 (手动定速)"),
            ("输出占空比 (pwm2):", "255 / 255 (100%)"),
            ("预期转速参考:", "约 3900 RPM（视风道背压微调）"),
            ("适用场景:", "性能跑分、编译/AI 推理散热压测、快速排热"),
        ]
        for idx, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet("color: #8B949E;")
            vl = QLabel(v)
            vl.setStyleSheet("color: #F0F6FC; font-weight: 600;")
            grid.addWidget(kl, idx, 0)
            grid.addWidget(vl, idx, 1)
        lay.addWidget(grp)

        hint = QLabel(
            "全速模式下风扇将以最大风压运转，噪声明显增大；完成高负载任务后可随时一键切换回「原厂默认自动」或「自定义温控曲线」，无需重启。"
        )
        hint.setObjectName("HintBox")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()
        return page

    def _build_curve_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # Presets + table
        grp_pts = QGroupBox("曲线控制点与预设模板")
        pts_lay = QVBoxLayout(grp_pts)
        pts_lay.setSpacing(8)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_lbl = QLabel("预设:")
        preset_lbl.setStyleSheet("color: #8B949E;")
        preset_row.addWidget(preset_lbl)
        for key, (label, _) in CURVE_PRESETS.items():
            b = QPushButton(label)
            b.clicked.connect(lambda _c, k=key: self._apply_preset(k))
            preset_row.addWidget(b)
        preset_row.addStretch()
        pts_lay.addLayout(preset_row)

        self.pts_table = QTableWidget(0, 3)
        self.pts_table.setHorizontalHeaderLabels(["节点", "温度 (°C)", "风扇转速 (%)"])
        self.pts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.pts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.pts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.pts_table.verticalHeader().setVisible(False)
        self.pts_table.verticalHeader().setDefaultSectionSize(34)
        self.pts_table.setMinimumHeight(205)
        self.pts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.pts_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        pts_lay.addWidget(self.pts_table, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_add_pt = QPushButton(" 添加节点")
        self.btn_add_pt.setIcon(get_icon("plus", color="#C9D1D9", size=14))
        self.btn_add_pt.clicked.connect(self._on_add_point)
        self.btn_del_pt = QPushButton(" 删除选中")
        self.btn_del_pt.setIcon(get_icon("minus", color="#C9D1D9", size=14))
        self.btn_del_pt.clicked.connect(self._on_delete_point)
        btn_row.addWidget(self.btn_add_pt)
        btn_row.addWidget(self.btn_del_pt)
        btn_row.addStretch()
        pts_lay.addLayout(btn_row)
        lay.addWidget(grp_pts, stretch=1)

        # Tuning options
        grp_tune = QGroupBox("曲线控温策略与保护")
        grid = QGridLayout(grp_tune)
        grid.setVerticalSpacing(8)

        self.combo_sensor = QComboBox()
        self.combo_sensor.addItem("k10temp Tctl (Ryzen 核心结温 · 推荐)", "k10temp")
        self.combo_sensor.addItem("IT8613E temp3 (主板 SIO CPU 温感)", "it8613_temp3")
        self.combo_sensor.currentIndexChanged.connect(self._on_tuning_changed)

        self.spin_hyst = QSpinBox()
        self.spin_hyst.setRange(1, 10)
        self.spin_hyst.setSuffix(" °C")
        self.spin_hyst.valueChanged.connect(self._on_tuning_changed)

        self.spin_poll = QDoubleSpinBox()
        self.spin_poll.setRange(0.5, 5.0)
        self.spin_poll.setSingleStep(0.5)
        self.spin_poll.setSuffix(" 秒")
        self.spin_poll.valueChanged.connect(self._on_tuning_changed)

        self.spin_crit = QSpinBox()
        self.spin_crit.setRange(80, 100)
        self.spin_crit.setSuffix(" °C (强制 100%)")
        self.spin_crit.valueChanged.connect(self._on_tuning_changed)

        grid.addWidget(QLabel("感温数据源:"), 0, 0)
        grid.addWidget(self.combo_sensor, 0, 1)
        grid.addWidget(QLabel("降速滞回防抽风:"), 1, 0)
        grid.addWidget(self.spin_hyst, 1, 1)
        grid.addWidget(QLabel("调节采样周期:"), 2, 0)
        grid.addWidget(self.spin_poll, 2, 1)
        grid.addWidget(QLabel("高温兜底全速线:"), 3, 0)
        grid.addWidget(self.spin_crit, 3, 1)
        lay.addWidget(grp_tune)

        return page

    def _load_config_into_ui(self, cfg: FanConfig) -> None:
        self._syncing_ui = True
        try:
            self.config = cfg.normalized()
            btn = self.mode_cards.get(self.config.mode)
            if btn:
                btn.setChecked(True)

            idx_sensor = self.combo_sensor.findData(self.config.sensor_source)
            if idx_sensor >= 0:
                self.combo_sensor.setCurrentIndex(idx_sensor)
            self.spin_hyst.setValue(self.config.hysteresis_c)
            self.spin_poll.setValue(self.config.poll_interval_s)
            self.spin_crit.setValue(self.config.critical_temp_c)

            self._rebuild_points_table()
            self._sync_mode_views()
        finally:
            self._syncing_ui = False

    def _rebuild_points_table(self) -> None:
        was_syncing = self._syncing_ui
        self._syncing_ui = True
        try:
            pts = self.config.points
            if self.pts_table.rowCount() == len(pts):
                for row, pt in enumerate(pts):
                    sp_t = self.pts_table.cellWidget(row, 1)
                    sp_s = self.pts_table.cellWidget(row, 2)
                    if isinstance(sp_t, QSpinBox) and isinstance(sp_s, QSpinBox):
                        if sp_t.value() != pt.temp_c:
                            sp_t.setValue(pt.temp_c)
                        if sp_s.value() != pt.speed_pct:
                            sp_s.setValue(pt.speed_pct)
                return

            self.pts_table.setRowCount(len(pts))
            for row, pt in enumerate(pts):
                num_lbl = QLabel(f"#{row + 1}")
                num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                num_lbl.setStyleSheet("color: #8B949E; font-weight: 600;")
                self.pts_table.setCellWidget(row, 0, num_lbl)

                sp_t = QSpinBox()
                sp_t.setRange(TEMP_MIN_C, TEMP_MAX_C)
                sp_t.setSuffix(" °C")
                sp_t.setValue(pt.temp_c)
                sp_t.valueChanged.connect(lambda val, r=row: self._on_table_temp_changed(r, val))
                self.pts_table.setCellWidget(row, 1, sp_t)

                sp_s = QSpinBox()
                sp_s.setRange(0, 100)
                sp_s.setSuffix(" %")
                sp_s.setValue(pt.speed_pct)
                sp_s.valueChanged.connect(lambda val, r=row: self._on_table_speed_changed(r, val))
                self.pts_table.setCellWidget(row, 2, sp_s)
        finally:
            self._syncing_ui = was_syncing

    def _sync_mode_views(self) -> None:
        mode = self.config.mode
        if mode == FanMode.AUTO:
            self.right_stack.setCurrentIndex(0)
            self.canvas.set_curve_state(
                factory_preview_points(),
                editable=False,
                line_color="#58A6FF",
                caption="只读预览：原厂 SmartGuardian 硬件曲线 (25°C停 / 35°C起转 / 95°C满)",
                critical_temp_c=95,
            )
        elif mode == FanMode.FULL:
            self.right_stack.setCurrentIndex(1)
            self.canvas.set_curve_state(
                [CurvePoint(TEMP_MIN_C, 100), CurvePoint(TEMP_MAX_C, 100)],
                editable=False,
                line_color="#F85149",
                caption="只读预览：全速锁定模式 (100% PWM=255)",
                critical_temp_c=100,
            )
        else:
            self.right_stack.setCurrentIndex(2)
            self.canvas.set_curve_state(
                self.config.points,
                editable=True,
                line_color="#3FB950",
                caption="自定义温控曲线（左键可直接拖拽节点调节）",
                critical_temp_c=self.config.critical_temp_c,
            )

    def _on_mode_card_selected(self, mode: str) -> None:
        if self._syncing_ui:
            return
        self.config.mode = mode
        self._sync_mode_views()

    def _on_canvas_points_changed(self, pts: List[CurvePoint]) -> None:
        if self._syncing_ui:
            return
        self.config.points = validate_and_normalize_points(pts)
        self._rebuild_points_table()

    def _on_table_temp_changed(self, row: int, new_temp: int) -> None:
        if self._syncing_ui or row >= len(self.config.points):
            return
        pts = [CurvePoint(p.temp_c, p.speed_pct) for p in self.config.points]
        min_t = (pts[row - 1].temp_c + 1) if row > 0 else TEMP_MIN_C
        max_t = (pts[row + 1].temp_c - 1) if row + 1 < len(pts) else TEMP_MAX_C
        clamped_t = max(min_t, min(max_t, new_temp))
        pts[row] = CurvePoint(clamped_t, pts[row].speed_pct)
        self.config.points = pts
        if clamped_t != new_temp:
            self._rebuild_points_table()
        self._sync_mode_views()

    def _on_table_speed_changed(self, row: int, new_speed: int) -> None:
        if self._syncing_ui or row >= len(self.config.points):
            return
        self.config.points[row] = CurvePoint(self.config.points[row].temp_c, max(0, min(100, new_speed)))
        self._sync_mode_views()

    def _on_tuning_changed(self) -> None:
        if self._syncing_ui:
            return
        self.config.sensor_source = str(self.combo_sensor.currentData())
        self.config.hysteresis_c = self.spin_hyst.value()
        self.config.poll_interval_s = self.spin_poll.value()
        self.config.critical_temp_c = self.spin_crit.value()
        self._sync_mode_views()

    def _apply_preset(self, key: str) -> None:
        label, pts = CURVE_PRESETS[key]
        self.config.points = [CurvePoint(p.temp_c, p.speed_pct) for p in pts]
        self._rebuild_points_table()
        self._sync_mode_views()
        self.toast.show_message(f"已载入「{label}」曲线模板，点击右下角【立即应用当前档位】生效。", "info")

    def _on_add_point(self) -> None:
        pts = list(self.config.points)
        if len(pts) >= 8:
            self.toast.show_message("最多支持 8 个温控曲线节点。", "error")
            return
        # Find the widest temperature gap to split cleanly
        best_gap = -1
        insert_idx = len(pts)
        new_t, new_s = 60, 50
        for i in range(len(pts) - 1):
            gap = pts[i + 1].temp_c - pts[i].temp_c
            if gap > best_gap:
                best_gap = gap
                insert_idx = i + 1
                new_t = (pts[i].temp_c + pts[i + 1].temp_c) // 2
                new_s = (pts[i].speed_pct + pts[i + 1].speed_pct) // 2
        if best_gap < 2:
            self.toast.show_message("现有节点温度间隔过密，无法继续插入。", "error")
            return
        pts.insert(insert_idx, CurvePoint(new_t, new_s))
        self.config.points = validate_and_normalize_points(pts)
        self._rebuild_points_table()
        self._sync_mode_views()

    def _on_delete_point(self) -> None:
        if len(self.config.points) <= 2:
            self.toast.show_message("至少保留 2 个控制点。", "error")
            return
        row = self.pts_table.currentRow()
        if row < 0 or row >= len(self.config.points):
            row = len(self.config.points) - 1
        pts = list(self.config.points)
        pts.pop(row)
        self.config.points = validate_and_normalize_points(pts)
        self._rebuild_points_table()
        self._sync_mode_views()

    def refresh_status(self, manual: bool = False) -> None:
        ok, resp, _ = self.client.get_status()
        if ok:
            self.daemon_running = True
            tel = resp.get("telemetry", {})
            active_cfg = resp.get("config", {})
            self.active_mode = active_cfg.get("mode")
            eff_temp = resp.get("effective_temp_c")
            persistent = resp.get("persistent_service", False)
            svc_tag = "开机服务在线" if persistent else "后台守护在线"
        else:
            self.daemon_running = False
            tel = read_telemetry()
            self.active_mode = tel.get("hw_inferred_mode")
            eff_temp = None
            svc_tag = "守护进程未启动"

        self._update_telemetry_cards(tel, svc_tag, eff_temp)
        if manual and ok:
            self.toast.show_message("已刷新实时温度与风扇状态。", "info", 2500)

    def _update_telemetry_cards(
        self,
        tel: Dict[str, Any],
        svc_tag: str,
        eff_temp: Optional[float],
    ) -> None:
        drv_loaded = bool(tel.get("driver_loaded"))
        k10 = tel.get("k10temp_c")
        t3 = tel.get("it8613_temp3_c")
        t1 = tel.get("it8613_temp1_c")
        t2 = tel.get("it8613_temp2_c")
        rpm = tel.get("fan_rpm")
        pwm = tel.get("pwm")
        pwm_pct = tel.get("pwm_pct")

        # Badge
        if self.daemon_running and drv_loaded:
            self.status_badge.setText(f"● it8613 已就绪 · {svc_tag}")
            self.status_badge.setObjectName("BadgeOk")
        elif drv_loaded:
            self.status_badge.setText("● it8613 已加载 · 只读监控")
            self.status_badge.setObjectName("BadgeSafe")
        else:
            self.status_badge.setText("● 未连接硬件（点击应用将 GUI 提权连接）")
            self.status_badge.setObjectName("BadgeWarn")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        # CPU Temp card
        if k10 is not None:
            self.card_cpu_val.setText(f"{k10:.1f} °C")
            color = "#3FB950" if k10 < 65 else ("#D29922" if k10 < 82 else "#F85149")
            self.card_cpu_val.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color};")
        else:
            self.card_cpu_val.setText("--.- °C")
        self.card_cpu_sub.setText(f"SIO temp3: {t3:.1f} °C" if t3 is not None else "SIO temp3: 等待驱动")

        # Fan RPM card
        self.card_rpm_val.setText(f"{rpm} RPM" if rpm is not None else "-- RPM")
        if pwm is not None and pwm_pct is not None:
            self.card_rpm_sub.setText(f"PWM: {pwm_pct}% ({pwm}/255)")
        else:
            self.card_rpm_sub.setText("PWM: 等待驱动")

        # Board card
        if t1 is not None and t2 is not None:
            self.card_board_val.setText(f"{t1:.0f}° / {t2:.0f}°C")
            hw_name = str(tel.get("hwmon_path") or "").rsplit("/", 1)[-1]
            self.card_board_sub.setText(f"设备: it8613 ({hw_name})")
        else:
            self.card_board_val.setText("-- / --")
            self.card_board_sub.setText("尚未加载 it87 (IT8613E)")

        # Active mode card
        if self.active_mode in FanMode.LABELS:
            self.card_mode_val.setText(FanMode.LABELS[self.active_mode])
            mode_colors = {
                FanMode.AUTO: "#58A6FF",
                FanMode.FULL: "#F85149",
                FanMode.CURVE: "#3FB950",
            }
            self.card_mode_val.setStyleSheet(
                f"font-size: 18px; font-weight: 700; color: {mode_colors[self.active_mode]};"
            )
        else:
            self.card_mode_val.setText("未接管")
            self.card_mode_val.setStyleSheet("font-size: 18px; font-weight: 700; color: #8B949E;")

        if eff_temp is not None and self.active_mode == FanMode.CURVE:
            self.card_mode_sub.setText(f"{svc_tag} · 滞回追踪 {eff_temp:.1f}°C")
        else:
            self.card_mode_sub.setText(svc_tag)

        # Canvas live crosshair
        live_t = (t3 if self.config.sensor_source == "it8613_temp3" and t3 is not None else k10)
        if live_t is None:
            live_t = t3
        self.canvas.set_live_point(live_t, pwm_pct)

    def _on_apply_clicked(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.btn_apply.setEnabled(False)
        cfg_to_apply = self.config.normalized()
        save_config(cfg_to_apply)

        def _task():
            if not self.client.is_daemon_running():
                ok_start, msg_start = self.client.start_transient_daemon()
                if not ok_start:
                    return False, None, msg_start
            return self.client.apply_config(cfg_to_apply)

        self._worker = WorkerThread(_task, self)
        self._worker.finished_with_result.connect(self._on_apply_done)
        self._worker.start()

    def _on_apply_done(self, ok: bool, payload: Any, msg: str) -> None:
        self._busy = False
        self.btn_apply.setEnabled(True)
        self.refresh_status()
        if ok:
            mode_name = FanMode.LABELS.get(self.config.mode, self.config.mode)
            extra = "（后台持续保活，关闭窗口仍生效）" if self.config.mode == FanMode.CURVE else "（硬件立即接管）"
            self.toast.show_message(f"已即时应用【{mode_name}】{extra}", "success")
        else:
            self.toast.show_message(msg or "应用失败", "error", 6000)

    def _open_service_dialog(self) -> None:
        dlg = ServiceDialog(self.client, self)
        dlg.state_changed.connect(self.refresh_status)
        dlg.exec()
        self.refresh_status()

    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
            return
        self.poll_timer.stop()
        super().closeEvent(event)
