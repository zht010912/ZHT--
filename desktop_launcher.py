"""Windows desktop launcher for the packaged ActionFlow application.

The installed app keeps user data and optional AI configuration outside the
installation directory, so upgrades and uninstalls never expose a key or erase
meeting data by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import urllib.request
import webbrowser
from pathlib import Path

from werkzeug.serving import BaseWSGIServer, make_server


APP_NAME = "ActionFlow"
DEFAULT_PORT = 8767
USER_SETTING_KEYS = {
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_BASE",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TIMEOUT_SECONDS",
    "MAX_MEETING_CHARS",
    "SEED_DEMO",
}


def _runtime_directory() -> Path:
    configured = os.getenv("ACTIONFLOW_DATA_DIR")
    root = Path(configured) if configured else Path(os.getenv("LOCALAPPDATA", Path.home())) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _load_user_settings(settings_file: Path) -> None:
    """Read the optional per-user settings file without overriding OS env vars."""
    if not settings_file.exists():
        settings_file.write_text(
            "# Optional ActionFlow local settings. Never commit this file.\n"
            "# DEEPSEEK_API_KEY=replace_with_your_key\n"
            "# DEEPSEEK_MODEL=deepseek-v4-flash\n",
            encoding="utf-8",
        )
        return

    for raw_line in settings_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key in USER_SETTING_KEYS and value:
            os.environ.setdefault(key, value)


def configure_runtime() -> Path:
    runtime_dir = _runtime_directory()
    _load_user_settings(runtime_dir / "settings.env")
    os.environ.setdefault("MEETING_DB_PATH", str(runtime_dir / "meeting_assistant.db"))
    return runtime_dir


def _is_actionflow_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.7) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("status") == "ok" and payload.get("database") == "ok"
    except Exception:
        return False


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choose_port(requested_port: int | None) -> tuple[int, bool]:
    preferred = requested_port or int(os.getenv("ACTIONFLOW_PORT", str(DEFAULT_PORT)))
    if _is_actionflow_running(preferred):
        return preferred, True
    if requested_port is not None:
        if not _is_port_available(preferred):
            raise RuntimeError(f"端口 {preferred} 已被其他应用占用。")
        return preferred, False
    for candidate in range(preferred, preferred + 20):
        if _is_port_available(candidate):
            return candidate, False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1], False


def _open_workspace(url: str) -> None:
    webbrowser.open_new_tab(url)


def _show_control_window(url: str, server: BaseWSGIServer | None, reused_server: bool) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("ActionFlow 会议协同工作台")
    root.resizable(False, False)
    root.configure(bg="#f7f8fc")

    frame = ttk.Frame(root, padding=24)
    frame.grid(sticky="nsew")
    ttk.Label(frame, text="ActionFlow 已就绪", font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, sticky="w")
    message = "检测到已有 ActionFlow 服务，已打开工作台。" if reused_server else "工作台已在默认浏览器打开，关闭此窗口即可停止服务。"
    ttk.Label(frame, text=message, wraplength=390).grid(row=1, column=0, pady=(10, 4), sticky="w")
    ttk.Label(frame, text=url, foreground="#4f46e5").grid(row=2, column=0, pady=(0, 18), sticky="w")
    ttk.Button(frame, text="打开工作台", command=lambda: _open_workspace(url)).grid(row=3, column=0, sticky="w")
    close_text = "关闭窗口" if reused_server else "停止服务并退出"

    def close() -> None:
        if server is not None:
            server.shutdown()
        root.destroy()

    ttk.Button(frame, text=close_text, command=close).grid(row=3, column=0, padx=(125, 0), sticky="w")
    ttk.Label(
        frame,
        text="AI 配置可放在 %LOCALAPPDATA%\\ActionFlow\\settings.env，安装包不包含任何 Key。",
        wraplength=390,
        foreground="#667085",
    ).grid(row=4, column=0, pady=(20, 0), sticky="w")
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the packaged ActionFlow desktop application.")
    parser.add_argument("--headless", action="store_true", help="Run the local server without opening a window.")
    parser.add_argument("--port", type=int, help="Use one explicit local port (headless/testing use).")
    args = parser.parse_args()

    configure_runtime()
    port, reused_server = choose_port(args.port)
    url = f"http://127.0.0.1:{port}"

    if reused_server:
        if not args.headless:
            _open_workspace(url)
            _show_control_window(url, None, reused_server=True)
        return 0

    from meeting_assistant.web import create_app

    server = make_server("127.0.0.1", port, create_app(), threaded=True)
    if args.headless:
        server.serve_forever()
        return 0

    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    _open_workspace(url)
    _show_control_window(url, server, reused_server=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
