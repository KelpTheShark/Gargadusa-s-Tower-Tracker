"""Reads a Gargadusa's Tower save (plain JSON) and boils it down to the notable
bits the tracker shows: Hall of Fame legends, ascended heroes, yearly awards and
the Crown Cup / Crown Cup League history. Read-only - never writes to the game's folder."""
import json
import os
import re
import sys
import time
from pathlib import Path

SAVE_DIR = Path(os.environ.get('GTT_SAVE_DIR') or (Path(os.environ.get('APPDATA', '')) / 'gargadusa' / 'saves'))
SEASONS = ['Spring', 'Summer', 'Autumn', 'Winter']
HERO_COLLECTIONS = [('roster', 'Active'), ('retirees', 'Retired'), ('memorial', 'Fallen')]
STAT_GROUPS = [
    ('Physical', ['str', 'dex', 'spd', 'agi']),
    ('Vitality', ['con', 'vit', 'end', 'dur', 'rec']),
    ('Mental', ['int', 'wis', 'lck']),
    ('Social', ['cha', 'ldr', 'tmw', 'tru', 'loy']),
    ('Combat', ['atk', 'def', 'hro', 'sur']),
    ('Arcane', ['arc', 'res']),
]

# Legend categories, mirrored from the game's own definitions (field + minimum).
LEGEND_DEFS = {
    'quest_master': dict(label='Quest Master', icon='⚔️', desc='Completed 100+ quests', field='questsCompleted', min=100),
    'iron_will': dict(label='Iron Will', icon='🛡️', desc='40+ quests without injury', field='questsWithoutInjury', min=40),
    'gold_standard': dict(label='Gold Standard', icon='💰', desc='Earned 25,000+ gold', field='totalGoldEarned', min=25000),
    'critical_ace': dict(label='Critical Ace', icon='🎯', desc='30+ critical successes', field='criticalSuccesses', min=30),
    'top_performer': dict(label='Star Player', icon='⭐', desc='Named top performer 20+ times', field='topPerformerCount', min=20),
    'peak_power': dict(label='Peak Power', icon='💎', desc='Reached 92+ OVR', field='ovr', min=92),
    'ascended': dict(label='Ascended', icon='✦', desc='Completed their Ambition journey and ascended', min=1),
    'wardkeeper': dict(label='Wardkeeper', icon='🗝️', desc='Stood the long watch and earned the Wardkeeper honor', min=1),
    'crown_champion': dict(label='Crown Champion', icon='👑', desc='Won a Crown Cup final', min=1),
    'raid_veteran': dict(label='Raid Veteran', icon='🔥', desc='Won 25+ raids', path=('raids', 'wins'), min=25),
    'tower_delver': dict(label='Tower Delver', icon='🗼', desc='Cleared 25+ tower floors', path=('tower', 'floorsCleared'), min=25),
}

AWARD_ORDER = ['mvp', 'sharpshooter', 'best_healer', 'iron_wall', 'unbreakable', 'rising_star', 'golden', 'veteran']
REALM_ORDER = ['realm_mvp', 'realm_slayer', 'realm_damage', 'realm_guardian', 'realm_healer', 'realm_clutch']
DIVISIONS = {'temple': 'Temple', 'merchants': 'Merchants', 'nobles': 'Nobles', 'military': 'Military'}


