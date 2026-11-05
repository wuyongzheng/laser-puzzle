"""Solver for Laser Puzzle levels: an answer-set program solved by clingo.

Usage:
  aspsolve.py <pack.json> <n> [seconds] [max-shapes]    solve, then look for other shapes
  aspsolve.py --selftest <pack.json>                    the stored solutions are models,
                                                        and the model's light = sim.py's
  aspsolve.py --bench <pack.json> <seconds> <out.json>  solve every level from scratch

Encoding. Light is tracked per square, direction and colour bit: E(c, d, b) means "colour bit b
leaves square c travelling in direction d". Every rule in RULES.md is local to one square and acts
on each colour bit separately, so each E is the OR of its "supports": an incoming E of the
neighbour plus the piece on the square that turns that input into this output. The per-piece
tables are produced by calling sim.py's own `process` on a lone piece, not written by hand.
Each square holds exactly one option: empty, or a toolbox piece in one of its distinct rotations.

The supports are given to clingo as rules ("E :- incoming E, piece"), everything else (one option
per square, toolbox counts, targets) as constraints. A plain SAT encoding (E <-> OR of supports)
also admits light that feeds itself round a loop with no laser behind it, and blocking those loops
one at a time after each solve was far too slow. Answer-set semantics only accepts light that a
chain of rules derives from a laser, and clingo checks that during the search.

Not local, and therefore handled differently:
  * teleporters: a support says "the first teleporter along d from here is that square";
  * entangled beams (quantum tangler + doppler): entangled light gets a layer of its own. When one
    twin crosses a doppler, the other changes colour at that moment. Neither the timing nor which
    beam is whose twin is modelled: entangled light may change colour anywhere along its path, on
    any pass (a beam can cross the same square several times), as long as some entangled light
    crosses a doppler the matching way. Every real solution is still a model; the extra models are
    thrown out by the exact check below. (Separate layers per twin and colour were tighter, but
    seven light layers made the search hopeless);
  * complementors and gates are encoded as a fixed point of their final inputs (a complementor may
    be switched off). The real drivers are iterative and can leave stale light behind, so on levels
    with these pieces a real solution may in rare cases be missed ("approximate" in the output).
    One such case: a level whose pieces end up in the dark because they steer the light that makes
    the complementor shut down: the encoding never places a piece in the dark;
Every solution clingo returns is replayed in fastsim (the exact simulator). A placement
that does not really win is blocked and the search continues.

Solutions are reported by shape: the multiset of (piece, rotation class). Two placements with the
same shape differ only by where the pieces stand, usually slides along a beam. "No other shape"
from a finished search is a proof, up to the approximations above, that the level has no
essentially different solution, including solutions with fewer pieces.
"""
import json
import os
import sys
import multiprocessing
import time

import clingo
from pysat.card import CardEnc, EncType

import sim
import solve

N = sim.N
DX, DY = sim.DX, sim.DY
NAMES = {v: k for k, v in sim.TYPE_IDS.items()}
TELEPORTERS = (12, 18)
COMPLEMENTOR = 15
GATES = (16, 22)
TANGLER, DOPPLER = 9, 7


class _Stub:
    """Stands in for sim.Tracer: records the beams `process` emits."""

    def __init__(self, board):
        self.b, self.next, self.entangle_counter = board, [], 100

    def emit(self, x, y, d, color, ent):
        self.next.append((d & 7, color, ent))


_TABLES = {}


def piece_table(typ, rot, color):
    """{(d, bit): [(d_out, bit_out, mode)]}, mode 'keep' / 'reset' (entanglement) or 'new'."""
    key = (typ, rot, color)
    if key in _TABLES:
        return _TABLES[key]
    rules = sim.Rules()
    table = {}
    for d in range(8):
        for bit in range(3):
            runs = []
            for ent in (0, 5):
                b = sim.Board()
                cell = b.at(7, 7)
                cell.type, cell.dir, cell.color = typ, rot, color
                t = _Stub(b)
                rules.process(t, 7, 7, d, 1 << bit, ent)
                runs.append(t.next)
            outs = []
            for (d0, c0, _), (d5, _, e5) in zip(*runs):
                assert d0 == d5 and c0 in (1, 2, 4), (typ, rot, d, bit, runs)
                mode = 'new' if e5 >= 100 else 'keep' if e5 == 5 else 'reset'
                outs.append((d0, c0.bit_length() - 1, mode))
            if outs:
                table[(d, bit)] = tuple(outs)
    _TABLES[key] = table
    return table


