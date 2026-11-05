"""Level generator: builds candidate levels solution-first, then keeps only the tight ones.

Usage: generate.py <toolbox> <count> <out.json> [seed] [lasers] [laser colors]
  toolbox: comma-separated piece names, e.g. reflector,reflector,splitter,prism
  lasers: number of lasers (default 1); laser colors: e.g. "w" or "rb" (default random)

For each candidate:
  1. place lasers on the edge, pointing into the board;
  2. place the toolbox pieces one at a time on squares the beams cross (the stored solution);
  3. put targets on squares whose colour changes when any single piece is removed, so that
     every piece is needed, with the colour the solution delivers there;
  4. run the solvers (beamsolve.other_shapes) for solutions of another shape; wherever one lights a
     square the stored one leaves dark, add a black target there, and repeat a few times;
  5. keep the level if the search then finishes without finding another shape.
"""
import json
import random
import sys

import beamsolve
import solve

COLORS = 'krgybmcw'


def lit(pieces):
    """{(x, y): colour of all light crossing that square} for every lit square."""
    field = solve.check(pieces)[1]
    out = {}
    for c in range(225):
        v = 0
        for ch in field[c * 8:c * 8 + 8]:
            v |= int(ch, 16)
        if v:
            out[(c % 15, c // 15)] = v
    return out


def edge_laser(rnd, color):
    side = rnd.randrange(4)
    k = rnd.randrange(2, 13)
    x, y, d = [(k, 0, 4), (14, k, 6), (k, 14, 0), (0, k, 2)][side]
    return dict(type='laser', x=x, y=y, dir=d, color=color)


def candidate(rnd, toolbox, n_lasers, laser_colors):
    colors = laser_colors or ''.join(rnd.choice('rgbw') for _ in range(n_lasers))
    lasers = []
    for c in colors[:n_lasers]:
        for _ in range(20):
            l = edge_laser(rnd, COLORS.index(c))
            if all((l['x'], l['y']) != (o['x'], o['y']) for o in lasers):
                lasers.append(l)
                break
    sol = []
    for name in rnd.sample(toolbox, len(toolbox)):
        before = lit(lasers + sol)
        squares = [sq for sq in before if all(sq != (p['x'], p['y']) for p in lasers + sol)
                   and 1 <= sq[0] <= 13 and 1 <= sq[1] <= 13]
        rnd.shuffle(squares)
        placed = False
        for x, y in squares[:12]:
            for d in rnd.sample(range(8), 8):
                p = dict(type=name, x=x, y=y, dir=d, color=4)
                after = lit(lasers + sol + [p])
                # the piece must change the light on a few squares, not just swallow it
                changed = [sq for sq in after if after[sq] != before.get(sq)]
                if len(changed) >= 3:
                    sol.append(p)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            return None
    final = lit(lasers + sol)
    occupied = {(p['x'], p['y']) for p in lasers + sol}
    # squares whose light changes when one piece is taken away
    witnesses = []
    for i in range(len(sol)):
        without = lit(lasers + sol[:i] + sol[i + 1:])
        diff = [sq for sq in final if sq not in occupied and without.get(sq) != final[sq]]
        if not diff:
            return None
        witnesses.append(diff)
    targets = {}
    for diff in witnesses:
        sq = rnd.choice(diff)
        targets[sq] = final[sq]
    for _ in range(rnd.randrange(0, 3)):              # a few extra targets on the beams
        sq = rnd.choice([s for s in final if s not in occupied])
        targets[sq] = final[sq]
    board = lasers + [dict(type='target', x=x, y=y, dir=0, color=c) for (x, y), c in targets.items()]
    return board, sol


def tighten(board, sol, rounds=4, seconds=20):
    toolbox = [dict(type=p['type'], color=p['color']) for p in sol]
    for _ in range(rounds):
        if not solve.check(board, sol)[0] or solve.check(board)[0]:
            return None
        if any(solve.check(board, sol[:i] + sol[i + 1:])[0] for i in range(len(sol))):
            return None
        # a few alternatives are enough to choose the next black target; only the last round,
        # which finds none, has to be a finished search
        others, complete, info = beamsolve.other_shapes(board, toolbox, seconds, 5, sol)
        took = info['seconds']
        if not others:
            return (board, took) if complete else None
        keep_dark = set(lit(board + sol))
        used = {(p['x'], p['y']) for p in board + sol}
        score = {}
        for s in others:
            for sq in set(lit(board + s)) - keep_dark - used:
                score[sq] = score.get(sq, 0) + 1
        if not score:
            return None
        sq = max(score, key=score.get)
        board = board + [dict(type='target', x=sq[0], y=sq[1], dir=0, color=0)]
    return None


def main():
    toolbox = sys.argv[1].split(',')
    count = int(sys.argv[2])
    out = sys.argv[3]
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    n_lasers = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    laser_colors = sys.argv[6] if len(sys.argv) > 6 else None
    rnd = random.Random(seed)
    levels = []
    tries = 0
    while len(levels) < count and tries < count * 400:
        tries += 1
        c = candidate(rnd, toolbox, n_lasers, laser_colors)
        if not c:
            continue
        board, sol = c
        r = tighten(board, sol)
        if not r:
            continue
        board, took = r
        levels.append(dict(number=len(levels) + 1, title=None, text=None, board=board,
                           toolbox=[dict(type=p['type'], color=p['color']) for p in sol],
                           solution=[dict(x=p['x'], y=p['y'], dir=p['dir']) for p in sol],
                           solve_seconds=round(took, 2), seed=seed, attempt=tries))
        print(f'level {len(levels)} after {tries} candidates (solver {took:.2f}s)', flush=True)
        json.dump(dict(format='laser-puzzle/1', levels=levels),
                  open(out, 'w'), indent=1)          # after every level, so a timeout keeps them


if __name__ == '__main__':
    main()
