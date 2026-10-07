"""iPhone 定位模擬後端（透過 USB，使用 Apple 開發者服務，與 Xcode 的 Simulate Location 同一機制）。

新版 pymobiledevice3 已改成 asyncio；舊版是同步 API。這裡的 `_aw()` 會自動判斷：
回傳的是協程就 await，不是就直接用，所以兩種版本都能跑。
所有裝置操作都在一條背景事件迴圈執行，UI 不會被卡住；連續的 set 只送最新一筆。

注意：pymobiledevice3 的 API 仍可能隨版本變動，這個檔案是整個專案唯一與它耦合的地方。
如果連線失敗，先用官方 CLI 確認環境沒問題：
    pymobiledevice3 developer dvt simulate-location set -- 25.033 121.5654
CLI 能動但這裡不行，就只需要調整 _connect()。
"""
import asyncio
import inspect
import json
import os
import queue
import threading
import time
import traceback
import urllib.request

import tunnel
from geo import fmt_coord
from storage import DIR

TUNNELD = "http://127.0.0.1:49151"


async def _aw(x):
    """x 若是 awaitable 就 await，否則原樣回傳。"""
    return await x if inspect.isawaitable(x) else x


class Device:
    CONNECT_TIMEOUT = 60                   # 連線整體逾時（秒）
    AUTO_FIRST = 1.5                       # 自動連線：啟動後第一次嘗試的等待秒數
    AUTO_DELAY = 3.0                       # 自動連線：找不到 iPhone 時的重試間隔
    AUTO_ERR_DELAY = 15.0                  # 自動連線：遇到其他錯誤時的重試間隔（同一個錯誤只提示一次）
    NO_DEVICE = ("NoDeviceConnectedError", "DeviceNotFoundError")   # 沒插手機是正常狀態，不吵使用者

    def __init__(self):
        self.messages = queue.Queue()      # 給 UI 顯示的狀態訊息
        self.on_progress = None            # 診斷工具用：收到進度訊息時呼叫
        self._step = ""                    # 目前進行到哪一步（逾時時用來定位）
        self._busy = False                 # 正在連線中（避免手動與自動同時連）
        self._quiet = False                # 自動嘗試時，找到 iPhone 之前不顯示進度
        self._auto = False
        self._auto_started = False
        self.ios_version = ""              # 已連接的 iPhone 的 iOS 版本（沒連線時為空字串）
        self.connected = False
        self._sim = None
        self._dvt = None
        self._rsd = None
        self._latest = None                # 尚未送出的最新座標
        self._sending = False
        self._last_msg = 0.0
        self._lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    # --- 給 UI 呼叫（非阻塞）---
    def connect(self):
        if not self.connected and not self._busy:
            self._submit(self._connect())

    def set_auto(self, on):
        """自動連接 iPhone：插上就連線、拔掉再插也會自動重連，不用手動按連接。"""
        self._auto = bool(on)
        if on and not self._auto_started:
            self._auto_started = True
            self._submit(self._auto_loop())

    @property
    def connected(self):
        return self._connected

    @connected.setter
    def connected(self, value):
        self._connected = bool(value)
        if not self._connected:
            self.ios_version = ""          # 斷線就清掉版本號

    def clear(self):
        self._submit(self._clear())

    def set(self, lat, lon):
        if not self.connected:
            return
        with self._lock:
            self._latest = (lat, lon)
            if self._sending:
                return
            self._sending = True
        self._submit(self._drain())

    # --- 內部 ---
    def _submit(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _progress(self, msg):
        self._step = msg
        if self._quiet:
            return
        self.messages.put(msg)
        if self.on_progress:
            self.on_progress(msg)

    def _describe(self, e):
        """把例外轉成使用者看得懂的說明。"""
        log = os.path.join(DIR, "device.log")
        hints = {
            "ConnectionFailedToUsbmuxdError":
                "連不到 Apple Mobile Device Service：請安裝 iTunes 或 Microsoft Store 的「Apple 裝置」，"
                "確認服務已啟動，並讓 iPhone 解鎖、信任此電腦",
            "NoDeviceConnectedError": "找不到 iPhone：請用 USB 連接、解鎖並信任此電腦",
            "DeviceNotFoundError": "找不到 iPhone：請用 USB 連接、解鎖並信任此電腦",
            "DeveloperModeIsNotEnabledError":
                "iPhone 尚未開啟開發者模式：設定 → 隱私權與安全性 → 開發者模式，開啟後重新開機再連線",
            "UserDeniedPairingError":
                "iPhone 上按過「不信任」：到 設定 → 一般 → 移轉或重置 iPhone → 重置 → 重置位置與隱私權，再重新連線",
            "PairingError": "配對失敗：請解鎖 iPhone，並在跳出的視窗按「信任」",
        }
        hint = hints.get(type(e).__name__)
        if hint is None and ("dtservicehub" in str(e) or "InvalidService" in type(e).__name__):
            hint = ("iPhone 尚未掛載 Developer Disk Image（開發者磁碟映像）。"
                    "請先用 Xcode、3uTools、愛思助手，或 pymobiledevice3 的 mounter 指令掛載一次後再連線")
        if type(e).__name__ == "TimeoutError":
            hint = (f"連線逾時，卡在「{self._step}」。請確認 iPhone 已解鎖並信任此電腦、"
                    "沒有其他程式（例如另一個 VirtualSpot）同時在連接 iPhone")
        return hint or f"{type(e).__name__}: {e}（完整記錄：{log}）"

    @staticmethod
    def _log_exc():
        """把目前這個例外的完整堆疊寫進 device.log（要在 except 區塊內呼叫）。"""
        try:
            os.makedirs(DIR, exist_ok=True)
            with open(os.path.join(DIR, "device.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except OSError:
            pass

    def _fail(self, e):
        self.connected = False
        self._log_exc()
        self.messages.put(f"裝置錯誤：{self._describe(e)}")

    async def _drain(self):
        while True:
            with self._lock:
                item, self._latest = self._latest, None
                if item is None:
                    self._sending = False
                    return
            if self._sim is None:
                with self._lock:
                    self._latest, self._sending = None, False
                return
            try:
                await _aw(self._sim.set(*item))
                if time.monotonic() - self._last_msg > 2:   # 讓使用者知道座標確實送出了（最多每 2 秒一次）
                    self._last_msg = time.monotonic()
                    self.messages.put(f"已送出座標 {fmt_coord(*item)}")
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._latest, self._sending = None, False
                self._fail(e)
                return

    async def _clear(self):
        if not self._sim:
            return
        ok = True
        try:
            await _aw(self._sim.clear())
        except Exception as e:  # noqa: BLE001
            ok = False
            self._fail(e)
        await self._disconnect()          # 無論 clear 成功與否都中斷連線：連線一結束，模擬定位就會停止
        if ok:
            self.messages.put("已還原真實定位並中斷連線。手機地圖若還沒變，請重開地圖 App 並等幾秒；要再模擬請按「連接 iPhone」")

    async def _disconnect(self):
        self.connected = False
        with self._lock:
            self._latest, self._sending = None, False
        for obj in (self._sim, self._dvt, self._rsd):      # 由內而外關閉
            if obj is None:
                continue
            try:
                if hasattr(obj, "__aexit__"):
                    await obj.__aexit__(None, None, None)
                elif hasattr(obj, "close"):
                    await _aw(obj.close())
                elif hasattr(obj, "__exit__"):
                    obj.__exit__(None, None, None)
            except Exception:  # noqa: BLE001  關閉時的錯誤不重要
                pass
        self._sim = self._dvt = self._rsd = None

    async def _connect(self):
        if self._busy:
            return
        self._busy = True
        try:
            await asyncio.wait_for(self._do_connect(), self.CONNECT_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            self._fail(e)
        finally:
            self._busy = False

    async def _auto_loop(self):
        delay, last_err = self.AUTO_FIRST, None
        while True:
            await asyncio.sleep(delay)
            delay = self.AUTO_DELAY
            if not self._auto or self.connected or self._busy:
                continue
            self._busy = True
            try:
                await asyncio.wait_for(self._do_connect(quiet=True), self.CONNECT_TIMEOUT)
                last_err = None
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ in self.NO_DEVICE:
                    last_err = None
                else:
                    text = self._describe(e)
                    if text != last_err:                 # 同一個錯誤只提示一次，之後安靜地重試
                        last_err = text
                        self._log_exc()
                        self.messages.put(f"裝置錯誤：{text}")
                    delay = self.AUTO_ERR_DELAY
            finally:
                self._busy = False
                self._quiet = False

    async def _do_connect(self, quiet=False):
        self._quiet = quiet
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
        except ImportError:
            raise RuntimeError("尚未安裝 pymobiledevice3（pip install pymobiledevice3）")

        self._progress("1/4 尋找 iPhone…（第一次需要在 iPhone 按「信任」）")
        lockdown = await _aw(create_using_usbmux())
        version = str(await _aw(lockdown.product_version))
        major = int(version.split(".")[0])
        self._quiet = False                  # 找到 iPhone 了，後續進度才顯示
        self._progress(f"2/4 已找到 iPhone（iOS {version}）")

        if major >= 17:
            # iOS 17+ 需要先在「系統管理員」終端機執行：pymobiledevice3 remote tunneld
            self._progress("3/4 連接 tunneld…（沒有的話會自動啟動，需要系統管理員權限）")
            if not await asyncio.get_running_loop().run_in_executor(None, tunnel.start):
                raise RuntimeError("無法啟動 tunneld：請在跳出的視窗按「是」允許系統管理員權限，並確認沒有防毒軟體擋住")
            rsd = await self._rsd_from_tunneld(await _aw(lockdown.udid))
            self._progress("4/4 開啟開發者服務（DVT）…")
            self._rsd = rsd
            self._dvt = await self._open_dvt(rsd)
            from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

            # 新版的 instrument 服務本身也要「進入」(async with / connect) 才算連線，否則 set() 會丟 not connected
            self._sim = await self._enter(LocationSimulation(self._dvt))
        else:
            from pymobiledevice3.services.simulate_location import DtSimulateLocation

            self._sim = DtSimulateLocation(lockdown)

        self.ios_version = version
        self.connected = True
        self.messages.put(f"已連接 iPhone（iOS {version}）")

    @staticmethod
    async def _open_dvt(rsd):
        try:  # 新版名稱
            from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider as Dvt
        except ImportError:  # 舊版名稱
            from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService as Dvt
        return await Device._enter(Dvt(rsd))

    @staticmethod
    async def _enter(obj):
        """等同 `async with obj as x`（不離開）；依版本退回 connect() 或同步 with。"""
        if hasattr(obj, "__aenter__"):
            got = await obj.__aenter__()
        elif hasattr(obj, "connect"):
            await _aw(obj.connect())
            got = obj
        elif hasattr(obj, "__enter__"):
            got = obj.__enter__()
        else:
            got = obj
        return got if got is not None else obj

    @staticmethod
    async def _rsd_from_tunneld(udid):
        def fetch():
            with urllib.request.urlopen(TUNNELD, timeout=3) as r:
                return json.load(r)

        try:
            data = await asyncio.get_running_loop().run_in_executor(None, fetch)
        except Exception:
            raise RuntimeError("連不到 tunneld：請用系統管理員身分執行 `pymobiledevice3 remote tunneld`")
        entries = data.get(udid) or next(iter(data.values()), None)
        if not entries:
            raise RuntimeError("tunneld 沒有找到裝置，確認 iPhone 已用 USB 連接並信任此電腦")
        e = entries[0]
        from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService

        rsd = RemoteServiceDiscoveryService((e["tunnel-address"], e["tunnel-port"]))
        await _aw(rsd.connect())
        return rsd
