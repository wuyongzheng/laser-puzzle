"""Beam-level solver for Laser Puzzle levels (the search itself is in beamsolve.c).

Usage:
  beamsolve.py <pack.json> <n> [seconds] [max-shapes]
  beamsolve.py --bench <pack.json> <seconds> <out.json>
  beamsolve.py --selftest <pack.json>

Instead of trying every piece on every lit square, the search takes one beam at a time and decides
what it meets first: a new piece on one of the free squares along it, or nothing new. Squares a
beam crosses are then closed to later pieces, so every placement is generated exactly once.
Teleporter jumps are decided the same way when the toolbox holds (mobile) teleporters. A new piece
keeps the set of rotations that treat the light it gets alike, and the set is split only when
light arrives that they treat differently.

Light is only traced through decided beams. Where the rules are monotone (no quantum tangler,
complementor or primary logic gate on the level), that light is part of the final light of every
way to finish the board, so a branch ends when
  - a target already gets a wrong colour,
  - the pieces left cannot bring every missing colour to its target (a BFS over light paths that
    may turn on any free square, counted in rounds so that it never overestimates), or
  - no choice of that many squares can hold the last piece on the way to every missing colour.
Before each branching step every option of every open beam is tried against these tests; the
beam with the fewest surviving options is branched on, options closest to finishing first.

Guarantees: every reported solution is replayed by the exact simulator. On a monotone level a
finished search has seen every placement in which every piece is lit, so "no other shape" is a
proof (pieces standing in the dark change nothing, unless they block a teleporter jump, which a
dark mobile teleporter cannot). On other levels the pruning is switched off and the result is
marked approximate: light that changes when more light arrives can make the decided beams wrong.
This is checked by a self-test that follows the stored solution of every level through the
search (it passes on every monotone level).

Extra settings for beamsolve.c can be passed in BEAMSOLVE_OPTS, ';'-separated (e.g. "rounds 0").
"""
import json
import os
import subprocess
import sys
import threading
import time

import sim
import solve

HERE = os.path.dirname(os.path.abspath(__file__))
BINARY = os.path.join(HERE, 'beamsolve')


_build_lock = threading.Lock()


def build():
    srcs = [os.path.join(HERE, f) for f in ('beamsolve.c', 'fastsim.c')]
    with _build_lock:
        if not os.path.exists(BINARY) or os.path.getmtime(BINARY) < max(map(os.path.getmtime, srcs)):
            tmp = f'{BINARY}.{os.getpid()}.tmp'
            subprocess.run(['gcc', '-O2', '-pthread', '-o', tmp, srcs[0]], check=True, cwd=HERE)
            os.replace(tmp, BINARY)


def _lines(board, toolbox):
    kinds = {}
    for p in toolbox:
        k = (sim.TYPE_IDS[p['type']], p['color'])
        kinds[k] = kinds.get(k, 0) + 1
    lines = solve._header(board) + [f'kind {t} {c} {n}' for (t, c), n in kinds.items()]
    return lines + [o.strip() for o in os.environ.get('BEAMSOLVE_OPTS', '').split(';') if o.strip()]


