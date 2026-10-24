"""Rebuild fetchamiibo/index.json.

Downloads the FlipperAmiibo dumps at their latest commit, reads each dump's amiibo ID (pages 21-22) and
names it with the AmiiboAPI database. Run from the repository root: python tools/build_index.py
"""
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

SOURCE = "Gioman101/FlipperAmiibo"
AMIIBO_API = "https://www.amiiboapi.org/api/amiibo/"
OUT = Path(__file__).resolve().parent.parent / "fetchamiibo" / "index.json"
UA = {"User-Agent": "fetchamiibo-index-builder"}

# Top-level FlipperAmiibo folders -> the amiibo series name AmiiboAPI uses, for dumps it doesn't know.
FOLDER_SERIES = {
    "Animal_Crossing": "Animal Crossing", "Legend_of_Zelda": "Legend Of Zelda",
    "Super_Smash_Bros": "Super Smash Bros.", "Super_Mario": "Super Mario Bros.",
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def pretty_stem(stem):
    """'HHD_Items_01' -> 'HHD Items 01', 'Wolf_Link_MAX_LEVEL' -> 'Wolf Link MAX LEVEL'."""
    text = re.sub(r"\s+", " ", stem.replace("_", " ")).strip()
    return re.sub(r"\b(\w+) s\b", r"\1's", text)  # Link_s_Awakening -> Link's Awakening


def path_rank(path):
    """Which copy to keep when the same amiibo is in several folders: its own series folder first,
    the catch-all Other/ folder and re-filed copies last."""
    return ("Other/" in path or "_from_" in path or "/SSB " in path, path.count("/"), path)


def main():
    sha = json.loads(get(f"https://api.github.com/repos/{SOURCE}/commits/HEAD"))["sha"]
    api = {(a["head"] + a["tail"]).lower(): a for a in json.loads(get(AMIIBO_API))["amiibo"]}

    dumps = {}  # amiibo id -> [path, ...]
    with tarfile.open(fileobj=io.BytesIO(get(f"https://codeload.github.com/{SOURCE}/tar.gz/{sha}"))) as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".nfc"):
                continue
            path = member.name.split("/", 1)[1]
            text = tar.extractfile(member).read().decode("utf-8", "replace")
            pages = dict(re.findall(r"Page (\d+): ([0-9A-Fa-f ]+)", text))
            amiibo_id = (pages.get("21", "") + pages.get("22", "")).replace(" ", "").lower()
            if len(amiibo_id) == 16:
                dumps.setdefault(amiibo_id, []).append(path)

    entries = []
    for amiibo_id, paths in dumps.items():
        paths.sort(key=path_rank)
        info = api.get(amiibo_id)
        same_id_names = len(paths) > 1 and info is None  # e.g. 40 Happy Home Designer cards share one ID
        for i, path in enumerate(paths):
            stem = Path(path).stem
            base = Path(paths[0]).stem
            if i and not same_id_names and not stem.lower().startswith(base.lower() + "_"):
                continue  # just another copy of the first one
            if info and not same_id_names:
                name = info["name"]
                if i:  # a save-data variant, e.g. Wolf_Link_20_Heart next to Wolf_Link
                    name += f" ({pretty_stem(stem[len(base) + 1:])})"
                entry = {"name": name, "character": info["character"], "game": info["amiiboSeries"],
                         "series": info["gameSeries"], "type": info["type"]}
            else:
                folder = path.split("/", 1)[0]
                entry = {"name": pretty_stem(stem), "character": pretty_stem(stem),
                         "game": FOLDER_SERIES.get(folder, pretty_stem(folder).replace(" Amiibo", "")),
                         "series": "", "type": "Card" if "Card" in path or "Items" in path else "Figure"}
            parts = path.split("/")[1:-1]  # sub-folders, e.g. Amiibo_Cards/Series_1 -> "Series 1"
            entry["line"] = pretty_stem(parts[-1]) if parts else ""
            entries.append({"id": amiibo_id, **entry, "path": path})

    entries.sort(key=lambda e: (e["game"].lower(), e["name"].lower(), e["path"]))
    OUT.write_text(json.dumps({"source": SOURCE, "commit": sha, "amiibo": entries}, indent=1,
                              ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(entries)} amiibo from {SOURCE}@{sha[:7]} -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
