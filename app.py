"""Gargadusa's Tower tracker - desktop entry point.

Same shape as the HRM tracker: index.html is the UI, this file exposes a small
pywebview js_api so the page can read the game's save folder and portraits.
Everything is read-only - the game's files are never written to.
"""
import base64
import json
import os
import struct
import threading
import time
import sys
from pathlib import Path

import webview

import archive
import save_reader

BUNDLE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
USER_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
CONFIG_PATH = USER_DIR / 'config.json'
ARCHIVE = archive.Archive(os.environ.get('GTT_ARCHIVE') or USER_DIR / 'archive.json')   # everything the game has since pruned lives on here
ASAR = Path(r'C:\Program Files (x86)\Steam\steamapps\common\GargadusasTower\resources\app.asar')


def _read_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    except OSError:
        pass


def _ingest(filename):
    """Read a save, merge it into the archive, return the merged view."""
    with archive.LOCK:
        return ARCHIVE.ingest(save_reader.load(filename))


def _watch_saves():
    """Keep the archive growing for every save slot, not just the one on screen."""
    seen = {}
    while True:
        try:
            for p in sorted(save_reader.SAVE_DIR.glob('*.json')):
                m = p.stat().st_mtime_ns
                if seen.get(p.name) != m:
                    seen[p.name] = m
                    try:
                        _ingest(p.name)
                    except Exception:
                        seen.pop(p.name, None)   # mid-write; retry next pass
        except OSError:
            pass
        time.sleep(15)


class Api:
    def __init__(self):
        # Keep private (underscore) - pywebview walks public attributes of the js_api object.
        self._asar_index = None
        self._asar_stamp = None
        self._portrait_cache = {}

    # ---- saves
    def list_saves(self):
        return {'saves': save_reader.list_saves(), 'selected': _read_config().get('selected')}

    def select_save(self, filename):
        cfg = _read_config()
        cfg['selected'] = filename
        _write_config(cfg)
        return True

    def load(self, filename):
        try:
            return {'ok': True, 'data': _ingest(filename)}
        except Exception as e:  # surface to the page rather than hanging it
            return {'ok': False, 'error': f'{type(e).__name__}: {e}'}

    def mtime(self, filename):
        return save_reader.mtime(filename)

    # ---- portraits (read straight out of the game's own install)
    def _stamp(self):
        try:
            st = ASAR.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _index(self):
        """Offsets into app.asar. Rebuilt whenever the game's archive changes (a game update moves every
        offset), and never cached when it could not be read."""
        stamp = self._stamp()
        if self._asar_index and stamp == self._asar_stamp:
            return self._asar_index
        self._portrait_cache = {}
        self._asar_index, self._asar_stamp = {}, stamp
        try:
            with open(ASAR, 'rb') as f:
                f.seek(4)
                psz = struct.unpack('<I', f.read(4))[0]
                f.seek(12)
                hl = struct.unpack('<I', f.read(4))[0]
                node = json.loads(f.read(hl))['files']['dist']['files']['adventurers']['files']['classic']['files']
            base = 8 + psz
            idx = {}
            for folder, sub in node.items():
                for fn, meta in (sub.get('files') or {}).items():
                    if fn.endswith('.png'):
                        idx[f'{folder}/{fn[:-4]}'] = (base + int(meta['offset']), int(meta['size']))
            self._asar_index = idx
        except Exception:
            self._asar_stamp = None      # force a retry next time
        return self._asar_index

    def portraits(self, keys):
        idx = self._index()
        out = {}
        try:
            f = open(ASAR, 'rb')
        except OSError:
            return out
        with f:
            for k in keys or []:
                if k in self._portrait_cache:
                    out[k] = self._portrait_cache[k]
                elif k in idx:
                    off, size = idx[k]
                    f.seek(off)
                    data = f.read(size)
                    if data[:8] != b'\x89PNG\r\n\x1a\n':   # offsets are stale/garbled: drop them, retry on the next call
                        self._asar_stamp = None
                        continue
                    url = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
                    self._portrait_cache[k] = out[k] = url
        return out


def main():
    api = Api()
    threading.Thread(target=_watch_saves, daemon=True).start()
    webview.create_window(
        "Gargadusa's Tower Tracker",
        url=str(BUNDLE_DIR / 'index.html'),
        js_api=api,
        width=1280, height=860, min_size=(900, 600),
        background_color='#14110f',
    )
    webview.start()


if __name__ == '__main__':
    main()
