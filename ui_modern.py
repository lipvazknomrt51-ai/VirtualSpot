"""新版介面（customtkinter，深色側邊欄風格）。

邏輯全部沿用 core.App，這裡只覆寫「畫面」。載入失敗時 app.py 會自動退回舊介面。
"""
import math
import os
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import filedialog

import customtkinter as ctk
import tkintermapview

import i18n
from i18n import tr

from core import KEYS, TILES, App
from geo import dist, fmt_coord, fmt_duration, offset
from routing import reverse_geocode
from storage import (dump_favorites_json, group_favorites, group_names, load_settings, merge_favorites,
                     parse_favorites_json, push_recent, save_favorites, save_recents, save_settings)
from version import __version__

i18n.install(ctk)      # 讓所有元件文字都能隨語言切換

# ---- 配色：(淺色, 深色) 成對，customtkinter 會依目前外觀自動套用 ----
BG = ("#eef2fa", "#0a1020")
NAV = ("#e3e9f6", "#0d1527")
CARD = ("#ffffff", "#111a2e")
INNER = ("#e9eefa", "#0d1527")
BORDER = ("#cdd6ea", "#1c2a47")
ACCENT = "#1f6bff"
ACCENT_H = "#1a58d1"
NAV_ACTIVE = ("#cfdffc", "#13315e")
TEXT = ("#1a2440", "#e8eefc")
MUTED = ("#5d6c8d", "#8ea0c4")
i18n.FORCE_EN_COLORS.append(MUTED)      # 灰色說明文字一律顯示英文
TOAST = ("#e8f0ff", "#16233f")
JOY_RING = ("#9fb2d9", "#2a3b63")
JOY_FILL = ("#e3ebfa", "#0f1930")
GREEN = "#2ecc71"
RED = "#e5484d"
RED_H = "#c13a3f"
FONT = "Microsoft JhengHei UI"

STYLES = {  # 名稱: (圖磚網址, 最大縮放)
    "深色地圖 (Esri)": ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", 16),
    "一般 (OSM)": TILES["一般 (OSM)"],
    "衛星 (Esri)": TILES["衛星 (Esri)"],
    "地形 (OpenTopoMap)": TILES["地形 (OpenTopoMap)"],
}
DEFAULT_STYLE = "深色地圖 (Esri)"
OVERLAYS = {  # 疊在底圖上的文字標籤圖層（深色底圖本身沒有地名）
    "深色地圖 (Esri)": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
}
SATELLITE_STYLE = "衛星 (Esri)"

QUICK = [  # 快速定位（近似座標，想換就直接改這份清單）
    ("台北 101", 25.0339, 121.5645),
    ("台北車站", 25.0478, 121.5170),
    ("西門町", 25.0421, 121.5081),
    ("淡水老街", 25.1677, 121.4396),
    ("九份老街", 25.1093, 121.8445),
    ("日月潭", 23.8570, 120.9150),
    ("台中國家歌劇院", 24.1623, 120.6400),
    ("高雄駁二", 22.6203, 120.2816),
    ("墾丁大街", 21.9460, 120.7983),
]
TRANSPORTS = ("步行", "開車", "騎車")
MODE_NAMES = {"teleport": "單點定位", "waypoint": "多點路線", "joystick": "搖桿模式"}


