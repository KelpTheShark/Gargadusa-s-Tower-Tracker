"""Keeps everything the tracker has ever seen.

The game trims old entries out of its own save (Hall of Fame legends/awards, the
memorial, history lists) as a campaign grows. Each time a save is read, its
notable data is merged into archive.json (beside the exe) and nothing is ever
removed from there. The page then shows the union, tagging entries the game has
since dropped as "kept".

Archive layout: { campaigns: { <worldDeck seed>: { name, legends{id}, ascended{id},
yearly{year{cat}}, realm{year{cat}}, cupSeasons{year}, cupEvents{year{event}},
memorial{id}, prizes{"year:event"} } } }
"""
import copy
import json
import os
import shutil
import threading
from pathlib import Path

LOCK = threading.RLock()
LEGEND_SORT = lambda e: (-len(e['badges']), e.get('name') or '')


def _when_key(w):
    return ((w or {}).get('year', 0), (w or {}).get('week', 0))



def _abs(w):
    return (w.get('year') or 0) * 52 + (w.get('week') or 0)


def _span(a, b):
    n = max(0, _abs(b) - _abs(a))
    y, w = divmod(n, 52)
    return {'weeks': n, 'text': (f'{y}y ' if y else '') + f'{w}w'}


class Archive:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {'version': 1, 'campaigns': {}}
        self._last = None
        self.load()

    # ---------------------------------------------------------- persistence
    def load(self):
        for p in (self.path, self.path.with_suffix('.prev.json')):
            try:
                self.data = json.loads(p.read_text(encoding='utf-8'))
                self.data.setdefault('campaigns', {})
                break
            except (OSError, json.JSONDecodeError):
                continue
        self._last = json.dumps(self.data, sort_keys=True)

    def save(self):
        blob = json.dumps(self.data, sort_keys=True)
        if blob == self._last:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_suffix('.prev.json'))
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.path)
            self._last = blob
            return True
        except OSError:
            return False


    def _resolve(self, base, epochs, name):
        """Pick which stored campaign this save belongs to. Same world seed is not enough: a restarted game with the
        same guild name reuses it. Saves of one run share embedded creation stamps; a restart shares none."""
        camps = self.data['campaigns']
        cands = [k for k in camps if k == base or k.startswith(base + '#')]
        fresh = set(epochs)
        best = max(cands, key=lambda k: len(fresh & set(camps[k].get('epochs', []))), default=None)
        if best is not None and fresh & set(camps[best].get('epochs', [])):
            return best
        legacy = [k for k in cands if not camps[k].get('epochs')]
        if legacy:                       # archive written before runs were fingerprinted: adopt it
            return legacy[0]
        if not cands:
            return base
        if not fresh:                    # nothing to compare against: assume the most recently seen run
            return max(cands, key=lambda k: _abs(camps[k].get('lastSeen') or {}))
        return f'{base}#{len(cands) + 1}'   # a different playthrough that happens to share the seed

    # ---------------------------------------------------------- merge
    def ingest(self, data):
        """Merge a freshly-read save summary into the archive and return the merged view."""
        with LOCK:
            heroes = data.pop('_heroes', {})
            fresh_prizes = data.pop('_prizes', {})
            epochs = data.pop('_epochs', [])
            key = self._resolve(data['campaign'], epochs, data['guild']['name'])
            data['campaign'] = key
            e = self.data['campaigns'].setdefault(key, {})
            seen = sorted(set(e.get('epochs', [])) | set(epochs))
            e['epochs'] = seen if len(seen) <= 2500 else seen[:60] + seen[-2440:]
            e['name'] = data['guild']['name']
            e['lastSeen'] = {'year': data['guild']['year'], 'week': data['guild']['week']}
            kept_total = 0

            # --- legends (grouped per hero, badges merged per category)
            arch = e.setdefault('legends', {})
            fresh_cats = {}
            for h in data['legends']:
                fresh_cats[h['id']] = {b['category'] for b in h['badges']}
                old = arch.get(h['id'])
                if old and h.get('where') == 'Gone':   # hero record left the save: keep the richer archived card
                    badges = h['badges']
                    h = copy.deepcopy(old)
                    h['badges'] = badges
                if old:
                    have = {b['category'] for b in h['badges']}
                    h['badges'] += [b for b in old['badges'] if b['category'] not in have]
                    h.pop('kept', None)
                h['badges'].sort(key=lambda b: _when_key(b.get('at')))
                arch[h['id']] = copy.deepcopy(h)
            legends = []
            for hid, h in arch.items():
                h = copy.deepcopy(h)
                cur = heroes.get(hid)
                if cur:
                    h.update({k: v for k, v in cur.items() if v is not None})
                elif h.get('where') in ('Active', None):
                    h['where'] = 'Gone'
                seen = fresh_cats.get(hid, set())
                for b in h['badges']:
                    b['kept'] = b['category'] not in seen
                    kept_total += b['kept']
                h['kept'] = hid not in fresh_cats
                legends.append(h)
            legends.sort(key=LEGEND_SORT)
            counts = {}
            for h in legends:
                for b in h['badges']:
                    counts[b['category']] = counts.get(b['category'], 0) + 1
            data['legends'], data['legendCounts'] = legends, counts
            held = {(h['id'], b['category']) for h in legends for b in h['badges']}
            for c in data['closing']:   # a badge the game pruned shouldn't show as "almost there"
                c['rows'] = [r for r in c['rows'] if (r['id'], c['category']) not in held]
            data['closing'] = [c for c in data['closing'] if c['rows']]

            # --- ascended heroes
            arch = e.setdefault('ascended', {})
            fresh_ids = set()
            for a in data['ascended']:
                if a.get('stub') and a['id'] in arch:   # hero record gone from the save - keep the full archived card
                    continue
                fresh_ids.add(a['id'])
                arch[a['id']] = copy.deepcopy(a)
            asc = []
            for hid, a in arch.items():
                a = copy.deepcopy(a)
                a['kept'] = hid not in fresh_ids
                if a['kept']:
                    kept_total += 1
                    cur = heroes.get(hid)
                    a['where'] = cur['where'] if cur else ('Gone' if a.get('where') == 'Active' else a.get('where'))
                asc.append(a)
            asc.sort(key=lambda a: (_when_key(a.get('ascendedAt'))[0] or 99, _when_key(a.get('ascendedAt'))[1] or 99))
            data['ascended'] = asc

            # --- yearly / realm awards
            for src, key, order in (('yearly', 'yearly', None), ('realm', 'realm', None)):
                arch = e.setdefault(key, {})
                fresh = {}
                for y in data[src]:
                    fresh[y['year']] = {a['category']: a for a in y['awards']}
                    slot = arch.setdefault(str(y['year']), {})
                    for a in y['awards']:
                        slot[a['category']] = copy.deepcopy(a)
                out = []
                for ys in sorted(arch, key=int):
                    rows = []
                    for cat, a in arch[ys].items():
                        a = copy.deepcopy(a)
                        a['kept'] = cat not in fresh.get(int(ys), {})
                        kept_total += a['kept']
                        rows.append(a)
                    # keep the game's own ordering where we know it
                    order_map = {}
                    for y in data[src]:
                        if y['year'] == int(ys):
                            order_map = {a['category']: i for i, a in enumerate(y['awards'])}
                    rows.sort(key=lambda a: order_map.get(a['category'], 99))
                    out.append({'year': int(ys), 'awards': rows})
                data[src] = out

            # --- Crown Cup seasons + festival history
            arch = e.setdefault('cupSeasons', {})
            fresh_years = set()
            for s in data['cup']['seasons']:
                fresh_years.add(s['year'])
                arch[str(s['year'])] = copy.deepcopy(s)
            seasons = []
            for ys in sorted(arch, key=int):
                s = copy.deepcopy(arch[ys])
                s['kept'] = int(ys) not in fresh_years
                kept_total += s['kept']
                seasons.append(s)
            data['cup']['seasons'] = seasons

            e.setdefault('prizes', {}).update(fresh_prizes)
            ev_arch = e.setdefault('cupEvents', {})
            hist = data['cup']['history']
            fresh_events = {}
            for y in hist['years']:
                slot = ev_arch.setdefault(str(y['year']), {})
                for k, ev in y['events'].items():
                    if ev.get('champion'):
                        fresh_events.setdefault(y['year'], set()).add(k)
                        slot[k] = copy.deepcopy(ev)
            have_years = {y['year'] for y in hist['years']}
            for ys in ev_arch:
                if int(ys) not in have_years:
                    hist['years'].append({'year': int(ys), 'current': False, 'events': {}})
            hist['years'].sort(key=lambda y: y['year'])
            stats = {'titles': 0, 'runnerUp': 0, 'third': 0, 'appearances': 0}
            for y in hist['years']:
                slot = ev_arch.get(str(y['year']), {})
                for k, _label in ((x['key'], x['label']) for x in hist['events']):
                    cur = y['events'].get(k)
                    if (not cur or not cur.get('champion')) and k in slot:
                        cur = copy.deepcopy(slot[k])
                        cur['kept'] = True
                        kept_total += 1
                        y['events'][k] = cur
                    elif cur and cur.get('champion'):
                        cur['kept'] = False
                    if cur and cur.get('player'):
                        p = cur['player']
                        p['gold'] = e['prizes'].get(p.get('key') or f"{y['year']}:{k}", p.get('gold'))
                        stats['appearances'] += 1
                        stats['titles'] += p['finish'] == 'champion'
                        stats['runnerUp'] += p['finish'] == 'finalist' or p.get('place') == 2
                        stats['third'] += p.get('place') == 3
                        slot_ev = ev_arch.setdefault(str(y['year']), {}).get(k)
                        if slot_ev and slot_ev.get('player'):
                            slot_ev['player']['gold'] = p['gold']
            hist['stats'] = stats

            # --- memorial
            arch = e.setdefault('memorial', {})
            fresh_ids = set()
            for m in data['memorial']:
                fresh_ids.add(m['id'])
                arch[m['id']] = copy.deepcopy(m)
            mem = []
            for mid, m in arch.items():
                m = copy.deepcopy(m)
                m['kept'] = mid not in fresh_ids
                kept_total += m['kept']
                mem.append(m)
            mem.sort(key=lambda m: _when_key(m.get('diedOn')), reverse=True)
            data['memorial'] = mem

            # --- commanders: evidence is accumulated, the timeline is rebuilt from it every time
            raw = data.pop('_cmd')
            c = e.setdefault('commanders', {'events': [], 'trust': [], 'heroes': {}, 'last': {}})
            # two different commanders can't be appointed in the same week: this save's evidence beats stale archive entries
            fresh_at = {(ev['year'], ev['week']): ev['name'] for ev in raw['events']}
            c['events'] = [x for x in c['events'] if fresh_at.get((x['year'], x['week']), x['name']) == x['name']]
            have = {(x['name'], x['year'], x['week']) for x in c['events']}
            for ev in raw['events']:
                if (ev['name'], ev['year'], ev['week']) not in have:
                    c['events'].append(ev)
                    have.add((ev['name'], ev['year'], ev['week']))
            th = {(x['name'], x['dir'], x['n'], x['year'], x['week']) for x in c['trust']}
            for t in raw['trust']:
                k = (t['name'], t['dir'], t['n'], t['year'], t['week'])
                if k not in th:
                    c['trust'].append(t)
                    th.add(k)
            for n, info in raw['heroes'].items():
                c['heroes'][n] = {**c['heroes'].get(n, {}), **{k: v for k, v in info.items() if v is not None}}
            cur = raw['current']
            if cur['name']:   # only the sitting commander's trust/approval moves; it freezes when they are replaced
                c['last'][cur['name']] = {'trust': cur['trust'], 'approval': cur['approval'], 'advice': cur['advice']}
            evs = sorted(c['events'], key=lambda x: (_abs(x), x['name']))
            stints = []
            for ev in evs:
                if stints and stints[-1]['name'] == ev['name']:
                    continue   # same commander seen from several sources
                stints.append({'name': ev['name'], 'start': {'year': ev['year'], 'week': ev['week']}})
            now = {'year': data['guild']['year'], 'week': data['guild']['week']}
            out = []
            for i, st in enumerate(stints):
                h = copy.deepcopy(c['heroes'].get(st['name'], {'name': st['name']}))
                nxt = stints[i + 1]['start'] if i + 1 < len(stints) else None
                died = h.get('diedOn') if h.get('where') == 'Fallen' else None
                serving = nxt is None and st['name'] == cur['name']
                end, reason = (nxt, 'replaced')
                if died and _abs(died) >= _abs(st['start']) and (nxt is None or _abs(died) <= _abs(nxt)):
                    end, reason = died, 'killed'
                ret = h.get('retiredAt') if h.get('where') == 'Retired' else None
                if ret and reason != 'killed' and _abs(ret) >= _abs(st['start']) and (nxt is None or _abs(ret) <= _abs(nxt)):
                    end, reason = ret, 'retired'
                if serving:
                    end, reason = now, 'serving'
                elif end is None:
                    end, reason = None, 'unknown'
                h.update({'start': st['start'], 'end': None if serving else end, 'reason': reason,
                          'tenure': _span(st['start'], end) if end else None,
                          'final': c['last'].get(st['name']),
                          'trust': sorted([t for t in c['trust'] if t['name'] == st['name']], key=_abs),
                          'kept': (h.get('where') in (None, 'Gone')) or not raw['heroes'].get(st['name'])})
                out.append(h)
            out.reverse()
            cur_view = next((x for x in out if x['reason'] == 'serving'), None)
            data['commanders'] = {'current': dict(cur, **({'hero': cur_view} if cur_view else {})), 'past': [x for x in out if x['reason'] != 'serving']}

            # --- legends slain (the game's own ledger caps at the last 40)
            arch = e.setdefault('slain', {})
            fresh_ids = set()
            for x in data['bestiary']['slain']:
                fresh_ids.add(x['id'])
                arch[x['id']] = copy.deepcopy(x)
            slain = []
            for sid, x in arch.items():
                x = copy.deepcopy(x)
                x['kept'] = sid not in fresh_ids
                kept_total += x['kept']
                slain.append(x)
            slain.sort(key=lambda x: _when_key(x.get('at')), reverse=True)
            data['bestiary']['slain'] = slain

            # --- academy graduates (the game trims graduateHistory to the last 20-30)
            arch = e.setdefault('grads', {})
            fresh_ids = set()
            for r in data['academy']['grads']:
                old = arch.get(r['id'])
                if old:
                    # graduation stats never update: keep the first snapshot (unless it was only a first-seen one and this is the real graduation sheet)
                    if old.get('snap') and not (old.get('snapAt') != 'graduation' and r.get('snapAt') == 'graduation' and r.get('snap')):
                        for k in ('snap', 'snapTop', 'snapAt'):
                            r[k] = old.get(k)
                    for k in ('portrait', 'sun', 'name', 'class', 'role', 'potential', 'year', 'gradOvr', 'gradLevel', 'gradAge'):
                        if r.get(k) in (None, []) and old.get(k) not in (None, []):
                            r[k] = old[k]
                    if r.get('outcome') == 'pending' and old.get('outcome') not in (None, 'pending'):
                        r['outcome'] = old['outcome']
                fresh_ids.add(r['id'])
                arch[r['id']] = copy.deepcopy(r)
            grads = []
            for gid, r in arch.items():
                r = copy.deepcopy(r)
                r['kept'] = gid not in fresh_ids
                if r['kept']:
                    kept_total += 1
                    if r.get('status') in ('Active', 'Injured', 'Free agent', 'On staff'):
                        r['status'] = 'Departed'
                grads.append(r)
            grads.sort(key=lambda r: (-(r.get('year') or 0), r.get('name') or ''))
            data['academy']['grads'] = grads
            data['academy']['total'] = max(data['academy'].get('total') or 0, len(grads))

            data['archive'] = {'kept': kept_total, 'path': str(self.path)}
            self.save()
            return data
