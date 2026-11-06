"""Update StockSense from inside the program.

The GitHub build publishes each new installer on the public "StockSense"
page. The program looks there for a newer version, downloads the installer
(only from that page, and checks it is complete) and runs it quietly. Settings
and the login live in %APPDATA%\\StockSense, so they survive the update."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import requests

REPO = "intjct/StockSense"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
INSTALLER_RE = re.compile(r"^StockSense-Setup-[0-9][0-9.]*\.exe$")


@dataclass
class Update:
    version: str
    url: str
    size: int = 0
    sha256: str = ""
    notes: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.5.0' -> (1, 5, 0). Anything that isn't a plain version -> ()."""
    t = (text or "").strip().lstrip("vV")
    if not re.fullmatch(r"\d+(\.\d+)*", t):
        return ()
    return tuple(int(x) for x in t.split("."))


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a) and bool(b) and a > b


def notes_for(body: str, version: str) -> str:
    """The bullet list under '## StockSense <version>' in the release notes (empty if not found)."""
    lines, out, on = (body or "").splitlines(), [], False
    for ln in lines:
        if ln.startswith("## "):
            if on:
                break
            on = parse_version(ln.split()[-1]) == parse_version(version) if ln.split() else False
            continue
        if on and ln.strip():
            out.append(ln.strip().lstrip("-").strip())
    return "\n".join(out)


def check(current: str, timeout: float = 10, get=requests.get) -> Update | None:
    """The newer release, or None when up to date. Raises on network trouble."""
    r = get(LATEST_URL, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    data = r.json()
    version = str(data.get("tag_name", "")).lstrip("vV")
    if not is_newer(version, current):
        return None
    for a in data.get("assets", []):
        url = a.get("browser_download_url", "")
        if INSTALLER_RE.match(a.get("name", "")) and url.startswith(DOWNLOAD_PREFIX):
            digest = str(a.get("digest") or "")
            return Update(version=version, url=url, size=int(a.get("size") or 0),
                          sha256=digest[7:].lower() if digest.startswith("sha256:") else "",
                          notes=notes_for(data.get("body", ""), version))
    return None


def download(u: Update, folder: str | None = None, get=requests.get, timeout: float = 30,
             min_size: int = 1_000_000) -> str:
    """Downloads the installer into a temp folder, checks it, returns its path."""
    if not u.url.startswith(DOWNLOAD_PREFIX):
        raise ValueError("bad update address")
    folder = folder or tempfile.mkdtemp(prefix="stocksense-update-")
    path = os.path.join(folder, os.path.basename(u.url))
    h = hashlib.sha256()
    n = 0
    with get(u.url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(path + ".part", "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                h.update(chunk)
                n += len(chunk)
    if (u.size and n != u.size) or (u.sha256 and h.hexdigest() != u.sha256) or n < min_size:
        os.remove(path + ".part")
        raise ValueError("download incomplete")
    os.replace(path + ".part", path)
    return path


def launch_installer(path: str) -> None:
    """Runs the installer quietly; it closes StockSense, installs over it and opens it again."""
    args = [path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, close_fds=True, creationflags=flags)
