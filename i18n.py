"""介面語言（繁體中文 / English）。

程式內的字串一律寫中文；顯示時用 tr() 轉換。語言為 "zh" 時原樣回傳；為 "en" 時先查整句對照表，
再比對帶變數的句型，都沒有就原樣回傳（寧可顯示中文，也不要顯示錯誤的英文）。
介面元件的文字由 install() 統一攔截，切換語言時 retranslate() 會一次更新全部。
"""
import re
import weakref

from storage import load_settings, save_settings

LANGS = ("zh", "en")
_CJK = re.compile("[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")
_lang = load_settings().get("lang", "zh")
if _lang not in LANGS:
    _lang = "zh"

EN = {
    # 導覽 / 區塊標題
    "📍  地圖": "📍  Map", "📌  單點定位": "📌  Single spot", "🔀  多點路線": "🔀  Route",
    "🎮  搖桿模式": "🎮  Joystick", "⭐  收藏位置": "⭐  Favorites", "⚙  設定": "⚙  Settings",
    "單點定位": "Single spot", "多點路線": "Route", "搖桿模式": "Joystick",
    "當前位置": "Current location", "◎  當前位置": "◎  Current location",
    "緯度": "Latitude", "經度": "Longitude", "尚未選擇位置": "No location selected",
    "定位模式": "Mode", "🔍  搜尋地點或輸入經緯度": "🔍  Search a place or enter lat,lon",
    "地名，或 25.03,121.56": "Place name, or 25.03,121.56", "快速定位": "Quick spots",
    "＋  自訂位置": "＋  Custom spot", "路線設定": "Route settings", "沿道路": "Follow roads",
    "生成路線": "Build route", "復原": "Undo", "清除": "Clear", "播放路線": "Play route",
    "暫停": "Pause", "循環": "Loop", "來回": "Ping-pong", "匯入 GPX": "Import GPX",
    "匯出 GPX": "Export GPX", "儲存路線": "Save route", "載入路線": "Load route",
    "移動速度": "Speed", "步行≈5 km/h　跑步≈11　騎車≈18　開車≈54":
        "Walk ≈5 km/h   Run ≈11   Bike ≈18   Drive ≈54",
    "在地圖上依序點選路線點": "Click the map to add route points in order",
    "搖桿": "Joystick", "也可以用鍵盤 WASD / 方向鍵": "You can also use WASD / arrow keys",
    "收藏位置": "Favorites", "＋ 收藏目前位置": "＋ Save this spot",
    "還沒有收藏。選好位置後按「收藏目前位置」。": "No favorites yet. Pick a spot, then press “Save this spot”.",
    "設定": "Settings", "地圖": "Map", "衛星": "Satellite", "地圖跟隨目前位置": "Map follows current location",
    "裝置": "Device", "自動連接 iPhone（插上就連線）": "Auto-connect iPhone (connect when plugged in)",
    "還原真實定位並中斷連線": "Restore real location and disconnect", "儲存診斷報告": "Save diagnostic report",
    "更新": "Update", "版本更新": "Updates", "檢查更新": "Check for updates",
    "外觀": "Appearance", "淺色": "Light", "深色": "Dark", "系統": "System", "中文": "中文", "語言": "Language",
    "地圖圖磚與路線、地址查詢使用公開服務（OpenStreetMap、Esri、OpenTopoMap、OSRM、Nominatim），僅適合個人輕量使用。":
        "Map tiles, routing and address lookup use public services (OpenStreetMap, Esri, OpenTopoMap, OSRM, "
        "Nominatim). For light personal use only.",
    # 底部 / 資訊列
    "➤  開始定位": "➤  Start", "■  停止定位": "■  Stop", "■  取消": "■  Cancel",
    "模擬狀態": "Simulation", "已停止": "Stopped", "執行中": "Running", "連接中…": "Connecting…",
    "已連接・待命": "Connected · standby", "未連接 iPhone": "iPhone not connected",
    "當前模擬位置": "Simulated location", "GPS 模擬": "GPS simulation", "已啟用": "On", "未啟用": "Off",
    "（無法取得地址）": "(address unavailable)", "目前位置": "Current location",
    # 地圖樣式 / 交通
    "深色地圖 (Esri)": "Dark map (Esri)", "一般 (OSM)": "Standard (OSM)", "衛星 (Esri)": "Satellite (Esri)",
    "地形 (OpenTopoMap)": "Terrain (OpenTopoMap)", "步行": "Walk", "開車": "Drive", "騎車": "Bike",
    # 快速定位
    "台北 101": "Taipei 101", "台北車站": "Taipei Main Station", "西門町": "Ximending",
    "淡水老街": "Tamsui Old Street", "九份老街": "Jiufen Old Street", "日月潭": "Sun Moon Lake",
    "台中國家歌劇院": "Taichung Opera House", "高雄駁二": "Kaohsiung Pier-2", "墾丁大街": "Kenting Street",
    # 更新對話框
    "發現新版本": "New version available", "要更新嗎？按「更新」會開啟下載頁面。":
        "Update now? “Update” opens the download page.",
    "不再提醒此版本": "Don't remind me about this version", "不更新": "Not now",
    # 對話框
    "為這個位置取個名字：": "Name this spot:", "收藏此位置": "Save this spot", "收藏": "Favorite", "名稱：": "Name:",
    "所有檔案": "All files", "VirtualSpot 路線": "VirtualSpot route",
    # 最近使用 / 收藏備份 / 速度浮動
    "最近使用": "Recent", "清除記錄": "Clear history", "匯出收藏": "Export favorites", "匯入收藏": "Import favorites",
    "收藏檔": "Favorites file", "自然速度浮動（±10%）": "Natural speed variation (±10%)",
    "沒有收藏可以匯出": "No favorites to export", "已清除最近記錄": "Recent history cleared",
    # 搜尋候選 / 路線進度 / 收藏分類 / 使用聲明
    "搜尋中…": "Searching…", "選擇地點": "Choose a place", "找到多個地點，請選擇": "Several places found. Pick one",
    "未分類": "Ungrouped", "分類（可留空）：": "Group (optional):", "分類（留空＝未分類）：": "Group (leave empty for none):",
    "設定分類": "Set group", "已更新分類": "Group updated", "取消": "Cancel",
    "請只在合法、且不違反服務條款的情況下使用。模擬定位可能違反某些遊戲或 App 的規則，帳號風險由使用者自行承擔。":
        "Use this only where it is legal and allowed by the terms of service. Faking your location may break the rules of "
        "some games and apps; any account risk is yours.",
    # 狀態訊息
    "請先選一個位置再收藏": "Pick a location first, then save it", "已複製座標": "Coordinates copied",
    "還沒有選擇位置": "No location selected yet", "已開啟自動連接 iPhone": "Auto-connect enabled",
    "已關閉自動連接，需要時請按「開始定位」": "Auto-connect disabled. Press “Start” when needed",
    "請先選擇位置（點地圖、搜尋或快速定位），再按開始定位":
        "Pick a location first (click the map, search, or a quick spot), then press Start",
    "定位模擬已開始": "Simulation started", "裝置錯誤": "Device error",
    "iPhone 已中斷連線，模擬已停止": "iPhone disconnected, simulation stopped",
    "請先在地圖上選一個起點（點地圖、搜尋或快速定位）": "Pick a starting point first (click the map, search, or a quick spot)",
    "請先在地圖上選一個起點（點地圖或輸入座標）": "Pick a starting point first (click the map or enter coordinates)",
    "深色地圖載入不了，先使用一般地圖（可到設定換樣式）": "Dark map unavailable, using the standard map (change it in Settings)",
    "已連接 iPhone。選好位置後按「開始定位」": "iPhone connected. Pick a location, then press Start",
    "已連接 iPhone。按「開始定位」，手機就會跳到所選位置": "iPhone connected. Press Start and the phone jumps to the chosen spot",
    "正在還原真實定位…": "Restoring real location…", "已取消": "Cancelled",
    "連接逾時：請確認 iPhone 已解鎖並按過「信任」、USB 線有接好，再按一次開始定位":
        "Connection timed out: make sure the iPhone is unlocked, you tapped “Trust”, and the USB cable is "
        "connected, then press Start again",
    "找不到這個地點": "Place not found", "至少需要 2 個路線點": "At least 2 route points are needed",
    "計算路線中…": "Calculating route…", "路線完成": "Route ready", "請先生成路線": "Build a route first",
    "沒有可匯出的內容：請先選位置或建立路線": "Nothing to export: pick a location or build a route first",
    "GPX 內沒有足夠的座標點": "The GPX file has too few points", "請先生成或匯入路線": "Build or import a route first",
    "路線已儲存": "Route saved", "路線座標不足": "Not enough route points", "已是最新版": "You're up to date",
    "診斷中…約 20 秒。若 iPhone 未連線，會短暫把定位設到台北 101 再還原":
        "Running diagnostics (~20 s). If the iPhone isn't connected, the location briefly jumps to Taipei 101 and is restored",
    "診斷中…約 20 秒": "Running diagnostics (~20 s)",
    "連接中…（第一次需要在 iPhone 按「信任」，可能要等幾十秒）":
        "Connecting… (the first time you must tap “Trust” on the iPhone; this can take a while)",
    "已連接 iPhone。請點地圖或輸入座標，手機才會開始移動":
        "iPhone connected. Click the map or enter coordinates to start moving the phone",
    "尚未連接 iPhone（仍可在地圖上規劃並匯出 GPX）":
        "iPhone not connected (you can still plan routes and export GPX)",
    "尚未設定 GitHub 倉庫（version.py 的 GITHUB_REPO）": "GitHub repository not set (GITHUB_REPO in version.py)",
    "非預期的下載網址": "Unexpected download URL",
    # device.py
    "連不到 Apple Mobile Device Service：請安裝 iTunes 或 Microsoft Store 的「Apple 裝置」，確認服務已啟動，並讓 iPhone 解鎖、信任此電腦":
        "Cannot reach Apple Mobile Device Service: install iTunes or “Apple Devices” from the Microsoft Store, "
        "make sure the service is running, then unlock the iPhone and trust this computer",
    "找不到 iPhone：請用 USB 連接、解鎖並信任此電腦": "iPhone not found: connect by USB, unlock it and trust this computer",
    "iPhone 尚未開啟開發者模式：設定 → 隱私權與安全性 → 開發者模式，開啟後重新開機再連線":
        "Developer Mode is off: Settings → Privacy & Security → Developer Mode, turn it on, restart, then reconnect",
    "iPhone 上按過「不信任」：到 設定 → 一般 → 移轉或重置 iPhone → 重置 → 重置位置與隱私權，再重新連線":
        "You tapped “Don't Trust”: go to Settings → General → Transfer or Reset iPhone → Reset → Reset Location & "
        "Privacy, then reconnect",
    "配對失敗：請解鎖 iPhone，並在跳出的視窗按「信任」": "Pairing failed: unlock the iPhone and tap “Trust” in the prompt",
    "iPhone 尚未掛載 Developer Disk Image（開發者磁碟映像）。請先用 Xcode、3uTools、愛思助手，或 pymobiledevice3 的 mounter 指令掛載一次後再連線":
        "The Developer Disk Image is not mounted. Mount it once with Xcode, 3uTools, or pymobiledevice3's "
        "mounter command, then reconnect",
    "1/4 尋找 iPhone…（第一次需要在 iPhone 按「信任」）": "1/4 Looking for iPhone… (first time: tap “Trust” on the iPhone)",
    "已還原真實定位並中斷連線。手機地圖若還沒變，請重開地圖 App 並等幾秒；要再模擬請按「連接 iPhone」":
        "Real location restored and disconnected. If the phone's map hasn't changed, reopen the Maps app and wait a few "
        "seconds. To simulate again, press “Connect iPhone”",
    "3/4 連接 tunneld…（沒有的話會自動啟動，需要系統管理員權限）":
        "3/4 Connecting to tunneld… (started automatically if missing; needs administrator rights)",
    "4/4 開啟開發者服務（DVT）…": "4/4 Starting developer services (DVT)…",
    "tunneld 沒有找到裝置，確認 iPhone 已用 USB 連接並信任此電腦":
        "tunneld found no device: make sure the iPhone is connected by USB and trusts this computer",
    "尚未安裝 pymobiledevice3（pip install pymobiledevice3）": "pymobiledevice3 is not installed (pip install pymobiledevice3)",
    "無法啟動 tunneld：請在跳出的視窗按「是」允許系統管理員權限，並確認沒有防毒軟體擋住":
        "Cannot start tunneld: click “Yes” on the administrator prompt and make sure antivirus isn't blocking it",
    "連不到 tunneld：請用系統管理員身分執行 `pymobiledevice3 remote tunneld`":
        "Cannot reach tunneld: run `pymobiledevice3 remote tunneld` as administrator",
}

