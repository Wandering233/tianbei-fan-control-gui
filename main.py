#!/usr/bin/env python3
"""
Entry point for TianBei MACO Live Fan Control Center.
Supports PyQt6 native GUI (default) and quick CLI status/mode switching.
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.client import DaemonClient
from core.config_store import load_config, save_config
from core.hwmon import read_telemetry
from core.models import FanMode


def print_status() -> int:
    client = DaemonClient()
    ok, resp, err = client.get_status()
    tel = resp.get("telemetry", {}) if ok else read_telemetry()

    print("=" * 68)
    print(" 🌀  天贝 (TianBei) MACO 实时风扇控制中心状态")
    print("=" * 68)
    print(f"  守护进程状态 : {'运行中' if ok else '未运行'} ({'开机服务' if client.is_persistent_service_enabled() else '按需/未安装'})")
    print(f"  IT8613E 驱动 : {'已加载 (' + str(tel.get('hwmon_path')) + ')' if tel.get('driver_loaded') else '未加载'}")
    print(f"  k10temp Tctl : {tel.get('k10temp_c')} °C")
    print(f"  IT8613 temp3 : {tel.get('it8613_temp3_c')} °C")
    print(f"  风扇实时转速 : {tel.get('fan_rpm')} RPM | PWM: {tel.get('pwm')} ({tel.get('pwm_pct')}%)")
    mode = (resp.get("config", {}).get("mode") if ok else tel.get("hw_inferred_mode")) or "unknown"
    print(f"  当前运行档位 : {FanMode.LABELS.get(mode, mode)}")
    if ok and mode == FanMode.CURVE:
        print(f"  滞回追踪温度 : {resp.get('effective_temp_c')} °C -> 目标 {resp.get('target_pct')}%")
    elif not ok:
        print(f"  守护连接提示 : {err}")
    print("=" * 68)
    return 0


def switch_mode_cli(target_mode: str) -> int:
    client = DaemonClient()
    cfg = load_config()
    cfg.mode = target_mode
    cfg = cfg.normalized()
    save_config(cfg)

    if not client.is_daemon_running():
        ok_start, msg_start = client.start_transient_daemon()
        if not ok_start:
            print(f"[-] 启动守护进程失败: {msg_start}")
            return 1

    ok, _, msg = client.apply_config(cfg)
    if not ok:
        print(f"[-] 切换档位失败: {msg}")
        return 1
    print(f"[+] 已实时切换到: {FanMode.LABELS[target_mode]}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="天贝 MACO 实时风扇控制中心")
    parser.add_argument("-s", "--status", action="store_true", help="查看当前温度、转速与风扇档位")
    parser.add_argument("-m", "--mode", choices=list(FanMode.ALL), help="直接切换风扇档位 (auto/full/curve)")
    parser.add_argument("--stop", action="store_true", help="停止后台守护进程并恢复原厂自动")
    parser.add_argument("--gui", action="store_true", help="启动图形界面 (默认)")
    args, _ = parser.parse_known_args()

    if args.status:
        sys.exit(print_status())

    if args.stop:
        client = DaemonClient()
        ok, msg = client.stop_daemon()
        print(("[+] " if ok else "[-] ") + msg)
        sys.exit(0 if ok else 1)

    if args.mode:
        sys.exit(switch_mode_cli(args.mode))

    from PyQt6.QtWidgets import QApplication
    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("TianBei-Fan-Control")
    app.setApplicationDisplayName("天贝 MACO 实时风扇控制中心")

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
