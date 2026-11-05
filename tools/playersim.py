"""How hard a level feels to a person: a model of a player (the search is in playersim.c).

Usage:
  playersim.py SKETCH.lvl ...               sketches: bits and tier
  playersim.py <pack.json> <n>              one level
  playersim.py --all <out.json> [budget]    every Laser Puzzle level

The player puts pieces where light already passes and ranks its moves by how good they look
(more targets lit right, fewer lit wrong, constrained targets first, unlit targets within one turn
of a beam). Two measures (docs/GRADER.md "The player model"):
  bits    following the stored solution in the player's preferred order: the sum over steps of
          log2(rank of the best right move), ties counted half. The measure to use.
  search  a depth-first search in the player's order with growing patience: log10 of the boards
          looked at before a win, cut at the budget. It saturates on most real levels.
Tiers by bits: easy < 6, medium 6-15, hard >= 15.
"""
import json
import math
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import sim

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
BINARY = os.path.join(HERE, 'playersim')
BUDGET = 2_000_000
_lock = threading.Lock()


def build():
    srcs = [os.path.join(HERE, f) for f in ('playersim.c', 'fastsim.c')]
    with _lock:
        if not os.path.exists(BINARY) or os.path.getmtime(BINARY) < max(map(os.path.getmtime, srcs)):
            tmp = f'{BINARY}.{os.getpid()}.tmp'
            subprocess.run(['gcc', '-O2', '-o', tmp, srcs[0], '-lm'], check=True, cwd=HERE)
            os.replace(tmp, BINARY)


def _lines(level, weights):
    lines = []
    lines += [f"fixed {sim.TYPE_IDS[p['type']]} {p['x']} {p['y']} {p['dir']} {p['color']}" for p in level['board']]
    kinds = {}
    for t in level['toolbox']:
        k = (sim.TYPE_IDS[t['type']], t['color'])
        kinds[k] = kinds.get(k, 0) + 1
    lines += [f'kind {t} {c} {n}' for (t, c), n in kinds.items()]
    if weights:
        lines.append('weights ' + ' '.join(map(str, weights)))
    return lines


def _run(lines, tag):
    out = subprocess.run([BINARY], input='\n'.join(lines) + '\n', capture_output=True, text=True).stdout
    line = next(l for l in out.splitlines() if l.startswith(tag + ' '))
    return {k: float(v) for k, v in (f.split('=') for f in line.split()[1:])}


def play(level, budget=BUDGET, weights=None):
    """The search: boards looked at before a win (difficulty = log10, budget + 0.5 if not found),
    and the solution-following ranks (bits)."""
    build()
    lines = _lines(level, weights)
    r = _run(lines + [f'play {budget}'], 'play')
    r['difficulty'] = round(math.log10(r['evals'] + 1), 2) if r['found'] else round(math.log10(budget) + 0.5, 2)
    want = [f"want {sim.TYPE_IDS[t['type']]} {s['x']} {s['y']} {s['dir']} {t['color']}"
            for t, s in zip(level['toolbox'], level['solution'])]
    r.update(_run(lines + want + ['follow'], 'follow'))
    return r


def tier(bits):
    return 'easy' if bits < 6 else 'medium' if bits < 15 else 'hard'


def designs():
    data = json.load(open(os.path.join(ROOT, 'designs', 'episodes.json')))
    return {lv['id']: lv for lv in data['levels']}


def run_many(items, budget, weights=None, workers=4):
    keys = list(items)
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda k: play(items[k], budget=budget, weights=weights), keys))
    return dict(zip(keys, res))


def main():
    a = sys.argv[1:]
    if a and a[0] == '--all':
        budget = int(a[2]) if len(a) > 2 else BUDGET
        res = run_many(designs(), budget)
        json.dump(res, open(a[1], 'w'), indent=0)
    elif a and a[0].endswith('.lvl'):
        import studio
        for path in a:
            level, problems = studio.to_level(*studio.load(path))
            r = play(level, budget=100_000)
            print(f"{path}: bits {r['bits']:.1f} ({tier(r['bits'])}), worst rank {r['maxrank']:.0f}, "
                  f"{int(r['notfirst'])} of {int(r['steps'])} steps not the best-looking move, {int(r['hidden'])} hidden")
    else:
        data = json.load(open(a[0]))
        print(play(data['levels'][int(a[1]) - 1]))


if __name__ == '__main__':
    main()