# 帶變數的句型：(正規表示式, 英文樣板)
_PATTERNS = [
    (r"已匯出 (\d+) 筆收藏", r"Exported \1 favorites"),
    (r"已匯入 (\d+) 筆收藏（略過 (\d+) 筆）", r"Imported \1 favorites (\2 skipped)"),
    (r"收藏檔讀取失敗：(.*)", r"Failed to read favorites file: \1"),
    (r"已收藏「(.*)」", r"Saved “\1”"),
    (r"發現新版本 (.*)（目前 v(.*)）", r"New version \1 available (current v\2)"),
    (r"(\d+) km/h（([\d.]+) m/s）", r"\1 km/h (\2 m/s)"),
    (r"已匯入 (\d+) 個點", r"Imported \1 points"),
    (r"已前往：(.*)", r"Moved to: \1"),
    (r"搜尋失敗：(.*)", r"Search failed: \1"),
    (r"進度 (\d+)%・剩餘 ([\d:]+)", r"Progress \1% · \2 left"),
    (r"已匯出 (\d+) 個點", r"Exported \1 points"),
    (r"已載入路線（(\d+) 點）", r"Route loaded (\1 points)"),
    (r"診斷報告已存到 (.*)", r"Diagnostic report saved to \1"),
    (r"診斷失敗：(.*)", r"Diagnostics failed: \1"),
    (r"GPX 讀取失敗：(.*)", r"Failed to read GPX: \1"),
    (r"路線讀取失敗：(.*)", r"Failed to read route: \1"),
    (r"內部錯誤：(.*)", r"Internal error: \1"),
    (r"導航失敗，改用直線：(.*)", r"Routing failed, using straight lines: \1"),
    (r"檢查更新失敗：(.*)", r"Update check failed: \1"),
    (r"裝置錯誤：(.*)", r"Device error: \1"),
    (r"已送出座標 (.*)", r"Sent coordinates \1"),
    (r"2/4 已找到 iPhone（iOS (.*)）", r"2/4 iPhone found (iOS \1)"),
    (r"已連接 iPhone（iOS (.*)）", r"iPhone connected (iOS \1)"),
    (r"連線逾時，卡在「(.*)」。請確認 iPhone 已解鎖並信任此電腦、沒有其他程式（例如另一個 VirtualSpot）同時在連接 iPhone",
     r"Connection timed out at “\1”. Make sure the iPhone is unlocked and trusts this computer, and that no other "
     r"program (for example another VirtualSpot) is connecting to it"),
    (r"(.*)（完整記錄：(.*)）", r"\1 (full log: \2)"),
    (r"發現新版本 (.*)（目前 v(.*)）\n要更新嗎？按「更新」會開啟下載頁面。",
     r"New version \1 available (current v\2)\nUpdate now? “Update” opens the download page."),
]
_COMPILED = [(re.compile(p, re.S), r) for p, r in _PATTERNS]

