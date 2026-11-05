"""Find duplicate and look-alike levels across packs and sketches.

Every level is first normalized: of the 8 board symmetries x 6 colour permutations that keep
its pieces working (asked of the engine, not assumed: a twister has no mirror image, a prism
only with two colours swapped), plus a shift of the whole layout to the corner, it takes the
one whose text form is smallest. Equal normal forms are exact duplicates.

Look-alikes are scored three ways, each from 0 to 1:
  mech  the solved light as a graph (pieces and targets joined by beams, labelled by type,
        how many ways light enters and leaves, and colour class), compared by
        Weisfeiler-Lehman label counts: the same mechanism stretched or moved scores high;
  pic   the fixed board as a picture (walls, conduits, occupied squares, targets, lasers),
        matched cell by cell with one square of slack, best of the 8 symmetries;
  mix   the ingredients: toolbox pieces, lasers, targets by colour class, as a cosine.

Usage:
  dedup.py [--top N] [--sheet out.png] SOURCE...
        SOURCE is a pack .json file or a folder of .lvl sketches.
"""
import collections
import glob
import json
import math
import os
import sys

import sim
import studio

N = sim.N
TYPES = list(sim.TYPE_IDS)
# pieces whose turning can't be seen with one beam on one square: they keep their direction
BY_DIRECTION = {'laser', 'logic_gate', 'primary_logic_gate', 'complementor'}
NO_DIRECTION = {'wall', 'occupied', 'target', 'teleporter', 'mobile_teleporter'}
STRUCTURE = {'wall', 'occupied', 'conduit'}


# ---- symmetries ----

def geometry(k):
    """The k-th board symmetry (0-7): a function on squares and one on directions."""
    turns, flip = k % 4, k >= 4

    def square(x, y):
        if flip:
            x = N - 1 - x
        for _ in range(turns):
            x, y = N - 1 - y, x
        return x, y

    def direction(d):
        if flip:
            d = (8 - d) & 7
        return (d + 2 * turns) & 7
    return square, direction


PERMS = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]


def recolour(c, perm):
    return sum(1 << perm[i] for i in range(3) if c & (1 << i))


_tables = {}


def table(type_name, rot, color):
    """How the piece treats one beam: {(d_in, colour in): sorted [(d_out, colour out)]}."""
    key = (type_name, rot, color)
    if key not in _tables:
        rules = sim.Rules()
        out = {}
        for din in range(8):
            for c in range(1, 8):
                b = sim.Board()
                b.place(type_name, 7, 7, rot, color)
                t = sim.Tracer(b, rules)
                rules.process(t, 7, 7, din, c, 0)
                rules.after_generation(t)
                out[(din, c)] = sorted((e[2], e[3]) for e in t.next)
        _tables[key] = out
    return _tables[key]


_maps = {}


def piece_map(type_name, rot, color, k, perm):
    """The direction the piece needs after symmetry k and colour permutation perm to work as
    the transformed piece, the smallest if several do; None if no direction does."""
    key = (type_name, rot, color, k, perm)
    if key in _maps:
        return _maps[key]
    _, gd = geometry(k)
    if type_name in NO_DIRECTION:
        res = 0
    elif type_name in BY_DIRECTION:
        res = gd(rot)
    else:
        want = {(gd(d), recolour(c, perm)): sorted((gd(o), recolour(oc, perm)) for o, oc in outs)
                for (d, c), outs in table(type_name, rot, color).items()}
        nc = recolour(color, perm)
        res = next((r for r in range(8) if table(type_name, r, nc) == want), None)
    _maps[key] = res
    return res


def transform(level, k, perm):
    """The level under symmetry k and colour permutation perm, or None if a piece can't follow."""
    gs, _ = geometry(k)
    board, toolbox, solution = [], [], []
    for p in level['board']:
        r = piece_map(p['type'], p['dir'], p['color'], k, perm)
        if r is None:
            return None
        x, y = gs(p['x'], p['y'])
        board.append(dict(type=p['type'], x=x, y=y, dir=r, color=recolour(p['color'], perm)))
    for t, s in zip(level['toolbox'], level['solution']):
        r = piece_map(t['type'], s['dir'], t['color'], k, perm)
        if r is None:
            return None
        x, y = gs(s['x'], s['y'])
        toolbox.append(dict(type=t['type'], color=recolour(t['color'], perm)))
        solution.append(dict(x=x, y=y, dir=r))
    xs = [p['x'] for p in board] + [s['x'] for s in solution]
    ys = [p['y'] for p in board] + [s['y'] for s in solution]
    dx, dy = min(xs), min(ys)
    for p in board + solution:
        p['x'] -= dx
        p['y'] -= dy
    return dict(board=board, toolbox=toolbox, solution=solution)


