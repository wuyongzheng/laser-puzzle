"""Design studio: turns a designer's sketch into a sound level and tells the designer how it came out.

This is the tool side of the AI design loop in docs/STUDIO.md. The designer (a person or an AI)
writes a sketch: the layout, the lasers, the intended solution, the trick it is meant to teach.
The studio then
  * fills in target colours left as '?' from the light of the intended solution;
  * checks that the solution wins, an empty toolbox loses and every piece is needed, and for an
    unneeded piece lists squares where a target would make it needed;
  * searches for solutions of another shape (beamsolve.other_shapes), sets aside the ones that
    only turn a piece without changing any light (the same picture to a player), and ranks the fixes that
    rule them out without touching the intended solution: a target on an intended beam in that
    beam's colour, a black target on a square only the other solutions light, or a wall where
    only they put a piece;
  * grades the level (grade.py), checks the sketch's "expect" lines against the design signals,
    and draws it (PNG, and ASCII on the terminal).

Usage:
  studio.py check <sketch.lvl> [--auto] [--seconds S] [--png out.png]
        report; --auto applies the best fixes until the level is unique (appended to the sketch,
        marked "% repair", so the designer can see, move or replace them)
  studio.py render <sketch.lvl|levels.json:n> <out.png> [--puzzle]
        the board with the solution and its light; --puzzle: as the player first sees it
  studio.py build <sketch-dir> <out.json> [name]
        a level pack from the sketches: in the episodes and order of <sketch-dir>/order.txt if
        there is one ("# episode title" lines, then one sketch name per line), else in file-name order
  studio.py coverage <sketch-dir>
        tricks, motifs and sizes covered so far, to choose what to design next
  studio.py turn TYPE DIN [DOUT] [--color C]
        which rotations of a piece send light travelling DIN (0=N, 1=NE, ... 7=NW) out in DOUT

Sketch format (.lvl): header lines "key: value", then "---", then one piece per line,
"[*]TYPE X Y DIR COLOR". '*' marks a toolbox piece: its position and direction are the intended
solution. TYPE is a glyph (# L T C X R B F P D S Q M W K) or a full type name; COLOR is one of
k r g y b m c w, or '?' for a target whose colour comes from the solution. '%' starts a comment.
Header keys: title, text, trick, motif, expect (e.g. "merges>=1, shared>=2"),
ink (budget of fixed elements per piece), accept ("idea": other solutions are allowed if every
one of them meets the expect lines), proof.
"""
import json
import os
import re
import sys

import beamsolve
import design
import grade
import sim
import solve

GLYPHS = {'#': 'wall', 'L': 'laser', 'R': 'reflector', 'B': 'bender', 'F': 'filter', 'P': 'prism',
          'D': 'doppler', 'S': 'splitter', 'Q': 'tangler', 'T': 'target', 'C': 'conduit',
          'X': 'teleporter', 'M': 'multi_filter', 'W': 'twister', 'K': 'complementor',
          'G': 'logic_gate', 'x': 'mobile_teleporter', 'r': 'dual_reflector', 'b': 'quad_bender',
          'o': 'occupied', 'g': 'primary_logic_gate', 'Z': 'starburst'}
COLORS = 'krgybmcw'
ORDER = list(sim.TYPE_IDS)


# ---- sketches ----

def parse(text):
    meta, pieces, body = {}, [], False
    for raw in text.splitlines():
        line = raw.split('%')[0].strip()
        if not line:
            continue
        if not body:
            if line == '---':
                body = True
            elif ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
            continue
        star = line.startswith('*')
        fields = line.lstrip('*').split()
        if len(fields) != 5:
            raise ValueError(f'expected "[*]TYPE X Y DIR COLOR", got {raw!r}')
        g, x, y, d, c = fields
        t = GLYPHS.get(g, g)
        if t not in sim.TYPE_IDS:
            raise ValueError(f'unknown piece {g!r} in {raw!r}')
        pieces.append(dict(type=t, x=int(x), y=int(y), dir=int(d), color=None if c == '?' else COLORS.index(c),
                           movable=star))
    return meta, pieces


def load(path):
    return parse(open(path).read())


