# Gargadusa's Tower Tracker

A desktop tracker for Gargadusa's Tower. It reads your save files and keeps a permanent archive of the notable things the game eventually prunes.

**Tabs:** Hall of Fame legends · Ascended Heroes · Yearly Awards · Crown Cup & League history · Memorial · Bestiary (Legends Slain) · Academy Graduates · Commanders

## Download

Grab `GargadusasTowerTracker.exe` from the [Releases](../../releases) page and run it. No install needed (Windows).

- It reads your saves from `%APPDATA%\gargadusa\saves` and never writes to the game's folders.
- Put the exe in its own folder: it creates `archive.json` and `config.json` next to itself. `archive.json` is your permanent history, so keep it (back it up, or keep the folder in Dropbox).
- Anything the game later prunes from your save stays visible, tagged 📦 kept.
- Hero portraits are read from the game's install at the default Steam path (`C:\Program Files (x86)\Steam\steamapps\common\GargadusasTower`). If the game is installed elsewhere the tracker still works but shows a generic icon instead of portraits.
- Leave the tracker running when a trainee graduates, before you sign them, to capture their exact graduation stat sheet.

## Source

The code is here too. To run or build from source:

    pip install pywebview pyinstaller
    python app.py
    python -m PyInstaller --onefile --windowed --noconfirm --name GargadusasTowerTracker --add-data "index.html;." --add-data "game_data.json;." app.py

`game_data.json` holds calling, ambition and trait names; `tools/extract_game_data.py` regenerates it from your install after a game update.

Browser preview for UI work: `python tools/fake_grads_test.py` writes a `dev_data.json` from a real save plus synthetic graduates; serve the folder with `python -m http.server` and open `index.html` (it falls back to `dev_data.json` when there is no pywebview bridge).

Ability, trait and ambition text © Gargadusa’s Tower, included with the developer’s permission
