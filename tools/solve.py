"""Brute-force solver for Laser Puzzle levels, used to check that a level has no shortcut.

Usage:
  solve.py <pack.json> <level-number> [seconds] [max-solutions]
  solve.py --selftest <pack.json>      checks that fastsim.c agrees with sim.py

The search runs in fastsim.c (a C port of sim.py, built on first use). Pieces are only placed on
an empty square that a beam currently crosses (a piece nobody shines on changes nothing), one at
a time, depth-first, stopping at the first win on each branch. Rotations of a piece on one square
that give the same beam picture are tried once. That can in principle miss a solution in which
the rotation only matters to a beam that arrives later, so "1 solution, complete" means no other
solution was found, not a proof. Solutions that light the board the same way using the same
squares count once (e.g. a splitter at dir 1 or dir 5).
"""
import json
import os
import random
import subprocess
import sys

import sim

HERE = os.path.dirname(os.path.abspath(__file__))
BINARY = os.path.join(HERE, 'fastsim')
NAMES = {v: k for k, v in sim.TYPE_IDS.items()}


def build():
    src = os.path.join(HERE, 'fastsim.c')
    if not os.path.exists(BINARY) or os.path.getmtime(BINARY) < os.path.getmtime(src):
        subprocess.run(['gcc', '-O2', '-o', BINARY, src], check=True)


def _run(text):
    build()
    return subprocess.run([BINARY], input=text, capture_output=True, text=True, check=True).stdout


def _header(board):
    lines = []
    for p in board:
        lines.append(f"fixed {sim.TYPE_IDS[p['type']]} {p['x']} {p['y']} {p['dir']} {p['color']}")
    return lines


def check(board, placed=()):
    """placed: pieces dicts with type/x/y/dir/color. Returns (won, field string)."""
    lines = _header(board)
    for p in placed:
        lines.append(f"place {sim.TYPE_IDS[p['type']]} {p['x']} {p['y']} {p['dir']} {p['color']}")
    out = _run('\n'.join(lines + ['check']) + '\n').split('\n')
    return out[0] == 'won 1', out[1].split()[1]


def solve(board, toolbox, seconds=60, max_solutions=20):
    """Returns (solutions, complete); each solution is a list of piece dicts."""
    kinds = {}
    for p in toolbox:
        k = (sim.TYPE_IDS[p['type']], p['color'])
        kinds[k] = kinds.get(k, 0) + 1
    lines = _header(board) + [f'kind {t} {c} {n}' for (t, c), n in kinds.items()]
    out = _run('\n'.join(lines + [f'solve {seconds} {max_solutions}']) + '\n')
    sols, complete = [], False
    for line in out.splitlines():
        if line.startswith('sol '):
            pieces = []
            for part in line.split(':', 1)[1].split(';'):
                if part.strip():
                    t, x, y, d, c = map(int, part.split())
                    pieces.append(dict(type=NAMES[t], x=x, y=y, dir=d, color=c))
            sols.append(pieces)
        elif line.startswith('done'):
            complete = 'complete=1' in line
    return sols, complete


def describe(pieces):
    return ', '.join(f"{p['type']}({p['x']},{p['y']}) d{p['dir']}"
                     for p in sorted(pieces, key=lambda p: (p['y'], p['x'])))


def py_field(b):
    return ''.join(f'{v:x}' for row in b.cells for c in row for v in c.inc)


def selftest(path):
    rnd = random.Random(1)
    cases = bad = 0
    rules = sim.Rules()
    for lv in json.load(open(path))['levels']:
        placed = [dict(t, **s) for t, s in zip(lv['toolbox'], lv['solution'])]
        variants = [placed] + [[dict(p, dir=rnd.randrange(8)) if rnd.random() < .5 else p
                                for p in placed] for _ in range(4)]
        for v in variants:
            b = sim.Board()
            for p in lv['board'] + v:
                b.place(p['type'], p['x'], p['y'], p['dir'], p['color'])
            sim.trace(b, rules)
            won, field = check(lv['board'], v)
            cases += 1
            if won != rules.won(b) or field != py_field(b):
                bad += 1
                print(f"MISMATCH {lv.get('id', lv['number'])}")
    print(f'{cases} boards compared, {bad} mismatches')
    return bad


def main():
    if sys.argv[1] == '--selftest':
        sys.exit(1 if selftest(sys.argv[2]) else 0)
    data = json.load(open(sys.argv[1]))
    level = data['levels'][int(sys.argv[2]) - 1]
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 60
    max_solutions = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    sols, complete = solve(level['board'], level['toolbox'], seconds, max_solutions)
    print(f"{len(sols)} solution(s), search {'complete' if complete else 'cut short'}")
    for s in sols:
        print('  ' + describe(s))


if __name__ == '__main__':
    main()
