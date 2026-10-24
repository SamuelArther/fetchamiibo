import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fetchamiibo as fa  # noqa: E402


def amiibo(name, game, type_="Figure", line="", character=None, path=None):
    return {"id": "0" * 16, "name": name, "character": character or name, "game": game, "series": game,
            "type": type_, "line": line, "path": path or f"{game}/{name}.nfc"}


ENTRIES = [
    amiibo("Isabelle", "Animal Crossing", "Card", "Series 1"),
    amiibo("Isabelle", "Animal Crossing", "Card", "Series 5"),
    amiibo("Isabelle", "Super Smash Bros."),
    amiibo("Isabelle - Winter", "Animal Crossing", "Card", "Series 2", character="Isabelle"),
    amiibo("Toon Link", "Super Smash Bros."),
    amiibo("Midna & Wolf Link", "Legend Of Zelda", character="Midna"),
    amiibo("Pokémon Trainer", "Super Smash Bros."),
    amiibo("8-bit Mario", "Super Mario Bros."),
]

NFC = "Filetype: Flipper NFC device\nVersion: 2\nDevice type: NTAG215\n" + "".join(
    f"Page {i}: {i:02X} 00 00 {255 - i:02X}\n" for i in range(135))


class SearchTests(unittest.TestCase):
    def test_exact_name_finds_every_game(self):
        exact, others = fa.search(ENTRIES, "isabelle")
        self.assertEqual([e["game"] for e in exact], ["Animal Crossing", "Animal Crossing", "Super Smash Bros."])
        self.assertEqual([e["name"] for e in others], ["Isabelle - Winter"])

    def test_loose_spelling(self):
        self.assertEqual(fa.search(ENTRIES, "TOON-LINK")[0][0]["name"], "Toon Link")
        self.assertEqual(fa.search(ENTRIES, "midna and wolf link")[0][0]["name"], "Midna & Wolf Link")
        self.assertEqual(fa.search(ENTRIES, "pokemon trainer")[0][0]["name"], "Pokémon Trainer")

    def test_partial_and_typo(self):
        exact, others = fa.search(ENTRIES, "wolf")
        self.assertEqual((exact, [e["name"] for e in others]), ([], ["Midna & Wolf Link"]))
        exact, others = fa.search(ENTRIES, "isabele")
        self.assertEqual(exact, [])
        self.assertIn("Isabelle", [e["name"] for e in others])

    def test_lookup_single_and_missing(self):
        self.assertEqual(fa.lookup(ENTRIES, "toon link")[0]["name"], "Toon Link")
        with self.assertRaises(fa.NotFound):
            fa.lookup(ENTRIES, "zzqqxx")

    def test_lookup_all(self):
        self.assertEqual(len(fa.lookup(ENTRIES, "isabelle", take_all=True)), 3)

    def test_which_one_prompt(self):
        with mock.patch.object(fa, "arrow_keys_ok", return_value=False), \
                mock.patch("builtins.input", return_value="3"), mock.patch("sys.stdout", new=io.StringIO()) as out:
            picked = fa.lookup(ENTRIES, "isabelle")[0]
        self.assertEqual(picked["game"], "Super Smash Bros.")
        self.assertIn("Which one?", out.getvalue())
        self.assertIn("Isabelle  (Super Smash Bros., Figure)", out.getvalue())

    def test_which_one_more_row(self):
        answers = iter(["4", "1"])
        with mock.patch.object(fa, "arrow_keys_ok", return_value=False), \
                mock.patch("builtins.input", lambda _: next(answers)), mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(fa.lookup(ENTRIES, "isabelle")[0]["name"], "Isabelle - Winter")


