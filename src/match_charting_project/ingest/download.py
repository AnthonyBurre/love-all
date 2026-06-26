"""Download raw Match Charting Project CSVs into data/raw."""

from pathlib import Path

import requests
from tqdm import tqdm

from match_charting_project.ingest.sources import all_sources
from match_charting_project.paths import ensure_dirs


def download_file(url: str, dest: Path, force: bool = False) -> bool:
    """Stream `url` to `dest`. Returns True if downloaded, False if cached."""
    if dest.exists() and not force:
        return False
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        with open(tmp, "wb") as fh, tqdm(
            total=total, unit="B", unit_scale=True, desc=dest.name, leave=False
        ) as bar:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
                bar.update(len(chunk))
    tmp.rename(dest)
    return True


def download(what: str = "core", force: bool = False) -> None:
    ensure_dirs()
    sources = all_sources(what)
    print(f"Downloading {len(sources)} files ({what}) -> data/raw ...")
    fetched = 0
    for src in sources:
        got = download_file(src.url, src.local_path, force=force)
        fetched += got
        flag = "  + " if got else "  . "
        print(flag + src.filename + ("" if got else " (cached)"))
    print(f"Done. {fetched} downloaded, {len(sources) - fetched} cached.")
