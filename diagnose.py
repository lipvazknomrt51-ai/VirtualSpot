"""連線診斷：逐步檢查 pymobiledevice3 環境，報告存到 ~/.virtualspot/diagnose.txt。
App 內「資料庫」分頁有「儲存診斷報告」按鈕；從原始碼執行也可以：python diagnose.py"""
import asyncio
import importlib
import importlib.metadata as md
import inspect
import json
import os
import pkgutil
import platform
import sys
import traceback

import tunnel
from storage import DIR


async def aw(x):
    return await x if inspect.isawaitable(x) else x


def run(path=None, connect=True):
    """執行診斷並回傳報告路徑。connect=False 時不會實際連線（App 已連線時用，避免兩個連線互搶）。"""
    lines = []

    def out(*a):
        line = " ".join(str(x) for x in a)
        print(line)
        lines.append(line)

    def section(t):
        out("\n=== " + t + " ===")

    section("環境")
    out("python", sys.version.split()[0], platform.platform())
    try:
        out("pymobiledevice3", md.version("pymobiledevice3"))
    except Exception as e:  # noqa: BLE001
        out("pymobiledevice3 未安裝：", e)

    section("模組檢查")
    for m in [
        "pymobiledevice3.lockdown",
        "pymobiledevice3.usbmux",
        "pymobiledevice3.remote.remote_service_discovery",
        "pymobiledevice3.services.simulate_location",
        "pymobiledevice3.services.dvt.instruments.dvt_provider",
        "pymobiledevice3.services.dvt.instruments.location_simulation",
    ]:
        try:
            importlib.import_module(m)
            out("OK  ", m)
        except Exception as e:  # noqa: BLE001
            out("FAIL", m, "->", type(e).__name__, e)

    section("dvt 相關模組清單")
    try:
        import pymobiledevice3.services.dvt as dvt_pkg
        for mod in pkgutil.walk_packages(dvt_pkg.__path__, "pymobiledevice3.services.dvt."):
            out(mod.name)
    except Exception as e:  # noqa: BLE001
        out("無法列出：", e)

    section("USB 裝置")
    try:
        from pymobiledevice3.usbmux import list_devices

        async def _list():
            return await aw(list_devices())

        devs = asyncio.run(_list())
        for d in devs:
            out(d)
        if not devs:
            out("沒有偵測到裝置：確認 USB、信任此電腦、已安裝 iTunes 或 Apple 裝置")
    except Exception:  # noqa: BLE001
        out(traceback.format_exc())

    section("tunneld（iOS 17+ 必須）")
    out("執行中" if tunnel.is_up() else "未執行（連接 iPhone 時 App 會自動啟動，需要系統管理員權限）")

    section("實際連線並設定座標")
    if not connect:
        out("略過：App 目前已連線")
    else:
        try:
            from device import Device

            async def _try():
                d = Device()
                d.on_progress = out
                await asyncio.wait_for(d._do_connect(), 60)
                out("連線成功")
                out("送出座標：台北 101（25.0339, 121.5645），請現在看 iPhone 的地圖 App ...")
                await aw(d._sim.set(25.0339, 121.5645))
                out("set() 沒有丟錯誤。等待後會還原真實定位。")
                await asyncio.sleep(float(os.environ.get("DIAG_WAIT", "15")))
                await aw(d._sim.clear())
                out("已還原真實定位")

            asyncio.run(_try())
        except Exception:  # noqa: BLE001
            out(traceback.format_exc())

    path = path or os.path.join(DIR, "diagnose.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    out("\n報告已存到", path)
    return path


if __name__ == "__main__":
    run()