def light(pieces):
    """Board after tracing: the sim.Board."""
    b = sim.Board()
    for p in pieces:
        b.place(p['type'], p['x'], p['y'], p['dir'], p['color'] or 0)
    sim.trace(b, sim.Rules())
    return b


def lit_colour(b, x, y):
    v = 0
    for c in b.at(x, y).inc:
        v |= c
    return v


def to_level(meta, pieces):
    """The level dict (pack format). Targets with colour '?' take the intended light's colour."""
    b = light([p for p in pieces if p['color'] is not None or p['type'] != 'target'])
    problems = []
    board, movable = [], []
    for p in pieces:
        q = dict(p)
        if q['color'] is None:
            q['color'] = lit_colour(b, q['x'], q['y'])
            if not q['color']:
                problems.append(f"target ({q['x']},{q['y']}) marked '?' gets no light; it would be black")
        q.pop('movable')
        (movable if p['movable'] else board).append(q)
    movable.sort(key=lambda p: (ORDER.index(p['type']), p['color']))
    level = dict(title=meta.get('title'), text=meta.get('text'), board=board,
                 toolbox=[dict(type=p['type'], color=p['color']) for p in movable],
                 solution=[dict(x=p['x'], y=p['y'], dir=p['dir']) for p in movable])
    return level, problems


# ---- repair ----

def lit_map(pieces):
    b = light(pieces)
    return {(x, y): v for y in range(sim.N) for x in range(sim.N) if (v := lit_colour(b, x, y))}


def witnesses(level):
    """For each unneeded piece: squares where a target in the intended colour would make it needed."""
    board, sol = level['board'], design.placed(level)
    final = lit_map(board + sol)
    occupied = {(p['x'], p['y']) for p in board + sol}
    out = {}
    for i, p in enumerate(sol):
        if not solve.check(board, sol[:i] + sol[i + 1:])[0]:
            continue
        without = lit_map(board + sol[:i] + sol[i + 1:])
        out[i] = [(sq, final[sq]) for sq in final if sq not in occupied and without.get(sq) != final[sq]]
    return out


def fixes(level, others):
    """Changes that keep the intended solution and rule out some of `others`, best first:
    (kind, (x, y), colour, indices of the other solutions it rules out)."""
    board, sol = level['board'], design.placed(level)
    mine = lit_map(board + sol)
    used = {(p['x'], p['y']) for p in board + sol}
    theirs = [lit_map(board + s) for s in others]
    cands = {}
    for i, (s, lm) in enumerate(zip(others, theirs)):
        for sq, c in mine.items():                     # a target on an intended beam, in its colour
            if sq not in used and lm.get(sq, 0) != c:
                cands.setdefault(('target', sq, c), set()).add(i)
        for sq in lm:                                   # a black target where only they shine
            if sq not in used and sq not in mine:
                cands.setdefault(('black', sq, 0), set()).add(i)
        for p in s:                                     # a wall where only they put a piece
            sq = (p['x'], p['y'])
            if sq not in used and sq not in mine:
                cands.setdefault(('wall', sq, 0), set()).add(i)
    style = {'target': 0, 'black': 1, 'wall': 2}
    return sorted(((k, sq, c, sorted(i)) for (k, sq, c), i in cands.items()),
                  key=lambda f: (-len(f[3]), style[f[0]], abs(f[1][0] - 7) + abs(f[1][1] - 7)))


def fix_line(f):
    kind, (x, y), c, _ = f
    return {'target': f'T {x} {y} 0 {COLORS[c]}', 'black': f'T {x} {y} 0 k', 'wall': f'# {x} {y} 0 k'}[kind]


def apply_fix(level, f):
    kind, (x, y), c, _ = f
    t = 'wall' if kind == 'wall' else 'target'
    level['board'].append(dict(type=t, x=x, y=y, dir=0, color=c))


# ---- report ----

