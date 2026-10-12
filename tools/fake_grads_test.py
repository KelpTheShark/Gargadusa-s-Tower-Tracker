"""Dev helper: injects synthetic academy graduates into a copy of a real save, runs it through the
reader + archive (including a simulated game trim to the last 20), and writes dev_data.json for the
browser preview. Nothing in the real save folder or archive is touched."""
import json
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
T = tempfile.mkdtemp()
os.makedirs(T + '/saves')
base = os.path.expandvars(r'%APPDATA%') + '/gargadusa/saves/'
raw = json.load(open(base + 'autosave.json', encoding='utf-8'))
g = raw['gameState']
random.seed(4)
classes = ['Knight', 'Archer', 'Priest', 'Rogue', 'Arcane Mage', 'Bard', 'Warrior', 'Mistwalker', 'Paladin', 'Druid']
roles = ['Tank', 'Healer', 'Melee', 'Ranged']
tiers = ['F-Tier', 'D-Tier', 'C-Tier', 'B-Tier', 'A-Tier', 'S-Tier']
gh = []
for i in range(70):
    z = {'id': f'youth-{i}', 'name': f'Grad Test {i}', 'potential': random.choice(tiers), 'role': random.choice(roles),
         'className': random.choice(classes), 'outcome': random.choice(['signed', 'signed', 'delivered', 'released']),
         'year': 1 + i // 15, 'gradOvr': random.randint(30, 70), 'gradLevel': random.randint(2, 6),
         'gradAge': random.randint(18, 22), 'gradSunSign': random.choice(['aries', 'leo', 'virgo']),
         'gradPortraitNum': random.randint(1, 200), 'gradGender': random.choice('MF'),
         'gradPortraitAgeBracket': 'young', 'sourceName': 'Academy'}
    if i < 8:
        z['rosterId'] = g['roster'][i]['id']
    elif i < 14:
        z['rosterId'] = f'gone-{i}'
    gh.append(z)
g['academy']['graduateHistory'] = gh
g['academy']['totalGraduates'] = len(gh)
json.dump(raw, open(T + '/saves/autosave.json', 'w', encoding='utf-8'))
os.environ['GTT_SAVE_DIR'] = T + '/saves'
os.environ['GTT_ARCHIVE'] = T + '/arch.json'
import app  # noqa: E402

a = app.Api().load('autosave.json')['data']['academy']
print('full:', a['total'], len(a['grads']))
before = next(r for r in a['grads'] if r['id'] == 'youth-0')['snap'][0]['stats'][0]['v']
hero = g['roster'][0]
hero['stats']['str'] += 25                           # the hero keeps growing after graduation
g['academy']['graduateHistory'] = gh[-20:]           # the game trims to the last 20
json.dump(raw, open(T + '/saves/autosave.json', 'w', encoding='utf-8'))
d = app.Api().load('autosave.json')['data']
r0 = next(r for r in d['academy']['grads'] if r['id'] == 'youth-0')
print('STR at graduation', before, '-> shown after growth:', r0['snap'][0]['stats'][0]['v'], '(hero now', round(hero['stats']['str']), ')',
      'FROZEN' if r0['snap'][0]['stats'][0]['v'] == before else 'BROKEN')
g['roster'] = g['roster'][4:]                        # and a graduate leaves the roster
json.dump(raw, open(T + '/saves/autosave.json', 'w', encoding='utf-8'))
d = app.Api().load('autosave.json')['data']
r5 = next(r for r in d['academy']['grads'] if r['id'] == 'youth-1')
print('after trim + departure:', len(d['academy']['grads']), 'kept', sum(r['kept'] for r in d['academy']['grads']), '| youth-1', r5['status'], 'snap kept' if r5['snap'] else 'NO SNAP')
json.dump(d, open(ROOT / 'dev_data.json', 'w', encoding='utf-8'), ensure_ascii=False)
shutil.rmtree(T, ignore_errors=True)