def quick_layout(n_spots, cols=2):
    """回傳快速定位每個按鈕的 (row, col)。最後一格固定留給「自訂位置」，永遠排在所有定位點之後。"""
    return [(i // cols, i % cols) for i in range(n_spots + 1)]


def _tile_ok(url_template):
    """試抓一張圖磚，確認這個圖磚來源真的連得到（用和 tkintermapview 相同的 User-Agent）。"""
    url = url_template.format(z=3, x=6, y=3)
    req = urllib.request.Request(url, headers={"User-Agent": "TkinterMapView"})
    with urllib.request.urlopen(req, timeout=6) as r:
        head = r.read(4)
        return r.status == 200 and (head == b"\x89PNG" or head[:2] == b"\xff\xd8")


def is_dark():
    return ctk.get_appearance_mode() == "Dark"


def rc(color):
    """把 (淺色, 深色) 成對的顏色換成目前外觀的單一顏色（給非 customtkinter 的元件用）。"""
    if isinstance(color, (tuple, list)):
        return color[1 if is_dark() else 0]
    return color


def asset_path(name):
    """assets 內的檔案路徑（原始碼執行與 PyInstaller 打包後都適用）。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def load_image(name, size, dark_name=None):
    """載入 assets 圖片成 CTkImage；檔案不見或壞掉時回傳 None（畫面照樣能用，只是沒有圖）。
    dark_name：深色外觀用的另一張圖（沒給就淺色深色共用同一張）。"""
    try:
        from PIL import Image
        img = Image.open(asset_path(name))
        img.load()
        dark = img
        if dark_name:
            dark = Image.open(asset_path(dark_name))
            dark.load()
        return ctk.CTkImage(light_image=img, dark_image=dark, size=size)
    except Exception:  # noqa: BLE001
        return None


class MapStyleToggle(ctk.CTkFrame):
    """地圖／衛星切換：兩顆帶縮圖的按鈕，選中的有藍色外框。介面同 CTkSegmentedButton（set / command）。"""

    def __init__(self, parent, items, command):
        super().__init__(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        self._on_pick, self._buttons, self._value = command, {}, None
        for i, (value, img_name) in enumerate(items):
            b = ctk.CTkButton(self, text=value, image=load_image(img_name, (72, 44)), compound="top",
                              width=84, height=74, font=F(12, True), corner_radius=8, border_width=2,
                              border_color=CARD, fg_color=CARD, hover_color=BORDER, text_color=TEXT,
                              command=lambda v=value: self._click(v))
            b.grid(row=0, column=i, padx=(6, 0 if i == 0 else 6), pady=6)
            self._buttons[value] = b

    def _click(self, value):
        self.set(value)
        self._on_pick(value)

    def set(self, value):
        self._value = value
        for v, b in self._buttons.items():
            b.configure(border_color=ACCENT if v == value else CARD)


def F(size=13, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def card(parent):
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)


def label(parent, text="", size=13, bold=False, color=TEXT, **kw):
    return ctk.CTkLabel(parent, text=text, font=F(size, bold), text_color=color, **kw)


def button(parent, text, command, primary=False, **kw):
    kw.setdefault("height", 36)
    return ctk.CTkButton(
        parent, text=text, command=command, font=F(13), corner_radius=8,
        fg_color=ACCENT if primary else INNER, hover_color=ACCENT_H if primary else BORDER,
        border_width=0 if primary else 1, border_color=BORDER, text_color="#ffffff" if primary else TEXT, **kw)


class _Btn:
    """讓核心邏輯的 button.config(text=..., state=...) 也能控制 CTkButton。"""

    def __init__(self, widget):
        self.w = widget

    def config(self, **kw):
        self.w.configure(**kw)

    configure = config


class _Query:
    """讓核心邏輯的 self.query.get() 讀到輸入框內容。"""

    def __init__(self, entry):
        self.entry = entry

    def get(self):
        return self.entry.get()


class PillSeg(ctk.CTkFrame):
    """小型單選切換（淺色 / 深色 / 系統、中文 / English）。items: [(key, 顯示文字), ...]。"""

    def __init__(self, parent, items, command):
        super().__init__(parent, fg_color=INNER, corner_radius=8, border_width=1, border_color=BORDER)
        self._command, self._btns = command, {}
        for i, (key, text) in enumerate(items):
            b = ctk.CTkButton(self, text=text, width=58, height=26, corner_radius=6, font=F(12),
                              fg_color="transparent", hover_color=BORDER, text_color=TEXT,
                              command=lambda k=key: self._click(k))
            b.grid(row=0, column=i, padx=2, pady=2)
            self._btns[key] = b

    def _click(self, key):
        self.set(key)
        self._command(key)

    def set(self, key):
        for k, b in self._btns.items():
            sel = k == key
            b.configure(fg_color=ACCENT if sel else "transparent", text_color="#ffffff" if sel else TEXT)


class Joystick(tk.Canvas):
    R, KNOB = 55, 22

    def __init__(self, master, on_change):
        super().__init__(master, width=150, height=150, bg=rc(CARD), highlightthickness=0)
        self.on_change = on_change
        self.pad = self.create_oval(75 - self.R, 75 - self.R, 75 + self.R, 75 + self.R,
                                    outline=rc(JOY_RING), width=2, fill=rc(JOY_FILL))
        self.knob = self.create_oval(0, 0, 0, 0, fill=ACCENT, outline="")
        self._move(0, 0)
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)

    def restyle(self):
        """切換淺色 / 深色後，重新套用顏色（這是一般 tk 畫布，不會自動跟著變）。"""
        self.configure(bg=rc(CARD))
        self.itemconfig(self.pad, outline=rc(JOY_RING), fill=rc(JOY_FILL))

    def _move(self, dx, dy):
        k = self.KNOB
        self.coords(self.knob, 75 + dx - k, 75 + dy - k, 75 + dx + k, 75 + dy + k)

    def _drag(self, e):
        dx, dy = e.x - 75, e.y - 75
        d = math.hypot(dx, dy)
        if d > self.R:
            dx, dy = dx * self.R / d, dy * self.R / d
        self._move(dx, dy)
        self.on_change((dx / self.R, -dy / self.R))      # 上為正

    def _release(self, _e):
        self._move(0, 0)
        self.on_change((0.0, 0.0))


class ModernApp(App):
    # ------------------------------------------------------------------ 組版
    def _build_ui(self):
        r = self.root
        r.configure(fg_color=BG)
        r.geometry("1320x820")
        r.minsize(1100, 700)
        r.after(400, self._fix_icon)         # CTk 會在 200ms 後換成預設圖示，所以晚一點再設

        self.joy = (0.0, 0.0)
        self.sim_active = False         # 使用者按了「開始定位」（與是否已連上 iPhone 分開）
        self._ui_conn = None
        self._connecting_until = 0.0
        self._geo_pos, self._geo_t, self._geo_busy = None, 0.0, False
        self._speed_labels = []
        self._nav_btns = {}
        self.status_view = tk.StringVar(value="")      # 畫面上顯示的狀態文字（已依語言轉換）
        self._dark_ok = False
        self._cur_style = "一般 (OSM)"
        self._last_mode = ctk.get_appearance_mode()

        r.grid_columnconfigure(2, weight=1)
        r.grid_rowconfigure(0, weight=1)
        self._build_nav()
        self._build_panel()
        self._build_right()
        self.status.trace_add("write", self._on_status)
        self._on_status()

        self.set_mode("teleport")
        self.show_page("dashboard")
        self._refresh_speed_labels()
        self._set_sim_ui(False, False)
        # 先用最穩的一般地圖；深色地圖確認連得到才切換，連不到就維持一般地圖，不會出現空白地圖
        self._base_style = "一般 (OSM)"
        self.set_map_style(self._base_style)
        threading.Thread(target=self._pick_dark_style, daemon=True).start()
        self.root.after(3000, self._theme_poll)

    def _pick_dark_style(self):
        try:
            ok = _tile_ok(STYLES[DEFAULT_STYLE][0])
        except Exception:  # noqa: BLE001
            ok = False

        def apply():
            self._dark_ok = ok
            self._sync_base_style()
            if not ok and is_dark():
                self.status.set("深色地圖載入不了，先使用一般地圖（可到設定換樣式）")
        self.ui_q.put(apply)

    def _sync_base_style(self):
        """依目前外觀決定底圖：深色外觀且深色圖磚連得到 → 深色地圖；否則一般地圖。
        使用者自己選了衛星或地形圖時不動它。"""
        self._base_style = DEFAULT_STYLE if (self._dark_ok and is_dark()) else "一般 (OSM)"
        if self._cur_style in (DEFAULT_STYLE, "一般 (OSM)") and self._cur_style != self._base_style:
            self.set_map_style(self._base_style)

    # ---- 外觀（淺色 / 深色 / 系統）與語言 ----
    def _set_theme(self, key):
        ctk.set_appearance_mode(key)
        s = load_settings()
        s["theme"] = key
        save_settings(s)
        self.root.after(80, self._apply_theme_extras)

    def _apply_theme_extras(self):
        """customtkinter 元件會自己換色；這裡處理不會自動換色的部分（搖桿畫布、地圖底圖）。"""
        self._last_mode = ctk.get_appearance_mode()
        joy = getattr(self, "joystick", None)
        if joy is not None:
            joy.restyle()
        self._sync_base_style()

    def _theme_poll(self):
        """「系統」模式下，作業系統切換深淺色時跟著變。"""
        try:
            if ctk.get_appearance_mode() != self._last_mode:
                self._apply_theme_extras()
        finally:
            self.root.after(3000, self._theme_poll)

    def _set_lang(self, lang):
        i18n.set_lang(lang)
        i18n.retranslate()                     # 所有 customtkinter 元件的文字
        self.transport_menu.configure(values=[tr(x) for x in TRANSPORTS])
        self.transport.set(tr(i18n.to_zh(self.transport.get())))
        self.style_menu.configure(values=[tr(k) for k in STYLES])
        self.style_var.set(tr(self._cur_style))
        self.query.entry.configure(placeholder_text=tr("地名，或 25.03,121.56"))
        self.status_view.set(i18n.tr_en(self.status.get()))
        self._refresh_speed_labels()
        self._geo_pos = None                   # 地址語言跟著換，讓它重新查一次
        self.refresh_favs()

    def _style_key(self, display):
        for k in STYLES:
            if display in (k, tr(k)):
                return k
        return display

    def _build_footer(self, right):
        """右下角：外觀與語言切換。"""
        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="e", pady=(8, 0))
        st = load_settings()
        label(bar, "◐", 14, color=MUTED).pack(side="left", padx=(0, 4))
        self.theme_seg = PillSeg(bar, [("light", "淺色"), ("dark", "深色"), ("system", "系統")], self._set_theme)
        self.theme_seg.pack(side="left", padx=(0, 14))
        self.theme_seg.set(st.get("theme", "dark") if st.get("theme") in ("light", "dark", "system") else "dark")
        label(bar, "🌐", 14, color=MUTED).pack(side="left", padx=(0, 4))
        self.lang_seg = PillSeg(bar, [("zh", "中文"), ("en", "English")], self._set_lang)
        self.lang_seg.pack(side="left")
        self.lang_seg.set(i18n.get_lang())

    def _fix_icon(self):
        icon = getattr(self, "_icon", None)
        if icon is not None:
            try:
                self.root.iconphoto(False, icon)
            except Exception:  # noqa: BLE001
                pass

    # ---- 左側導覽 ----
    def _build_nav(self):
        nav = ctk.CTkFrame(self.root, fg_color=NAV, corner_radius=0, width=170)
        nav.grid(row=0, column=0, sticky="ns")
        nav.pack_propagate(False)
        label(nav, "VirtualSpot", 18, True).pack(anchor="w", padx=18, pady=(20, 16))
        items = [("map", "📍  地圖"), ("teleport", "📌  單點定位"), ("waypoint", "🔀  多點路線"),
                 ("joystick", "🎮  搖桿模式"), ("favs", "⭐  收藏位置"), ("settings", "⚙  設定")]
        for key, text in items:
            b = ctk.CTkButton(nav, text=text, anchor="w", height=44, corner_radius=8, font=F(14),
                              fg_color="transparent", hover_color=NAV_ACTIVE, text_color=TEXT,
                              command=lambda k=key: self.nav_to(k))
            b.pack(fill="x", padx=10, pady=2)
            self._nav_btns[key] = b

    def _set_nav_active(self, key):
        for k, b in self._nav_btns.items():
            b.configure(fg_color=NAV_ACTIVE if k == key else "transparent")

    def nav_to(self, key):
        if key in MODE_NAMES:
            self.set_mode(key)
            self.show_page("dashboard")
        elif key == "map":
            self.show_page("dashboard")
            self._set_nav_active("map")
        else:
            self.show_page(key)
            self._set_nav_active(key)

    def show_page(self, name):
        name = "dashboard" if name == "map" else name
        for pg in self.pages.values():
            pg.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    # ---- 中間面板 ----
    def _build_panel(self):
        panel = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0, width=410)
        panel.grid(row=0, column=1, sticky="ns")
        panel.pack_propagate(False)

        # 固定在面板最下方：不隨頁面捲動，按下去的回饋一定看得到
        footer = ctk.CTkFrame(panel, fg_color=BG, corner_radius=0)
        footer.pack(side="bottom", fill="x")
        self.start_btn = ctk.CTkButton(footer, text="➤  開始定位", height=52, font=F(17, True), corner_radius=10,
                                       fg_color=ACCENT, hover_color=ACCENT_H, command=self.toggle_sim)
        self.start_btn.pack(fill="x", padx=8, pady=(8, 6))
        sc = card(footer)
        sc.pack(fill="x", padx=8, pady=(0, 10))
        srow = ctk.CTkFrame(sc, fg_color="transparent")
        srow.pack(fill="x", padx=14, pady=(10, 0))
        self._logo_img_s = load_image("logo_pin.png", (22, 22), "logo_pin_dark.png")
        if self._logo_img_s:
            ctk.CTkLabel(srow, text="", image=self._logo_img_s).pack(side="left", padx=(0, 8))
        label(srow, "模擬狀態", 14, True).pack(side="left")
        self.sim_text = label(srow, "已停止", 14, True, color=MUTED)
        self.sim_text._always_en = True        # 模擬狀態不管顏色（灰/綠/黃/藍）一律英文
        self.sim_text.configure(text="已停止")
        self.sim_text.pack(side="right")
        self.sim_dot = label(srow, "●", 14, color=MUTED)
        self.sim_dot.pack(side="right", padx=(0, 6))
        self.ios_lbl = label(sc, "iPhone iOS —", 12, color=MUTED)      # 已連接的 iPhone 版本號
        self.ios_lbl.pack(anchor="w", padx=14, pady=(2, 0))
        label(sc, "", 12, color=MUTED, textvariable=self.status_view, anchor="w", justify="left",
              wraplength=350).pack(anchor="w", padx=14, pady=(4, 10))

        self.pages = {
            "dashboard": self._build_dashboard(panel),
            "favs": self._build_favs(panel),
            "settings": self._build_settings(panel),
        }

    def _build_dashboard(self, parent):
        pg = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)

        # 當前位置
        c = card(pg)
        c.pack(fill="x", padx=8, pady=(8, 6))
        hrow = ctk.CTkFrame(c, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=(12, 6))
        self._logo_img = load_image("logo_pin.png", (26, 26), "logo_pin_dark.png")
        if self._logo_img:
            ctk.CTkLabel(hrow, text="", image=self._logo_img).pack(side="left", padx=(0, 8))
        label(hrow, "當前位置" if self._logo_img else "◎  當前位置", 17, True).pack(side="left")
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=14)
        self.lat_lbl = self._coord_box(row, 0, "緯度")
        self.lon_lbl = self._coord_box(row, 1, "經度")
        arow = ctk.CTkFrame(c, fg_color=INNER, corner_radius=10)
        arow.pack(fill="x", padx=14, pady=(8, 12))
        self.addr_lbl = label(arow, "尚未選擇位置", 13, anchor="w", justify="left", wraplength=290)
        self.addr_lbl.pack(side="left", fill="x", expand=True, padx=10, pady=8)
        ctk.CTkButton(arow, text="⧉", width=32, height=28, fg_color="transparent", hover_color=BORDER,
                      text_color=TEXT, command=self.copy_coords).pack(side="right", padx=6)

        # 定位模式
        self.mode_card = card(pg)
        self.mode_card.pack(fill="x", padx=8, pady=6)
        label(self.mode_card, "定位模式", 16, True).pack(anchor="w", padx=14, pady=(12, 6))
        # 單選：未選是空心 ○，按下去變成實心 ●（border_width_checked = 直徑的一半，所以整顆填滿；CTkRadioButton 綁 self.mode，set_mode 改值時會自動同步）
        mrow = ctk.CTkFrame(self.mode_card, fg_color="transparent")
        mrow.pack(fill="x", padx=14, pady=(0, 14))
        for i, (key, name) in enumerate(MODE_NAMES.items()):
            mrow.grid_columnconfigure(i, weight=1)
            ctk.CTkRadioButton(mrow, text=name, variable=self.mode, value=key, font=F(13),
                               radiobutton_width=18, radiobutton_height=18, border_width_unchecked=2,
                               border_width_checked=9, fg_color=ACCENT, hover_color=ACCENT_H,
                               border_color=MUTED, text_color=TEXT,
                               command=lambda k=key: self.set_mode(k)).grid(row=0, column=i, sticky="w")

        # 各模式專屬區塊（路線 / 搖桿），依模式顯示
        self.mode_box = ctk.CTkFrame(pg, fg_color="transparent")
        self.route_sec = self._build_route_section(self.mode_box)
        self.joy_sec = self._build_joystick_section(self.mode_box)

        # 搜尋
        self.search_card = card(pg)
        self.search_card.pack(fill="x", padx=8, pady=6)
        label(self.search_card, "🔍  搜尋地點或輸入經緯度", 14, color=MUTED).pack(anchor="w", padx=14, pady=(12, 6))
        srow = ctk.CTkFrame(self.search_card, fg_color="transparent")
        srow.pack(fill="x", padx=14, pady=(0, 12))
        entry = ctk.CTkEntry(srow, placeholder_text=tr("地名，或 25.03,121.56"), height=38, font=F(13))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: (self.go(), self.root.focus_set()))
        ctk.CTkButton(srow, text="🔍", width=44, height=38, fg_color=ACCENT, hover_color=ACCENT_H,
                      command=lambda: (self.go(), self.root.focus_set())).pack(side="left", padx=(8, 0))
        self.query = _Query(entry)

        # 快速定位
        qc = card(pg)
        qc.pack(fill="x", padx=8, pady=6)
        label(qc, "快速定位", 16, True).pack(anchor="w", padx=14, pady=(12, 4))
        grid = ctk.CTkFrame(qc, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=(0, 10))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        cells = quick_layout(len(QUICK))
        for (name, la, lo), (row_, col_) in zip(QUICK, cells):
            button(grid, name, lambda p=(la, lo): self.quick_go(p), height=40, anchor="w").grid(
                row=row_, column=col_, sticky="ew", padx=4, pady=4)
        row_, col_ = cells[-1]                      # 自訂位置一律放最後面
        button(grid, "＋  自訂位置", self.add_fav, height=40, anchor="w").grid(
            row=row_, column=col_, sticky="ew", padx=4, pady=4)

        return pg

    def _coord_box(self, parent, col, title):
        parent.grid_columnconfigure(col, weight=1)
        box = ctk.CTkFrame(parent, fg_color=INNER, corner_radius=10)
        box.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
        label(box, title, 12, color=MUTED).pack(anchor="w", padx=10, pady=(6, 0))
        lb = label(box, "—", 18, True)
        lb.pack(anchor="w", padx=10, pady=(0, 8))
        return lb

    def _speed_block(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x")
        label(top, "移動速度", 13, color=MUTED).pack(side="left")
        lb = label(top, "", 13, True)
        lb.pack(side="right")
        self._speed_labels.append(lb)
        ctk.CTkSlider(f, from_=1, to=30, variable=self.speed,
                      command=lambda _v: self._refresh_speed_labels()).pack(fill="x", pady=(4, 0))
        label(f, "步行≈5 km/h　跑步≈11　騎車≈18　開車≈54", 11, color=MUTED).pack(anchor="w")
        return f

    def _refresh_speed_labels(self):
        v = self.speed.get()
        for lb in self._speed_labels:
            lb.configure(text=f"{v * 3.6:.0f} km/h（{v:.1f} m/s）")

    def _build_route_section(self, parent):
        c = card(parent)
        label(c, "路線設定", 16, True).pack(anchor="w", padx=14, pady=(12, 6))
        pad = dict(fill="x", padx=14, pady=3)

        r1 = ctk.CTkFrame(c, fg_color="transparent")
        r1.pack(**pad)
        ctk.CTkSwitch(r1, text="沿道路", variable=self.snap, font=F(13)).pack(side="left")
        self.transport.set(tr(self.transport.get()))
        self.transport_menu = ctk.CTkOptionMenu(r1, values=[tr(x) for x in TRANSPORTS], variable=self.transport,
                                                width=96, font=F(13))
        self.transport_menu.pack(side="right")

        r2 = ctk.CTkFrame(c, fg_color="transparent")
        r2.pack(**pad)
        rb = button(r2, "生成路線", self.build_route, primary=True)
        rb.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.route_btn = _Btn(rb)
        button(r2, "復原", self.undo_waypoint).pack(side="left", expand=True, fill="x", padx=4)
        button(r2, "清除", self.clear_route).pack(side="left", expand=True, fill="x", padx=(4, 0))

        pb = button(c, "播放路線", self.toggle_play, primary=True)
        pb.pack(**pad)
        self.play_btn = _Btn(pb)

        pr = ctk.CTkFrame(c, fg_color="transparent")
        pr.pack(**pad)
        self.prog_lbl = label(pr, "—", 12, color=MUTED)
        self.prog_lbl.pack(anchor="w")
        self.prog_bar = ctk.CTkSlider(pr, from_=0, to=1, command=self.seek_route)      # 拖曳可跳到路線的某一段
        self.prog_bar.set(0)
        self.prog_bar.pack(fill="x", pady=(2, 0))

        r3 = ctk.CTkFrame(c, fg_color="transparent")
        r3.pack(**pad)
        ctk.CTkSwitch(r3, text="循環", variable=self.loop, font=F(13)).pack(side="left")
        ctk.CTkSwitch(r3, text="來回", variable=self.pingpong, font=F(13)).pack(side="left", padx=16)

        ctk.CTkSwitch(c, text="自然速度浮動（±10%）", variable=self.jitter, font=F(13)).pack(anchor="w", padx=14, pady=3)

        r4 = ctk.CTkFrame(c, fg_color="transparent")
        r4.pack(**pad)
        button(r4, "匯入 GPX", self.import_gpx).pack(side="left", expand=True, fill="x", padx=(0, 4))
        button(r4, "匯出 GPX", self.export_gpx).pack(side="left", expand=True, fill="x", padx=(4, 0))
        r5 = ctk.CTkFrame(c, fg_color="transparent")
        r5.pack(**pad)
        button(r5, "儲存路線", self.save_route).pack(side="left", expand=True, fill="x", padx=(0, 4))
        button(r5, "載入路線", self.load_route).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._speed_block(c).pack(fill="x", padx=14, pady=(8, 12))
        label(c, "在地圖上依序點選路線點", 12, color=MUTED).pack(anchor="w", padx=14, pady=(0, 10))
        return c

    def _build_joystick_section(self, parent):
        c = card(parent)
        label(c, "搖桿", 16, True).pack(anchor="w", padx=14, pady=(12, 6))

        def on_change(v):
            self.joy = v
        self.joystick = Joystick(c, on_change)
        self.joystick.pack(pady=4)
        label(c, "也可以用鍵盤 WASD / 方向鍵", 12, color=MUTED).pack()
        self._speed_block(c).pack(fill="x", padx=14, pady=(8, 12))
        return c

    # ---- 收藏頁 ----
    def _build_favs(self, parent):
        pg = ctk.CTkFrame(parent, fg_color="transparent")
        head = ctk.CTkFrame(pg, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(16, 8))
        label(head, "收藏位置", 20, True).pack(side="left")
        button(head, "＋ 收藏目前位置", self.add_fav, primary=True, width=140).pack(side="right")
        bk = ctk.CTkFrame(pg, fg_color="transparent")
        bk.pack(fill="x", padx=14, pady=(0, 6))
        button(bk, "匯出收藏", self.export_favs).pack(side="left", expand=True, fill="x", padx=(0, 4))
        button(bk, "匯入收藏", self.import_favs).pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.fav_box = ctk.CTkScrollableFrame(pg, fg_color="transparent", corner_radius=0)
        self.fav_box.pack(fill="both", expand=True, padx=4)
        self.refresh_favs()
        return pg

    def refresh_favs(self):
        for w in self.fav_box.winfo_children():
            w.destroy()
        if not self.favs:
            label(self.fav_box, "還沒有收藏。選好位置後按「收藏目前位置」。", 13, color=MUTED).pack(pady=20)
        grouped = group_favorites(self.favs)
        show_heads = any(g for g, _ in grouped)               # 有用到分類才顯示分類標題
        for g, items in grouped:
            if show_heads:
                label(self.fav_box, g or "未分類", 14, True).pack(anchor="w", padx=10, pady=(10, 0))
            for i, f in items:
                row = card(self.fav_box)
                row.pack(fill="x", padx=6, pady=4)
                ctk.CTkButton(row, text=f"{f['name']}\n{fmt_coord(f['lat'], f['lon'])}", anchor="w", height=52,
                              font=F(13), fg_color="transparent", hover_color=BORDER, text_color=TEXT,
                              command=lambda i=i: self.go_fav(i)).pack(side="left", fill="x", expand=True)
                ctk.CTkButton(row, text="✕", width=36, height=36, fg_color="transparent", hover_color=RED_H,
                              text_color=MUTED, command=lambda i=i: self.remove_fav(i)).pack(side="right", padx=(0, 8))
                ctk.CTkButton(row, text="🏷", width=36, height=36, fg_color="transparent", hover_color=BORDER,
                              text_color=MUTED, command=lambda i=i: self.edit_fav_group(i)).pack(side="right")
        if self.recents:                                  # 最近開始定位過的位置
            head = ctk.CTkFrame(self.fav_box, fg_color="transparent")
            head.pack(fill="x", padx=10, pady=(16, 2))
            label(head, "最近使用", 16, True).pack(side="left")
            ctk.CTkButton(head, text="清除記錄", width=80, height=28, font=F(12), fg_color="transparent",
                          hover_color=BORDER, text_color=MUTED, command=self.clear_recents).pack(side="right")
            for i, f in enumerate(self.recents):
                row = card(self.fav_box)
                row.pack(fill="x", padx=6, pady=4)
                ctk.CTkButton(row, text=f"{f['name']}\n{fmt_coord(f['lat'], f['lon'])}", anchor="w", height=52,
                              font=F(13), fg_color="transparent", hover_color=BORDER, text_color=TEXT,
                              command=lambda i=i: self.go_recent(i)).pack(side="left", fill="x", expand=True)

    def _add_recent(self, pos):
        """開始定位時記下這個位置（有查到地址就用地址當名字）。"""
        name = fmt_coord(*pos)
        if getattr(self, "_geo_pos", None) == pos:
            shown = self.info_name.cget("text")
            if shown and shown != "—":
                name = shown
        self.recents = push_recent(self.recents, {"name": name, "lat": pos[0], "lon": pos[1]})
        try:
            save_recents(self.recents)
        except OSError:
            pass
        self.refresh_favs()

    def go_recent(self, i):
        self.playing = False
        self.play_btn.config(text="播放路線")
        self.set_pos((self.recents[i]["lat"], self.recents[i]["lon"]))
        self.show_page("dashboard")
        self._set_nav_active("map")

    def clear_recents(self):
        self.recents = []
        try:
            save_recents(self.recents)
        except OSError:
            pass
        self.refresh_favs()
        self.status.set("已清除最近記錄")

    def export_favs(self):
        if not self.favs:
            self.status.set("沒有收藏可以匯出")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="VirtualSpot-favorites.json",
                                            filetypes=[(tr("收藏檔"), "*.json")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump_favorites_json(self.favs))
        self.status.set(f"已匯出 {len(self.favs)} 筆收藏")

    def import_favs(self):
        path = filedialog.askopenfilename(filetypes=[(tr("收藏檔"), "*.json"), (tr("所有檔案"), "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                spots = parse_favorites_json(f.read())
        except Exception as e:  # noqa: BLE001
            self.status.set(f"收藏檔讀取失敗：{e}")
            return
        self.favs, added, skipped = merge_favorites(self.favs, spots)
        save_favorites(self.favs)
        self.refresh_favs()
        self.status.set(f"已匯入 {added} 筆收藏（略過 {skipped} 筆）")

    def go_fav(self, i):
        self.playing = False
        self.play_btn.config(text="播放路線")
        self.set_pos((self.favs[i]["lat"], self.favs[i]["lon"]))
        self.show_page("dashboard")
        self._set_nav_active("map")

    def remove_fav(self, i):
        del self.favs[i]
        save_favorites(self.favs)
        self.refresh_favs()

    def add_fav(self):
        if self.pos is None:
            self.status.set("請先選一個位置再收藏")
            return
        got = self._ask_fav_details()
        if got is None:
            return
        name, group = got[0].strip() or fmt_coord(*self.pos), got[1].strip()
        spot = {"name": name, "lat": self.pos[0], "lon": self.pos[1]}
        if group:
            spot["group"] = group
        self.favs.append(spot)
        save_favorites(self.favs)
        self.refresh_favs()
        self.status.set(f"已收藏「{name}」")

    def _ask_fav_details(self):
        """收藏時問名稱和分類（分類可留空，也可以選用過的分類）。回傳 (名稱, 分類)；取消回傳 None。"""
        result = {}
        win = ctk.CTkToplevel(self.root)
        win.title(tr("收藏此位置"))
        win.geometry("360x260")
        win.configure(fg_color=BG)
        win.transient(self.root)
        label(win, "為這個位置取個名字：", 13).pack(anchor="w", padx=18, pady=(16, 4))
        name_e = ctk.CTkEntry(win, height=36, font=F(13))
        name_e.pack(fill="x", padx=18)
        label(win, "分類（可留空）：", 13).pack(anchor="w", padx=18, pady=(12, 4))
        grp = ctk.CTkComboBox(win, values=group_names(self.favs) or [""], height=36, font=F(13))
        grp.set("")
        grp.pack(fill="x", padx=18)

        def ok():
            result["v"] = (name_e.get(), grp.get())
            win.destroy()

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=18)
        button(row, "收藏", ok, primary=True).pack(side="left", expand=True, fill="x", padx=(0, 4))
        button(row, "取消", win.destroy).pack(side="left", expand=True, fill="x", padx=(4, 0))
        win.grab_set()
        self.root.wait_window(win)
        return result.get("v")

    def edit_fav_group(self, i):
        g = ctk.CTkInputDialog(text=tr("分類（留空＝未分類）："), title=tr("設定分類")).get_input()
        if g is None:
            return
        g = g.strip()
        if g:
            self.favs[i]["group"] = g
        else:
            self.favs[i].pop("group", None)
        save_favorites(self.favs)
        self.refresh_favs()
        self.status.set("已更新分類")

    # ---- 設定頁 ----
    def _build_settings(self, parent):
        pg = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)
        label(pg, "設定", 20, True).pack(anchor="w", padx=14, pady=(16, 8))

        c = card(pg)
        c.pack(fill="x", padx=8, pady=6)
        label(c, "地圖", 16, True).pack(anchor="w", padx=14, pady=(12, 6))
        self.style_var = tk.StringVar(value=tr(DEFAULT_STYLE))
        self.style_menu = ctk.CTkOptionMenu(c, values=[tr(k) for k in STYLES], variable=self.style_var,
                                            font=F(13), command=lambda d: self.set_map_style(self._style_key(d)))
        self.style_menu.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkSwitch(c, text="地圖跟隨目前位置", variable=self.follow, font=F(13)).pack(
            anchor="w", padx=14, pady=(0, 12))

        c = card(pg)
        c.pack(fill="x", padx=8, pady=6)
        label(c, "裝置", 16, True).pack(anchor="w", padx=14, pady=(12, 6))
        self.auto_var = tk.BooleanVar(value=load_settings().get("auto_connect", True))
        ctk.CTkSwitch(c, text="自動連接 iPhone（插上就連線）", variable=self.auto_var, font=F(13),
                      command=self._on_auto_toggle).pack(anchor="w", padx=14, pady=(0, 8))
        button(c, "還原真實定位並中斷連線", self.dev.clear).pack(fill="x", padx=14, pady=3)
        button(c, "儲存診斷報告", self.run_diagnose).pack(fill="x", padx=14, pady=(3, 12))

        c = card(pg)
        c.pack(fill="x", padx=8, pady=6)
        label(c, "版本更新", 16, True).pack(anchor="w", padx=14, pady=(12, 6))
        button(c, "檢查更新", lambda: self.check_update(manual=True)).pack(fill="x", padx=14, pady=(3, 12))

        label(pg, "請只在合法、且不違反服務條款的情況下使用。模擬定位可能違反某些遊戲或 App 的規則，"
                  "帳號風險由使用者自行承擔。", 12, wraplength=340, justify="left",
              anchor="w").pack(anchor="w", padx=14, pady=(8, 0))
        label(pg, "地圖圖磚與路線、地址查詢使用公開服務（OpenStreetMap、Esri、OpenTopoMap、OSRM、"
                  "Nominatim），僅適合個人輕量使用。", 11, color=MUTED, wraplength=340, justify="left",
              anchor="w").pack(anchor="w", padx=14, pady=(8, 12))
        return pg

    # ---- 右側：地圖 + 資訊列 ----
    def _build_right(self):
        right = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        right.grid(row=0, column=2, sticky="nsew", padx=(0, 10), pady=10)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        mapbox = ctk.CTkFrame(right, fg_color=CARD, corner_radius=12)
        mapbox.grid(row=0, column=0, sticky="nsew")
        self.map = tkintermapview.TkinterMapView(mapbox, corner_radius=12)
        self.map.pack(fill="both", expand=True)
        self.map.add_left_click_map_command(self.on_click)
        self.map.canvas.bind("<Button-1>", lambda _e: self.root.focus_set(), add="+")

        # 地圖上的小工具：地圖/衛星切換、回到目前位置
        self.map_seg = MapStyleToggle(mapbox, [("地圖", "btn_map.png"), ("衛星", "btn_satellite.png")],
                                      self._on_map_seg)
        self.map_seg.set("地圖")
        self.map_seg.place(relx=1.0, x=-14, y=14, anchor="ne")
        ctk.CTkButton(mapbox, text="⌖", width=42, height=42, font=F(20), fg_color=INNER, hover_color=BORDER,
                      border_width=1, border_color=BORDER, text_color=TEXT,
                      command=self.locate_me).place(relx=1.0, rely=1.0, x=-14, y=-14, anchor="se")

        # 狀態訊息也會短暫顯示在地圖上方，不用去找左邊的文字
        self.toast_box = ctk.CTkFrame(mapbox, fg_color=TOAST, corner_radius=10, border_width=1,
                                      border_color=BORDER)
        self.toast_lbl = label(self.toast_box, "", 13, wraplength=520, justify="left")
        self.toast_lbl.pack(padx=14, pady=8)
        self._toast_job = None

        info = ctk.CTkFrame(right, fg_color="transparent")
        info.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for c in range(4):
            info.grid_columnconfigure(c, weight=1, uniform="info")
        self.info_name = self._info_card(info, 0, "當前模擬位置", "—", sub="—")
        self.info_gps = self._info_card(info, 1, "GPS 模擬", "未啟用")
        self.info_speed = self._info_card(info, 2, "移動速度", "0 km/h")
        self.info_gps._always_en = True        # GPS 模擬 已啟用/未啟用 固定英文
        self.info_gps.configure(text="未啟用")
        self.info_mode = self._info_card(info, 3, "定位模式", MODE_NAMES["teleport"])
        self._build_footer(right)

    def _info_card(self, parent, col, title, value, sub=None):
        c = card(parent)
        c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        label(c, title, 12, color=MUTED).pack(anchor="w", padx=12, pady=(10, 0))
        lb = label(c, value, 15, True, anchor="w", justify="left", wraplength=210)
        lb.pack(anchor="w", padx=12, pady=(2, 0 if sub else 10))
        if sub:
            self.info_coord = label(c, sub, 12, color=MUTED)
            self.info_coord.pack(anchor="w", padx=12, pady=(0, 10))
        return lb

    # ------------------------------------------------------------------ 行為
    def _on_auto_toggle(self):
        v = bool(self.auto_var.get())
        s = load_settings()
        s["auto_connect"] = v
        save_settings(s)
        self.dev.set_auto(v)
        self.status.set("已開啟自動連接 iPhone" if v else "已關閉自動連接，需要時請按「開始定位」")

    def _on_status(self, *_):
        text = self.status.get()
        self.status_view.set(i18n.tr_en(text))
        if not text or text.startswith("已送出座標"):      # 移動時每隔幾秒就會有這則，不要一直跳
            return
        self.toast_lbl.configure(text=tr(text))
        self.toast_box.place(relx=0.5, y=14, anchor="n")
        if self._toast_job is not None:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(7000, self.toast_box.place_forget)

    def set_mode(self, key):
        self.mode.set(key)
        self.info_mode.configure(text=MODE_NAMES[key])
        self.route_sec.pack_forget()
        self.joy_sec.pack_forget()
        self.mode_box.pack_forget()
        if key == "waypoint":
            self.route_sec.pack(fill="x")
            self.mode_box.pack(fill="x", padx=8, pady=6, after=self.mode_card)
        elif key == "joystick":
            self.joy_sec.pack(fill="x")
            self.mode_box.pack(fill="x", padx=8, pady=6, after=self.mode_card)
        if key != "joystick":
            self.joy = (0.0, 0.0)
        self._set_nav_active(key)

    def set_map_style(self, name):
        url, max_zoom = STYLES[name]
        self.map.set_tile_server(url, max_zoom=max_zoom)
        self._apply_overlay(OVERLAYS.get(name))
        self.map.set_zoom(min(int(self.map.zoom), max_zoom))
        self._cur_style = name
        self.style_var.set(tr(name))
        self.map_seg.set("衛星" if name == SATELLITE_STYLE else "地圖")

    def _apply_overlay(self, url):
        """深色底圖要疊上文字標籤；換成其他樣式時要把疊圖拿掉。"""
        if url is None and not getattr(self, "_overlay_on", False):
            return
        try:
            self.map.set_overlay_tile_server(url)
        except Exception:  # noqa: BLE001  舊版 tkintermapview 沒有這個方法就略過（只是少了地名）
            self.map.overlay_tile_server = url
        self._overlay_on = url is not None

    def _on_map_seg(self, value):
        self.set_map_style(SATELLITE_STYLE if value == "衛星" else self._base_style)

    def locate_me(self):
        if self.pos is None:
            self.status.set("還沒有選擇位置")
            return
        self._follow_center, self._follow_t = self.pos, time.monotonic()
        self.map.set_position(*self.pos)

    def show_candidates(self, results):
        """搜尋到多個地點時，列出讓使用者選。"""
        win = ctk.CTkToplevel(self.root)
        win.title(tr("選擇地點"))
        win.geometry(f"460x{min(110 + 60 * len(results), 480)}")
        win.configure(fg_color=BG)
        win.transient(self.root)
        label(win, "找到多個地點，請選擇", 15, True).pack(anchor="w", padx=16, pady=(14, 8))

        def pick(r):
            win.destroy()
            self.goto_result(r)

        for r in results:
            parts = [x.strip() for x in r["name"].split(",")]
            text = parts[0] + ("\n" + ", ".join(parts[1:3]) if len(parts) > 1 else "")
            ctk.CTkButton(win, text=text, anchor="w", height=52, font=F(13), fg_color=CARD, hover_color=NAV_ACTIVE,
                          text_color=TEXT, command=lambda r=r: pick(r)).pack(fill="x", padx=14, pady=3)
        win.grab_set()

    def quick_go(self, p):
        self.playing = False
        self.play_btn.config(text="播放路線")
        self.set_pos(p)

    def copy_coords(self):
        if self.pos is None:
            self.status.set("還沒有選擇位置")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(fmt_coord(*self.pos))
        self.status.set("已複製座標")

    def _should_send(self):
        return self.sim_active

    def on_connected(self):
        if not self.sim_active:
            self.status.set("已連接 iPhone。選好位置後按「開始定位」" if self.pos is None
                            else "已連接 iPhone。按「開始定位」，手機就會跳到所選位置")
        elif self.pos is not None:
            self.dev.set(*self.pos)

    def toggle_sim(self):
        if self.sim_active:                          # 停止（或取消連線中）
            self.sim_active = False
            self._connecting_until = 0.0
            if self.dev.connected:
                self.status.set("正在還原真實定位…")
                self.dev.clear()                     # 會還原並中斷連線，之後自動重連（待命）
            else:
                self.status.set("已取消")
            return
        if self.pos is None:
            self.status.set("請先選擇位置（點地圖、搜尋或快速定位），再按開始定位")
            return
        self.sim_active = True
        self._add_recent(self.pos)
        if self.dev.connected:
            self.dev.set(*self.pos)
            self.status.set("定位模擬已開始")
        else:                                        # 還沒連上（自動連線尚未完成）：立刻嘗試連線
            self._connecting_until = time.monotonic() + 90
            self.connect_device()

    def _refresh_ios(self, c):
        v = getattr(self.dev, "ios_version", "") if c else ""
        self.ios_lbl.configure(text=f"iPhone iOS {v}" if v else "iPhone iOS —")

    def _set_sim_ui(self, c, connecting):
        self._refresh_ios(c)
        running = self.sim_active and c
        if running:
            self.start_btn.configure(text="■  停止定位", fg_color=RED, hover_color=RED_H)
            self._sim_look(GREEN, "執行中")
            self.info_gps.configure(text="已啟用", text_color=GREEN)
            return
        if connecting:
            self.start_btn.configure(text="■  取消", fg_color=RED, hover_color=RED_H)
            self._sim_look("#f0b429", "連接中…")
        else:
            self.start_btn.configure(text="➤  開始定位", fg_color=ACCENT, hover_color=ACCENT_H)
            if c:
                self._sim_look("#4da3ff", "已連接・待命")
            else:
                self._sim_look(MUTED, "未連接 iPhone")
        self.info_gps.configure(text="未啟用", text_color=MUTED)

    def _sim_look(self, color, text):
        self.sim_dot.configure(text_color=color)
        self.sim_text.configure(text=text, text_color=color)

    def after_tick(self):
        c = self.dev.connected
        if c:
            self._connecting_until = 0.0
        elif self._connecting_until and time.monotonic() >= self._connecting_until:
            self._connecting_until = 0.0
            self.sim_active = False
            self.status.set("連接逾時：請確認 iPhone 已解鎖並按過「信任」、USB 線有接好，再按一次開始定位")
        connecting = bool(self._connecting_until) and not c
        if connecting and self.status.get().startswith("裝置錯誤"):
            self._connecting_until, connecting = 0.0, False
            self.sim_active = False
        if self.sim_active and not c and not connecting:      # 模擬中途斷線（例如拔掉 USB）
            self.sim_active = False
            self.status.set("iPhone 已中斷連線，模擬已停止")
        state = (c, connecting, self.sim_active)
        if state != self._ui_conn:
            self._ui_conn = state
            self._set_sim_ui(c, connecting)
        self._update_progress()
        moving = self.playing or bool(self.keys) or self.joy != (0.0, 0.0)
        text = f"{self.speed.get() * 3.6:.0f} km/h" if moving and self.pos is not None else "0 km/h"
        if self.info_speed.cget("text") != text:
            self.info_speed.configure(text=text)

    def _update_progress(self):
        if len(self.route) < 2:
            text, frac = "—", 0.0
        else:
            frac, left = self.route_progress()
            text = f"進度 {round(frac * 100)}%・剩餘 {fmt_duration(left)}"
        if self.prog_lbl.cget("text") != text:
            self.prog_lbl.configure(text=text)
            self.prog_bar.set(frac)
        elif self.playing:
            self.prog_bar.set(frac)

    def on_key_down(self, e):
        try:
            w = self.root.focus_get()
        except Exception:  # noqa: BLE001  下拉選單開啟時 focus_get 可能出錯
            w = None
        if isinstance(w, (tk.Entry, tk.Text)):
            return
        k = e.keysym.lower()
        if k in KEYS:
            self.keys.add(k)

    def step_keys(self, dt):
        dx = sum(KEYS[k][0] for k in self.keys)
        dy = sum(KEYS[k][1] for k in self.keys)
        mag = math.hypot(dx, dy)
        if mag > 0:
            dx, dy = dx / mag, dy / mag
        dx, dy = dx + self.joy[0], dy + self.joy[1]
        m = math.hypot(dx, dy)
        if m < 0.05:
            return
        if m > 1:
            dx, dy = dx / m, dy / m
        if self.pos is None:
            self.status.set("請先在地圖上選一個起點（點地圖、搜尋或快速定位）")
            return
        s = self.speed.get() * dt
        self.set_pos(offset(self.pos, dy * s, dx * s))

    # ---- 位置顯示與地址 ----
    def set_pos(self, p):
        super().set_pos(p)
        la, lo = self.pos
        self.lat_lbl.configure(text=f"{la:.4f}")
        self.lon_lbl.configure(text=f"{lo:.4f}")
        self.info_coord.configure(text=fmt_coord(la, lo))
        self._maybe_geocode()

    def _maybe_geocode(self):
        if self._geo_busy or self.pos is None:
            return
        now = time.monotonic()
        if self._geo_pos is not None and (dist(self._geo_pos, self.pos) < 30 or now - self._geo_t < 4):
            return
        self._geo_busy = True
        pos = self.pos

        def work():
            try:
                addr = reverse_geocode(pos[0], pos[1], lang="en" if i18n.get_lang() == "en" else "zh-TW")
            except Exception:  # noqa: BLE001  地址只是附加資訊，失敗就略過
                addr = ""
            self.ui_q.put(lambda: self._set_address(addr, pos))
        threading.Thread(target=work, daemon=True).start()

    def _set_address(self, addr, pos):
        self._geo_busy = False
        self._geo_pos, self._geo_t = pos, time.monotonic()
        self.addr_lbl.configure(text=addr or "（無法取得地址）")
        self.info_name.configure(text=(addr.split(",")[0].strip() if addr else "—") or "—")

    # ---- 更新提示（深色版）----
    def ask_update(self, tag, url):
        win = ctk.CTkToplevel(self.root)
        win.title(tr("發現新版本"))
        win.geometry("400x200")
        win.resizable(False, False)
        win.transient(self.root)
        label(win, f"發現新版本 {tag}（目前 v{__version__}）", 15, True).pack(padx=20, pady=(22, 4))
        label(win, "要更新嗎？按「更新」會開啟下載頁面。", 13, color=MUTED).pack()
        skip = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(win, text="不再提醒此版本", variable=skip, font=F(13)).pack(pady=12)
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack()

        def do_update():
            import webbrowser
            webbrowser.open(url)
            win.destroy()

        def no_update():
            if skip.get():
                s = load_settings()
                s["skipped_version"] = tag
                save_settings(s)
            win.destroy()

        button(row, "更新", do_update, primary=True, width=110).pack(side="left", padx=6)
        button(row, "不更新", no_update, width=110).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", no_update)

        def front():
            try:
                win.lift()
                win.focus_force()
                win.grab_set()
            except Exception:  # noqa: BLE001
                pass
        win.after(200, front)
