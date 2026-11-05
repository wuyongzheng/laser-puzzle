"""Level design helper: draw a level's beams and check it.

Usage:
  design.py show <pack.json> <n>        board with the stored solution placed, beams drawn
  design.py check <pack.json> [n ...]   the checks below, for every level (or the ones given)

Checks:
  * the stored solution wins and an empty toolbox does not;
  * every toolbox piece is needed: removing any one of them loses;
  * the solvers find no solution of a different shape (other pieces or other rotations,
    including solutions with fewer pieces). Same-shape solutions only move pieces, usually
    sliding them along a beam, and solutions that only turn a piece without changing any light
    count as the same too. beamsolve.other_shapes runs the beam solver (beamsolve.py) and
    then, if needed, the one in aspsolve.py. The check reports whether that search finished and
    which solver finished it: a finished search is a proof, except for the approximations listed
    in those files. If it did not finish, the brute-force search in solve.py gets the same time
    to look for shortcuts as well.

  design.py tighten <pack.json> <n>     squares where a black target or a wall would rule out
                                        other solutions without touching the stored one
"""
import json
import os
import sys

import aspsolve
import beamsolve
import sim
import solve

GLYPH = {'wall': '#', 'laser': 'L', 'reflector': 'R', 'bender': 'B', 'filter': 'F', 'prism': 'P',
         'doppler': 'D', 'splitter': 'S', 'tangler': 'Q', 'target': 'T', 'conduit': 'C',
         'teleporter': 'X', 'multi_filter': 'M', 'twister': 'W', 'complementor': 'K',
         'logic_gate': 'G', 'starburst': '*', 'mobile_teleporter': 'x', 'dual_reflector': 'r',
         'quad_bender': 'b', 'occupied': 'o', 'primary_logic_gate': 'g'}
COLOR = 'krgybmcw'


def placed(level):
    return [dict(t, **s) for t, s in zip(level['toolbox'], level['solution'])]


def render(pieces):
    """ASCII board. Pieces: glyph+dir+colour (targets also show what they receive, e.g. T0b=b
    is a blue target that is getting blue). Empty squares show the colour of light crossing."""
    b = sim.Board()
    for p in pieces:
        b.place(p['type'], p['x'], p['y'], p['dir'], p['color'])
    rules = sim.Rules()
    sim.trace(b, rules)
    at = {(p['x'], p['y']): p for p in pieces}
    rows = []
    for y in range(sim.N):
        row = []
        for x in range(sim.N):
            lit = 0
            for v in b.at(x, y).inc:
                lit |= v
            p = at.get((x, y))
            if p is None:
                row.append(f' {COLOR[lit]}  ' if lit else ' .  ')
            elif p['type'] == 'target':
                mark = '=' if lit == p['color'] else '!'
                row.append(f"T{COLOR[p['color']]}{mark}{COLOR[lit]}")
            else:
                row.append(f"{GLYPH[p['type']]}{p['dir']}{COLOR[p['color']]} ")
        rows.append(''.join(row))
    return '\n'.join(rows), rules.won(b)