class BrowseTests(unittest.TestCase):
    def test_game_letter_amiibo_with_back(self):
        # Animal Crossing -> letter I -> back -> I again -> second Isabelle
        answers = iter(["1", "b", "1", "2"])
        with mock.patch.object(fa, "arrow_keys_ok", return_value=False), \
                mock.patch("builtins.input", lambda _: next(answers)), mock.patch("sys.stdout", new=io.StringIO()):
            picked = fa.browse(ENTRIES)
        self.assertEqual((picked["name"], picked["line"]), ("Isabelle", "Series 5"))

    def test_letters(self):
        self.assertEqual(fa.letter_of(ENTRIES[-1]), "#")
        self.assertEqual(fa.letter_of(ENTRIES[6]), "P")


class FileTests(unittest.TestCase):
    def test_file_names_tell_twins_apart(self):
        self.assertEqual(fa.file_stem(ENTRIES[0], ENTRIES), "Isabelle (Animal Crossing, Series 1)")
        self.assertEqual(fa.file_stem(ENTRIES[2], ENTRIES), "Isabelle (Super Smash Bros.)")
        self.assertEqual(fa.file_stem(ENTRIES[4], ENTRIES), "Toon Link")
        self.assertEqual(fa.safe_filename('a: b/c?'), "a - b_c_")

    def test_nfc_to_bin(self):
        data = fa.nfc_to_bin(NFC)
        self.assertEqual(len(data), 540)
        self.assertEqual(data[:4], bytes([0, 0, 0, 255]))
        self.assertEqual(data[-4:], bytes([134, 0, 0, 121]))
        with self.assertRaises(ValueError):
            fa.nfc_to_bin(NFC.replace("Page 134:", "Page 999:"))

    def test_fetch_writes_nfc_and_bin(self):
        index = {"source": "x/y", "commit": "abc", "amiibo": ENTRIES}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(fa, "download", return_value=NFC.encode()) as dl:
            saved = fa.fetch(ENTRIES[5], index, Path(tmp), want_bin=True)
            self.assertEqual([p.name for p in saved], ["Midna & Wolf Link.nfc", "Midna & Wolf Link.bin"])
            self.assertEqual(saved[0].read_text(encoding="utf-8"), NFC)
        self.assertEqual(dl.call_args[0][0],
                         "https://raw.githubusercontent.com/x/y/abc/Legend%20Of%20Zelda/Midna%20%26%20Wolf%20Link.nfc")

    def test_fetch_rejects_non_nfc(self):
        index = {"source": "x/y", "commit": "abc", "amiibo": ENTRIES}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fa, "download", return_value=b"<html>"):
            with self.assertRaises(ValueError):
                fa.fetch(ENTRIES[0], index, Path(tmp))

    def test_flipper_sd_detection_on_posix_mounts(self):
        if sys.platform == "win32":
            self.skipTest("Windows looks at removable drive letters instead")
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "Flipper SD"
            (card / "nfc").mkdir(parents=True)
            (card / "subghz").mkdir()
            real_path = fa.Path
            with mock.patch.object(fa, "Path", lambda p: real_path(tmp) if p == "/Volumes" else real_path(p)):
                self.assertEqual(fa.find_flipper_sd(), card)


class IndexTests(unittest.TestCase):
    def test_bundled_index(self):
        data = json.loads(fa.BUNDLED_INDEX.read_text(encoding="utf-8"))
        self.assertRegex(data["commit"], r"^[0-9a-f]{40}$")
        self.assertGreater(len(data["amiibo"]), 800)
        for e in data["amiibo"]:
            self.assertTrue(e["name"] and e["game"] and e["path"].endswith(".nfc"), e)
        smash = [e for e in data["amiibo"] if e["name"] == "Isabelle" and e["game"] == "Super Smash Bros."]
        self.assertEqual(len(smash), 1)

    def test_main_list(self):
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            self.assertEqual(fa.main(["--list"]), 0)
        self.assertIn("Super Smash Bros.\tIsabelle\tFigure", out.getvalue())

    def test_main_not_found(self):
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(fa.main(["zzqqxx"]), 1)
        self.assertIn("No amiibo called", err.getvalue())


if __name__ == "__main__":
    unittest.main()
