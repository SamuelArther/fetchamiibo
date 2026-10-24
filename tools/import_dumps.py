"""Copy new amiibo dumps into dumps/ and rebuild fetchamiibo/index.json.

Reads every source repository below (earlier ones win), keeps one dump per amiibo ID (plus save-data
variants such as Wolf Link 20 Heart), converts raw .bin dumps to Flipper .nfc, and names everything with
the AmiiboAPI database. Dumps already in dumps/ are never changed or removed, so file URLs stay stable.
Run from anywhere: python tools/import_dumps.py
"""
import argparse
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

SOURCES = [
    "Gioman101/FlipperAmiibo",
    "AmiiboDB/Amiibo",
    "Re3koning/AmiiboFiles",
]
AMIIBO_API = "https://www.amiiboapi.org/api/amiibo/"
ROOT = Path(__file__).resolve().parent.parent
DUMPS = ROOT / "dumps"
INDEX = ROOT / "fetchamiibo" / "index.json"
REPO = "SamuelArther/fetchamiibo"
UA = {"User-Agent": "fetchamiibo-importer"}

# Top-level source folders -> the amiibo series name AmiiboAPI uses, for dumps it doesn't know.
FOLDER_SERIES = {
    "Animal_Crossing": "Animal Crossing", "Legend_of_Zelda": "Legend Of Zelda",
    "Super_Smash_Bros": "Super Smash Bros.", "Super_Mario": "Super Mario Bros.",
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
        return r.read()


def pretty_stem(stem):
    """'HHD_Items_01' -> 'HHD Items 01', 'Wolf_Link_MAX_LEVEL' -> 'Wolf Link MAX LEVEL'."""
    text = re.sub(r"\s+", " ", stem.replace("_", " ")).strip()
    return re.sub(r"\b(\w+) s\b", r"\1's", text)  # Link_s_Awakening -> Link's Awakening


def safe_name(name):
    name = re.sub(r"\s*:\s*", " - ", name)
    return re.sub(r'[<>"/\\|?*]+', "_", name).strip(" .") or "amiibo"


def nfc_id(text):
    pages = dict(re.findall(r"Page (\d+): ([0-9A-Fa-f ]+)", text))
    amiibo_id = (pages.get("21", "") + pages.get("22", "")).replace(" ", "").lower()
    return amiibo_id if len(amiibo_id) == 16 and len(pages) >= 135 else None


def bin_to_nfc(data):
    """A raw NTAG215 dump as a Flipper NFC device file, in the same layout as the FlipperAmiibo dumps."""
    hexs = lambda b: " ".join(f"{x:02X}" for x in b)  # noqa: E731
    lines = ["Filetype: Flipper NFC device", "Version: 2",
             "# Nfc device type can be UID, Mifare Ultralight, Bank card", "Device type: NTAG215",
             "# UID, ATQA and SAK are common for all formats", f"UID: {hexs(data[0:3] + data[4:8])}",
             "ATQA: 44 00", "SAK: 00", "# Mifare Ultralight specific data", "Signature: " + hexs(bytes(32)),
             "Mifare version: 00 04 04 02 01 00 11 03",
             "Counter 0: 0", "Tearing 0: 00", "Counter 1: 0", "Tearing 1: 00", "Counter 2: 0", "Tearing 2: 00",
             "Pages total: 135"]
    lines += [f"Page {i}: {hexs(data[i * 4:i * 4 + 4])}" for i in range(135)]
    return "\n".join(lines) + "\n"


def collect(files):
    """{amiibo id: [(path, .nfc text), ...]} from (path, size, read) triples; .nfc files win over .bin."""
    found = {}
    for path, size, read in sorted(files, key=lambda f: not f[0].lower().endswith(".nfc")):
        low = path.lower()
        if "essential" in low:
            continue  # key files and tools, never dumps
        if low.endswith(".nfc"):
            text = read().decode("utf-8", "replace")
            if not text.startswith("Filetype: Flipper NFC device") or "NTAG215" not in text:
                continue
        elif low.endswith(".bin") and size in (540, 572):
            data = read()
            if data[0] != 0x04 or data[12:16] != b"\xf1\x10\xff\xee":
                continue  # not an NTAG215 image
            text = bin_to_nfc(data)
        else:
            continue
        amiibo_id = nfc_id(text)
        if amiibo_id:
            found.setdefault(amiibo_id, []).append((path, text))
    return found


def harvest(repo):
    """Every amiibo dump in a GitHub repository."""
    with tarfile.open(fileobj=io.BytesIO(get(f"https://codeload.github.com/{repo}/tar.gz/HEAD"))) as tar:
        return collect([(m.name.split("/", 1)[1], m.size, lambda m=m: tar.extractfile(m).read())
                        for m in tar if m.isfile()])


def harvest_local(folder):
    """Every amiibo dump under a local folder, e.g. ones read from real amiibo with a Flipper."""
    root = Path(folder)
    return collect([(p.relative_to(root).as_posix(), p.stat().st_size, p.read_bytes)
                    for p in sorted(root.rglob("*")) if p.is_file()])


def path_rank(path):
    """Which copy to keep when the same amiibo is in several folders: its own series folder first,
    the catch-all Other/ folder and re-filed copies last."""
    return ("Other/" in path or "_from_" in path or "/SSB " in path, path.count("/"), path)


def candidates(repo, found, api):
    """One candidate entry per distinct dump: the main dump of each ID plus its save-data variants."""
    for amiibo_id, copies in found.items():
        copies.sort(key=lambda c: path_rank(c[0]))
        known = amiibo_id in api
        if not known and len({pretty_stem(Path(c[0]).stem).lower() for c in copies}) < 2:
            continue  # an ID AmiiboAPI doesn't know, e.g. a guessed pre-release ID that won't scan
        base = Path(copies[0][0]).stem
        seen_stems = set()
        for i, (path, text) in enumerate(copies):
            stem = Path(path).stem
            if not known and len(copies) > 1:  # e.g. 40 Happy Home Designer cards sharing one ID
                variant = pretty_stem(stem)
            elif i == 0:
                variant = ""
            elif stem.lower().startswith(base.lower() + "_"):  # Wolf_Link_20_Heart next to Wolf_Link
                variant = pretty_stem(stem[len(base) + 1:])
            else:
                continue  # just another copy of the first one
            if variant.lower() in seen_stems:
                continue
            seen_stems.add(variant.lower())
            folder = path.split("/", 1)[0] if "/" in path else ""
            parts = path.split("/")[1:-1]
            yield {"id": amiibo_id, "variant": variant, "from": repo, "from_path": path,
                   "fallback_name": pretty_stem(stem),
                   "fallback_game": FOLDER_SERIES.get(folder, pretty_stem(folder).replace(" Amiibo", "")) or "Other",
                   "line": pretty_stem(parts[-1]) if parts else "",
                   "fallback_type": "Card" if "Card" in path or "Items" in path else "Figure"}, text


def describe(entry, api):
    """Fill in name / character / game / series / type from AmiiboAPI, or from the file name."""
    info = api.get(entry["id"])
    if info and not (entry["variant"] and entry["variant"] == entry["fallback_name"]):
        name = info["name"] + (f" ({entry['variant']})" if entry["variant"] else "")
        entry.update(name=name, character=info["character"], game=info["amiiboSeries"],
                     series=info["gameSeries"], type=info["type"])
    else:
        entry.update(name=entry["fallback_name"], character=entry["fallback_name"], game=entry["fallback_game"],
                     series="", type=entry["fallback_type"])


def new_path(entry, taken):
    folder = safe_name(entry["game"])
    for stem in (entry["name"], f"{entry['name']} ({entry['line']})", f"{entry['name']} ({entry['type']})",
                 f"{entry['name']} ({entry['id']})"):
        path = f"dumps/{folder}/{safe_name(stem)}.nfc"
        if path.lower() not in taken:
            return path
    raise SystemExit(f"no free file name for {entry}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local", metavar="DIR", help="also import .nfc/.bin dumps from this folder (they go first)")
    parser.add_argument("--credit", default="community dump", help="who to credit for the --local dumps")
    args = parser.parse_args()
    api = {(a["head"] + a["tail"]).lower(): a for a in json.loads(get(AMIIBO_API))["amiibo"]}
    try:
        entries = json.loads(INDEX.read_text(encoding="utf-8"))["amiibo"]
    except (OSError, ValueError, KeyError):
        entries = []
    entries = [e for e in entries if "from" in e and (ROOT / e["path"]).is_file()]
    have = {(e["id"], e["variant"].lower()) for e in entries}
    owner = {e["id"]: e["from"] for e in entries}  # the first source with an ID owns it and its variants
    taken = {e["path"].lower() for e in entries}
    added = 0
    sources = ([(args.credit, lambda: harvest_local(args.local))] if args.local else []) + \
        [(repo, lambda repo=repo: harvest(repo)) for repo in SOURCES]
    for repo, load in sources:
        try:
            found = load()
        except OSError as e:  # a source that's gone or down just adds nothing this time
            print(f"skipped {repo}: {e}", file=sys.stderr)
            continue
        for entry, text in candidates(repo, found, api):
            if (entry["id"], entry["variant"].lower()) in have or owner.setdefault(entry["id"], repo) != repo:
                continue
            describe(entry, api)
            entry["path"] = new_path(entry, taken)
            out = ROOT / entry["path"]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(text.encode("utf-8"))
            have.add((entry["id"], entry["variant"].lower()))
            taken.add(entry["path"].lower())
            entries.append(entry)
            added += 1

    for entry in entries:
        describe(entry, api)  # AmiiboAPI names can improve after a dump was imported
    entries.sort(key=lambda e: (e["game"].lower(), e["name"].lower(), e["path"]))
    keys = ("id", "name", "character", "game", "series", "type", "line", "path", "variant", "from", "from_path",
            "fallback_name", "fallback_game", "fallback_type")
    data = {"source": REPO, "ref": "main", "amiibo": [{k: e[k] for k in keys} for e in entries]}
    INDEX.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = sorted({f"{a['amiiboSeries']}: {a['name']}" for i, a in api.items()
                      if not any(e["id"] == i for e in entries)})
    wanted = ["# Wanted", "",
              "amiibo that AmiiboAPI lists but no source has a dump of yet. If you own one, read it with a Flipper",
              "(NFC > Read, then Save) and open a pull request or an issue with the .nfc file.", ""]
    (DUMPS / "WANTED.md").write_text("\n".join(wanted + [f"- {m}" for m in missing]) + "\n", encoding="utf-8")
    print(f"{added} new dumps, {len(entries)} in total. Not dumped anywhere yet: {len(missing)}", file=sys.stderr)


if __name__ == "__main__":
    main()
