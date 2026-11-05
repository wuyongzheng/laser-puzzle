"""Difficulty grader and design signals for Laser Puzzle levels.

Usage:
  grade.py <pack.json> <n>                       report for one level
  grade.py --bench <pack.json> <out.json> [secs] grade every level of a pack (4 at a time)

Difficulty comes from the beam solver (beamsolve.c, "grade" mode). It follows the stored solution
through the search, which at each step takes the open beam with the fewest options that survive
its deductions (wrong colour on a target, pieces still needed, where the last pieces can go):
  * a step with one surviving option is forced: a player who sees the same deduction just plays it;
  * otherwise every wrong option is searched until it is refuted (at most BUDGET nodes each), and
    the refutation's size and depth say how much trial and error, or how deep a look ahead, the
    step takes. A wrong option still open at the budget counts as BUDGET nodes.
Steps are in the solver's order, which is not a player's, so this describes how a level solves
rather than how hard it feels (for that, see playersim.py).

Design signals come from the light of the stored solution (sim.py):
  * merges: placed pieces that receive light from two or more directions (a splitter or prism
    combining beams: the "second use" of a piece);
  * reversals: pieces that send light straight back the way it came;
  * recolours: pieces whose output colours differ from what they receive;
  * shared: placed pieces whose removal changes the light of two or more targets (one beam
    serving several);
  * blockers: placed pieces whose light reaches no target (they only stop or absorb light);
  * depth: the most placed pieces on the way from a laser to one target (following beams square
    by square, so it can overcount where beams of different colours share a square, and it
    undercounts a beam that passes through the same piece twice, since a path visits a square once);
  * black targets, walls, and the mirror/rotation symmetry of the fixed board.
"""
import json
import math
import os
import subprocess
import sys

import beamsolve
import sim

HERE = os.path.dirname(os.path.abspath(__file__))
TELEPORTERS = {12, 18}


def run_grade(level, seconds=60, budget=5000):
    """The grade lines of beamsolve along the stored solution: list of dicts, complete flag."""
    beamsolve.build()
    lines = beamsolve._lines(level['board'], level['toolbox'])
    lines += [f"want {sim.TYPE_IDS[t['type']]} {q['x']} {q['y']} {q['dir']} {t['color']}"
              for t, q in zip(level['toolbox'], level['solution'])]
    lines += [f'grade {budget}', f'bsolve {seconds} 1']
    try:
        out = subprocess.run([beamsolve.BINARY], input='\n'.join(lines) + '\n', capture_output=True,
                             text=True, timeout=seconds + 30).stdout
    except subprocess.TimeoutExpired:
        return [], False, False
    steps = [{k: int(v) for k, v in (f.split('=') for f in l.split()[1:])}
             for l in out.splitlines() if l.startswith('grade ')]
    reached = 'sol 1:' in out
    mono = 'monotone=1' in out
    return steps, reached, mono


def difficulty(steps, reached, budget):
    """Summary of the grade lines."""
    choice = [s for s in steps if s['options'] > 1]
    work = sum(s['refute_nodes'] + s['open'] * budget for s in steps)
    return dict(
        steps=len(steps),
        forced=sum(s['options'] == 1 for s in steps),
        choices=len(choice),
        bits=round(sum(math.log2(s['options']) for s in steps), 1),   # guessing with no lookahead
        search=work,                                                    # trial and error to refute
        log_search=round(math.log10(1 + work), 2),
        deepest=max((s['refute_depth'] for s in steps), default=0),
        open=sum(s['open'] for s in steps),
        not_first=sum(s['rank'] > 0 for s in steps),        # the solver's favourite was wrong
        reached=reached,
    )


def _transparent(t):
    return t in (0, 10, 21)


