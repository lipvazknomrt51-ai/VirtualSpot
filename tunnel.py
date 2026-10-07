"""內建 tunneld：偵測不到現成的 tunneld 時，自動以子程序啟動（需要系統管理員權限）。
打包成 exe 時，exe 以 `VirtualSpot.exe --tunneld` 重新啟動自己來跑這個服務。"""
import os
import subprocess
import sys
import time
import urllib.request

from storage import DIR

TUNNELD = "http://127.0.0.1:49151"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_proc = None


def is_up():
    try:
        with urllib.request.urlopen(TUNNELD, timeout=1):
            return True
    except Exception:  # noqa: BLE001
        return False


def start(wait=30):
    """確保 tunneld 可用；必要時自動啟動。回傳 True 表示可用。"""
    global _proc
    if is_up():
        return True
    if _proc is None or _proc.poll() is not None:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--tunneld"]
        else:
            app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
            cmd = [sys.executable, app, "--tunneld"]
        _proc = subprocess.Popen(cmd, creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_up():
            return True
        if _proc.poll() is not None:      # 子程序提早結束（通常是沒有系統管理員權限）
            return False
        time.sleep(0.5)
    return False


def stop():
    """只關掉『由本程式啟動』的 tunneld，不動使用者自己開的。"""
    global _proc
    if _proc is not None and _proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(_proc.pid), "/T", "/F"], creationflags=_NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            _proc.terminate()
        try:
            _proc.wait(3)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def run_tunneld_cli():
    """子程序入口：等同執行 `pymobiledevice3 remote tunneld`。記錄寫在 ~/.virtualspot/tunneld.log。"""
    os.makedirs(DIR, exist_ok=True)
    log = open(os.path.join(DIR, "tunneld.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log       # 視窗版 exe 沒有 stdout，且方便除錯
    sys.argv = ["pymobiledevice3", "remote", "tunneld"]
    import runpy

    runpy.run_module("pymobiledevice3", run_name="__main__", alter_sys=True)