def solve_level(board, toolbox, seconds=60, max_shapes=10, exclude_pieces=None):
    """Returns (solutions, complete, info); one solution per shape, like aspsolve.solve_level.
    With exclude_pieces, that solution's shape is skipped."""
    import aspsolve
    build()
    skip = aspsolve.shape_key(exclude_pieces) if exclude_pieces else None
    text = '\n'.join(_lines(board, toolbox) + [f'bsolve {seconds} {max_shapes + (skip is not None)}']) + '\n'
    start = time.time()
    proc = subprocess.Popen([BINARY], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.stdin.write(text)
    proc.stdin.close()
    watchdog = threading.Timer(seconds + 10, proc.kill)      # the solver checks its clock between steps
    watchdog.start()
    sols, times, info = [], [], dict(complete=0, monotone=0)
    for line in proc.stdout:
        if line.startswith('sol '):
            pieces = []
            for part in line.split(':', 1)[1].split(';'):
                if part.strip():
                    t, x, y, d, c = map(int, part.split())
                    pieces.append(dict(type=solve.NAMES[t], x=x, y=y, dir=d, color=c))
            if skip is not None and aspsolve.shape_key(pieces) == skip:
                continue
            sols.append(pieces)
            times.append(round(time.time() - start, 2))
        elif line.startswith('done'):
            info = {k: int(v) for k, v in (f.split('=') for f in line.split()[1:])}
    proc.wait()
    watchdog.cancel()
    sols, times = sols[:max_shapes], times[:max_shapes]
    info['times'] = times
    info['seconds'] = round(time.time() - start, 2)
    info['approximate'] = not info.get('monotone')
    return sols, bool(info.get('complete')), info


def other_shapes(board, toolbox, seconds, max_shapes, exclude_pieces=None):
    """Both solvers in turn, one process at a time: the beam solver first (a finished search on a
    monotone level is a proof), then, if it was cut short or the level is not monotone, aspsolve
    for the remaining time. Returns (solutions, complete, info) with the shapes of both; info
    tells which solver finished ('proved_by')."""
    import aspsolve
    start = time.time()
    beam_share = seconds if seconds <= 10 else max(10, seconds / 3)
    sols, complete, info = solve_level(board, toolbox, beam_share, max_shapes, exclude_pieces)
    info = dict(beam=info, approximate=info['approximate'], proved_by='beam' if complete and not info['approximate'] else None)
    if info['proved_by'] or len(sols) >= max_shapes:
        info['seconds'] = round(time.time() - start, 2)
        return sols, bool(info['proved_by']), info
    rest = max(1, seconds - (time.time() - start))
    more, complete2, info2 = aspsolve.solve_level(board, toolbox, rest, max_shapes, exclude_pieces)
    seen = {aspsolve.shape_key(s) for s in sols}
    for s in more:
        if aspsolve.shape_key(s) not in seen and len(sols) < max_shapes:
            seen.add(aspsolve.shape_key(s))
            sols.append(s)
    info.update(asp=info2, approximate=info2.get('approximate', False),
                proved_by='asp' if complete2 else None, seconds=round(time.time() - start, 2))
    return sols, complete2, info


def selftest(path, workers=4):
    """Follow each stored solution's branch through the search: on a monotone level the search must
    reach it. Prints the misses; returns their number on monotone levels."""
    from concurrent.futures import ThreadPoolExecutor
    build()
    jobs = json.load(open(path))['levels']

    def run(lv):
        name = lv.get('id', lv['number'])
        lines = _lines(lv['board'], lv['toolbox'])
        lines += [f"want {sim.TYPE_IDS[t['type']]} {q['x']} {q['y']} {q['dir']} {t['color']}"
                  for t, q in zip(lv['toolbox'], lv['solution'])]
        try:
            res = subprocess.run([BINARY], input='\n'.join(lines + ['bsolve 20 1']) + '\n',
                                 capture_output=True, text=True, timeout=40)
        except subprocess.TimeoutExpired:
            return True, f'{name}: timeout'
        out = res.stdout
        if res.returncode:
            return True, f'{name}: exit code {res.returncode}'
        if 'sol 1' in out or 'DOES NOT WIN' in out:     # found, or no winning solution stored
            return None
        mono = 'monotone=1' in out
        why = [l for l in out.splitlines() if l.startswith('ptest:') and 'wins' not in l]
        return mono, f"{name} {'monotone' if mono else 'approximate'}: {why[0] if why else out.strip()}"

    with ThreadPoolExecutor(workers) as ex:
        misses = [r for r in ex.map(run, jobs) if r]
    for _, line in misses:
        print(line)
    bad = sum(m for m, _ in misses)
    print(f'{len(jobs)} levels: {bad} miss(es) on monotone levels, {len(misses) - bad} on approximate ones')
    return bad


def bench(path, seconds, out, workers=4):
    """Solve every level from scratch, `workers` at a time; results to `out` (JSON)."""
    import aspsolve
    from concurrent.futures import ThreadPoolExecutor
    jobs = json.load(open(path))['levels']

    def work(lv):
        stored = [dict(t, **s) for t, s in zip(lv['toolbox'], lv['solution'])]
        sols, complete, info = solve_level(lv['board'], lv['toolbox'], seconds, 20)
        keys = [aspsolve.shape_key(p) for p in sols]
        r = dict(number=lv['number'], title=lv['title'], pieces=len(lv['toolbox']),
                 first=info['times'][0] if sols else None, shapes=len(sols), complete=complete,
                 stored_found=aspsolve.shape_key(stored) in keys,
                 min_used=min(map(len, sols), default=None), info=info, solutions=sols)
        print(f"L{lv['number']:3} {len(lv['toolbox']):2} pieces: first "
              f"{r['first'] if sols else '-':>6}s, {len(sols)} shape(s)"
              f"{' (complete)' if complete else ''}{' approx' if info['approximate'] else ''}"
              f"{'' if r['stored_found'] or not complete or info['approximate'] else '  STORED SHAPE MISSING'}",
              flush=True)
        return r

    build()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(work, jobs))
    json.dump(res, open(out, 'w'), indent=1)


def main():
    if sys.argv[1] == '--selftest':
        sys.exit(1 if selftest(sys.argv[2]) else 0)
    if sys.argv[1] == '--bench':
        bench(sys.argv[2], float(sys.argv[3]), sys.argv[4])
        return
    data = json.load(open(sys.argv[1]))
    lv = data['levels'][int(sys.argv[2]) - 1]
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 60
    max_shapes = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    sols, complete, info = solve_level(lv['board'], lv['toolbox'], seconds, max_shapes)
    print(f"{len(sols)} shape(s), search {'complete' if complete else 'cut short'} after "
          f"{info['seconds']}s ({info})")
    for p, t in zip(sols, info['times']):
        print(f'  {t:7.2f}s  ' + solve.describe(p))


if __name__ == '__main__':
    main()