def signals(level):
    b = sim.solved_board(level)
    sim.trace(b, sim.Rules())
    placed = {(s['x'], s['y']) for s in level['solution']}
    targets = [(p['x'], p['y']) for p in level['board'] if p['type'] == 'target']
    lasers = [(p['x'], p['y']) for p in level['board'] if p['type'] == 'laser']
    cell = lambda xy: b.at(*xy)
    N = sim.N

    def downstream(xy):
        """Cells light leaving xy runs into first (non-transparent), and targets it crosses."""
        hits, crossed = set(), set()
        c = cell(xy)
        for d in range(8):
            if not c.out[d]:
                continue
            x, y = xy
            while True:
                x, y = x + sim.DX[d], y + sim.DY[d]
                if not (0 <= x < N and 0 <= y < N):
                    break
                t = b.at(x, y).type
                if (x, y) in targets:
                    crossed.add((x, y))
                if _transparent(t):
                    continue
                hits.add((x, y))
                if t in TELEPORTERS:                     # light jumps to the next teleporter
                    tx, ty = x, y
                    while True:
                        tx, ty = tx + sim.DX[d], ty + sim.DY[d]
                        if not (0 <= tx < N and 0 <= ty < N):
                            break
                        if b.at(tx, ty).type in TELEPORTERS:
                            hits.add((tx, ty))
                            break
                break
        return hits, crossed

    edges, feeds = {}, {}
    nodes = set(lasers) | placed | {(x, y) for y in range(N) for x in range(N)
                                    if not _transparent(b.at(x, y).type) and any(b.at(x, y).out)}
    for xy in nodes:
        edges[xy], feeds[xy] = downstream(xy)

    def reach(xy):                     # targets reachable from xy, and pieces on the way
        seen, stack, tg = {xy}, [xy], set()
        while stack:
            u = stack.pop()
            tg |= feeds.get(u, set())
            for v in edges.get(u, ()):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        return tg, seen

    reaches = {xy: reach(xy)[0] for xy in placed}
    # depth: most placed pieces on a path from a laser to a target (longest simple path, small graphs)
    best = 0

    def dfs(u, onpath, count):
        nonlocal best
        if feeds.get(u):
            best = max(best, count)
        if len(onpath) > 40:
            return
        for v in edges.get(u, ()):
            if v not in onpath:
                onpath.add(v)
                dfs(v, onpath, count + (v in placed))
                onpath.discard(v)
    for l in lasers:
        dfs(l, {l}, 0)

    def inputs(c):
        return sum(1 for d in range(8) if c.inc[d])

    merges = sum(inputs(cell(xy)) >= 2 for xy in placed)
    reversals = sum(any(cell(xy).inc[d] and cell(xy).out[(d + 4) & 7] for d in range(8)) for xy in placed)
    recolours = 0
    for xy in placed:
        c = cell(xy)
        got = 0
        for d in range(8):
            got |= c.inc[d]
        outs = {c.out[d] for d in range(8) if c.out[d]}
        recolours += any(o != got for o in outs)
    # targets whose light changes when one placed piece is taken away
    def target_light(lv):
        bb = sim.solved_board(lv)
        sim.trace(bb, sim.Rules())
        out = []
        for t in targets:
            v = 0
            for k in bb.at(*t).inc:
                v |= k
            out.append(v)
        return out
    full = target_light(level)
    serves = []
    for i in range(len(level['solution'])):
        without = dict(level, toolbox=level['toolbox'][:i] + level['toolbox'][i + 1:],
                       solution=level['solution'][:i] + level['solution'][i + 1:])
        serves.append(sum(a != b for a, b in zip(full, target_light(without))))
    fixed = {(p['x'], p['y']): (p['type'], p['color']) for p in level['board']}
    walls = sum(p['type'] == 'wall' for p in level['board'])

    def sym(f):
        same = sum(fixed.get(f(x, y)) == v for (x, y), v in fixed.items())
        return same / max(1, len(fixed))
    symmetry = max(sym(lambda x, y: (N - 1 - x, y)), sym(lambda x, y: (x, N - 1 - y)),
                   sym(lambda x, y: (N - 1 - x, N - 1 - y)), sym(lambda x, y: (y, x)),
                   sym(lambda x, y: (N - 1 - y, N - 1 - x)))
    return dict(
        pieces=len(level['toolbox']),
        kinds=len({(t['type'], t['color']) for t in level['toolbox']}),
        targets=len(targets),
        black=sum(1 for p in level['board'] if p['type'] == 'target' and p['color'] == 0),
        lasers=len(lasers),
        walls=walls,
        symmetry=round(symmetry, 2),
        merges=merges,
        reversals=reversals,
        recolours=recolours,
        shared=sum(n >= 2 for n in serves),
        blockers=sum(not r for r in reaches.values()),
        depth=best,
    )


def grade_level(level, seconds=60, budget=5000):
    steps, reached, mono = run_grade(level, seconds, budget)
    r = dict(difficulty(steps, reached, budget), approximate=not mono)
    r.update(signals(level))
    return r, steps


def bench(path, out, seconds=60, budget=5000, workers=4):
    from concurrent.futures import ThreadPoolExecutor
    jobs = json.load(open(path))['levels']

    def work(lv):
        r, _ = grade_level(lv, seconds, budget)
        r.update(number=lv['number'], title=lv['title'])
        print(f"L{lv['number']:3} {r['pieces']:2} pieces: search {r['search']:>8} "
              f"forced {r['forced']}/{r['steps']}{'' if r['reached'] else ' (not reached)'}", flush=True)
        return r

    beamsolve.build()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(work, jobs))
    json.dump(res, open(out, 'w'), indent=1)


def main():
    if sys.argv[1] == '--bench':
        bench(sys.argv[2], sys.argv[3], *(float(a) for a in sys.argv[4:5]))
        return
    data = json.load(open(sys.argv[1]))
    r, steps = grade_level(data['levels'][int(sys.argv[2]) - 1])
    for s in steps:
        print(f"  {s['placed']:2} placed, {s['left']:2} left: {s['options']:3} option(s)"
              + (f", refuted in {s['refute_nodes']} nodes (depth {s['refute_depth']})"
                 + (f", {s['open']} not refuted" if s['open'] else '') if s['options'] > 1 else ', forced'))
    print(json.dumps(r))


if __name__ == '__main__':
    main()
