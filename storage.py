"""收藏地點、最近使用位置、設定的本機儲存（~/.virtualspot/）。"""
import json
import os

DIR = os.path.join(os.path.expanduser("~"), ".virtualspot")
FILE = os.path.join(DIR, "favorites.json")
SETTINGS = os.path.join(DIR, "settings.json")


def load_favorites():
    try:
        with open(FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if {"name", "lat", "lon"} <= d.keys()]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def save_favorites(favs):
    os.makedirs(DIR, exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(favs, f, ensure_ascii=False, indent=2)


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    os.makedirs(DIR, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 收藏備份 / 最近使用
RECENT_LIMIT = 10


def clean_spot(d):
    """把一筆位置整理成 {name, lat, lon}；格式不對或座標超出範圍就回傳 None。"""
    try:
        lat, lon = float(d["lat"]), float(d["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        name = str(d.get("name") or "").strip() or f"{lat:.4f}, {lon:.4f}"
        group = str(d.get("group") or "").strip()
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    spot = {"name": name, "lat": lat, "lon": lon}
    if group:                       # 分類是選填的；舊的收藏檔沒有這個欄位
        spot["group"] = group
    return spot


def _same(a, b):
    return abs(a["lat"] - b["lat"]) < 1e-5 and abs(a["lon"] - b["lon"]) < 1e-5


def dump_favorites_json(favs):
    return json.dumps({"app": "VirtualSpot", "favorites": favs}, ensure_ascii=False, indent=2)


def parse_favorites_json(text):
    """讀備份檔：可以是 {"favorites": [...]} 或單純的陣列。內容不是收藏就丟 ValueError。"""
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("favorites")
    if not isinstance(data, list):
        raise ValueError("not a favorites file")
    spots = [c for c in (clean_spot(d) for d in data if isinstance(d, dict)) if c]
    if data and not spots:
        raise ValueError("no valid favorites")
    return spots


def merge_favorites(current, incoming):
    """把匯入的收藏併進目前的收藏（座標相同的視為重複）。回傳 (合併後清單, 新增數, 略過數)。"""
    merged, added = list(current), 0
    for spot in incoming:
        if any(_same(spot, m) for m in merged):
            continue
        merged.append(spot)
        added += 1
    return merged, added, len(incoming) - added


def group_favorites(favs):
    """依分類整理收藏：回傳 [(分類名稱, [(原本的索引, 收藏), ...]), ...]。
    有分類的照第一次出現的順序排在前面，沒有分類的（名稱為 ""）放最後；組內維持原本順序。"""
    groups, order = {}, []
    for i, f in enumerate(favs):
        g = str(f.get("group") or "").strip()
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append((i, f))
    order.sort(key=lambda g: g == "")          # 排序穩定，只把未分類移到最後
    return [(g, groups[g]) for g in order]


def group_names(favs):
    """目前用到的分類名稱（不含未分類），依第一次出現的順序。"""
    seen = []
    for f in favs:
        g = str(f.get("group") or "").strip()
        if g and g not in seen:
            seen.append(g)
    return seen


def push_recent(recents, spot, limit=RECENT_LIMIT):
    """把 spot 放到最近使用的最前面（同座標只留一筆），最多保留 limit 筆。"""
    c = clean_spot(spot)
    if c is None:
        return list(recents)
    return ([c] + [r for r in recents if not _same(r, c)])[:limit]


def recents_path():
    return os.path.join(DIR, "recents.json")


def load_recents():
    try:
        with open(recents_path(), encoding="utf-8") as f:
            data = json.load(f)
        return [c for c in (clean_spot(d) for d in data if isinstance(d, dict)) if c][:RECENT_LIMIT]
    except (OSError, ValueError, TypeError):
        return []


def save_recents(recents):
    os.makedirs(DIR, exist_ok=True)
    with open(recents_path(), "w", encoding="utf-8") as f:
        json.dump(recents, f, ensure_ascii=False, indent=2)
