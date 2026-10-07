"""VirtualSpot 核心邏輯與舊介面（ttk）。新介面在 ui_modern.py，啟動器是 app.py。"""
import json
import math
import os
import queue
import random
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

import tkintermapview

from device import Device
import i18n
from i18n import to_zh, tr as _t
from geo import (dist, fmt_coord, jitter_factor, offset, parse_coords, parse_gpx, resample, route_progress,
                 simplify, to_gpx)
from routing import PROFILES, fetch_route, search_places
import tunnel
from storage import load_favorites, load_recents, load_settings, save_favorites, save_settings
from updater import check_latest, is_newer
from version import __version__

# 以 --windowed 打包成視窗程式後沒有主控台，sys.stdout / stderr 會是 None，
# 部分套件（如 pymobiledevice3）會因此出錯，所以先接到空裝置。
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

TICK_MS = 200
TAIWAN_VIEW = (23.7, 121.0)    # 開啟時只把地圖移到台灣全景，不設定任何位置
TILES = {  # 名稱: (圖磚網址, 最大縮放)
    "一般 (OSM)": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", 19),
    "衛星 (Esri)": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", 19),
    "地形 (OpenTopoMap)": ("https://tile.opentopomap.org/{z}/{x}/{y}.png", 17),
}
KEYS = {"w": (0, 1), "up": (0, 1), "s": (0, -1), "down": (0, -1),
        "a": (-1, 0), "left": (-1, 0), "d": (1, 0), "right": (1, 0)}


