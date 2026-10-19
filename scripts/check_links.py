"""Check that every external documentation link in the catalog resolves (HTTP 2xx after redirects).

Network access required; run manually or in CI. Uses only the standard library and sends
read-only HEAD requests (falling back to GET when a server rejects HEAD).
Usage: python scripts/check_links.py
"""
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "linux-command-guide-link-check/1.0 (+https://github.com/itsnavin/linux-command-guide)"


def man_url(ref, site=None):
    page, section = ref.rsplit(".", 1)
    if site == "debian":
        return f"https://manpages.debian.org/{page}.{section}"
    return f"https://man7.org/linux/man-pages/man{section[0]}/{page}.{section}.html"


def collect():
    urls = {}
    cats = json.loads((ROOT / "data" / "categories.json").read_text(encoding="utf-8"))
    for cat in cats:
        for cmd in json.loads((ROOT / "data" / "commands" / f"{cat['id']}.json").read_text(encoding="utf-8")):
            if cmd.get("man"):
                urls.setdefault(man_url(cmd["man"], cmd.get("manSite")), []).append(cmd["id"])
            for doc in cmd.get("docs", []):
                urls.setdefault(doc["url"], []).append(cmd["id"])
    return urls


def check(url):
    for method in ("HEAD", "GET"):
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return url, resp.status, None
            except urllib.error.HTTPError as err:
                if err.code in (403, 405) and method == "HEAD":
                    break
                if err.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                return url, err.code, str(err)
            except Exception as err:  # network errors
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                return url, None, str(err)
    return url, None, "unreachable"


def main():
    urls = collect()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, sorted(urls)))
    bad = [(u, s, e) for u, s, e in results if not (s and 200 <= s < 300)]
    for url, status, err in bad:
        print(f"BROKEN {status or '-'} {url} (used by {', '.join(urls[url])}): {err}")
    print(f"links: {len(results) - len(bad)}/{len(results)} OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
