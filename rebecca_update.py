"""Manual update check. Rebecca never phones home: this runs only when you click 'Check for updates'."""
import re
import urllib.parse
import urllib.request

LATEST = "https://github.com/jaedenko/Rebecca/releases/latest"   # redirects to .../releases/tag/<newest>


def parse_version(tag):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", tag or "")
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def is_newer(latest_tag, current):
    return parse_version(latest_tag) > parse_version(current)


def check(current, timeout=8):
    """Return (latest_tag, release_page_url, is_newer). Raises on network errors.
    Follows the public 'latest release' redirect, so there is no API key or rate limit involved."""
    req = urllib.request.Request(LATEST, headers={"User-Agent": "Rebecca-update-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        url = r.geturl()
    m = re.search(r"/releases/tag/([^/?#]+)", url)
    if not m:
        raise RuntimeError("no releases published yet")
    tag = urllib.parse.unquote(m.group(1))
    return tag, url, is_newer(tag, current)
