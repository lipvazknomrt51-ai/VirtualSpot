"""檢查 GitHub 最新 Release。只負責「查版本」，不會自動下載或替換程式。"""
import json
import urllib.request

from version import GITHUB_REPO


def _parts(v):
    out = []
    for p in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return out


def is_newer(latest, current):
    a, b = _parts(latest), _parts(current)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return a > b


def check_latest():
    """回傳 (tag, release 頁面網址)；失敗會丟例外。"""
    if GITHUB_REPO.startswith("YOUR_"):
        raise RuntimeError("尚未設定 GitHub 倉庫（version.py 的 GITHUB_REPO）")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "VirtualSpot"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    url = data["html_url"]
    if not url.startswith("https://github.com/"):
        raise RuntimeError("非預期的下載網址")
    return data["tag_name"], url
