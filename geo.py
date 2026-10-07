"""地理工具：距離、重新取樣、位移、GPX。座標一律用 (lat, lon)。"""
import math
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

EARTH_R = 6371008.8


def fmt_coord(lat, lon):
    """畫面上一律用這個格式顯示座標：'42.3152, 140.9741'（小數 4 位，緯度在前）。"""
    return f"{lat:.4f}, {lon:.4f}"


def jitter_factor(pct=0.1, rnd=random.random):
    """速度浮動倍率：1 ± pct 之間的隨機值（pct=0.1 → 0.9 ~ 1.1）。"""
    return 1 + (rnd() * 2 - 1) * pct


def dist(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def simplify(path, max_points=400):
    """把很長的折線簡化到約 max_points 個點以內（Ramer-Douglas-Peucker）。
    只用來畫地圖：點太多時地圖每次拖曳、縮放都要重畫整條線，會很卡。播放仍使用完整路線。"""
    n = len(path)
    if n <= max_points:
        return list(path)
    if n > 5000:                                   # 先粗略抽樣，避免後面計算太久
        step = math.ceil(n / 5000)
        path = list(path[::step]) + ([path[-1]] if (n - 1) % step else [])
        n = len(path)
    lat0, lon0 = path[0]
    kx, ky = 111_320 * math.cos(math.radians(lat0)), 111_320
    pts = [((lon - lon0) * kx, (lat - lat0) * ky) for lat, lon in path]

    def rdp(tol):
        keep = [False] * n
        keep[0] = keep[-1] = True
        stack = [(0, n - 1)]
        while stack:
            i, j = stack.pop()
            ax, ay = pts[i]
            dx, dy = pts[j][0] - ax, pts[j][1] - ay
            length = math.hypot(dx, dy)
            best, idx = -1.0, -1
            for k in range(i + 1, j):
                px, py = pts[k][0] - ax, pts[k][1] - ay
                d = abs(dy * px - dx * py) / length if length else math.hypot(px, py)
                if d > best:
                    best, idx = d, k
            if best > tol and idx > 0:
                keep[idx] = True
                stack += [(i, idx), (idx, j)]
        return [path[k] for k in range(n) if keep[k]]

    tol = 2.0
    out = rdp(tol)
    while len(out) > max_points and tol < 20000:
        tol *= 2.5
        out = rdp(tol)
    return out


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def resample(path, step):
    """把折線依固定間距（公尺）重新取樣。"""
    if len(path) < 2 or step <= 0:
        return list(path)
    out = [path[0]]
    need = step  # 距離下一個取樣點還差多少公尺
    for a, b in zip(path, path[1:]):
        d = dist(a, b)
        if d <= 0:
            continue
        pos = 0.0
        while d - pos >= need:
            pos += need
            out.append(lerp(a, b, pos / d))
            need = step
        need -= d - pos
    out.append(path[-1])
    return out


def offset(p, north_m, east_m):
    lat = p[0] + north_m / 111_320
    lon = p[1] + east_m / (111_320 * math.cos(math.radians(p[0])))
    return (lat, lon)


def parse_gpx(text):
    """讀取 GPX 內的 wpt / trkpt / rtept，回傳 [(lat, lon), ...]。"""
    pts = []
    for el in ET.fromstring(text).iter():
        if el.tag.rsplit("}", 1)[-1] in ("wpt", "trkpt", "rtept"):
            try:
                pts.append((float(el.attrib["lat"]), float(el.attrib["lon"])))
            except (KeyError, ValueError):
                pass
    return pts


_NUM = r"(-?\d+(?:\.\d+)?)"
_PAIR = re.compile(rf"\s*{_NUM}\s*(?:[,，;；/\s])\s*{_NUM}\s*")
_MAPS_URL = re.compile(rf"@{_NUM},{_NUM}")


def parse_coords(text):
    """解析 '緯度,經度'（逗號、全形逗號、空格、斜線皆可）或 Google 地圖網址中的 @緯度,經度。
    若順序寫反（第一個數字超過 90，例如台灣的 '121.56,25.03'）會自動對調。
    不是座標就回傳 None。"""
    m = _MAPS_URL.search(text) or _PAIR.fullmatch(text)
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if abs(a) > 90 and abs(b) <= 90:
        a, b = b, a
    if abs(a) <= 90 and abs(b) <= 180:
        return (a, b)
    return None


def to_gpx(points, interval_s=1.0):
    start = datetime.now(timezone.utc)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="VirtualSpot" xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    for i, (lat, lon) in enumerate(points):
        t = (start + timedelta(seconds=i * interval_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f'  <wpt lat="{lat:.6f}" lon="{lon:.6f}"><time>{t}</time></wpt>')
    lines.append("</gpx>")
    return "\n".join(lines) + "\n"


def route_progress(idx, count, direction=1, speed=1.0, step_m=1.0):
    """播放進度。idx 是目前走到第幾個點、count 是總點數（每點間隔 step_m 公尺）。
    回傳 (已走比例 0~1, 目前方向上剩餘秒數)。"""
    if count < 2:
        return 0.0, 0.0
    idx = max(0, min(idx, count - 1))
    frac = idx / (count - 1)
    left = ((count - 1 - idx) if direction >= 0 else idx) * step_m
    return frac, left / max(speed, 0.1)


def fmt_duration(sec):
    """秒數 → mm:ss（超過一小時用 h:mm:ss）。"""
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
