# fetchamiibo

Download an amiibo's NFC dump from the command line, ready to write with a Flipper Zero.

```
fetchamiibo isabelle
```

```
Which one?
> 1) Isabelle  (Animal Crossing, Card, Series 1)
  2) Isabelle  (Animal Crossing, Card, Series 5)
  3) Isabelle  (Super Smash Bros., Figure)
  4) More amiibo with this in the name (7)...
```

- **Type a name** and it's saved straight away. If several amiibo share that name (Isabelle is a card, a
  Series 5 card and a Smash figure), you get a **Which one?** menu listing them all with their games.
- **Type nothing** and you get menus: pick a **game**, then a **letter**, then the amiibo.
- Menus work with the **arrow keys** or the **mouse** (click a row; the wheel scrolls). Type a letter to jump to
  it, a number to jump to that row, Backspace or Left to go back, and Esc to quit.
- Typos are fine: `fetchamiibo toon-link`, `fetchamiibo pokemon trainer`, `fetchamiibo isabele`.

956 amiibo across 28 games: Smash (Sora included), Animal Crossing cards and figures, Zelda up to Tears of the
Kingdom, Mario, Splatoon up to Side Order and Raiders, Metroid Prime 4, Xenoblade 3, Fire Emblem, Kirby,
Monster Hunter, Mario Sports Superstars cards and more. The dumps live in this repository under
[`dumps/`](dumps), so nothing depends on anyone else's repository staying up.

## Install

| | |
|---|---|
| **Homebrew** (macOS, Linux, [brew-windows](https://github.com/SamuelArther/brew-windows)) | `brew install samuelarther/tap/fetchamiibo` |
| **Scoop** (Windows) | `scoop bucket add samuelarther https://github.com/SamuelArther/scoop-bucket`<br>`scoop install fetchamiibo` |
| **winget** (Windows) | `winget install SamuelArther.fetchamiibo` |
| **pip** (any OS, Python 3.9+) | `pipx install fetchamiibo` or `pip install fetchamiibo` |
| **Download** | Single-file programs for Windows, macOS and Linux on the [Releases](https://github.com/SamuelArther/fetchamiibo/releases) page |

No dependencies beyond Python's standard library.

## Usage

```
fetchamiibo                      menus: game -> letter -> amiibo
fetchamiibo <name>               save that amiibo (asks "Which one?" if several match)
fetchamiibo <name> --all         save every amiibo that matches, no questions
fetchamiibo <name> --bin         also save a raw 540-byte .bin (Tagmo, Proxmark, phone NFC writers)
fetchamiibo <name> -o DIR        save into DIR
fetchamiibo --list               print every amiibo: game, name, type
fetchamiibo --update             download the newest amiibo list
```

Files are named after the amiibo, plus the game when the name alone is ambiguous:
`Toon Link.nfc`, `Isabelle (Super Smash Bros.).nfc`, `Isabelle (Animal Crossing, Series 5).nfc`.

## Getting it onto the Flipper

- **SD card in your computer:** if a Flipper SD card is plugged in (it has `nfc` and `subghz` folders),
  fetchamiibo saves straight to `nfc/amiibo/` on it. `-o` overrides that.
- **Over USB:** open [qFlipper](https://flipperzero.one/update), go to the file manager, and drag the `.nfc` file into
  `SD Card/nfc/`.

Then on the Flipper: **NFC > Saved > the amiibo > Emulate**, and hold it to the Switch / 3DS / Wii U reader.
To make a physical copy, use **Write** with a blank NTAG215 tag, or use the `.bin` with Tagmo on Android.

## Where the dumps come from

Collected from [Gioman101/FlipperAmiibo](https://github.com/Gioman101/FlipperAmiibo) (the bulk of them),
[AmiiboDB/Amiibo](https://github.com/AmiiboDB/Amiibo) and [Re3koning/AmiiboFiles](https://github.com/Re3koning/AmiiboFiles),
named with [AmiiboAPI](https://www.amiiboapi.org/). Full credits are in [dumps/CREDITS.md](dumps/CREDITS.md).

- A weekly GitHub Action (`python tools/import_dumps.py`) copies in anything new those repositories add and
  rebuilds `fetchamiibo/index.json`. `fetchamiibo --update` fetches the latest list.
- [dumps/WANTED.md](dumps/WANTED.md) lists the amiibo nobody has dumped yet: the newest Street Fighter 6 cards,
  Kirby Air Riders, Mario Galaxy and more.

### Adding amiibo you own

Read the real amiibo with a Flipper Zero (**NFC > Read**, hold the amiibo to the back, **Save**). Then either open
an issue or pull request with the `.nfc` file, or add it yourself:

```
python tools/import_dumps.py --local path/to/your/dumps --credit "your name"
```

`.nfc` and raw `.bin` dumps both work, and amiibo that are already in the collection are skipped.

## Development

```
python -m unittest discover -s tests       # unit tests, no network
python -m fetchamiibo isabelle             # run from the checkout
python tools/console_drive.py "wait2,down,enter" -o out   # Windows: drive the arrow menus in a hidden console
```

Releases: bump `__version__` in `fetchamiibo/__init__.py`, then push a `v*` tag. `release.yml` builds the
programs and `pypi.yml` publishes to PyPI.

amiibo is a trademark of Nintendo. Flipper Zero is a trademark of Flipper Devices. This project is not affiliated
with either.

MIT licensed.