def lit_squares(pieces):
    field = solve.check([p for p in pieces])[1]
    return {
        (c % sim.N, c // sim.N) for c in range(sim.N * sim.N) if field[c * 8:c * 8 + 8] != '0' * 8}


def tighten(level, seconds=120):
    board, sol = level['board'], placed(level)
    keep_dark = lit_squares(board + sol)
    used = {(p['x'], p['y']) for p in board + sol}
    others, complete, info = beamsolve.other_shapes(board, level['toolbox'], seconds, 200, sol)
    black, wall = {}, {}
    for s in others:
        for sq in lit_squares(board + s) - keep_dark - used:
            black[sq] = black.get(sq, 0) + 1
        for p in s:
            sq = (p['x'], p['y'])
            if sq not in used and sq not in keep_dark:
                wall[sq] = wall.get(sq, 0) + 1
    print(f'{len(others)} other solution(s) found ({"complete" if complete else "cut short"})')
    for name, d in (('black target', black), ('wall', wall)):
        best = sorted(d.items(), key=lambda kv: -kv[1])[:12]
        print(f'  {name} at: ' + ', '.join(f'({x},{y})x{n}' for (x, y), n in best))


def equivalent(level, other):
    """Can `other` be turned into the intended solution's shape by turning pieces in ways that
    change no light at all? Then it is the same solution to a player (pieces only slide along
    their beams, which shapes already allow, or turn where it makes no difference)."""
    board, sol = level['board'], placed(level)
    goal = aspsolve.shape_key(sol)
    def picture(s):
        b = sim.Board()
        for p in board + s:
            b.place(p['type'], p['x'], p['y'], p['dir'], p['color'])
        sim.trace(b, sim.Rules())
        return [(c.inc[:], c.out[:]) for row in b.cells for c in row]
    want = picture(other)
    seen, frontier = {aspsolve.shape_key(other)}, [other]
    while frontier:
        cur = frontier.pop()
        if aspsolve.shape_key(cur) == goal:
            return True
        for i, p in enumerate(cur):
            for d in range(8):
                if d == p['dir']:
                    continue
                nxt = cur[:i] + [dict(p, dir=d)] + cur[i + 1:]
                k = aspsolve.shape_key(nxt)
                if k not in seen and picture(nxt) == want:
                    seen.add(k)
                    frontier.append(nxt)
    return False


def check_level(level, seconds=120):
    board = level['board']
    sol = placed(level)
    issues = []
    if not solve.check(board, sol)[0]:
        issues.append('stored solution does not win')
    if solve.check(board)[0]:
        issues.append('wins with an empty toolbox')
    spare = [i for i in range(len(sol)) if solve.check(board, sol[:i] + sol[i + 1:])[0]]
    if spare:
        issues.append(f'pieces not needed: {[sol[i]["type"] for i in spare]}')
    others, complete, info = beamsolve.other_shapes(board, level['toolbox'], seconds, 50, sol)
    if not complete:
        # the brute-force search finds different things fast (it follows the light forward)
        mine = aspsolve.shape_key(sol)
        seen = {aspsolve.shape_key(s) for s in others}
        for s in solve.solve(board, level['toolbox'], seconds, 50)[0]:
            k = aspsolve.shape_key(s)
            if k != mine and k not in seen:
                seen.add(k)
                others.append(s)
    others = [s for s in others if not equivalent(level, s)]   # same light, a piece turned
    if level.get('accept') == 'idea' and complete and others and len(others) < 50:
        import studio                       # variants are fine if every one uses the trick
        if studio.all_use_trick(level, others, level.get('expect')):
            return issues, f'idea-unique: {len(others)} variant(s), all use the trick ({info["proved_by"]}, {info["seconds"]}s)'
    fewer = [s for s in others if len(s) < len(sol)]
    if others:
        issues.append(f'{len(others)} other solution(s), e.g. {solve.describe(others[0])}')
    if fewer:
        issues.append(f'solvable with {min(map(len, fewer))} of {len(sol)} pieces')
    status = f'search complete ({info["proved_by"]})' if complete else 'search cut short'
    if info.get('approximate'):
        status += ', approximate rules'
    return issues, f'{len(others)} other shape(s), {status} in {info["seconds"]}s'


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    data = json.load(open(path))
    picks = [int(n) for n in sys.argv[3:]]
    levels = [lv for lv in data['levels'] if not picks or lv['number'] in picks]
    if cmd == 'show':
        for lv in levels:
            text, won = render(lv['board'] + placed(lv))
            print(f"=== {lv['number']}: {lv.get('title')}  ({'WIN' if won else 'not solved'})")
            print('toolbox: ' + ', '.join(f"{p['type']}({COLOR[p['color']]})" for p in lv['toolbox']))
            print(text)
    elif cmd == 'tighten':
        for lv in levels:
            tighten(lv)
    elif cmd == 'check':
        bad = 0
        seconds = float(os.environ.get('SECONDS_PER_LEVEL', 120))
        for lv in levels:
            issues, summary = check_level(lv, seconds)
            bad += bool(issues)
            verdict = 'PROBLEM' if issues else 'UNVERIFIED' if 'cut short' in summary else 'OK'
            print(f"{lv['number']:2} {lv.get('title')}: {verdict} ({summary})")
            for i in issues:
                print('     - ' + i)
        sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