def app_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _load_game_data():
    try:
        return json.loads((app_dir() / 'game_data.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'callings': {}, 'ambitions': {}, 'traits': {}, 'titleBonuses': {}}


GAME = _load_game_data()


def pretty(s):
    return re.sub(r'\s+', ' ', re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', str(s or '')).replace('_', ' ').replace('-', ' ')).strip().title()


def when(d):
    if not d or d.get('year') is None:
        return None
    return {'year': d.get('year'), 'week': d.get('week')}


# ---------------------------------------------------------------- requirement text
def req_text(r):
    if not r:
        return ''
    t = r.get('type')
    n = r.get('count')
    if t == 'compound':
        joiner = ' and ' if r.get('mode', 'all') == 'all' else ' or '
        return joiner.join(req_text(c) for c in r.get('conditions', []))
    tier = f" (tier {r['minTier']}+)" if r.get('minTier') else ''
    table = {
        'top_performer': f'Named top performer {n}x',
        'critical_successes': f'{n} critical successes',
        'quests_without_injury': f'{n} quests without injury',
        'no_party_deaths': f'{n} quests with no party deaths',
        'underdog_victories': f'{n} underdog victories',
        'same_party_quests': f'{n} quests with the same party',
        'high_tier_quests': f'{n} high-tier quests{tier}',
        'witnessed_levelups': f'Witnessed {n} level-ups',
        'provings_assisted': f'Assisted {n} provings',
        'party_variety': f'Quested with {n} different parties',
        'location_variety': f'Quested in {n} different locations',
        'quest_variety': f"Completed {r.get('types')} different quest types",
        'total_quests': f'{n} quests completed',
        'first_completions': f'{n} first-time quest completions',
        'high_morale_streak': f"{n}-quest streak at {r.get('threshold')}+ morale",
        'ovr_threshold': f"Reach {r.get('ovr')} OVR",
        'gold_earned': f"Earn {int(r.get('amount', 0)):,} gold",
        'levels_gained': f'Gain {n} levels',
        'tower_floors': f'Clear {n} tower floors',
        'critical_recoveries': f'{n} critical recoveries',
    }
    return table.get(t, pretty(t) + (f' {n}' if n else ''))


BONUS_NAMES = {
    'damageBonus': 'damage', 'injuryReduction': 'injury reduction', 'deathReduction': 'death reduction',
    'powerBonus': 'party power', 'goldBonus': 'gold', 'xpBonus': 'XP', 'lootBonus': 'loot',
}


def bonus_text(b):
    return ', '.join(f"+{round(v * 100):g}% {BONUS_NAMES.get(k, pretty(k))}" for k, v in (b or {}).items())


# ---------------------------------------------------------------- heroes
def portrait_key(*candidates):
    """Pull 'adventurer-male-prime/84' style keys out of the game's portrait paths."""
    for c in candidates:
        m = re.search(r'(adventurer-(?:male|female)-(?:young|prime|veteran))/(\d+)\.png', str(c or ''))
        if m:
            return f'{m.group(1)}/{m.group(2)}'
    return None


def career(a, group, key):
    return ((a.get('careerStats') or {}).get(group) or {}).get(key) or 0


def trait_list(a):
    out = []
    for t in a.get('traits') or []:
        info = GAME['traits'].get(t) or {}
        out.append({'id': t, 'name': info.get('name') or pretty(t), 'desc': info.get('description', '')})
    return out


def brief(a, where):
    return {
        'id': a.get('id'), 'name': a.get('name'), 'class': a.get('class'), 'emoji': a.get('emoji'),
        'rarity': a.get('classRarity'), 'gender': a.get('gender'), 'age': a.get('age'),
        'level': a.get('level'), 'ovr': a.get('ovr'), 'where': where,
        'portrait': portrait_key(a.get('portrait'), a.get('portraitFallback')),
    }


def ambition_info(aid):
    info = GAME['ambitions'].get(aid) or {}
    return {'id': aid, 'name': info.get('name') or pretty(aid), 'desc': info.get('description', '')}


def ascended_detail(a, where):
    done = a.get('completedAmbitions') or []
    drive = next((c for c in done if c.get('tier') == 'drive'), None)
    calling = next((c for c in done if c.get('tier') == 'calling'), None)
    asc = next((c for c in done if c.get('tier') == 'ascension'), None)
    cid = (asc or calling or {}).get('id') or a.get('callingId')
    cdef = GAME['callings'].get(cid) or {}
    title_id = cdef.get('titleId')
    stats = a.get('stats') or {}
    d = brief(a, where)
    d.update({
        'joined': when({'year': a.get('joinedYear'), 'week': a.get('joinedWeek')}),
        'weeksInGuild': a.get('weeksInGuild'),
        'status': a.get('status'),
        'ascensionType': cdef.get('name') or pretty(cid),
        'ascensionId': cid,
        'flavor': cdef.get('flavor'),
        'family': cdef.get('family'),
        'callingReq': req_text((cdef.get('calling') or {}).get('requirement')),
        'ascensionReq': req_text((cdef.get('ascension') or {}).get('requirement')),
        'title': pretty(title_id) if title_id else None,
        'titleBonus': bonus_text(GAME['titleBonuses'].get(title_id)),
        'drive': dict(ambition_info((drive or {}).get('id') or a.get('ambition')), at=when(drive)),
        'callingDone': when(calling),
        'ascendedAt': when(asc),
        'traits': trait_list(a),
        'potential': a.get('potential'),
        'quests': a.get('questsCompleted'),
        'questSuccesses': a.get('questSuccesses'),
        'crits': a.get('criticalSuccesses'),
        'noInjury': a.get('questsWithoutInjury'),
        'topPerformer': a.get('topPerformerCount'),
        'gold': a.get('totalGoldEarned'),
        'kills': career(a, 'quests', 'totalKills'),
        'damage': career(a, 'quests', 'totalDamageDealt'),
        'healing': career(a, 'quests', 'totalHealingDone'),
        'records': a.get('recordTitleIds') or [],
        'signature': bool(a.get('signatureGranted')),
        'stats': [{'group': g, 'stats': [{'k': k.upper(), 'v': stats.get(k)} for k in ks if k in stats]} for g, ks in STAT_GROUPS],
        'sun': a.get('sunSign'), 'moon': a.get('moonSign'),
    })
    return d


def memorial_entry(a):
    gear = ((a.get('gearAtDeath') or {}).get('display')) or []
    car = a.get('career') or {}
    d = brief(a, 'Fallen')
    d.update({
        'joined': when({'year': a.get('joinedYear'), 'week': a.get('joinedWeek')}),
        'diedOn': when(a.get('diedOn')),
        'cause': a.get('cause'),
        'narrative': a.get('deathNarrative'),
        'gear': [{'name': x.get('name'), 'rarity': x.get('rarity')} for x in gear],
        'quests': a.get('questsCompleted'),
        'levelsGained': car.get('levelsGained'),
        'statsGained': car.get('totalStatsGained'),
        'bonds': car.get('bondsForged'),
        'allies': car.get('alliesWorkedWith'),
        'injuries': car.get('injuries'),
        'topPerformer': car.get('topPerformerCount'),
        'sun': car.get('sunSign') or a.get('sunSign'),
        'traits': trait_list(a),
        'titles': [pretty(t) for t in a.get('titles') or []],
        'kills': (((a.get('careerStats') or {}).get('quests') or {}).get('totalKills')) or 0,
        'damage': (((a.get('careerStats') or {}).get('quests') or {}).get('totalDamageDealt')) or 0,
    })
    return d


def site_name(sid):
    return (GAME.get('sites') or {}).get(sid) or pretty(sid)


def bestiary(g):
    led = g.get('breachLegends') or {}
    slain = [{
        'id': x.get('id'), 'name': x.get('name'), 'epithet': x.get('epithet'), 'title': x.get('title') or x.get('name'),
        'creature': pretty(x.get('baseId')), 'trophy': x.get('trophy'), 'site': site_name(x.get('site')),
        'severity': pretty(x.get('severity')), 'escapes': x.get('escapes') or 0, 'at': when(x),
        'slainBy': x.get('slainBy'),
    } for x in led.get('slain') or []]
    slain.sort(key=lambda x: ((x['at'] or {}).get('year', 0), (x['at'] or {}).get('week', 0)), reverse=True)
    at_large = [{
        'id': (x.get('legend') or {}).get('id'), 'title': (x.get('legend') or {}).get('title') or (x.get('legend') or {}).get('name'),
        'creature': pretty((x.get('legend') or {}).get('baseId')), 'escapes': x.get('escapes') or 0,
        'site': site_name(x.get('site')), 'severity': pretty(x.get('severity')), 'at': when(x),
    } for x in led.get('atLarge') or []]
    return {'slain': slain, 'atLarge': at_large}


STAFF_COLLECTIONS = ['staff', 'professionals', 'scouts', 'gatherers', 'astrologers', 'tacticians']


def stat_groups(stats):
    return [{'group': g, 'stats': [{'k': k.upper(), 'v': round(stats[k])} for k in ks if k in stats]} for g, ks in STAT_GROUPS]


def academy_grads(g):
    """Academy graduates: the game's graduateHistory (it trims this to the last 20-30) joined to wherever the hero is now."""
    where = {}
    for coll, label in HERO_COLLECTIONS:
        for a in g.get(coll) or []:
            where[a.get('id')] = (a, label)
    for a in g.get('freeAgentPool') or []:
        where.setdefault(a.get('id'), (a, 'Free agent'))
    for coll in STAFF_COLLECTIONS:
        for a in g.get(coll) or []:
            where.setdefault(a.get('id'), (a, 'On staff'))
    acad = g.get('academy') or {}

    def row(z, pending=False):
        hid = z.get('rosterId') or z.get('poolId') or z.get('id')
        a, w = where.get(hid) or where.get(z.get('id')) or (None, None)
        if a is None:
            w = 'Departed' if (z.get('rosterId') or z.get('poolId')) else None
        elif w == 'Active' and (a.get('injuryWeeks') or 0) > 0:
            w = 'Injured'
        stats = a.get('stats') if a else z.get('stats')
        bracket = z.get('gradPortraitAgeBracket')
        pk = portrait_key(a.get('portrait') if a else None, a.get('portraitFallback') if a else None)
        if not pk and z.get('gradPortraitNum') and z.get('gradGender') and bracket:
            pk = f"adventurer-{'female' if z['gradGender'] == 'F' else 'male'}-{bracket}/{z['gradPortraitNum']}"
        top = sorted(((k.upper(), round(v)) for k, v in (stats or {}).items()), key=lambda kv: -kv[1])[:3]
        sun = (a or {}).get('sunSign') or z.get('gradSunSign')
        return {
            'id': z.get('id') or hid, 'name': (a or {}).get('name') or z.get('name'),
            'class': z.get('className') or (a or {}).get('class'),
            'role': z.get('role'), 'potential': z.get('potential') or z.get('finalPotentialTier') or z.get('currentPotentialTier'),
            'outcome': z.get('outcome') if not pending else 'pending', 'year': z.get('year'),
            'source': z.get('sourceName'), 'fee': z.get('transferFee'),
            'gradOvr': z.get('gradOvr'), 'gradLevel': z.get('gradLevel'), 'gradAge': z.get('gradAge'),
            'sun': pretty(sun) if sun else None, 'status': w, 'portrait': pk, 'gender': z.get('gradGender') or (a or {}).get('gender'),
            # stats are frozen by the archive at first sight (a pending trainee's sheet IS the graduation sheet)
            'snap': stat_groups(stats) if stats else None, 'snapTop': [{'k': k, 'v': v} for k, v in top],
            'snapAt': 'graduation' if pending else 'first seen',
            'traits': trait_list(a) if a else [],
        }

    out = [row(z) for z in acad.get('graduateHistory') or []]
    have = {r['id'] for r in out}
    for t in acad.get('trainees') or []:       # finished but not yet signed/released
        if t.get('graduated') and not t.get('dismissed') and t.get('id') not in have:
            z = dict(t, className=(t.get('assignedClass') or {}).get('name'), potential=t.get('finalPotentialTier') or t.get('currentPotentialTier'),
                     year=None)
            out.append(row(z, pending=True))
    return {'grads': out, 'total': acad.get('totalGraduates') or len(out), 'reputation': acad.get('reputation'),
            'trainees': len([t for t in acad.get('trainees') or [] if not t.get('graduated') and not t.get('dismissed')])}


def commander_raw(g, heroes):
    """Raw commander evidence. Farewell letters are NOT used (they were a bug and may not be sent any more);
    a commander's end comes from the next appointment, retirement or death instead."""
    # letters name people, not ids. A retired adventurer can also be on the roster as staff (e.g. Quartermaster) under
    # the same name, so the adventurer record wins and the staff job is noted separately.
    rank = {'Fallen': 0, 'Retired': 1, 'Active': 2}
    heroes_by_name, staff_job = {}, {}
    for a, w in heroes.values():
        n = a.get('name')
        if a.get('type') not in (None, 'adventurer'):
            staff_job[n] = pretty(a.get('type'))
            continue
        if n not in heroes_by_name or rank.get(w, 9) < rank.get(heroes_by_name[n][1], 9):
            heroes_by_name[n] = (a, w)
    events, trust = [], []
    for c in g.get('commanderCorrespondence') or []:
        key, v, ts = c.get('letterKey') or '', c.get('vars') or {}, c.get('timestamp') or {}
        name = v.get('commanderName')
        if not name or ts.get('year') is None:
            continue
        if key.startswith('acceptance'):
            events.append({'name': name, 'year': ts['year'], 'week': ts.get('week'), 'src': 'letter'})
        elif key.startswith('trust.'):
            m = re.match(r'trust\.(up|down)_(\d+)', key)
            if m:
                trust.append({'name': name, 'dir': m.group(1), 'n': int(m.group(2)), 'year': ts['year'], 'week': ts.get('week')})
    for b in g.get('commanderBiography') or []:
        if b.get('type') == 'commander_appointed' and b.get('name'):
            events.append({'name': b['name'], 'year': b.get('year'), 'week': b.get('week'), 'src': 'biography'})
    cur_name = next((n for n, (a, _w) in heroes_by_name.items() if a.get('id') == g.get('guildCommanderId')), None)
    if cur_name and g.get('commanderAppointedYear') is not None:
        events.append({'name': cur_name, 'year': g['commanderAppointedYear'], 'week': g.get('commanderAppointedWeek'), 'src': 'current'})

    infos = {}
    for n, (a, w) in heroes_by_name.items():
        if not (a.get('weeksAsCommander') or n in {e['name'] for e in events}):
            continue
        done = a.get('completedAmbitions') or []
        infos[n] = {
            'id': a.get('id'), 'name': n, 'class': a.get('class'), 'emoji': a.get('emoji'), 'rarity': a.get('classRarity'),
            'portrait': portrait_key(a.get('portrait'), a.get('portraitFallback')), 'where': w,
            'diedOn': when(a.get('diedOn')) if w == 'Fallen' else None, 'cause': a.get('cause') if w == 'Fallen' else None,
            'weeksAsCommander': a.get('weeksAsCommander') or 0, 'questsAsCaptain': a.get('questsAsCaptain') or 0,
            'weeksAsCaptain': a.get('weeksAsCaptain') or 0, 'level': a.get('level'), 'ovr': a.get('ovr'),
            'retiredAt': when(a.get('retiredAt')) if w == 'Retired' else None, 'staffJob': staff_job.get(n),
            'ascended': any(c.get('tier') == 'ascension' for c in done),
            'titles': [pretty(t) for t in a.get('titles') or []],
        }
    advice = g.get('commanderAdviceRecord') or {}
    return {
        'events': events, 'trust': trust, 'heroes': infos,
        'current': {'name': cur_name, 'trust': g.get('commanderTrust'), 'approval': g.get('commanderApproval'),
                    'advice': {k: advice.get(k, 0) for k in ('followed', 'ignored', 'vindicated', 'missed')},
                    'mutinyStage': g.get('mutinyStage'), 'unrest': g.get('mutinyUnrest'),
                    'appointed': {'year': g.get('commanderAppointedYear'), 'week': g.get('commanderAppointedWeek')}},
    }


EPOCH_RE = re.compile(r'(?<!\d)1[6-9]\d{11}(?!\d)')
EPOCH_SOURCES = ('commanderCorrespondence', 'feedEntries', 'transactionHistory', 'crownCorrespondence', 'academyLog', 'renownLog')


def run_epochs(g):
    """Real-time creation stamps embedded in ids (letters, feed, transactions, legends). Two playthroughs can share a
    world seed and guild name, but never these, so overlap with a stored set means 'same run'."""
    out = set()
    for k in EPOCH_SOURCES:
        out.update(int(x) for x in EPOCH_RE.findall(json.dumps(g.get(k) or [])))
    out.update(int(x) for x in EPOCH_RE.findall(json.dumps((g.get('hallOfFame') or {}).get('legends') or [])))
    return sorted(out)


def legend_value(a, d):
    if 'field' in d:
        return a.get(d['field']) or 0
    if 'path' in d:
        return career(a, *d['path'])
    return 0


# ---------------------------------------------------------------- awards & cup
def award_row(x):
    return {
        'category': x.get('category'), 'label': x.get('label'), 'icon': x.get('icon'), 'desc': x.get('description'),
        'name': x.get('name'), 'class': x.get('class'), 'guild': x.get('guildName'), 'isPlayer': x.get('isPlayerGuild'),
        'value': x.get('value'), 'id': x.get('adventurerId'),
        'portrait': portrait_key(x.get('portrait'), x.get('portraitFallback')),
        'runnerUp': x.get('runnerUp'), 'third': x.get('thirdPlace'),
    }


def perf_row(p):
    if not p:
        return None
    return {
        'name': p.get('name'), 'class': p.get('class'), 'role': p.get('role'), 'ovr': p.get('ovr'),
        'guild': p.get('guildName'), 'portrait': portrait_key(p.get('portrait')),
        'damage': p.get('damageDealt'), 'healing': p.get('healingDone'), 'kos': p.get('knockouts'),
        'taken': p.get('damageTaken'), 'rounds': p.get('roundsSurvived'), 'slot': p.get('selectedRole'),
    }


def crown_cup(g, names, player_gid='player'):
    elo = {e['year']: e for e in g.get('cclEloChampions') or []}
    seasons = []
    for h in g.get('crownCupHistory') or []:
        y = h.get('year')
        results = [{'place': r.get('place'), 'guildId': r.get('guildId'), 'guild': r.get('guildName'),
                    'division': DIVISIONS.get(r.get('divisionId'), pretty(r.get('divisionId')))}
                   for r in h.get('cupResults') or []]
        champs = [{'division': DIVISIONS.get(k, pretty(k)), 'guild': v.get('guildName'),
                   'guildId': v.get('guildId'), 'renown': v.get('annualRenown')}
                  for k, v in (h.get('champions') or {}).items()]
        recs = {}
        for k, v in (h.get('records') or {}).items():
            recs[k] = {'name': v.get('name'), 'guild': v.get('guildName'), 'portrait': portrait_key(v.get('portrait')),
                       'value': v.get('knockouts') or v.get('value') or v.get('damageTaken') or v.get('rounds')}
        e = elo.get(y)
        seasons.append({
            'year': y,
            'cupWinner': (h.get('cupWinner') or {}).get('guildName'),
            'cupWinnerId': (h.get('cupWinner') or {}).get('guildId'),
            'results': results,
            'divisionChampions': champs,
            'eloChampion': e and {'guild': e.get('championName'), 'guildId': e.get('championGuildId'),
                                   'rating': e.get('championRating'), 'playerRank': e.get('playerRank'),
                                   'totalGuilds': e.get('totalGuilds'), 'playerHonor': e.get('playerHonor')},
            'mvp': perf_row(h.get('mvp')),
            'allTournament': [perf_row(p) for p in h.get('allTournamentTeam') or []],
            'records': recs,
            'playerQualified': any(r['guildId'] == player_gid for r in results),
            'bracketSize': h.get('bracketSize'),
            'skipped': bool(h.get('skipped')),
        })
    # years with an Elo champion but no cup record (older data) still show up
    have = {s['year'] for s in seasons}
    for y, e in elo.items():
        if y not in have:
            seasons.append({'year': y, 'cupWinner': None, 'results': [], 'divisionChampions': [],
                            'eloChampion': {'guild': e.get('championName'), 'guildId': e.get('championGuildId'),
                                            'rating': e.get('championRating'), 'playerRank': e.get('playerRank'),
                                            'totalGuilds': e.get('totalGuilds'), 'playerHonor': e.get('playerHonor')},
                            'allTournament': [], 'records': {}, 'playerQualified': False})
    seasons.sort(key=lambda s: s['year'])

    # live standings for the season in progress
    div = g.get('divisions') or {}
    renown = div.get('annualRenown') or {}
    live = []
    for a in div.get('assignments') or []:
        rows = sorted(({'guildId': gid, 'guild': names.get(gid, gid), 'renown': renown.get(gid, 0)} for gid in a.get('guildIds', [])),
                      key=lambda r: -r['renown'])
        live.append({'division': DIVISIONS.get(a.get('divisionId'), pretty(a.get('divisionId'))), 'rows': rows,
                     'hasPlayer': any(r['guildId'] == player_gid for r in rows)})
    ladder = g.get('cclLadderRatings') or {}
    top_elo = sorted(({'guildId': k, 'guild': names.get(k, k), **v} for k, v in ladder.items()), key=lambda r: -r.get('rating', 0))[:10]
    return {'seasons': seasons, 'live': {'year': div.get('year'), 'phase': div.get('currentPhase'), 'divisions': live, 'elo': top_elo}}


# ---------------------------------------------------------------- festival cup history
EVENT_KEYS = [('muster', 'Spring Festival'), ('duelists', 'Summer Festival'), ('melee', 'Autumn Festival'), ('crownCup', 'The Crown Cup')]
FINISH = {'champion': 'Champion', 'finalist': 'Finalist', 'semifinalist': 'Semifinalist', 'division_finalist': 'Division Finalist',
          'round_of_16': 'Out in the Round of 16', 'round_of_32': 'Out in the Round of 32', 'entered': 'Entered'}


def prize_gold(g, cache):
    """Festival prize gold only lives in the (500-entry) transaction log, so remember what we've seen."""
    names = {label: key for key, label in EVENT_KEYS}
    for t in g.get('transactionHistory') or []:
        if t.get('type') != 'season_event_prize':
            continue
        m = re.search(r'Season Event prize: (.+?) \(', t.get('description') or '')
        key = names.get(m.group(1)) if m else None
        yr = (t.get('timestamp') or {}).get('year')
        if key and yr is not None:
            cache[f'{yr}:{key}'] = t.get('amount')
    return cache


def cup_history(g, icons, cache):
    div = g.get('divisions') or {}
    cup_by_year = {h.get('year'): h for h in g.get('crownCupHistory') or []}
    events_by_year = {ps.get('year'): ps.get('events') or {} for ps in div.get('previousSeasons') or []}
    if div.get('year') is not None:
        events_by_year[div['year']] = div.get('events') or {}
    years = sorted(set(events_by_year) | set(cup_by_year) | ({div['year']} if div.get('year') else set()))
    out, titles, runner, third, apps = [], 0, 0, 0, 0
    for y in years:
        ev = events_by_year.get(y, {})
        row = {'year': y, 'current': y == div.get('year'), 'events': {}}
        for key, label in EVENT_KEYS:
            e = ev.get(key) or {}
            champ = e.get('champion') or {}
            if key == 'crownCup' and (cup_by_year.get(y) or {}).get('cupWinner'):
                cw = cup_by_year[y]['cupWinner']
                champ = {'guildId': cw.get('guildId'), 'name': cw.get('guildName')}
            pl = e.get('player')
            player = None
            if pl:
                rr, place = pl.get('roundReached'), pl.get('place')
                if place == 1 or rr == 'champion':
                    finish = 'champion'
                else:
                    finish = rr or 'entered'
                player = {'label': FINISH.get(finish, pretty(finish)), 'place': place, 'finish': finish,
                          'gold': cache.get(f'{y}:{key}'), 'key': f'{y}:{key}'}
                apps += 1
                titles += finish == 'champion'
                runner += finish == 'finalist' or place == 2
                third += place == 3
            row['events'][key] = {
                'label': label,
                'champion': champ.get('name'),
                'icon': icons.get(champ.get('guildId')),
                'player': player,
                'duelist': e.get('duelist') and {'name': e['duelist'].get('name'), 'wins': e['duelist'].get('wins'), 'losses': e['duelist'].get('losses')},
            }
        out.append(row)
    return {'years': out, 'events': [{'key': k, 'label': l} for k, l in EVENT_KEYS],
            'stats': {'titles': titles, 'runnerUp': runner, 'third': third, 'appearances': apps}}


# ---------------------------------------------------------------- main entry
def summarize(g, meta):
    names = {r['id']: r.get('name') for r in g.get('rivalGuilds') or []}
    names['player'] = g.get('guildName')
    icons = {r['id']: r.get('icon') for r in g.get('rivalGuilds') or []}
    icons['player'] = g.get('guildIcon')
    heroes = {}
    for coll, where in HERO_COLLECTIONS:
        for a in g.get(coll) or []:
            heroes[a.get('id')] = (a, where)

    prizes = prize_gold(g, {})
    hof = g.get('hallOfFame') or {}
    legends_raw = hof.get('legends') or []

    # --- legends grouped by hero
    by_hero = {}
    for l in legends_raw:
        hid = l.get('adventurerId')
        e = by_hero.setdefault(hid, {'id': hid, 'name': l.get('name'), 'class': l.get('class'),
                                     'portrait': portrait_key(l.get('portrait'), l.get('portraitFallback')),
                                     'gender': l.get('gender'), 'badges': []})
        e['badges'].append({'category': l.get('category'), 'label': l.get('label'), 'icon': l.get('icon'),
                            'reason': l.get('reason'), 'value': l.get('statValue'), 'at': when(l.get('inductedAt')),
                            'manual': bool(l.get('isManual'))})
    legends = []
    for hid, e in by_hero.items():
        a_w = heroes.get(hid)
        if a_w:
            e.update(brief(a_w[0], a_w[1]))
        else:
            e['where'] = 'Gone'
        e['badges'].sort(key=lambda b: ((b['at'] or {}).get('year', 0), (b['at'] or {}).get('week', 0)))
        legends.append(e)
    legends.sort(key=lambda e: (-len(e['badges']), e.get('name') or ''))
    counts = {}
    for l in legends_raw:
        counts[l.get('category')] = counts.get(l.get('category'), 0) + 1

    # --- closing in on a legend badge (living heroes only)
    inducted = {(l.get('adventurerId'), l.get('category')) for l in legends_raw}
    closing = []
    for cat, d in LEGEND_DEFS.items():
        if 'field' not in d and 'path' not in d:
            continue
        rows = []
        for hid, (a, where) in heroes.items():
            if where != 'Active' or (hid, cat) in inducted:
                continue
            v = legend_value(a, d)
            if v >= d['min'] * 0.5:
                rows.append({**brief(a, where), 'value': v, 'pct': min(100, round(100 * v / d['min']))})
        rows.sort(key=lambda r: -r['pct'])
        if rows:
            closing.append({'category': cat, 'label': d['label'], 'icon': d['icon'], 'desc': d['desc'], 'min': d['min'], 'rows': rows[:6]})

    # --- ascended heroes
    ascended, seen = [], set()
    legend_asc = {l.get('adventurerId'): l for l in legends_raw if l.get('category') == 'ascended'}
    for hid, (a, where) in heroes.items():
        done = a.get('completedAmbitions') or []
        if any(c.get('tier') == 'ascension' for c in done) or hid in legend_asc:
            ascended.append(ascended_detail(a, where))
            seen.add(hid)
    for hid, l in legend_asc.items():
        if hid not in seen:  # hero record no longer in the save - fall back to the legend entry
            ascended.append({'id': hid, 'name': l.get('name'), 'class': l.get('class'), 'where': 'Gone',
                             'portrait': portrait_key(l.get('portrait')), 'ascendedAt': when(l.get('inductedAt')),
                             'ascensionType': 'Unknown', 'traits': [], 'stats': [], 'drive': {}, 'stub': True})
    ascended.sort(key=lambda d: ((d.get('ascendedAt') or {}).get('year', 99), (d.get('ascendedAt') or {}).get('week', 99)))

    # --- yearly awards
    yearly = [{'year': y.get('year'), 'awards': sorted((award_row(x) for x in y.get('awards') or []),
                                                       key=lambda r: AWARD_ORDER.index(r['category']) if r['category'] in AWARD_ORDER else 99)}
              for y in hof.get('yearlyAwards') or []]
    realm = [{'year': y.get('year'), 'awards': sorted((award_row(x) for x in y.get('awards') or []),
                                                      key=lambda r: REALM_ORDER.index(r['category']) if r['category'] in REALM_ORDER else 99)}
             for y in hof.get('realmAwards') or []]

    def rec(d):
        return {k: {'name': v.get('name'), 'class': v.get('class'), 'guild': v.get('guildName'), 'isPlayer': v.get('isPlayer'),
                    'value': v.get('value'), 'since': when(v.get('since'))} for k, v in (d or {}).items()}

    return {
        'meta': meta,
        'guild': {'name': g.get('guildName'), 'tier': g.get('guildTier'), 'year': g.get('year'), 'week': g.get('week'),
                  'season': SEASONS[g['season']] if isinstance(g.get('season'), int) and 0 <= g['season'] < 4 else None,
                  'gold': g.get('gold'), 'renown': g.get('renown')},
        'legends': legends,
        'legendCounts': counts,
        'legendDefs': {k: {kk: vv for kk, vv in v.items() if kk in ('label', 'icon', 'desc')} for k, v in LEGEND_DEFS.items()},
        'closing': closing,
        'ascended': ascended,
        'yearly': yearly,
        'realm': realm,
        'records': rec(hof.get('records')),
        'realmRecords': rec(hof.get('realmRecords')),
        'cup': dict(crown_cup(g, names), history=cup_history(g, icons, prizes)),
        'memorial': sorted((memorial_entry(a) for a in g.get('memorial') or []),
                           key=lambda m: ((m.get('diedOn') or {}).get('year', 0), (m.get('diedOn') or {}).get('week', 0)), reverse=True),
        'deathCount': g.get('deathCount'),
        'bestiary': bestiary(g),
        'academy': academy_grads(g),
        '_epochs': run_epochs(g),
        '_cmd': commander_raw(g, heroes),
        'campaign': str((g.get('worldDeck') or {}).get('seed') or g.get('factionCharacterSeed') or g.get('guildName')),
        '_heroes': {hid: brief(a, w) for hid, (a, w) in heroes.items()},
        '_prizes': prizes,
    }


# ---------------------------------------------------------------- files
def _read_json(path, retries=3):
    last = None
    for _ in range(retries):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:  # game may be mid-write
            last = e
            time.sleep(0.4)
    raise last


_peek_cache = {}


def list_saves():
    out = []
    if not SAVE_DIR.exists():
        return out
    for p in sorted(SAVE_DIR.glob('*.json')):
        st = p.stat()
        key = (p.name, st.st_mtime_ns)
        info = _peek_cache.get(key)
        if info is None:
            try:
                gs = _read_json(p)['gameState']
                info = {'guild': gs.get('guildName'), 'year': gs.get('year'), 'week': gs.get('week'),
                        'legends': len((gs.get('hallOfFame') or {}).get('legends') or [])}
            except Exception:
                info = {'guild': None, 'year': None, 'week': None, 'legends': 0}
            _peek_cache[key] = info
        out.append({'file': p.name, 'mtime': st.st_mtime, **info})
    out.sort(key=lambda s: -s['mtime'])
    return out


def load(filename):
    p = SAVE_DIR / os.path.basename(filename)
    st = p.stat()
    raw = _read_json(p)
    meta = {'file': p.name, 'mtime': st.st_mtime, 'version': raw.get('version'), 'timestamp': raw.get('timestamp')}
    return summarize(raw['gameState'], meta)


def mtime(filename):
    try:
        return (SAVE_DIR / os.path.basename(filename)).stat().st_mtime
    except OSError:
        return None


if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) > 1 else 'save_4.json'
    data = load(name)
    print(json.dumps(data, indent=1, ensure_ascii=False)[:6000])
