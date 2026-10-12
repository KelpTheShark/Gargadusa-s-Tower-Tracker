"""One-off helper: pulls display names/requirements for callings, ambitions and traits
out of the game's own app.asar so the tracker can show readable names.
Read-only. Run: python tools/extract_game_data.py   -> writes game_data.json"""
import json, re, struct, sys
from pathlib import Path

ASAR = Path(r'C:\Program Files (x86)\Steam\steamapps\common\GargadusasTower\resources\app.asar')
OUT = Path(__file__).resolve().parent.parent / 'game_data.json'

def asar_files():
    f = open(ASAR, 'rb')
    f.seek(4); psz = struct.unpack('<I', f.read(4))[0]
    f.seek(12); hl = struct.unpack('<I', f.read(4))[0]
    hdr = json.loads(f.read(hl)); base = 8 + psz
    def walk(n, p=''):
        for k, v in n.get('files', {}).items():
            q = p + '/' + k
            if 'files' in v: yield from walk(v, q)
            elif not v.get('unpacked'): yield q, int(v['size']), int(v['offset'])
    for q, s, off in walk(hdr):
        yield q, (lambda s=s, off=off: (f.seek(base + off), f.read(s))[1])

def balanced(s, start):
    """Return the {...} block starting at s[start]=='{'."""
    depth = 0; i = start; instr = None
    while i < len(s):
        c = s[i]
        if instr:
            if c == chr(92): i += 1
            elif c == instr: instr = None
        elif c in '"\'`': instr = c
        elif c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: return s[start:i + 1]
        i += 1

def js_obj_to_json(txt):
    txt = re.sub(r'([{,])\s*([A-Za-z_$][\w$]*)\s*:', r'\1"\2":', txt)
    txt = txt.replace('!0', 'true').replace('!1', 'false')
    txt = re.sub(r'(?<![\w."])\.(\d)', r'0.\1', txt)
    return txt

def main():
    data = {'callings': {}, 'ambitions': {}, 'traits': {}, 'titleBonuses': {}, 'sites': {}}
    for q, rd in asar_files():
        if q.endswith('artCatalog-B44K-f1G.js') or 'artCatalog' in q:
            s = rd().decode('utf-8', 'replace')
            for m in re.finditer(r'(\w+):\{id:"\1",name:"([^"]+)",family:"(\w+)"', s):
                blk = balanced(s, m.start() + len(m.group(1)) + 1)
                if not blk: continue
                d = {'name': m.group(2), 'family': m.group(3)}
                for key, pat in (('titleId', r'titleId:"(\w+)"'), ('flavor', r'signatureFlavor:"([^"]*)"')):
                    mm = re.search(pat, blk); d[key] = mm.group(1) if mm else None
                for key in ('deedGate', 'calling', 'ascension'):
                    mm = re.search(key + r':\{', blk)
                    if mm:
                        sub = balanced(blk, mm.end() - 1)
                        try: d[key] = json.loads(js_obj_to_json(sub))
                        except Exception: d[key] = {'raw': sub}
                rm = re.search(r'roles:\[([^\]]*)\]', blk)
                d['roles'] = re.findall(r'"(\w+)"', rm.group(1)) if rm else []
                data['callings'][m.group(1)] = d
            for m in re.finditer(r'\b(Lo|Oo)=\{', s):
                blk = balanced(s, m.end() - 1)
                try: data['titleBonuses'].update(json.loads(js_obj_to_json(blk)))
                except Exception: pass
        if q.endswith('locale-en-CZdMWsWK.js') or re.search(r'locale-en-\w+\.js$', q):
            s = rd().decode('utf-8', 'replace')
            m = re.search(r'uHa=\{site:\{', s)
            if m:
                blk = s[m.start():m.start() + 400000]
                for mm in re.finditer(r'(\w+):\{name:"([^"]+)",broke:', blk):
                    data['sites'][mm.group(1)] = mm.group(2)
            m = re.search(r'IYe=\{', s)
            if m:
                blk = balanced(s, m.end() - 1)
                for mm in re.finditer(r'(\w+):\{name:"([^"]+)",description:"([^"]*)"', blk):
                    data['ambitions'][mm.group(1)] = {'name': mm.group(2), 'description': mm.group(3)}
            m = re.search(r'morale_anchor:\{name', s)
            if m:
                blk = s[max(0, m.start() - 8000):m.start() + 8000]
                for mm in re.finditer(r'(\w+):\{name:"([^"]+)",description:"([^"]*)"', blk):
                    data['traits'][mm.group(1)] = {'name': mm.group(2), 'description': mm.group(3)}
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    print({k: len(v) for k, v in data.items()}, '->', OUT)

if __name__ == '__main__':
    main()