def expectations(expect, signals):
    """'merges>=1, shared>=2' -> list of (text, ok)."""
    out = []
    for part in filter(None, (p.strip() for p in (expect or '').split(','))):
        m = re.fullmatch(r'(\w+)\s*(>=|<=|==|>|<)\s*(\d+)', part)
        if not m or m.group(1) not in signals:
            out.append((part, None))
            continue
        v, op, n = signals[m.group(1)], m.group(2), int(m.group(3))
        ok = {'>=': v >= n, '<=': v <= n, '==': v == n, '>': v > n, '<': v < n}[op]
        out.append((f'{part} (is {v})', ok))
    return out


def ink(level):
    """Fixed walls, conduits, occupied squares and targets per toolbox piece: how much the board
    has to say for each piece."""
    fixed = sum(p['type'] in ('wall', 'conduit', 'occupied', 'target') for p in level['board'])
    return fixed / max(1, len(level['toolbox']))


def all_use_trick(level, others, expect):
    """'accept: idea': the level may have other solutions if the search enumerated all of them and
    each one meets the sketch's expect lines, i.e. uses the trick too: several solutions are fine,
    but never one that dodges the idea."""
    if not expect:
        print('  accept: idea needs expect lines naming the trick')
        return False
    ok = True
    for s in others:
        alt = dict(level, toolbox=[dict(type=p['type'], color=p['color']) for p in s],
                   solution=[dict(x=p['x'], y=p['y'], dir=p['dir']) for p in s])
        sig = grade.signals(alt)
        bad = [t for t, good in expectations(expect, sig) if not good]
        print(f"    {'uses the trick' if not bad else 'DODGES the trick (' + '; '.join(bad) + ')'}: {solve.describe(s)}")
        ok = ok and not bad
    return ok


def check(path, auto=False, seconds=60, png=None, rounds=6):
    meta, pieces = load(path)
    idea = meta.get('accept') == 'idea'
    level, problems = to_level(meta, pieces)
    sol = design.placed(level)
    added = []
    print(f"== {meta.get('title') or os.path.basename(path)} ({len(sol)} pieces)")
    for p in problems:
        print('  PROBLEM:', p)
    budget = float(meta['ink']) if meta.get('ink') else None
    print(f"  ink: {ink(level):.1f} fixed elements per piece" + (f' (budget {budget})' if budget else ''))
    if budget and ink(level) > budget:
        print('  PROBLEM: over the ink budget')
    if not solve.check(level['board'], sol)[0]:
        print('  PROBLEM: the intended solution does not win')
        print(design.render(level['board'] + sol)[0])
        return False
    if solve.check(level['board'])[0]:
        print('  PROBLEM: the level is won with an empty toolbox')
    spare = witnesses(level)
    for i, sqs in spare.items():
        p = sol[i]
        print(f"  PROBLEM: {p['type']} at ({p['x']},{p['y']}) is not needed. A target on one of these "
              f"squares would make it needed: " + ', '.join(f'({x},{y}) {COLORS[c]}' for (x, y), c in sqs[:8]))
        if auto and sqs:
            (x, y), c = min(sqs, key=lambda s: abs(s[0][0] - p['x']) + abs(s[0][1] - p['y']))
            f = ('target', (x, y), c, [])
            apply_fix(level, f)
            added.append(fix_line(f))
    proved = False
    for r in range(rounds if auto else 1):
        others, complete, info = beamsolve.other_shapes(level['board'], level['toolbox'], seconds, 30, sol)
        same = [s for s in others if design.equivalent(level, s)]
        others = [s for s in others if not design.equivalent(level, s)]
        if same:
            print(f'  {len(same)} solution(s) only turn a piece without changing any light (fine), e.g. {solve.describe(same[0])}')
        proved = complete and not others and not info.get('approximate')
        if idea and complete and others and len(others) < 30 and not info.get('approximate'):
            proved = all_use_trick(level, others, meta.get('expect'))
        how = f"proved by the {info.get('proved_by')} solver" if complete else 'search cut short'
        found = f"{len(others)}{'+' if len(others) >= 30 else ''}" if complete or others else 'none found yet'
        print(f"  other solutions: {found} ({how}, {info['seconds']}s)")
        if not others or proved:
            break
        for s in others[:3]:
            print('    e.g.', solve.describe(s))
        fl = fixes(level, others)
        if not auto:
            print('  fixes that keep the intended solution (rules out how many of these):')
            for f in fl[:10]:
                print(f'    {fix_line(f):18} {len(f[3])}')
            break
        # greedy: best fixes until every listed alternative is ruled out
        left = set(range(len(others)))
        while left and fl:
            f = max(fl, key=lambda f: len(left & set(f[3])))
            if not left & set(f[3]):
                break
            apply_fix(level, f)
            added.append(fix_line(f))
            left -= set(f[3])
            fl = fixes(level, [others[i] for i in sorted(left)])
            fl = [(k, sq, c, [sorted(left)[j] for j in idx]) for k, sq, c, idx in fl]
    if added:
        with open(path, 'a') as fh:
            fh.write(''.join(f'{l}  % repair\n' for l in added))
        print('  added to the sketch: ' + '; '.join(added))
    r, steps = grade.grade_level(level, 30)
    print(f"  grade: {r['forced']} of {r['steps']} steps forced, refuting the rest took {r['search']} nodes "
          f"(deepest {r['deepest']}){'' if r['reached'] else ', grading cut short'}")
    sig = {k: r[k] for k in ('merges', 'reversals', 'recolours', 'shared', 'blockers', 'depth',
                             'targets', 'black', 'walls', 'symmetry')}
    print('  signals:', ', '.join(f'{k} {v}' for k, v in sig.items()))
    for text, ok in expectations(meta.get('expect'), r):
        print(f"  expect {text}: {'ok' if ok else 'NOT MET' if ok is not None else 'unknown signal'}")
    print(design.render(level['board'] + sol)[0])
    if png:
        draw(level, png)
        print('  picture:', png)
    if budget and ink(level) > budget:
        print(f'  ink after repairs: {ink(level):.1f}, over the budget of {budget}')
        proved = False
    variants = len(others) if proved else 0
    print(f"  verdict: {('IDEA-UNIQUE (proved; ' + str(variants) + ' variant(s), all use the trick)') if variants else 'UNIQUE (proved)' if proved else 'NOT PROVED UNIQUE'}")
    return proved