def key_of(level):
    """Text form of the puzzle as the player sees it: the fixed board and the toolbox."""
    board = sorted((p['type'], p['x'], p['y'], p['dir'], p['color']) for p in level['board'])
    tools = sorted((t['type'], t['color']) for t in level['toolbox'])
    return repr((board, tools))


def normalize(level):
    """(normal form key, normalized level)."""
    best = None
    for k in range(8):
        for perm in PERMS:
            t = transform(level, k, perm)
            if t is not None:
                key = key_of(t)
                if best is None or key < best[0]:
                    best = (key, t)
    return best


# ---- look-alike measures ----

def colour_class(c):
    return 'k' if not c else 'w' if c == 7 else 'p' if c in (1, 2, 4) else 's'


def mech_labels(level, rounds=3):
    """Weisfeiler-Lehman label counts of the solved light's graph."""
    b = sim.solved_board(level)
    sim.trace(b, sim.Rules())
    names = {v: k for k, v in sim.TYPE_IDS.items()}
    nodes, edges = {}, collections.defaultdict(list)
    for y in range(N):
        for x in range(N):
            c = b.at(x, y)
            if c.type and any(c.inc) and names[c.type] not in ('wall', 'occupied'):
                ins = ''.join(sorted(colour_class(v) for v in c.inc if v))
                outs = ''.join(sorted(colour_class(v) for v in c.out if v))
                nodes[(x, y)] = f"{names[c.type]}:{ins}>{outs}"
    for (x, y) in list(nodes) + [(p['x'], p['y']) for p in level['board'] if p['type'] == 'laser']:
        c = b.at(x, y)
        nodes.setdefault((x, y), 'laser:' + colour_class(c.color))
        for d in range(8):
            if not c.out[d]:
                continue
            nx, ny = x + sim.DX[d], y + sim.DY[d]
            while 0 <= nx < N and 0 <= ny < N:
                if (nx, ny) in nodes or b.at(nx, ny).type:
                    if (nx, ny) in nodes:
                        edges[(x, y)].append(((nx, ny), colour_class(c.out[d])))
                    break
                nx, ny = nx + sim.DX[d], ny + sim.DY[d]
    labels = dict(nodes)
    counts = collections.Counter(labels.values())
    for _ in range(rounds):
        labels = {n: labels[n] + '(' + ','.join(sorted(col + labels[m] for m, col in edges[n])) + ')'
                  for n in labels}
        counts.update(hash(v) for v in labels.values())
    return counts


def weighted_jaccard(a, b):
    keys = set(a) | set(b)
    top = sum(min(a[k], b[k]) for k in keys)
    bottom = sum(max(a[k], b[k]) for k in keys)
    return top / bottom if bottom else 0.0


def picture(level):
    """{(x, y): kind} of the fixed board."""
    kinds = {}
    for p in level['board']:
        t = p['type']
        kinds[(p['x'], p['y'])] = ('#' if t in STRUCTURE else 'T' + colour_class(p['color']) if t == 'target'
                                   else 'L' if t == 'laser' else 'P')
    return kinds


def picture_variants(level):
    out = []
    for k in range(8):
        gs, _ = geometry(k)
        pic = {gs(x, y): v for (x, y), v in picture(level).items()}
        if pic:
            mx, my = min(x for x, _ in pic), min(y for _, y in pic)
            pic = {(x - mx, y - my): v for (x, y), v in pic.items()}
        out.append(pic)
    return out


def pic_score(a, b):
    """Share of cells in each picture matched in the other: walls and other structure on the
    same square, targets and lasers within one square (structure comes in blocks, where any
    slack would match almost anything)."""
    if not a or not b:
        return 0.0

    def cover(p, q):
        near = lambda x, y, v: (q.get((x, y)) == v if v == '#' else
                                any(q.get((x + i, y + j)) == v for i in (-1, 0, 1) for j in (-1, 0, 1)))
        return sum(near(x, y, v) for (x, y), v in p.items()) / len(p)
    return min(cover(a, b), cover(b, a))


def mix_vector(level):
    v = collections.Counter('tool:' + t['type'] for t in level['toolbox'])
    for p in level['board']:
        if p['type'] in ('laser', 'target'):
            v[p['type'] + ':' + colour_class(p['color'])] += 1
        elif p['type'] not in STRUCTURE:
            v['fixed:' + p['type']] += 1
    v['structure'] = math.sqrt(sum(p['type'] in STRUCTURE for p in level['board']))
    return v


