"""fetchamiibo: download amiibo NFC dumps for a Flipper Zero (or as raw .bin for other NFC writers)."""
import argparse
import difflib
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

__version__ = "1.1.0"

REPO = "SamuelArther/fetchamiibo"
INDEX_URL = f"https://raw.githubusercontent.com/{REPO}/main/fetchamiibo/index.json"
BUNDLED_INDEX = Path(__file__).resolve().parent / "index.json"
UA = {"User-Agent": f"fetchamiibo/{__version__} (+https://github.com/{REPO})"}
BACK = "< Back"


def cache_dir():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "fetchamiibo"


class NotFound(Exception):
    pass


# ---------------------------------------------------------------- index

def load_index():
    """The index downloaded by --update if there is one, otherwise the copy that shipped with this version."""
    for path in (cache_dir() / "index.json", BUNDLED_INDEX):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("amiibo"):
                return data
        except (OSError, ValueError):
            continue
    sys.exit("fetchamiibo: the amiibo list is missing. Run `fetchamiibo --update` to download it.")


def update_index():
    data = json.loads(download(INDEX_URL))
    if not data.get("amiibo"):
        raise ValueError("the downloaded amiibo list is empty")
    path = cache_dir() / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def download(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def norm(text):
    """Loose form for matching: 'Pokémon' == 'pokemon', 'Midna & Wolf Link' == 'midna and wolf link'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def details(entry, game=True):
    """'Super Smash Bros., Figure', plus the card series when there is one."""
    parts = [entry["game"]] if game else []
    parts.append(entry["type"])
    if entry.get("line") and entry["line"] != entry["game"]:
        parts.append(entry["line"])
    return ", ".join(parts)


def label(entry, game=True):
    return f"{entry['name']}  ({details(entry, game)})"


def search(entries, query):
    """(exact, others): amiibo named exactly `query`, and the rest that contain it. With no exact or
    partial hits, `others` holds the closest spellings."""
    q = norm(query)
    exact = [e for e in entries if norm(e["name"]) == q]
    words = q.split()
    partial = [e for e in entries if e not in exact
               and all(w in norm(e["name"]) or w in norm(e["character"]) for w in words)]
    partial.sort(key=lambda e: (len(e["name"]), e["game"], e["name"]))
    if exact or partial:
        return exact, partial
    names = {norm(e["name"]): None for e in entries}
    close = difflib.get_close_matches(q, list(names), n=8, cutoff=0.6)
    return [], sorted((e for e in entries if norm(e["name"]) in close),
                      key=lambda e: (close.index(norm(e["name"])), e["game"]))


def letter_of(entry):
    first = norm(entry["name"])[:1].upper()
    return first if first.isalpha() else "#"


# ---------------------------------------------------------------- menus

def ask(prompt, default=None):
    try:
        answer = input(prompt).strip().lstrip("﻿")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return answer or default


def arrow_keys_ok():
    """Arrow-key menus need a real console on both ends; piped input gets the numbered prompts."""
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def enable_ansi():
    """Let the classic Windows console understand the escape codes the menus redraw with."""
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle, mode = kernel.GetStdHandle(-11), ctypes.c_uint32()
        if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


class WinConsole:
    """Raw Windows console input, so menus get mouse clicks and the scroll wheel as well as keys."""
    VK = {0x26: "up", 0x28: "down", 0x21: "pgup", 0x22: "pgdn", 0x24: "home", 0x23: "end",
          0x0D: "enter", 0x1B: "esc", 0x08: "backspace", 0x25: "left"}

    def __init__(self):
        import ctypes
        from ctypes import wintypes as w

        class KEY(ctypes.Structure):
            _fields_ = [("down", w.BOOL), ("repeat", w.WORD), ("vk", w.WORD), ("scan", w.WORD),
                        ("char", w.WCHAR), ("state", w.DWORD)]

        class MOUSE(ctypes.Structure):
            _fields_ = [("x", w.SHORT), ("y", w.SHORT), ("buttons", w.DWORD), ("state", w.DWORD), ("flags", w.DWORD)]

        class EVENT(ctypes.Union):
            _fields_ = [("key", KEY), ("mouse", MOUSE), ("pad", w.BYTE * 16)]

        class RECORD(ctypes.Structure):
            _fields_ = [("type", w.WORD), ("event", EVENT)]

        class INFO(ctypes.Structure):
            _fields_ = [("size", w.SHORT * 2), ("cursor", w.SHORT * 2), ("attr", w.WORD),
                        ("window", w.SHORT * 4), ("max", w.SHORT * 2)]

        self.ctypes, self.w, self.RECORD, self.INFO = ctypes, w, RECORD, INFO
        self.kernel = ctypes.windll.kernel32
        self.stdin, self.stdout = self.kernel.GetStdHandle(-10), self.kernel.GetStdHandle(-11)
        self.saved = w.DWORD()
        self.kernel.GetConsoleMode(self.stdin, ctypes.byref(self.saved))

    def __enter__(self):
        # Mouse input on, quick-edit (which swallows clicks) and Ctrl+C-as-signal off while the menu is up.
        mode = (self.saved.value | 0x0010 | 0x0080) & ~0x0040 & ~0x0001 & ~0x0200
        self.kernel.SetConsoleMode(self.stdin, mode)
        return self

    def __exit__(self, *_):
        self.kernel.SetConsoleMode(self.stdin, self.saved)

    def cursor_row(self):
        info = self.INFO()
        self.kernel.GetConsoleScreenBufferInfo(self.stdout, self.ctypes.byref(info))
        return info.cursor[1]

    def read(self):
        """A key name or character, ("click", row), or wheelup / wheeldown."""
        rec, count = self.RECORD(), self.w.DWORD()
        while True:
            self.kernel.ReadConsoleInputW(self.stdin, self.ctypes.byref(rec), 1, self.ctypes.byref(count))
            if rec.type == 1 and rec.event.key.down:  # KEY_EVENT
                key = rec.event.key
                if key.vk in self.VK:
                    return self.VK[key.vk]
                if key.char == "\x03":
                    return "ctrl-c"
                if key.char and key.char != "\0":
                    return key.char
            elif rec.type == 2:  # MOUSE_EVENT
                m = rec.event.mouse
                if m.flags == 4:  # MOUSE_WHEELED: the high word of the button state is the direction
                    return "wheelup" if m.buttons & 0x80000000 == 0 else "wheeldown"
                if m.flags in (0, 2) and m.buttons & 1:  # left button pressed, or double-clicked
                    return ("click", m.y)


class PosixKeys:
    """Keyboard input for the menus on macOS and Linux, with mouse clicks through xterm mouse reporting."""

    def __enter__(self):
        sys.stdout.write("\x1b[?1000h\x1b[?1006h")  # report button presses, in SGR form
        sys.stdout.flush()
        return self

    def __exit__(self, *_):
        sys.stdout.write("\x1b[?1000l\x1b[?1006l")
        sys.stdout.flush()

    def cursor_row(self):
        """0-based screen row of the cursor, asked of the terminal with a cursor position report."""
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            sys.stdout.write("\x1b[6n")
            sys.stdout.flush()
            reply = ""
            while not reply.endswith("R") and len(reply) < 32 and select.select([fd], [], [], 0.3)[0]:
                reply += os.read(fd, 1).decode(errors="ignore")  # no answer in time = no mouse support
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        m = re.search(r"\[(\d+);\d+R", reply)
        return int(m[1]) - 1 if m else None

    def read(self):
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1).decode(errors="ignore")
            if ch == "\x1b" and select.select([fd], [], [], 0.05)[0]:
                seq = os.read(fd, 32).decode(errors="ignore")
                m = re.match(r"\[<(\d+);(\d+);(\d+)([Mm])", seq)
                if m:
                    button = int(m[1])
                    if button == 64:
                        return "wheelup"
                    if button == 65:
                        return "wheeldown"
                    return ("click", int(m[3]) - 1) if button == 0 and m[4] == "M" else ""
                return {"[A": "up", "[B": "down", "[D": "left", "[5~": "pgup", "[6~": "pgdn", "[H": "home",
                        "[F": "end", "OH": "home", "OF": "end"}.get(seq, "")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        return {"\r": "enter", "\n": "enter", "\x1b": "esc", "\x03": "ctrl-c", "\x7f": "backspace",
                "\x08": "backspace"}.get(ch, ch)


def menu_input():
    return WinConsole() if os.name == "nt" else PosixKeys()


def arrow_menu(title, rows, default=0, back=False):
    """Menu driven by the arrow keys or the mouse. Typing a number jumps to that row and typing a letter jumps
    to the next row starting with it. Returns the picked row index, or -1 for Backspace / Left when back=True."""
    enable_ansi()
    n, cols = len(rows), shutil.get_terminal_size().columns
    height = min(n, max(3, shutil.get_terminal_size().lines - 5))  # rows on screen; never more than there are
    width = len(str(n))
    cur, top, typed, drawn = default, 0, "", 0
    print()
    sys.stdout.write("\x1b[?25l")  # hide the cursor while the menu is up
    try:
        with menu_input() as keyboard:
            clicks = keyboard.cursor_row() is not None
            keys = ("Up/Down" + (" or click" if clicks else "") + ", Enter pick, type to jump"
                    + (", Backspace back" if back else "") + ", Esc quit")
            while True:
                top = min(max(top, cur - height + 1), cur)
                out = [(title + (f"  ({cur + 1} of {n})" if n > height else ""))[:cols - 1]]
                for i in range(top, top + height):
                    text = f"{'>' if i == cur else ' '} {i + 1:>{width}}) {rows[i]}"[:cols - 1]
                    out.append(f"\x1b[7m{text}\x1b[0m" if i == cur else text)
                out.append(f"\x1b[2m{keys[:cols - 1]}\x1b[0m")
                sys.stdout.write((f"\x1b[{drawn}F\x1b[J" if drawn else "") + "\n".join(out) + "\n")
                sys.stdout.flush()
                drawn = len(out)
                first_row = keyboard.cursor_row() - drawn + 1 if clicks else 0

                key = keyboard.read()
                if isinstance(key, tuple):  # ("click", screen row)
                    if not clicks:
                        continue
                    row = key[1] - first_row
                    if not 0 <= row < height:
                        continue
                    cur, key = top + row, "enter"
                typed = typed + key if key.isdigit() else ""
                if key.isdigit():
                    if not 1 <= int(typed) <= n:
                        typed = key
                    if 1 <= int(typed) <= n:
                        cur = int(typed) - 1
                elif len(key) == 1 and key.isalpha():
                    order = list(range(cur + 1, n)) + list(range(cur + 1))
                    cur = next((i for i in order if rows[i][:1].lower() == key.lower()), cur)
                elif key in ("up", "down"):
                    cur = (cur + (1 if key == "down" else -1)) % n
                elif key in ("wheelup", "wheeldown"):
                    cur = max(0, cur - 3) if key == "wheelup" else min(n - 1, cur + 3)
                elif key in ("pgup", "pgdn"):
                    cur = max(0, cur - height) if key == "pgup" else min(n - 1, cur + height)
                elif key in ("home", "end"):
                    cur = 0 if key == "home" else n - 1
                elif key in ("backspace", "left") and back:
                    sys.stdout.write(f"\x1b[{drawn + 1}F\x1b[J")
                    return -1
                elif key in ("esc", "ctrl-c"):
                    sys.stdout.write("\x1b[?25h\n")
                    sys.exit(1)
                elif key == "enter":
                    sys.stdout.write(f"\x1b[{drawn}F\x1b[J" + f"{title} {rows[cur]}"[:cols - 1] + "\n")
                    return cur
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def choose(title, options, back=False):
    """Pick one of `options`. Returns its index, or -1 when the user goes back (only offered with back=True)."""
    if arrow_keys_ok():
        rows = ([BACK] if back else []) + options
        i = arrow_menu(title, rows, default=1 if back and options else 0, back=back)
        return -1 if i == -1 or (back and i == 0) else i - (1 if back else 0)
    print(f"\n{title}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    if back:
        print("  b) back")
    while True:
        answer = ask(f"Pick [1-{len(options)}" + (", b" if back else "") + "]: ", "")
        if back and answer.lower() in ("b", "back"):
            return -1
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print("  Not an option, try again.")


def which_one(matches, more=()):
    """'Which one?' over amiibo that share a name. `more` are looser matches offered behind one extra row."""
    options = [label(e) for e in matches]
    if more:
        options.append(f"More amiibo with this in the name ({len(more)})...")
    i = choose("Which one?", options)
    if more and i == len(matches):
        return which_one(list(more))
    return matches[i]


def browse(entries):
    """Game -> letter -> amiibo menus. Returns the picked amiibo."""
    games = {}
    for e in entries:
        games.setdefault(e["game"], []).append(e)
    names = sorted(games, key=str.lower)
    while True:
        g = choose("Pick a game:", [f"{name} ({len(games[name])})" for name in names])
        in_game = games[names[g]]
        letters = {}
        for e in in_game:
            letters.setdefault(letter_of(e), []).append(e)
        keys = sorted(letters, key=lambda k: (k == "#", k))
        while True:
            if len(keys) > 1:
                li = choose("Pick a letter:", [f"{k} ({len(letters[k])})" for k in keys], back=True)
                if li == -1:
                    break
                picks = letters[keys[li]]
            else:
                picks = in_game
            picks = sorted(picks, key=lambda e: (norm(e["name"]), details(e, False)))
            ai = choose("Pick an amiibo:", [label(e, game=False) for e in picks], back=True)
            if ai != -1:
                return picks[ai]
            if len(keys) == 1:
                break


def lookup(entries, query, take_all=False):
    """Amiibo for a typed name: one straight away, or a 'Which one?' menu when several match."""
    exact, others = search(entries, query)
    matches = exact or others
    if not matches:
        raise NotFound(f"No amiibo called '{query}'. Run fetchamiibo with no name to browse them all.")
    if take_all or len(matches) == 1:
        return matches if take_all else [matches[0]]
    if not exact:
        print(f"No amiibo is called exactly '{query}'.")
    return [which_one(matches, others if exact else ())]


# ---------------------------------------------------------------- saving

def safe_filename(name):
    name = re.sub(r"\s*:\s*", " - ", name)
    return re.sub(r'[<>"/\\|?*]+', "_", name).strip(" .") or "amiibo"


def file_stem(entry, entries):
    """The amiibo's name, plus its game (and card series) when other amiibo share that name."""
    twins = [e for e in entries if norm(e["name"]) == norm(entry["name"])]
    if len(twins) < 2:
        return safe_filename(entry["name"])
    extra = entry["game"]
    if sum(e["game"] == entry["game"] for e in twins) > 1:
        extra += f", {entry.get('line') or entry['type']}"
    return safe_filename(f"{entry['name']} ({extra})")


def nfc_to_bin(text):
    """The 540-byte NTAG215 image (pages 0-134) that Tagmo, Proxmark and most phone writers use."""
    pages = dict(re.findall(r"^Page (\d+): ([0-9A-Fa-f ]+)$", text, re.M))
    try:
        return b"".join(bytes.fromhex(pages[str(i)]) for i in range(135))
    except (KeyError, ValueError):
        raise ValueError("the dump is not a complete NTAG215 image") from None


def find_flipper_sd():
    """A mounted Flipper Zero SD card (it has nfc/ and subghz/ folders at the top), if one is plugged in."""
    roots = []
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.SetErrorMode(1)  # no "insert a disk" dialogs for empty card readers
        mask = kernel.GetLogicalDrives()
        for i in range(2, 26):
            root = f"{chr(65 + i)}:\\"
            if mask >> i & 1 and kernel.GetDriveTypeW(root) == 2:  # DRIVE_REMOVABLE
                roots.append(Path(root))
    else:
        for base in ("/Volumes", f"/media/{os.environ.get('USER', '')}", "/media",
                     f"/run/media/{os.environ.get('USER', '')}"):
            try:
                roots += [p for p in Path(base).iterdir() if p.is_dir()]
            except OSError:
                pass
    for root in roots:
        try:
            if (root / "nfc").is_dir() and (root / "subghz").is_dir():
                return root
        except OSError:
            pass
    return None


def fetch(entry, index, out_dir, want_bin=False):
    """Download one amiibo's dump into out_dir. Returns the saved paths."""
    url = (f"https://raw.githubusercontent.com/{index['source']}/{index.get('ref', 'main')}/"
           + urllib.parse.quote(entry["path"]))
    try:
        text = download(url).decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # The dump moved since this list was made: get the current list and look the amiibo up by ID.
        fresh = update_index()
        moved = [x for x in fresh["amiibo"]
                 if x["id"] == entry["id"] and x.get("variant", "") == entry.get("variant", "")]
        if not moved:
            raise
        entry, index = moved[0], fresh
        url = (f"https://raw.githubusercontent.com/{index['source']}/{index.get('ref', 'main')}/"
               + urllib.parse.quote(entry["path"]))
        text = download(url).decode("utf-8")
    if not text.startswith("Filetype: Flipper NFC device"):
        raise ValueError(f"{url} is not a Flipper NFC file")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem(entry, index["amiibo"])
    saved = [out_dir / f"{stem}.nfc"]
    saved[0].write_bytes(text.encode("utf-8"))  # byte for byte, LF line endings and all
    if want_bin:
        saved.append(out_dir / f"{stem}.bin")
        saved[1].write_bytes(nfc_to_bin(text))
    return saved


def pause_if_double_clicked():
    """Keep the window open when the .exe was started from Explorer, which closes it as soon as we exit."""
    if os.name == "nt" and getattr(sys, "frozen", False) and arrow_keys_ok():
        import ctypes
        ids = (ctypes.c_uint32 * 4)()
        if ctypes.windll.kernel32.GetConsoleProcessList(ids, 4) <= 1:
            ask("Press Enter to close.")


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fetchamiibo",
        description="Download an amiibo's NFC dump to write with a Flipper Zero. With no name, pick one from "
                    "menus by game and letter.")
    parser.add_argument("name", nargs="*", help="amiibo name, e.g. isabelle or 'toon link'")
    parser.add_argument("-o", "--output", metavar="DIR",
                        help="folder to save into (default: a plugged-in Flipper SD card's nfc/amiibo "
                             "folder, otherwise the current folder)")
    parser.add_argument("--bin", action="store_true", help="also save a raw 540-byte .bin (Tagmo, Proxmark, ...)")
    parser.add_argument("--all", action="store_true", help="save every amiibo that matches the name, no questions")
    parser.add_argument("--list", action="store_true", help="print every amiibo (game, name, type) and exit")
    parser.add_argument("--update", action="store_true", help="download the newest amiibo list")
    parser.add_argument("--version", action="version", version=f"fetchamiibo {__version__}")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    try:
        if args.update:
            index = update_index()
            print(f"Amiibo list updated: {len(index['amiibo'])} amiibo.")
            if not args.name:
                return 0
        else:
            index = load_index()
        entries = index["amiibo"]

        if args.list:
            for e in entries:
                print(f"{e['game']}\t{e['name']}\t{details(e, False)}")
            return 0

        query = " ".join(args.name).strip()
        if query:
            picks = lookup(entries, query, args.all)
        else:
            print(f"fetchamiibo {__version__}: {len(entries)} amiibo")
            picks = [browse(entries)]

        if args.output:
            out_dir = Path(args.output).expanduser()
        else:
            sd = find_flipper_sd()
            out_dir = sd / "nfc" / "amiibo" if sd else Path.cwd()
            if sd:
                print(f"Flipper SD card found at {sd}")

        for entry in picks:
            for path in fetch(entry, index, out_dir, args.bin):
                print(f"Saved {path}")
        if not args.output and out_dir == Path.cwd():
            print("Copy the .nfc to your Flipper's SD card under nfc/ (qFlipper works), then open NFC > Saved.")
    except NotFound as e:
        print(e, file=sys.stderr)
        pause_if_double_clicked()
        return 1
    except (OSError, ValueError) as e:
        print(f"fetchamiibo: {e}", file=sys.stderr)
        pause_if_double_clicked()
        return 1
    pause_if_double_clicked()
    return 0