def behaviour_key(typ, rot, color):
    """Rotations with equal keys behave identically."""
    if typ in TELEPORTERS:
        return (typ,)
    if typ == COMPLEMENTOR:
        return (typ, rot & 1)
    if typ in GATES:
        return (typ, rot)
    return (typ, tuple(sorted(piece_table(typ, rot, color).items())))


def rotation_classes(typ, color):
    """{rotation: representative rotation}."""
    first = {}
    rep = {}
    for r in range(8):
        k = behaviour_key(typ, r, color)
        first.setdefault(k, r)
        rep[r] = first[k]
    return rep


def step(c, d):
    x, y = c % N + DX[d], c // N + DY[d]
    return y * N + x if 0 <= x < N and 0 <= y < N else None


def back(c, d):
    return step(c, (d + 4) & 7)


class Encoding:
    TRUE, FALSE = 1, -1

    def __init__(self, board, toolbox):
        self.nv = 1
        self.clauses = [[1]]
        self._and, self._or = {}, {}
        self.atoms, self.sup = {}, {}
        self.fixed = {p['y'] * N + p['x']: (sim.TYPE_IDS[p['type']], p['dir'], p['color']) for p in board}
        kinds = {}
        for p in toolbox:
            k = (sim.TYPE_IDS[p['type']], p['color'])
            kinds[k] = kinds.get(k, 0) + 1
        self.kinds = kinds
        types = {t for t, _ in kinds} | {t for t, _, _ in self.fixed.values()}
        self.members = TANGLER in types and DOPPLER in types
        self.approximate = bool(types & {COMPLEMENTOR, 22}) or (bool(types & {16}) and COMPLEMENTOR in types)
        self.build()

    # ---- basic CNF helpers -------------------------------------------------------------------
    def new(self):
        self.nv += 1
        return self.nv

    def and_(self, lits):
        if self.FALSE in lits:
            return self.FALSE
        lits = sorted(set(l for l in lits if l != self.TRUE))
        if not lits:
            return self.TRUE
        if len(lits) == 1:
            return lits[0]
        key = tuple(lits)
        if key not in self._and:
            v = self.new()
            for l in lits:
                self.clauses.append([-v, l])
            self.clauses.append([v] + [-l for l in lits])
            self._and[key] = v
        return self._and[key]

    def or_(self, lits):
        return -self.and_([-l for l in lits])

    def atom(self, key):
        v = self.atoms.get(key)
        if v is None:
            v = self.atoms[key] = self.new()
            self.sup[v] = []
        return v

    def support(self, head, body, cond):
        """Rule: head (atom key) is lit if every body atom (keys) is lit and every cond literal holds."""
        if any(k is None for k in body) or self.FALSE in cond:
            return
        bv = tuple(self.atom(k) for k in body)
        self.sup[self.atom(head)].append((bv, tuple(c for c in cond if c != self.TRUE)))

    # ---- light atoms ---------------------------------------------------------------------------
    def inc(self, layer, c, d, b):
        """Key of the atom for 'bit b arrives at c travelling d' in a layer, or None."""
        p = back(c, d)
        return None if p is None else ('E', layer, p, d, b)

    def inany(self, c, d, b):
        if not self.members:
            return self.inc('N', c, d, b)
        return None if back(c, d) is None else ('A', c, d, b)

    def lit_of(self, key):
        return self.FALSE if key is None else self.atom(key)

    # ---- the model -----------------------------------------------------------------------------
    def build(self):
        self.options = {}          # cell -> [(literal, type, rot, color, instance)]
        self.empty = {}
        classes = {}
        for (t, col), cnt in self.kinds.items():
            classes[(t, col)] = sorted(set(rotation_classes(t, col).values()))
        for c in range(N * N):
            if c in self.fixed:
                continue
            opts = []
            for (t, col), rots in classes.items():
                for r in rots:
                    opts.append((self.new(), t, r, col, None))
            self.options[c] = opts
            self.empty[c] = self.new()
            lits = [self.empty[c]] + [o[0] for o in opts]
            enc = CardEnc.equals(lits, 1, top_id=self.nv, encoding=EncType.seqcounter)
            self.nv = max(self.nv, enc.nv)
            self.clauses += enc.clauses
        # entangled light gets a layer of its own ('T') when a doppler can recolour a twin
        self.layers = ['N', 'T'] if self.members else ['N']

        # behaviours per cell: (condition literal, type, rot, color, instance)
        beh = {}
        for c in range(N * N):
            if c in self.fixed:
                t, r, col = self.fixed[c]
                beh[c] = [(self.TRUE, t, r, col, None)]
            else:
                beh[c] = [(self.empty[c], 0, 0, 0, None)] + self.options[c]
        self.beh = beh

        for c in range(N * N):
            trans = {}
            for lit, t, r, col, inst in beh[c]:
                if t == 2:                                    # laser: a source
                    for b in range(3):
                        if col >> b & 1:
                            self.support(('E', 'N', c, r, b), (), (self.TRUE,))
                    continue
                if t in TELEPORTERS or t == COMPLEMENTOR or t in GATES:
                    continue
                for (d, b), outs in piece_table(t, r, col).items():
                    for d2, b2, mode in outs:
                        m = None
                        if mode == 'new':
                            m = 0 if d2 == r else 1
                        trans.setdefault((d, b, d2, b2, mode, inst, m), []).append(lit)
            for (d, b, d2, b2, mode, inst, m), lits in trans.items():
                y = self.or_(lits)
                for layer in self.layers:
                    head = self.route(layer, mode, inst, c, d2, b2, m)
                    if head is not None:
                        self.support(head, (self.inc(layer, c, d, b),), (y,))
        self.build_teleporters()
        self.build_complementors_gates()
        if self.members:
            self.build_twin_shifts()
        if self.members:
            for c in range(N * N):
                for d in range(8):
                    for b in range(3):
                        k = self.inany(c, d, b)
                        if k is None:
                            continue
                        for layer in self.layers:
                            self.support(k, (self.inc(layer, c, d, b),), (self.TRUE,))
        # targets
        for c, (t, r, col) in self.fixed.items():
            if t != 10:
                continue
            for b in range(3):
                lits = [self.lit_of(self.inany(c, d, b)) for d in range(8)]
                if col >> b & 1:
                    self.clauses.append([l for l in lits if l != self.FALSE])
                else:
                    self.clauses += [[-l] for l in lits if l != self.FALSE]
        # a placed piece must have light arriving (a piece in the dark changes nothing), or for a
        # teleporter, light arriving or leaving: a teleporter that only receives jumps gets no light in
        leaving = {}
        for k, v in self.atoms.items():
            if k[0] in 'EP':
                leaving.setdefault(k[2], []).append(v)
        for c, e in self.empty.items():
            lits = [self.lit_of(self.inany(c, d, b)) for d in range(8) for b in range(3)]
            lits = [l for l in lits if l != self.FALSE]
            tele = self.tele_lit(c)
            self.clauses.append([e, tele] + lits)
            if tele != self.FALSE:
                self.clauses.append([-tele] + lits + leaving.get(c, []))
        # toolbox counts
        for (t, col), cnt in self.kinds.items():
            lits = [o[0] for c in self.options for o in self.options[c] if (o[1], o[3]) == (t, col)]
            out = self.counter(lits, cnt + 1)
            if len(out) > cnt:
                self.clauses.append([-out[cnt]])
        # shape counters, one per (type, colour, rotation class)
        self.class_lits = {}
        for c, opts in self.options.items():
            for lit, t, r, col, inst in opts:
                self.class_lits.setdefault((t, col, r), []).append(lit)
        self.counters = {k: self.counter(lits, self.kinds[(k[0], k[1])] + 1)
                         for k, lits in self.class_lits.items()}

    def route(self, layer, mode, inst, c, d, b, m):
        if mode == 'reset' or (layer == 'N' and mode == 'keep'):
            return ('E', 'N', c, d, b)
        if mode == 'keep':
            return ('P', layer, c, d, b)
        if not self.members:                                   # mode 'new'
            return ('E', 'N', c, d, b)
        return ('P', 'T', c, d, b)

    def emit_key(self, layer, c, d, b):
        return ('E', 'N', c, d, b) if layer == 'N' else ('P', layer, c, d, b)

    def tele_lit(self, c):
        if c in self.fixed:
            return self.TRUE if self.fixed[c][0] in TELEPORTERS else self.FALSE
        return self.or_([o[0] for o in self.options[c] if o[1] in TELEPORTERS])

    def build_teleporters(self):
        tl = [self.tele_lit(c) for c in range(N * N)]
        if all(l == self.FALSE for l in tl):
            return
        for c in range(N * N):
            if tl[c] == self.FALSE:
                continue
            for d in range(8):
                between = []
                t2 = step(c, d)
                while t2 is not None:
                    if tl[t2] != self.FALSE:
                        first = self.and_([tl[c], tl[t2]] + [-l for l in between])
                        for layer in self.layers:
                            for b in range(3):
                                self.support(self.emit_key(layer, t2, d, b), (self.inc(layer, c, d, b),), (first,))
                        if tl[t2] == self.TRUE:
                            break
                        between.append(tl[t2])
                    t2 = step(t2, d)

    def build_complementors_gates(self):
        for c in range(N * N):
            for lit, t, r, col, inst in self.beh[c]:
                if t == COMPLEMENTOR:
                    live = self.live(c)
                    for i in range(8):
                        if (i & 1) != (r & 1):
                            continue
                        for b in range(3):
                            dark = -self.lit_of(self.inany(c, i, b))
                            for b2 in range(3):
                                if b2 != b:
                                    self.support(('E', 'N', c, i, b), (self.inany(c, i, b2),), (lit, live, dark))
                elif t in GATES:
                    both = [self.and_([self.lit_of(self.inany(c, (r - 1) & 7, b)),
                                       self.lit_of(self.inany(c, (r + 1) & 7, b))]) for b in range(3)]
                    for b in range(3):
                        cond = [lit]
                        if t == 22:
                            cond += [-both[o] for o in range(3) if o != b]
                        self.support(('E', 'N', c, r, b),
                                     (self.inany(c, (r - 1) & 7, b), self.inany(c, (r + 1) & 7, b)), tuple(cond))

    def live(self, c):
        if not hasattr(self, '_live'):
            self._live = {}
        if c not in self._live:
            self._live[c] = self.new()
        return self._live[c]

    def build_twin_shifts(self):
        """Entangled layer: E = Pre, possibly shifted by a twin's doppler crossing (see module doc)."""
        dop = {}                                               # cell -> [(lit, rot)]
        for c in range(N * N):
            for lit, t, r, col, inst in self.beh[c]:
                if t == DOPPLER:
                    dop.setdefault(c, []).append((lit, r))
        cross = {}
        for layer in self.layers[1:]:
            for fwd in (True, False):
                lits = []
                for c, opts in dop.items():
                    for lit, r in opts:
                        d = (r + (2 if fwd else 6)) & 7
                        for b in range(3):
                            lits.append(self.and_([lit, self.lit_of(self.inc(layer, c, d, b))]))
                cross[(layer, fwd)] = [l for l in lits if l != self.FALSE]
        for layer in self.layers[1:]:
            twin = layer
            partner = {fwd: self.or_(cross[(twin, fwd)]) for fwd in (True, False)}
            for c in range(N * N):
                for d in range(8):
                    for b in range(3):
                        pre = ('P', layer, c, d, b)
                        if pre not in self.atoms:
                            continue
                        pv = self.atom(pre)
                        keep, sf, sr = self.new(), self.new(), self.new()
                        self.clauses.append([-pv, keep, sf, sr])
                        for v in (keep, sf, sr):
                            self.clauses.append([-v, pv])
                        self.clauses.append([-sf, partner[True]])
                        self.clauses.append([-sr, partner[False]])
                        self.support(('E', layer, c, d, b), (pre,), (keep,))
                        self.support(('E', layer, c, d, (b + 1) % 3), (pre,), (sf,))   # R->G->B->R
                        self.support(('E', layer, c, d, (b + 2) % 3), (pre,), (sr,))   # R->B->G->R

    def counter(self, lits, ub):
        """Unary counter: out[k] <-> at least k+1 of lits are true (k < ub)."""
        prev = []
        for x in lits:
            cur = []
            for k in range(min(len(prev) + 1, ub)):
                a = prev[k] if k < len(prev) else self.FALSE
                b = self.and_([prev[k - 1], x]) if k > 0 else x
                cur.append(self.or_([a, b]))
            prev = cur
        return prev

    # ---- reading a model ---------------------------------------------------------------------
    def placement(self, model):
        out = []
        for c, opts in self.options.items():
            for lit, t, r, col, inst in opts:
                if model[lit - 1] > 0:
                    out.append(dict(type=NAMES[t], x=c % N, y=c // N, dir=r, color=col))
        return out

    def chosen(self, model):
        return [o[0] for c, opts in self.options.items() for o in opts if model[o[0] - 1] > 0]

    def shape_of(self, pieces):
        sh = {}
        for p in pieces:
            t = sim.TYPE_IDS[p['type']]
            k = (t, p['color'], rotation_classes(t, p['color'])[p['dir']])
            sh[k] = sh.get(k, 0) + 1
        return sh

    def not_shape(self, shape):
        """Clause: the class counts differ from `shape` somewhere."""
        cl = []
        for k, out in self.counters.items():
            s = shape.get(k, 0)
            if s < len(out):
                cl.append(out[s])               # at least s+1
            if s > 0:
                cl.append(-out[s - 1])          # fewer than s
        return cl

    def field(self, model):
        """sim-style field string: for each square and direction, the hex colour arriving."""
        out = []
        for c in range(N * N):
            for d in range(8):
                v = 0
                for b in range(3):
                    k = self.inany(c, d, b)
                    if k is not None and k in self.atoms and model[self.atoms[k] - 1] > 0:
                        v |= 1 << b
                out.append(f'{v:x}')
        return ''.join(out)

    def field_assumptions(self, field):
        """Literals that fix the light arriving everywhere to a sim-style field, or None."""
        out = []
        for c in range(N * N):
            for d in range(8):
                v = int(field[c * 8 + d], 16)
                for b in range(3):
                    k = self.inany(c, d, b)
                    lit = self.atoms.get(k) if k is not None else None
                    if lit is None:
                        if v >> b & 1:
                            return None
                    else:
                        out.append(lit if v >> b & 1 else -lit)
        return out

    def option_lits(self, pieces):
        """The option literals that place `pieces` (tanglers take instances 0, 1, ... in order)."""
        out, used = [], {}
        for p in pieces:
            c = p['y'] * N + p['x']
            t = sim.TYPE_IDS[p['type']]
            r = rotation_classes(t, p['color'])[p['dir']]
            i = used.get((t, p['color']), 0)
            for lit, t2, r2, col, inst in self.options[c]:
                if (t2, r2, col) == (t, r, p['color']) and (inst is None or inst[2] == i):
                    out.append(lit)
                    used[(t, p['color'])] = i + 1
                    break
            else:
                raise KeyError(p)
        return out


class Search:
    """An incremental search over one level, in clingo."""

    def __init__(self, board, toolbox):
        t0 = time.time()
        self.board = board
        self.enc = enc = Encoding(board, toolbox)
        self.ctl = clingo.Control(['--models=1'] + os.environ.get('CLINGO_ARGS', '').split())
        with self.ctl.backend() as bk:
            self.amap = amap = [0] * (enc.nv + 1)
            for v in range(1, enc.nv + 1):
                amap[v] = bk.add_atom()
            bk.add_rule([amap[1]], [])                                  # TRUE
            for v in range(2, enc.nv + 1):
                if v not in enc.sup:                                     # free choice, constrained by clauses
                    bk.add_rule([amap[v]], [], choice=True)
            for v, sups in enc.sup.items():                              # light: only what a rule derives
                for body, cond in sups:
                    bk.add_rule([amap[v]], [amap[a] for a in body] + [self.lit(c) for c in cond])
            for cl in enc.clauses:
                bk.add_rule([], [-self.lit(l) for l in cl])
        self.ctl.ground([('base', [])])
        self.build_seconds = time.time() - t0
        self.stats = dict(spurious=0, calls=0)

    def lit(self, l):
        return self.amap[l] if l > 0 else -self.amap[-l]

    def add_clause(self, cl):
        with self.ctl.backend() as bk:
            bk.add_rule([], [-self.lit(l) for l in cl])

    def next_solution(self, assumptions=()):
        """Returns (pieces, model), or (None, None) when there is none. A model is a list indexed
        like a SAT model: model[v - 1] > 0 iff variable v is true."""
        while True:
            self.stats['calls'] += 1
            model = None
            with self.ctl.solve(assumptions=[self.lit(a) for a in assumptions], yield_=True) as h:
                for m in h:
                    model = [v if m.is_true(self.amap[v]) else -v for v in range(1, self.enc.nv + 1)]
                    break
            if model is None:
                return None, None
            pieces = self.enc.placement(model)
            if solve.check(self.board, pieces)[0]:
                return pieces, model
            self.stats['spurious'] += 1
            # block this placement, but not placements that add pieces to it
            sh = self.enc.shape_of(pieces)
            cl = [-l for l in self.enc.chosen(model)]
            cl += [out[sh.get(k, 0)] for k, out in self.enc.counters.items() if sh.get(k, 0) < len(out)]
            cl += [-a for a in assumptions]
            self.add_clause(cl)

    def shapes(self, exclude=()):
        """Yields solutions with distinct shapes until there are no more."""
        for sh in exclude:
            self.add_clause(self.enc.not_shape(sh))
        while True:
            pieces, _ = self.next_solution()
            if pieces is None:
                return
            yield pieces
            self.add_clause(self.enc.not_shape(self.enc.shape_of(pieces)))


def _worker(conn, board, toolbox, max_shapes, exclude_pieces):
    s = Search(board, toolbox)
    conn.send(('info', dict(vars=s.enc.nv, clauses=len(s.enc.clauses), build=round(s.build_seconds, 2),
                            approximate=s.enc.approximate)))
    excl = [s.enc.shape_of(exclude_pieces)] if exclude_pieces else []
    n = 0
    for pieces in s.shapes(excl):
        conn.send(('sol', pieces, round(time.time() - t0_child[0], 2)))
        n += 1
        if n >= max_shapes:
            conn.send(('stop', s.stats))
            return
    conn.send(('done', s.stats))


t0_child = [0.0]


def solve_level(board, toolbox, seconds=60, max_shapes=10, exclude_pieces=None):
    """Solutions with distinct shapes, found within `seconds` (the search runs in a child process,
    because CaDiCaL cannot be interrupted). With exclude_pieces, that solution's shape is skipped.
    Returns (solutions, complete, info); complete means the search proved there are no more
    shapes. info has the encoding size, the time each solution was found ('times') and stats."""
    ctx = multiprocessing.get_context('fork')
    parent, child = ctx.Pipe(duplex=False)
    t0_child[0] = time.time()
    proc = ctx.Process(target=_worker, args=(child, board, toolbox, max_shapes, exclude_pieces))
    proc.start()
    child.close()
    deadline = time.time() + seconds
    sols, info, complete = [], dict(times=[]), False
    try:
        while True:
            left = deadline - time.time()
            if left <= 0 or not parent.poll(left):
                break
            try:
                msg = parent.recv()
            except EOFError:
                info['error'] = 'worker died'
                break
            if msg[0] == 'info':
                info.update(msg[1])
            elif msg[0] == 'sol':
                sols.append(msg[1])
                info['times'].append(msg[2])
            else:
                info['stats'] = msg[1]
                complete = msg[0] == 'done'
                break
    finally:
        proc.kill()
        proc.join()
    info['seconds'] = round(time.time() - t0_child[0], 2)
    return sols, complete, info


def shape_key(pieces):
    return tuple(sorted((p['type'], p['color'], rotation_classes(sim.TYPE_IDS[p['type']], p['color'])[p['dir']])
                        for p in pieces))


def describe(pieces):
    return solve.describe(pieces)


def selftest(path):
    """Every stored solution must be a model, and the model's light must equal sim.py's."""
    bad = total = missed = 0
    for lv in json.load(open(path))['levels']:
        pieces = [dict(t, **s) for t, s in zip(lv['toolbox'], lv['solution'])]
        won, want = solve.check(lv['board'], pieces)
        if not won:
            continue
        total += 1
        s = Search(lv['board'], lv['toolbox'])
        # spare pieces left in the dark change nothing; the encoding leaves them off the board
        pieces = [p for p in pieces if p['type'] in ('teleporter', 'mobile_teleporter')
                  or want[(p['y'] * N + p['x']) * 8:(p['y'] * N + p['x']) * 8 + 8] != '0' * 8]
        chosen = set(s.enc.option_lits(pieces))
        assume = list(chosen) + [s.enc.empty[c] for c in s.enc.empty
                                 if not any(o[0] in chosen for o in s.enc.options[c])]
        got, model = s.next_solution(assume)
        kind = 'approximate' if s.enc.approximate else 'entangled' if s.enc.members else 'exact'
        tag = f"{lv.get('id', lv['number'])} ({kind})"
        if got is None:
            bad += not s.enc.approximate
            missed += s.enc.approximate
            print(f'{tag}: stored solution is NOT a model', flush=True)
        elif s.enc.field(model) != want:
            # the solver may pick another light pattern for the same pieces (where a twin
            # changes colour, which complementor is off); sim.py's must be one of them
            force = s.enc.field_assumptions(want)
            got2 = force is not None and s.next_solution(assume + force)[0] is not None
            if not got2 or not (s.enc.members or s.enc.approximate):
                bad += not s.enc.approximate
                missed += s.enc.approximate
                print(f'{tag}: sim.py light is NOT a model', flush=True)
    print(f'{total} stored solutions checked, {bad} failures, {missed} missed on approximate levels')
    return bad


def bench(path, seconds, out, workers=4):
    """Solve every level from scratch, `workers` at a time; results to `out` (JSON)."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = json.load(open(path))['levels']

    def work(lv):
        try:
            return work1(lv)
        except Exception as e:                       # keep going; report the level as failed
            print(f"L{lv['number']}: ERROR {e!r}", flush=True)
            return dict(number=lv['number'], error=repr(e))

    def work1(lv):
        stored = [dict(t, **s) for t, s in zip(lv['toolbox'], lv['solution'])]
        sols, complete, info = solve_level(lv['board'], lv['toolbox'], seconds, 20)
        keys = [shape_key(p) for p in sols]
        r = dict(number=lv['number'], title=lv['title'], pieces=len(lv['toolbox']),
                 first=info['times'][0] if sols else None, shapes=len(sols), complete=complete,
                 stored_found=shape_key(stored) in keys, min_used=min(map(len, sols), default=None),
                 approximate=info.get('approximate'), stats=info.get('stats'), vars=info.get('vars'),
                 solutions=sols)
        print(f"L{lv['number']:3} {len(lv['toolbox']):2} pieces: first "
              f"{r['first'] if sols else '-':>6}s, {len(sols)} shape(s){' (complete)' if complete else ''}"
              f"{'' if r['stored_found'] or not complete else '  STORED SHAPE MISSING'}", flush=True)
        return r

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(work, jobs))
    json.dump(res, open(out, 'w'), indent=1)


def main():
    if sys.argv[1] == '--bench':
        bench(sys.argv[2], float(sys.argv[3]), sys.argv[4])
        return
    if sys.argv[1] == '--selftest':
        sys.exit(1 if selftest(sys.argv[2]) else 0)
    data = json.load(open(sys.argv[1]))
    lv = data['levels'][int(sys.argv[2]) - 1]
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 60
    max_shapes = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    sols, complete, info = solve_level(lv['board'], lv['toolbox'], seconds, max_shapes)
    print(f"{len(sols)} shape(s), search {'complete' if complete else 'cut short'} after "
          f"{info['seconds']}s ({info})")
    for p, t in zip(sols, info['times']):
        print(f'  {t:7.2f}s  ' + describe(p))


if __name__ == '__main__':
    main()