def cosine(a, b):
    dot = sum(a[k] * b.get(k, 0) for k in a)
    na, nb = math.sqrt(sum(x * x for x in a.values())), math.sqrt(sum(x * x for x in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---- corpus ----

def load_sources(sources):
    """[(name, level)]"""
    out = []
    for src in sources:
        if os.path.isdir(src):
            for path in sorted(glob.glob(os.path.join(src, '**', '*.lvl'), recursive=True)):
                if '/dropped/' in path:
                    continue
                meta, pieces = studio.load(path)
                level = studio.to_level(meta, pieces)[0]
                out.append((os.path.relpath(path, src if len(sources) == 1 else os.path.dirname(src.rstrip('/'))),
                            level))
        else:
            data = json.load(open(src))
            tag = os.path.splitext(os.path.basename(src))[0]
            for i, level in enumerate(data['levels'], 1):
                out.append((f"{tag} L{i} {level.get('title') or ''}".strip(), level))
    return out


def main():
    args = sys.argv[1:]
    opt = lambda name, default=None: args[args.index(name) + 1] if name in args else default
    top, sheet = int(opt('--top', 40)), opt('--sheet')
    skip = {opt('--top'), opt('--sheet')}
    sources = [a for a in args if not a.startswith('--') and a not in skip]
    levels = load_sources(sources)

    items = []
    for name, level in levels:
        key, norm = normalize(level)
        title = level.get('title') or ''
        items.append(dict(name=name, level=level, key=key, title=title,
                          mech=mech_labels(level), pics=picture_variants(level),
                          mix=mix_vector(level)))

    groups = collections.defaultdict(list)
    for it in items:
        groups[it['key']].append(it['name'])
    exact = [g for g in groups.values() if len(g) > 1]
    print(f"{len(items)} levels; exact duplicates (same normal form): {len(exact)}")
    for g in exact:
        print('  = ' + ' | '.join(g))

    titles = collections.defaultdict(list)
    for it in items:
        if it['title']:
            titles[it['title'].lower()].append(it['name'])
    clashes = [v for v in titles.values() if len(v) > 1]
    print(f"title clashes: {len(clashes)}")
    for v in clashes:
        print('  ~ ' + ' | '.join(v))

    pairs = []
    for i in range(len(items)):
        a = items[i]
        for j in range(i + 1, len(items)):
            b = items[j]
            if a['key'] == b['key']:
                continue
            mech = weighted_jaccard(a['mech'], b['mech'])
            mix = cosine(a['mix'], b['mix'])
            if mech < 0.5 and mix < 0.9:
                pic = 0.0
            else:
                pic = max(pic_score(a['pics'][0], q) for q in b['pics'])
            score = max(mech, pic) * 0.7 + mix * 0.3
            pairs.append((score, mech, pic, mix, a, b))
    pairs.sort(key=lambda p: -p[0])
    print(f"\nlook-alikes, top {top} (score = 0.7 * max(mech, pic) + 0.3 * mix):")
    print(f"{'score':>5} {'mech':>5} {'pic':>5} {'mix':>5}  pair")
    for score, mech, pic, mix, a, b in pairs[:top]:
        print(f"{score:5.2f} {mech:5.2f} {pic:5.2f} {mix:5.2f}  {a['name']}  <->  {b['name']}")

    if sheet:
        draw_sheet([(a, b, f"{s:.2f} m{m:.2f} p{p:.2f} x{x:.2f}") for s, m, p, x, a, b in pairs[:top]], sheet)


def draw_sheet(pairs, out):
    """Each pair side by side, as the player first sees them."""
    import tempfile
    from PIL import Image, ImageDraw
    W, rows = 300, []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (a, b, label) in enumerate(pairs):
            row = Image.new('RGB', (2 * W + 10, W + 40), 'black')
            d = ImageDraw.Draw(row)
            for k, it in enumerate((a, b)):
                path = os.path.join(tmp, f"{i}-{k}.png")
                studio.draw(it['level'], path, puzzle=True)
                im = Image.open(path).convert('RGB')
                im.thumbnail((W, W))
                row.paste(im, (k * (W + 10), 20))
                d.text((k * (W + 10) + 4, 4), it['name'][:48], fill='white')
            d.text((4, W + 24), label, fill='yellow')
            rows.append(row)
    cols = 2
    sheet = Image.new('RGB', (cols * (2 * W + 30), ((len(rows) + cols - 1) // cols) * (W + 50)), 'black')
    for i, row in enumerate(rows):
        sheet.paste(row, ((i % cols) * (2 * W + 30), (i // cols) * (W + 50)))
    sheet.save(out)


if __name__ == '__main__':
    main()