# ---- pictures ----

def rgb(c):
    return tuple(255 if c >> b & 1 else 40 for b in range(3)) if c else (20, 20, 20)


def draw(level, out, puzzle=False, cell=40):
    from PIL import Image, ImageDraw
    pieces = level['board'] + ([] if puzzle else design.placed(level))
    b = light(pieces)
    m = cell // 2
    W = sim.N * cell + 2 * m
    toolbox_h = cell + m if puzzle else 0
    img = Image.new('RGB', (W, W + toolbox_h), (28, 28, 34))
    d = ImageDraw.Draw(img)
    centre = lambda x, y: (m + x * cell + cell // 2, m + y * cell + cell // 2)
    for y in range(sim.N):
        for x in range(sim.N):
            x0, y0 = m + x * cell, m + y * cell
            d.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], outline=(45, 45, 55))
    for p in pieces:                            # occupied: light passes, nothing can be placed
        if p['type'] == 'occupied':
            x0, y0 = m + p['x'] * cell, m + p['y'] * cell
            d.rectangle([x0 + 2, y0 + 2, x0 + cell - 3, y0 + cell - 3], fill=(48, 48, 58))
    for y in range(sim.N):                      # beams; light both ways along a step in its mix
        for x in range(sim.N):
            for k in range(8):
                nx, ny = x + sim.DX[k], y + sim.DY[k]
                back = b.at(nx, ny).out[(k + 4) & 7] if 0 <= nx < sim.N and 0 <= ny < sim.N else 0
                if k >= 4 and back:
                    continue
                c = b.at(x, y).out[k] | back
                if c:
                    cx, cy = centre(x, y)
                    d.line([cx, cy, cx + sim.DX[k] * cell, cy + sim.DY[k] * cell], fill=rgb(c), width=3)
    movable = {(s['x'], s['y']) for s in ([] if puzzle else level['solution'])}
    for p in pieces:
        x, y = p['x'], p['y']
        x0, y0 = m + x * cell, m + y * cell
        cx, cy = centre(x, y)
        t, col = p['type'], rgb(p['color'])
        if t == 'wall':
            d.rectangle([x0 + 1, y0 + 1, x0 + cell - 2, y0 + cell - 2], fill=(95, 95, 105))
            continue
        if t == 'target':
            got = lit_colour(b, x, y)
            r = cell // 2 - 5
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col if p['color'] else (150, 150, 150), width=4)
            if got == p['color']:
                d.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2], fill=col if p['color'] else (150, 150, 150))
            continue
        if t == 'occupied':
            continue
        if t == 'conduit':
            d.rectangle([x0 + 4, y0 + 4, x0 + cell - 5, y0 + cell - 5], outline=(140, 140, 150), width=2)
            k, r = p['dir'], cell // 2 - 6              # the one axis light may travel along
            d.line([cx - sim.DX[k] * r, cy - sim.DY[k] * r, cx + sim.DX[k] * r, cy + sim.DY[k] * r],
                   fill=(140, 140, 150), width=2)
            continue
        box = [x0 + 5, y0 + 5, x0 + cell - 6, y0 + cell - 6]
        d.rounded_rectangle(box, 6, fill=(60, 60, 70), outline=(230, 190, 60) if (x, y) in movable else col, width=2)
        k = p['dir']
        tick = col if t in ('laser', 'filter', 'multi_filter') else (200, 200, 200)
        d.line([cx, cy, cx + sim.DX[k] * (cell // 2 - 6), cy + sim.DY[k] * (cell // 2 - 6)], fill=tick, width=3)
        glyph = next((g for g, n in GLYPHS.items() if n == t), t[0])
        d.text((x0 + 8, y0 + 7), glyph, fill=(240, 240, 240))
    if puzzle:
        x = m
        for t in level['toolbox']:
            glyph = next((g for g, n in GLYPHS.items() if n == t['type']), t['type'][0])
            d.rounded_rectangle([x, W, x + cell - 8, W + cell - 8], 6, fill=(60, 60, 70), outline=(230, 190, 60), width=2)
            d.text((x + 12, W + 10), glyph, fill=(240, 240, 240))
            x += cell
    img.save(out)


# ---- packs and coverage ----

def sketches(folder):
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith('.lvl'))


def read_order(folder):
    """[(episode title, [sketch path, ...])] from folder/order.txt: '# title' starts an episode, then
    one sketch name (without .lvl) per line. Every sketch in the folder must be listed exactly once."""
    episodes, listed = [], []
    for raw in open(os.path.join(folder, 'order.txt')):
        line = raw.split('%')[0].strip()
        if line.startswith('#'):
            episodes.append((line[1:].strip(), []))
        elif line:
            if not episodes:
                raise SystemExit(f'{folder}/order.txt: {line!r} comes before the first "# episode" line')
            episodes[-1][1].append(os.path.join(folder, line + '.lvl'))
            listed.append(line + '.lvl')
    have = {os.path.basename(p) for p in sketches(folder)}
    twice = sorted({f for f in listed if listed.count(f) > 1})
    missing, unknown = sorted(have - set(listed)), sorted(set(listed) - have)
    if twice or missing or unknown:
        raise SystemExit(f'{folder}/order.txt: listed twice {twice}, not listed {missing}, no such sketch {unknown}')
    return episodes


def build(folder, out, name=None):
    """The pack: episodes from order.txt if the folder has one, else one episode in file-name order."""
    if os.path.exists(os.path.join(folder, 'order.txt')):
        episodes = read_order(folder)
    else:
        episodes = [('', sketches(folder))]
    levels = []
    for episode, path in [(k, p) for k, (_, paths) in enumerate(episodes, 1) for p in paths]:
        meta, pieces = load(path)
        level, problems = to_level(meta, pieces)
        if problems:
            raise SystemExit(f'{path}: {problems}')
        level = dict(number=len(levels) + 1, id=os.path.basename(path)[:-4], **level, episode=episode,
                     origin=f'studio: {os.path.basename(path)}',
                     trick=meta.get('trick'), motif=meta.get('motif'))
        if meta.get('accept'):                   # 'idea': variants allowed, all using the trick
            level['accept'] = meta['accept']
            level['expect'] = meta.get('expect')
        if meta.get('proof'):                    # e.g. a uniqueness claim the solvers can't prove
            level['proof'] = meta['proof']
        levels.append(level)
    data = dict(format='laser-puzzle/1', name=name or os.path.basename(folder),
                board=dict(width=15, height=15), directions=['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'],
                colors=['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'],
                episodes=[title for title, _ in episodes], levels=levels)
    json.dump(data, open(out, 'w'), indent=1)
    print(f'{out}: {len(levels)} levels')


def coverage(folder):
    rows = []
    for path in sketches(folder):
        meta, pieces = load(path)
        n = sum(p['movable'] for p in pieces)
        kinds = sorted({p['type'] for p in pieces if p['movable']})
        rows.append((os.path.basename(path), meta.get('trick', '-'), meta.get('motif', '-'), n, kinds))
    print(f"{'sketch':24} {'trick':22} {'motif':14} pieces  toolbox")
    for r in rows:
        print(f'{r[0]:24} {r[1]:22} {r[2]:14} {r[3]:6}  {", ".join(r[4])}')
    for i, label in ((1, 'tricks'), (2, 'motifs')):
        seen = {}
        for r in rows:
            seen[r[i]] = seen.get(r[i], 0) + 1
        print(f'{label}: ' + ', '.join(f'{k} x{v}' for k, v in sorted(seen.items())))
    sizes = {}
    for r in rows:
        b = '1-3' if r[3] <= 3 else '4-5' if r[3] <= 5 else '6-8' if r[3] <= 8 else '9+'
        sizes[b] = sizes.get(b, 0) + 1
    print('sizes: ' + ', '.join(f'{k} pieces x{v}' for k, v in sorted(sizes.items())))


DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']


def turns(type_name, color=7):
    """{(rotation, d_in): [(d_out, colour out), ...]} for one piece with white (or `color`) light."""
    table = {}
    for rot in range(8):
        for din in range(8):
            b = sim.Board()
            b.place(type_name, 7, 7, rot, 7 if type_name in ('filter', 'doppler') else 0)
            x, y = 7 - sim.DX[din], 7 - sim.DY[din]
            b.place('laser', x, y, din, color)
            sim.trace(b, sim.Rules())
            table[(rot, din)] = [(k, b.at(7, 7).out[k]) for k in range(8) if b.at(7, 7).out[k]]
    return table


def main():
    args = sys.argv[1:]
    opt = lambda name, default=None: args[args.index(name) + 1] if name in args else default
    cmd = args[0]
    if cmd == 'check':
        ok = check(args[1], auto='--auto' in args, seconds=float(opt('--seconds', 60)), png=opt('--png'))
        sys.exit(0 if ok else 1)
    if cmd == 'render':
        src, out = args[1], args[2]
        if src.endswith('.lvl'):
            meta, pieces = load(src)
            level = to_level(meta, pieces)[0]
        else:
            path, n = src.rsplit(':', 1)
            data = json.load(open(path))
            level = data['levels'][int(n) - 1]
        draw(level, out, puzzle='--puzzle' in args)
        return
    if cmd == 'turn':
        t = GLYPHS.get(args[1], args[1])
        din = int(args[2])
        want = int(args[3]) if len(args) > 3 and args[3].isdigit() else None
        shown = 0
        col = opt('--color', '7')
        col = int(col) if col.isdigit() else COLORS.index(col)    # a bitmask or a letter: r, g, ...
        for rot in range(8):
            outs = turns(t, col)[(rot, din)]
            if want is None or any(k == want for k, _ in outs):
                shown += 1
                print(f'{t} rotation {rot}: light travelling {DIRS[din]} leaves '
                      + (', '.join(f'{DIRS[k]} ({COLORS[c]})' for k, c in outs) or 'nowhere (absorbed)'))
        if not shown:
            print(f'no rotation of {t} sends light travelling {DIRS[din]} out {DIRS[want]}')
        return
    if cmd == 'build':
        build(args[1], args[2], args[3] if len(args) > 3 else None)
        return
    if cmd == 'coverage':
        coverage(args[1])
        return
    raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
