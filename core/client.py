"""
Unprivileged client for talking to tianbei-fan-daemon over Unix socket,
ensuring driver module matches running kernel, and elevating cleanly via pkexec.
"""

import json
import os
import platform
import socket
import subprocess
import sys
from typing import Any, Dict, Tuple

from .models import FanConfig

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTL_BIN = os.path.join(BASE_DIR, "bin", "tianbei-fan-ctl")
DRIVER_DIR = os.path.join(BASE_DIR, "driver", "it87")
DRIVER_KO = os.path.join(DRIVER_DIR, "it87.ko")
BUILT_KERNEL_FILE = os.path.join(DRIVER_DIR, "BUILT_FOR_KERNEL")
SOCK_PATH = "/run/tianbei-fan/control.sock"
UNIT_NAME = "tianbei-fan-daemon.service"


class DaemonClient:
    """Communicate with the privileged fan daemon and manage GUI elevation."""

    def is_daemon_running(self) -> bool:
        try:
            resp = self._rpc({"cmd": "ping"}, timeout=0.6)
            return bool(resp.get("ok"))
        except OSError:
            return False

    def is_persistent_service_installed(self) -> bool:
        return os.path.exists(f"/etc/systemd/system/{UNIT_NAME}")

    def is_persistent_service_enabled(self) -> bool:
        res = subprocess.run(
            ["systemctl", "is-enabled", UNIT_NAME],
            capture_output=True,
            text=True,
        )
        return res.returncode == 0 and res.stdout.strip() == "enabled"

    def ensure_driver_built_for_current_kernel(self) -> Tuple[bool, str]:
        """Rebuild driver/it87/it87.ko as regular user if running kernel changed."""
        cur_kver = platform.release()
        built_kver = ""
        if os.path.exists(BUILT_KERNEL_FILE):
            try:
                with open(BUILT_KERNEL_FILE, "r", encoding="utf-8") as f:
                    built_kver = f.read().strip()
            except OSError:
                built_kver = ""

        if os.path.exists(DRIVER_KO) and built_kver == cur_kver:
            return True, cur_kver

        headers_build = f"/lib/modules/{cur_kver}/build"
        if not os.path.exists(headers_build):
            return False, f"当前内核 {cur_kver} 缺少内核头文件 ({headers_build})，无法编译 it87 驱动。"

        res = subprocess.run(
            ["make", "-C", DRIVER_DIR, "clean", "modules"],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0 or not os.path.exists(DRIVER_KO):
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"编译 it87 驱动失败: {err}"

        with open(BUILT_KERNEL_FILE, "w", encoding="utf-8") as f:
            f.write(f"{cur_kver}\n")
        return True, cur_kver

    def _run_pkexec(self, action: str) -> Tuple[bool, str]:
        if action in ("start-transient", "install-system"):
            ok, info = self.ensure_driver_built_for_current_kernel()
            if not ok:
                return False, info

        cmd = ["pkexec", sys.executable, CTL_BIN, action, "--uid", str(os.getuid())]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            if res.returncode in (126, 127) or "dismissed" in err.lower() or "not authorized" in err.lower():
                return False, "已取消 GUI 提权授权（pkexec）。"
            return False, err or f"提权操作失败 (exit={res.returncode})"
        return True, res.stdout.strip()

    def start_transient_daemon(self) -> Tuple[bool, str]:
        return self._run_pkexec("start-transient")

    def stop_daemon(self) -> Tuple[bool, str]:
        """Gracefully shut down daemon via socket (no root needed) or systemctl fallback."""
        if self.is_daemon_running():
            try:
                resp = self._rpc({"cmd": "shutdown"}, timeout=3.0)
                if resp.get("ok"):
                    return True, resp.get("message", "已停止后台守护进程并恢复原厂自动。")
            except OSError:
                pass
        return self._run_pkexec("stop-daemon")

    def install_system_service(self) -> Tuple[bool, str]:
        return self._run_pkexec("install-system")

    def uninstall_system_service(self) -> Tuple[bool, str]:
        return self._run_pkexec("uninstall-system")

    def _rpc(self, payload: Dict[str, Any], timeout: float = 2.0) -> Dict[str, Any]:
        if not os.path.exists(SOCK_PATH):
            raise FileNotFoundError(f"守护进程未连接 ({SOCK_PATH})")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(SOCK_PATH)
            line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            s.sendall(line)
            chunks = []
            while True:
                buf = s.recv(4096)
                if not buf:
                    break
                chunks.append(buf)
                if b"\n" in buf:
                    break
            raw = b"".join(chunks).split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
            if not raw:
                raise RuntimeError("守护进程返回空响应")
            return json.loads(raw)

    def get_status(self) -> Tuple[bool, Dict[str, Any], str]:
        try:
            resp = self._rpc({"cmd": "status"}, timeout=1.5)
            if not resp.get("ok"):
                return False, resp, resp.get("error", "状态查询失败")
            return True, resp, "OK"
        except (OSError, ValueError, RuntimeError) as exc:
            return False, {}, str(exc)

    def apply_config(self, cfg: FanConfig) -> Tuple[bool, Dict[str, Any], str]:
        try:
            resp = self._rpc({"cmd": "set_config", "config": cfg.normalized().to_dict()}, timeout=4.0)
            if not resp.get("ok"):
                return False, resp, resp.get("error", "应用设置失败")
            return True, resp, "已应用配置"
        except (OSError, ValueError, RuntimeError) as exc:
            return False, {}, str(exc)
