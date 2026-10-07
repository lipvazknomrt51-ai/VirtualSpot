"""沿道路導航：使用 OSM 社群的公開 OSRM 服務（僅適合輕量使用）。
想用自己的伺服器就改 BASE。"""
import json
import urllib.parse
import urllib.request

BASE = "https://routing.openstreetmap.de"
PROFILES = {"步行": "routed-foot", "開車": "routed-car", "騎車": "routed-bike",
            "Walk": "routed-foot", "Drive": "routed-car", "Bike": "routed-bike"}   # 英文介面的選項


def fetch_route(points, transport="步行"):
    """points: [(lat, lon), ...]，回傳沿道路的 [(lat, lon), ...]。失敗會丟例外。"""
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    # 注意：此服務的 URL 裡 profile 固定寫 driving，實際路網由前面的 routed-xxx 決定
    url = f"{BASE}/{PROFILES[transport]}/route/v1/driving/{coords}?overview=full&geometries=geojson"
    req = urllib.request.Request(url, headers={"User-Agent": "VirtualSpot/1.0 (open-source)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    if data.get("code") != "Ok":
        raise RuntimeError(data.get("message") or data.get("code") or "unknown error")
    return [(lat, lon) for lon, lat in data["routes"][0]["geometry"]["coordinates"]]


def reverse_geocode(lat, lon, lang="zh-TW"):
    """座標轉地址（OSM Nominatim，公開服務請輕量使用，每秒不超過 1 次）。失敗會丟例外。"""
    url = (f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=18"
           f"&lat={lat:.6f}&lon={lon:.6f}&accept-language={lang}")
    req = urllib.request.Request(url, headers={"User-Agent": "VirtualSpot/1.0 (open-source)"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r).get("display_name", "")


def search_places(query, limit=5, lang="zh-TW"):
    """地名搜尋，回傳多個候選：[{name, lat, lon}, ...]（OSM Nominatim）。沒有結果回傳空清單；網路失敗會丟例外。"""
    query = (query or "").strip()
    if not query:
        return []
    url = (f"https://nominatim.openstreetmap.org/search?format=jsonv2&limit={int(limit)}"
           f"&accept-language={lang}&q={urllib.parse.quote(query)}")
    req = urllib.request.Request(url, headers={"User-Agent": "VirtualSpot/1.0 (open-source)"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.load(r)
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            lat, lon = float(d["lat"]), float(d["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            out.append({"name": str(d.get("display_name") or f"{lat:.4f}, {lon:.4f}"), "lat": lat, "lon": lon})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out