class App:
    def __init__(self, root):
        self.root = root
        root.title("VirtualSpot")
        try:
            from app_icon import ICON_PNG_B64
            self._icon = tk.PhotoImage(data=ICON_PNG_B64)   # 要留著參照，否則圖示會被回收
            root.iconphoto(True, self._icon)
        except Exception:  # noqa: BLE001  圖示失敗不影響使用
            pass
        root.geometry("1150x820")

        self.dev = Device()
        self.ui_q = queue.Queue()
        self.keys = set()
        self.favs = load_favorites()
        self.recents = load_recents()
        self._was_connected = False

        self.pos = None                 # 使用者選定位置之前為 None，也不會送任何座標給 iPhone
        self.marker = None
        self.waypoints, self.wp_markers = [], []
        self.route, self.route_path = [], None
        self.play_points, self.idx, self.direction, self.acc = [], 0, 1, 0.0
        self.playing = False

        self.mode = tk.StringVar(value="teleport")
        self.speed = tk.DoubleVar(value=5)
        self.snap = tk.BooleanVar(value=True)
        self.transport = tk.StringVar(value="步行")
        self.loop = tk.BooleanVar(value=True)
        self.pingpong = tk.BooleanVar(value=False)
        self.follow = tk.BooleanVar(value=True)
        self.tiles = tk.StringVar(value="一般 (OSM)")
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="尚未連接 iPhone（仍可在地圖上規劃並匯出 GPX）")
        self.coord = tk.StringVar()
        self.jitter = tk.BooleanVar(value=False)       # 播放路線時速度自然浮動（±10%）
        self._jit, self._jit_t = 1.0, 0.0
        self._load_prefs()

        self._build_ui()
        self.map.set_position(*TAIWAN_VIEW)
        self.map.set_zoom(8)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<KeyPress>", self.on_key_down)
        root.bind("<KeyRelease>", lambda e: self.keys.discard(e.keysym.lower()))
        root.bind("<FocusOut>", lambda e: self.keys.clear())
        root.after(TICK_MS, self.tick)
        root.after(2000, lambda: self.check_update(manual=False))
        self.dev.set_auto(load_settings().get("auto_connect", True))   # 插上 iPhone 就自動連線

    # ---------- 記住上次的設定（速度、交通方式、速度浮動；不記位置，避免一開就送出舊座標）----------
    def _load_prefs(self):
        s = load_settings()
        sp = s.get("speed")
        if isinstance(sp, (int, float)) and not isinstance(sp, bool) and 1 <= sp <= 30:
            self.speed.set(float(sp))
        if s.get("transport") in PROFILES:
            self.transport.set(s["transport"])
        if isinstance(s.get("speed_jitter"), bool):
            self.jitter.set(s["speed_jitter"])

    def _save_prefs(self):
        try:
            s = load_settings()
            s.update(speed=round(float(self.speed.get()), 1), transport=to_zh(self.transport.get()),
                     speed_jitter=bool(self.jitter.get()))
            save_settings(s)
        except Exception:  # noqa: BLE001  存不起來不影響關閉
            pass

    def _speed_factor(self, dt):
        """速度浮動：開啟時每 2~5 秒換一個 0.9~1.1 倍的倍率，關閉時固定 1。"""
        if not self.jitter.get():
            return 1.0
        self._jit_t -= dt
        if self._jit_t <= 0:
            self._jit, self._jit_t = jitter_factor(0.1), random.uniform(2, 5)
        return self._jit

    # ---------- UI ----------
    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=6)
        outer.pack(side="left", fill="y")
        # 狀態列與座標先排版（貼在最下方），視窗再矮也不會被切掉
        ttk.Label(outer, textvariable=self.status, wraplength=250, foreground="#b00").pack(
            side="bottom", anchor="w", pady=4)
        ttk.Label(outer, textvariable=self.coord, font=("Consolas", 10)).pack(side="bottom", anchor="w")
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)
        side = ttk.Frame(nb, padding=10)
        lib = ttk.Frame(nb, padding=10)
        nb.add(side, text="控制")
        nb.add(lib, text="資料庫")

        ttk.Button(side, text="連接 iPhone", command=self.connect_device).pack(fill="x")
        ttk.Button(side, text="還原真實定位", command=self.dev.clear).pack(fill="x", pady=(4, 10))

        ttk.Label(side, text="地圖樣式：").pack(anchor="w")
        cb = ttk.Combobox(side, textvariable=self.tiles, values=list(TILES), state="readonly")
        cb.pack(fill="x", pady=(0, 10))
        cb.bind("<<ComboboxSelected>>", self.set_tiles)

        ttk.Label(side, text="點地圖時：").pack(anchor="w")
        ttk.Radiobutton(side, text="瞬移", value="teleport", variable=self.mode).pack(anchor="w")
        ttk.Radiobutton(side, text="加路線點", value="waypoint", variable=self.mode).pack(anchor="w")

        ttk.Label(side, text="座標 (25.03,121.56) 或地名：").pack(anchor="w", pady=(10, 0))
        e = ttk.Entry(side, textvariable=self.query)
        e.pack(fill="x")
        e.bind("<Return>", lambda _e: self.go())
        ttk.Button(side, text="前往", command=self.go).pack(fill="x", pady=(2, 10))

        row = ttk.Frame(side); row.pack(fill="x")
        ttk.Checkbutton(row, text="沿道路", variable=self.snap).pack(side="left")
        ttk.Combobox(row, textvariable=self.transport, values=["步行", "開車", "騎車"],
                     width=6, state="readonly").pack(side="left", padx=6)
        self.route_btn = ttk.Button(side, text="生成路線", command=self.build_route)
        self.route_btn.pack(fill="x", pady=(4, 0))
        row = ttk.Frame(side); row.pack(fill="x", pady=4)
        ttk.Button(row, text="復原一點", command=self.undo_waypoint).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="清除路線", command=self.clear_route).pack(side="left", expand=True, fill="x")

        ttk.Label(side, text="速度 (m/s)：").pack(anchor="w", pady=(10, 0))
        ttk.Scale(side, from_=1, to=30, variable=self.speed).pack(fill="x")
        ttk.Label(side, text="步行≈1.4　跑步≈3　騎車≈5　開車≈15").pack(anchor="w")

        self.play_btn = ttk.Button(side, text="播放路線", command=self.toggle_play)
        self.play_btn.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(side, text="循環", variable=self.loop).pack(anchor="w")
        ttk.Checkbutton(side, text="來回", variable=self.pingpong).pack(anchor="w")
        ttk.Checkbutton(side, text="地圖跟隨", variable=self.follow).pack(anchor="w")
        ttk.Button(side, text="匯出 GPX", command=self.export_gpx).pack(fill="x", pady=(10, 0))

        ttk.Label(side, text="鍵盤 WASD / 方向鍵 自由移動").pack(anchor="w", pady=(10, 0))

        ttk.Button(lib, text="匯入 GPX", command=self.import_gpx).pack(fill="x")
        row = ttk.Frame(lib); row.pack(fill="x", pady=4)
        ttk.Button(row, text="儲存路線", command=self.save_route).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="載入路線", command=self.load_route).pack(side="left", expand=True, fill="x")
        ttk.Separator(lib).pack(fill="x", pady=10)
        ttk.Label(lib, text="收藏地點（雙擊前往）：").pack(anchor="w")
        self.fav_list = tk.Listbox(lib, height=14, exportselection=False)
        self.fav_list.pack(fill="both", expand=True)
        self.fav_list.bind("<Double-Button-1>", lambda _e: self.fav_go())
        row = ttk.Frame(lib); row.pack(fill="x", pady=4)
        ttk.Button(row, text="收藏目前位置", command=self.add_fav).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="刪除", command=self.del_fav).pack(side="left", expand=True, fill="x")
        self.refresh_favs()
        ttk.Separator(lib).pack(fill="x", pady=10)
        ttk.Button(lib, text="檢查更新", command=lambda: self.check_update(manual=True)).pack(fill="x", pady=4)
        ttk.Button(lib, text="儲存診斷報告", command=self.run_diagnose).pack(fill="x", pady=4)

        self.map = tkintermapview.TkinterMapView(self.root, corner_radius=0)
        self.map.pack(side="right", fill="both", expand=True)
        self.map.add_left_click_map_command(self.on_click)

    def set_tiles(self, _e=None):
        url, max_zoom = TILES[self.tiles.get()]
        self.map.set_tile_server(url, max_zoom=max_zoom)
        self.map.set_zoom(min(int(self.map.zoom), max_zoom))
        self.root.focus_set()

    # ---------- 事件 ----------
    def on_key_down(self, e):
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, tk.Listbox)):
            return
        k = e.keysym.lower()
        if k in KEYS:
            self.keys.add(k)

    def on_click(self, coords):
        p = (coords[0], coords[1])
        if self.mode.get() != "waypoint":
            self.playing = False
            self.play_btn.config(text="播放路線")
            self.set_pos(p)
        else:
            self.waypoints.append(p)
            self.wp_markers.append(self.map.set_marker(p[0], p[1], text=str(len(self.waypoints))))

    def go(self):
        text = self.query.get().strip()
        if not text:
            return
        coords = parse_coords(text)
        if coords:
            self.playing = False
            self.play_btn.config(text="播放路線")
            self.set_pos(coords)
            return
        self.status.set("搜尋中…")
        lang = "en" if i18n.get_lang() == "en" else "zh-TW"

        def work():
            res, err = [], None
            try:
                res = search_places(text, 5, lang)
            except Exception as e:  # noqa: BLE001  Nominatim 連不上時，退回地圖套件內建的查詢
                err = e
                try:
                    c = tkintermapview.convert_address_to_coordinates(text)
                    if c:
                        res, err = [{"name": text, "lat": c[0], "lon": c[1]}], None
                except Exception:  # noqa: BLE001
                    pass
            self.ui_q.put(lambda: self.on_search_results(res, err))
        threading.Thread(target=work, daemon=True).start()

    def on_search_results(self, results, err=None):
        """搜尋結果回來了：沒有 → 提示；一個 → 直接前往；多個 → 交給 show_candidates 讓使用者選。"""
        if err is not None and not results:
            self.status.set(f"搜尋失敗：{err}")
        elif not results:
            self.status.set("找不到這個地點")
        elif len(results) == 1:
            self.goto_result(results[0])
        else:
            self.show_candidates(results)

    def show_candidates(self, results):
        """舊介面沒有選單，直接前往第一個結果；新介面會覆寫成可以選的清單。"""
        self.goto_result(results[0])

    def goto_result(self, r):
        self.playing = False
        self.play_btn.config(text="播放路線")
        self.set_pos((r["lat"], r["lon"]))
        self.status.set("已前往：" + r["name"].split(",")[0].strip())

    # ---------- 路線 ----------
    def build_route(self):
        if len(self.waypoints) < 2:
            self.status.set("至少需要 2 個路線點")
            return
        pts, snap, tr = list(self.waypoints), self.snap.get(), self.transport.get()
        self.route_btn.config(state="disabled")
        self.status.set("計算路線中…")

        def work():
            try:
                path, msg = (fetch_route(pts, tr) if snap else pts), "路線完成"
            except Exception as e:  # noqa: BLE001
                path, msg = pts, f"導航失敗，改用直線：{e}"
            self.ui_q.put(lambda: self.set_route(path, msg))
        threading.Thread(target=work, daemon=True).start()

    def set_route(self, path, msg):
        self.playing = False
        self.play_btn.config(text="播放路線")
        self.route_btn.config(state="normal")
        self.route, self.play_points, self.idx, self.direction = path, [], 0, 1
        if self.route_path:
            self.route_path.delete()
        # 畫面上只畫簡化後的線（點太多地圖會很卡）；播放和匯出仍用完整路線
        self.route_path = self.map.set_path(simplify(path), color="#ff8800", width=5) if len(path) > 1 else None
        self.status.set(msg)

    def undo_waypoint(self):
        if self.waypoints:
            self.waypoints.pop()
            self.wp_markers.pop().delete()

    def clear_route(self):
        self.playing = False
        self.play_btn.config(text="播放路線")
        for m in self.wp_markers:
            m.delete()
        self.waypoints, self.wp_markers = [], []
        self.route, self.play_points, self.idx = [], [], 0
        if self.route_path:
            self.route_path.delete()
            self.route_path = None

    def toggle_play(self):
        if self.playing:
            self.playing = False
            self.play_btn.config(text="播放路線")
            return
        if len(self.route) < 2:
            self.status.set("請先生成路線")
            return
        if not self.play_points:
            self.play_points, self.idx = resample(self.route, 1), 0   # 每 1 公尺一點
        self.direction = 1
        self.set_pos(self.play_points[self.idx])
        self.playing = True
        self.play_btn.config(text="暫停")

    def route_progress(self):
        """(已走比例, 剩餘秒數)；還沒開始播放時為 (0, 全程秒數)。"""
        pts = self.play_points
        if pts:
            return route_progress(self.idx, len(pts), self.direction, self.speed.get())
        if len(self.route) > 1:
            total = sum(dist(a, b) for a, b in zip(self.route, self.route[1:]))
            return 0.0, total / max(self.speed.get(), 0.1)
        return 0.0, 0.0

    def seek_route(self, frac):
        """跳到路線的某個位置（0~1）。播放中會從那裡繼續走。"""
        if len(self.route) < 2:
            return
        if not self.play_points:
            self.play_points = resample(self.route, 1)
        self.idx = max(0, min(len(self.play_points) - 1, int(round(float(frac) * (len(self.play_points) - 1)))))
        self.set_pos(self.play_points[self.idx])

    def export_gpx(self):
        pts = resample(self.route, max(self.speed.get(), 1)) if len(self.route) > 1 else ([self.pos] if self.pos else [])
        if not pts:
            self.status.set("沒有可匯出的內容：請先選位置或建立路線")
            return
        path = filedialog.asksaveasfilename(defaultextension=".gpx", filetypes=[("GPX", "*.gpx")],
                                            initialfile="route.gpx")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(to_gpx(pts, 1.0))
            self.status.set(f"已匯出 {len(pts)} 個點")

    # ---------- 匯入 / 儲存 / 收藏 ----------
    def import_gpx(self):
        path = filedialog.askopenfilename(filetypes=[("GPX", "*.gpx"), (_t("所有檔案"), "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                pts = parse_gpx(f.read())
        except Exception as e:  # noqa: BLE001
            self.status.set(f"GPX 讀取失敗：{e}")
            return
        if len(pts) < 2:
            self.status.set("GPX 內沒有足夠的座標點")
            return
        self.clear_route()
        self.set_route(pts, f"已匯入 {len(pts)} 個點")
        self.set_pos(pts[0])
        lats, lons = [p[0] for p in pts], [p[1] for p in pts]
        self.map.fit_bounding_box((max(lats), min(lons)), (min(lats), max(lons)))

    def save_route(self):
        if len(self.route) < 2:
            self.status.set("請先生成或匯入路線")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="route.json",
                                            filetypes=[(_t("VirtualSpot 路線"), "*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"waypoints": self.waypoints, "route": self.route}, f)
            self.status.set("路線已儲存")

    def load_route(self):
        path = filedialog.askopenfilename(filetypes=[(_t("VirtualSpot 路線"), "*.json"), (_t("所有檔案"), "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            wps = [(float(a), float(b)) for a, b in data["waypoints"]]
            route = [(float(a), float(b)) for a, b in data["route"]]
            if len(route) < 2:
                raise ValueError("路線座標不足")
        except Exception as e:  # noqa: BLE001
            self.status.set(f"路線讀取失敗：{e}")
            return
        self.clear_route()
        self.waypoints = wps
        self.wp_markers = [self.map.set_marker(p[0], p[1], text=str(i + 1)) for i, p in enumerate(wps)]
        self.set_route(route, f"已載入路線（{len(route)} 點）")
        self.set_pos(route[0])

    def refresh_favs(self):
        self.fav_list.delete(0, "end")
        for f in self.favs:
            self.fav_list.insert("end", f["name"])

    def add_fav(self):
        if self.pos is None:
            self.status.set("請先選一個位置再收藏")
            return
        name = simpledialog.askstring(_t("收藏"), _t("名稱："), parent=self.root)
        if name is None:
            return
        name = name.strip() or fmt_coord(*self.pos)
        self.favs.append({"name": name, "lat": self.pos[0], "lon": self.pos[1]})
        save_favorites(self.favs)
        self.refresh_favs()

    def _selected_fav_index(self):
        sel = self.fav_list.curselection()
        return sel[0] if sel else None

    def fav_go(self):
        i = self._selected_fav_index()
        if i is not None:
            self.playing = False
            self.play_btn.config(text="播放路線")
            self.set_pos((self.favs[i]["lat"], self.favs[i]["lon"]))

    def del_fav(self):
        i = self._selected_fav_index()
        if i is not None:
            del self.favs[i]
            save_favorites(self.favs)
            self.refresh_favs()

    def on_close(self):
        """關閉視窗前先還原真實定位，避免手機卡在假位置。"""
        self.dev.set_auto(False)             # 關閉中，不要再自動重連
        self._save_prefs()
        def finish():
            tunnel.stop()                    # 只會關掉本程式自己啟動的 tunneld
            self.root.destroy()

        if not self.dev.connected:
            finish()
            return
        self.dev.clear()
        deadline = time.monotonic() + 3

        def wait():
            if self.dev.connected and time.monotonic() < deadline:
                self.root.after(100, wait)
            else:
                finish()
        wait()

    # ---------- 檢查更新 ----------
    def check_update(self, manual=False):
        def work():
            try:
                tag, url = check_latest()
            except Exception as e:  # noqa: BLE001
                if manual:
                    self.ui_q.put(lambda: self.status.set(f"檢查更新失敗：{e}"))
                return
            if is_newer(tag, __version__):
                if manual or tag != load_settings().get("skipped_version"):
                    self.ui_q.put(lambda: self.ask_update(tag, url))
            elif manual:
                self.ui_q.put(lambda: self.status.set("已是最新版"))
        threading.Thread(target=work, daemon=True).start()

    def ask_update(self, tag, url):
        win = tk.Toplevel(self.root)
        win.title(_t("發現新版本"))
        win.transient(self.root)
        win.resizable(False, False)
        ttk.Label(win, padding=16, justify="center",
                  text=f"發現新版本 {tag}（目前 v{__version__}）\n要更新嗎？按「更新」會開啟下載頁面。").pack()
        skip = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="不再提醒此版本", variable=skip).pack()
        row = ttk.Frame(win, padding=12)
        row.pack()

        def do_update():
            webbrowser.open(url)
            win.destroy()

        def no_update():
            if skip.get():
                s = load_settings()
                s["skipped_version"] = tag
                save_settings(s)
            win.destroy()

        ttk.Button(row, text="更新", command=do_update).pack(side="left", padx=6)
        ttk.Button(row, text="不更新", command=no_update).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", no_update)
        win.grab_set()

    def run_diagnose(self):
        self.status.set("診斷中…約 20 秒。若 iPhone 未連線，會短暫把定位設到台北 101 再還原" if not self.dev.connected else "診斷中…約 20 秒")

        def work():
            try:
                import diagnose
                path = diagnose.run(connect=not self.dev.connected)
                msg = f"診斷報告已存到 {path}"
            except Exception as e:  # noqa: BLE001
                msg = f"診斷失敗：{type(e).__name__}: {e}"
            self.ui_q.put(lambda: self.status.set(msg))
        threading.Thread(target=work, daemon=True).start()

    def connect_device(self):
        self.status.set("連接中…（第一次需要在 iPhone 按「信任」，可能要等幾十秒）")
        self.dev.connect()

    # ---------- 位置 ----------
    def set_pos(self, p):
        self.pos = (p[0], p[1])
        if self.marker is None:
            self.marker = self.map.set_marker(self.pos[0], self.pos[1], text=_t("目前位置"))
        else:
            self.marker.set_position(*self.pos)
        if self.follow.get():
            self._follow_map(self.pos)
        self.coord.set(fmt_coord(*self.pos))
        if self._should_send():
            self.dev.set(*self.pos)

    def _should_send(self):
        """目前是否要把位置送給 iPhone。舊介面：只要連上就送；新介面：要按了「開始定位」才送。"""
        return True

    def on_connected(self):
        """剛連上 iPhone 時呼叫一次。"""
        if self.pos is None:
            self.status.set("已連接 iPhone。請點地圖或輸入座標，手機才會開始移動")
        elif self._should_send():
            self.dev.set(*self.pos)

    def _follow_map(self, pos):
        """地圖跟隨：重畫地圖很吃力，每個時間格都置中會卡住。
        只有標記離上次置中的位置夠遠（超過可視範圍的約 3 成）、或大幅跳躍時才重新置中，且最少間隔 0.5 秒。"""
        now = time.monotonic()
        last = getattr(self, "_follow_center", None)
        if last is not None:
            try:
                mpp = 156543.03392 * math.cos(math.radians(pos[0])) / (2 ** float(self.map.zoom))
                half = 0.5 * min(self.map.winfo_width(), self.map.winfo_height()) * mpp
            except Exception:  # noqa: BLE001  量不到就退回「只受時間限制」
                half = 0.0
            d = dist(last, pos)
            if half > 0:
                if d <= 0.3 * half:
                    return                                     # 還在畫面中央附近，不必動地圖
                if d <= half and now - self._follow_t < 0.5:
                    return                                     # 最多每 0.5 秒置中一次
            elif now - self._follow_t < 0.5:
                return
            # d > half：標記已經跳出畫面（例如快速定位到很遠的地方），一律立刻置中
        self._follow_center, self._follow_t = pos, now
        self.map.set_position(*pos)

    def tick(self):
        try:
            try:
                while True:
                    self.ui_q.get_nowait()()
            except queue.Empty:
                pass
            try:
                while True:
                    self.status.set(self.dev.messages.get_nowait())
            except queue.Empty:
                pass

            if self.dev.connected and not self._was_connected:
                self.on_connected()
            self._was_connected = self.dev.connected
            self.after_tick()

            dt = TICK_MS / 1000
            if self.playing:
                self.step_play(dt)
            else:
                self.step_keys(dt)
        except Exception as e:  # noqa: BLE001  單次出錯不能讓整個主迴圈停掉
            self.status.set(f"內部錯誤：{type(e).__name__}: {e}")
        finally:
            self.root.after(TICK_MS, self.tick)

    def after_tick(self):
        """每個時間格呼叫一次，給新介面更新畫面用（舊介面不需要）。"""

    def step_play(self, dt):
        self.acc += self.speed.get() * dt * self._speed_factor(dt)
        n = int(self.acc)
        self.acc -= n
        if n <= 0 or not self.play_points:
            return
        count = len(self.play_points)
        i = self.idx + n * self.direction
        if i >= count:
            if self.loop.get():
                if self.pingpong.get():
                    self.direction, i = -1, count - 1
                else:
                    i = 0
            else:
                i, self.playing = count - 1, False
                self.play_btn.config(text="播放路線")
        elif i < 0:
            if self.loop.get():
                self.direction, i = 1, 0
            else:
                i, self.playing = 0, False
                self.play_btn.config(text="播放路線")
        self.idx = i
        self.set_pos(self.play_points[i])

    def step_keys(self, dt):
        dx = sum(KEYS[k][0] for k in self.keys)
        dy = sum(KEYS[k][1] for k in self.keys)
        mag = math.hypot(dx, dy)
        if mag == 0:
            return
        if self.pos is None:
            self.status.set("請先在地圖上選一個起點（點地圖或輸入座標）")
            return
        d = self.speed.get() * dt
        self.set_pos(offset(self.pos, dy / mag * d, dx / mag * d))

