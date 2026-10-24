# Credits

These dumps were collected by other people. fetchamiibo copies them here so the tool keeps working on its own,
and every entry in `fetchamiibo/index.json` records where its file came from (`from` and `from_path`).

| Source | What it gave |
|---|---|
| [Gioman101/FlipperAmiibo](https://github.com/Gioman101/FlipperAmiibo) | The original collection: 931 Flipper `.nfc` dumps, copied byte for byte |
| [AmiiboDB/Amiibo](https://github.com/AmiiboDB/Amiibo) | Newer amiibo such as Sora, Pyra and Mythra, Side Order, Tears of the Kingdom and Xenoblade 3, converted from `.bin` |
| [Re3koning/AmiiboFiles](https://github.com/Re3koning/AmiiboFiles) | Metroid Prime 4, more Tears of the Kingdom, Splatoon Raiders, Donkey Kong Bananza |
| [AmiiboAPI](https://www.amiiboapi.org/) ([8bitDream/AmiiboAPI](https://github.com/8bitDream/AmiiboAPI)) | Names, games, series and types, matched by the amiibo ID inside each dump |

Thank you to all of them.

Each amiibo ID is taken from the first source above that has it. Dumps from `.bin` files are converted to the same
Flipper layout as the FlipperAmiibo files. Dumps whose ID AmiiboAPI doesn't know, such as guessed pre-release IDs,
are left out. [WANTED.md](WANTED.md) lists the amiibo that nobody has dumped yet.