_REV = {}


def to_zh(text):
    """英文顯示字串轉回程式內部使用的中文鍵（例如交通方式 Walk → 步行）。找不到就原樣回傳。"""
    if not _REV:
        _REV.update({v: k for k, v in EN.items()})
    return _REV.get(text, text)


def get_lang():
    return _lang


def set_lang(lang, save=True):
    global _lang
    _lang = lang if lang in LANGS else "zh"
    if save:
        s = load_settings()
        s["lang"] = _lang
        save_settings(s)


def tr(text):
    """依目前語言轉換字串。"""
    if _lang != "en":
        return text
    return _translate(text)


def tr_en(text):
    """不管目前語言，一律轉成英文（灰色說明文字固定顯示英文用）。"""
    return _translate(text)


def _translate(text):
    if not isinstance(text, str) or not _CJK.search(text):
        return text
    if text in EN:
        return EN[text]
    for rx, rep in _COMPILED:
        m = rx.fullmatch(text)
        if m:
            return m.expand(rep)
    # 多行字串：逐行翻譯
    if "\n" in text:
        return "\n".join(_translate(p) for p in text.split("\n"))
    return text


# ---------------------------------------------------------------- 介面元件攔截
_registry = weakref.WeakSet()
FORCE_EN_COLORS = []      # 這些文字顏色（灰色說明文字）的元件固定顯示英文，由 ui_modern 登錄


def _show(w, text):
    return tr_en(text) if getattr(w, "_force_en", False) or getattr(w, "_always_en", False) else tr(text)
_TEXT_CLASSES = ("CTkLabel", "CTkButton", "CTkSwitch", "CTkCheckBox", "CTkRadioButton")


def install(ctk):
    """攔截 customtkinter 元件的 text= 參數：存下中文原文，顯示時依語言轉換。只需呼叫一次。"""
    for name in _TEXT_CLASSES:
        cls = getattr(ctk, name)
        if getattr(cls, "_i18n_patched", False):
            continue
        orig_init, orig_cfg = cls.__init__, cls.configure

        def __init__(self, *a, _oi=orig_init, **k):
            self._force_en = k.get("text_color") in FORCE_EN_COLORS
            self._always_en = False
            if isinstance(k.get("text"), str):
                self._i18n_src = k["text"]
                k["text"] = _show(self, k["text"])
            _oi(self, *a, **k)
            _registry.add(self)

        def configure(self, *a, _oc=orig_cfg, **k):
            if "text_color" in k:
                self._force_en = k["text_color"] in FORCE_EN_COLORS
            if isinstance(k.get("text"), str):
                self._i18n_src = k["text"]
                k["text"] = _show(self, k["text"])
            return _oc(self, *a, **k)

        cls.__init__, cls.configure = __init__, configure
        cls._i18n_patched = True


def retranslate():
    """依目前語言更新所有已登錄的元件文字。"""
    for w in list(_registry):
        src = getattr(w, "_i18n_src", None)
        if src is None:
            continue
        try:
            w.configure(text=src)
        except Exception:  # noqa: BLE001  元件已被銷毀
            pass
