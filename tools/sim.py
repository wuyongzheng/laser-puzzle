"""Reference beam simulator for Laser Puzzle. docs/RULES.md describes the same rules in words.

Usage: sim.py <pack.json>   -- plays every stored solution and reports the result.

Conventions: grid 15x15, dir 0=N clockwise in 45-degree steps, colours are an RGB bitmask
(R=1, G=2, B=4). `rel = (beam_dir - piece_dir) & 7` is the direction of travel of the incoming
beam relative to the piece.
"""
import json
import sys

N = 15
DX = [0, 1, 1, 1, 0, -1, -1, -1]
DY = [-1, -1, 0, 1, 1, 1, 0, -1]
DOPPLER_FWD = [0, 2, 4, 0, 1]   # R->G->B->R
DOPPLER_REV = [0, 4, 1, 0, 2]   # R->B->G->R
QUEUE_MAX = 32                  # emit silently drops beams beyond this
GENERATIONS = 0x400             # a trace runs at most 1023 generations
COMPLEMENT = [0, 6, 5, 4, 3, 2, 1, 0]   # white (7) emits nothing

TYPE_IDS = {
    'wall': 1, 'laser': 2, 'reflector': 3, 'bender': 4, 'filter': 5, 'prism': 6,
    'doppler': 7, 'splitter': 8, 'tangler': 9, 'target': 10, 'conduit': 11,
    'teleporter': 12, 'multi_filter': 13, 'twister': 14, 'complementor': 15,
    'logic_gate': 16, 'starburst': 17, 'mobile_teleporter': 18, 'dual_reflector': 19,
    'quad_bender': 20, 'occupied': 21, 'primary_logic_gate': 22,
}


class Cell:
    __slots__ = ('type', 'color', 'dir', 'off', 'inc', 'out', 'snap')

    def __init__(self):
        self.type = self.color = self.dir = 0
        self.off = 0         # complementor shut down
        self.inc = [0] * 8   # colour arriving, by direction of travel
        self.out = [0] * 8   # colour leaving, by direction
        self.snap = [0] * 8  # copy of inc taken by the complementor loop


class Board:
    def __init__(self):
        self.cells = [[Cell() for _ in range(N)] for _ in range(N)]

    def at(self, x, y):
        return self.cells[y][x]

    def place(self, type_name, x, y, d, color):
        c = self.at(x, y)
        c.type, c.dir, c.color = TYPE_IDS[type_name], d, color


class Tracer:
    """One source's trace: a double-buffered queue of (x, y, dir, color, entangle_id)."""

    def __init__(self, board, rules):
        self.b, self.rules = board, rules
        self.next = []
        self.entangle_counter = 1

    def emit(self, x, y, d, color, ent):
        if len(self.next) != QUEUE_MAX:
            self.next.append([x, y, d & 7, color, ent])

    def run(self, x, y, d, color):
        self.emit(x, y, d, color, 0)
        left = GENERATIONS
        while self.next:
            left -= 1
            if left == 0:
                break
            cur, self.next = self.next, []
            for bx, by, bd, bc, be in cur:
                self.b.at(bx, by).out[bd] |= bc
                bx, by = (bx + DX[bd]) & 0xff, (by + DY[bd]) & 0xff   # byte arithmetic
                if bx < N and by < N:
                    self.rules.process(self, bx, by, bd, bc, be)
            self.rules.after_generation(self)


class Rules:
    def process(self, t, x, y, d, color, ent):
        cell = t.b.at(x, y)
        rot = cell.dir
        cell.inc[d] |= color
        rel = (d - rot) & 7
        k = cell.type
        emit = t.emit
        if k in (0, 10, 21):                         # empty, target, occupied: light passes
            emit(x, y, d, color, ent)
        elif k == 3:                                 # reflector
            if rel in (1, 2, 3):
                emit(x, y, rot - rel, color, ent)
        elif k == 4:                                 # bender
            if rel in (0, 1, 2, 3):
                emit(x, y, rot - rel - 1, color, ent)
        elif k == 5:                                 # filter
            if rel in (2, 6) and cell.color & color:
                emit(x, y, d, cell.color & color, ent)
        elif k == 6:                                 # prism: each primary bends differently
            if color & 4:
                o = {1: 1, 2: 2, 5: -3, 6: -2}.get(rel)
                if o is not None:
                    emit(x, y, rot + o, 4, ent)
            if color & 2:
                o = {0: 1, 2: 3, 5: -4, 7: -2}.get(rel)
                if o is not None:
                    emit(x, y, rot + o, 2, ent)
            if color & 1:
                o = {0: -2, 2: -4, 5: 3, 7: 1}.get(rel)
                if o is not None:
                    emit(x, y, rot + o, 1, ent)
        elif k == 7:                                 # doppler (entangled beams: see after_generation)
            if rel == 2:
                c = (2 if color & 4 else 0) | (1 if color & 2 else 0) | (4 if color & 1 else 0)
                emit(x, y, d, color if ent else c, ent)
            elif rel == 6:
                c = (1 if color & 4 else 0) | (4 if color & 2 else 0) | (2 if color & 1 else 0)
                emit(x, y, d, color if ent else c, ent)
        elif k == 8:                                 # splitter: always disentangles
            if rel not in (0, 4):
                emit(x, y, d, color, 0)
                emit(x, y, rot + {1: -1, 2: -2, 3: -3, 5: 3, 6: 2, 7: 1}[rel], color, 0)
        elif k == 9:                                 # quantum tangler
            if rel == 2:
                for c in (1, 2, 4):
                    if color & c:
                        emit(x, y, rot, c, t.entangle_counter)
                        emit(x, y, rot - 4, c, t.entangle_counter)
                        t.entangle_counter += 1
        elif k == 11:                                # conduit
            if rel in (0, 4):
                emit(x, y, d, color, ent)
        elif k in (12, 18):                          # teleporters: jump to the next one along d
            x, y = x + DX[d], y + DY[d]
            while 0 <= x < N and 0 <= y < N:
                if t.b.at(x, y).type in (12, 18):
                    emit(x, y, d, color, ent)
                    return
                x, y = x + DX[d], y + DY[d]
        elif k == 13:                                # multi-filter: colour depends on the side hit
            keep = {2: 4, 6: 4, 1: 2, 5: 2, 0: 1, 4: 1}.get(rel)
            if keep is None:
                emit(x, y, d, color, ent)
            elif color & keep:
                emit(x, y, d, keep, ent)
        elif k == 14:                                # twister
            emit(x, y, d - 2, color, ent)
        elif k == 17:                                # starburst: four beams, rotated 45 degrees
            for o in ((1, 7, 3, 5) if d & 1 == 0 else (0, 2, 4, 6)):
                emit(x, y, o, color, 0)
        elif k == 19:                                # dual reflector: reflector on both faces
            o = {1: -1, 2: -2, 3: -3, 5: 3, 6: 2, 7: 1}.get(rel)
            if o is not None:
                emit(x, y, rot + o, color, ent)
        elif k == 20:                                # quad bender: bender on both faces
            emit(x, y, rot + [-1, -2, -3, -4, 3, 2, 1, 0][rel], color, ent)
        # wall (1), laser (2), complementor (15), gates (16, 22): absorbed

    def after_generation(self, t):
        """Entangled beams that just left a doppler change colour together."""
        q = t.next
        for i, (x, y, d, c, e) in enumerate(q):
            if x < N and y < N and e and t.b.at(x, y).type == 7:
                forward_side = ((d - t.b.at(x, y).dir) & 7) == 2
                for j, other in enumerate(q):
                    if other[4] == e:
                        table = DOPPLER_REV if (i == j) == forward_side else DOPPLER_FWD
                        other[3] = table[other[3]]

    def clear_beams(self, b):
        for row in b.cells:
            for c in row:
                c.inc = [0] * 8
                c.out = [0] * 8

    def trace_lasers(self, b):
        for x, y, d, color in list(self.lasers(b)):
            Tracer(b, self).run(x, y, d, color)

    def lasers(self, b):
        for y in range(N):
            for x in range(N):
                c = b.at(x, y)
                if c.type == 2:
                    yield x, y, c.dir, c.color

    def complementors(self, b):
        for y in range(N):
            for x in range(N):
                c = b.at(x, y)
                if c.type == 15 and not c.off:
                    yield x, y, c

    def emit_complements(self, b):
        for x, y, c in list(self.complementors(b)):
            for i in range(8):
                if c.inc[i] and (c.dir & 1) == (i & 1) and COMPLEMENT[c.inc[i]]:
                    Tracer(b, self).run(x, y, i, COMPLEMENT[c.inc[i]])

    def got_new_input(self, b):
        return any(c.inc[i] and not c.snap[i] for _, _, c in self.complementors(b) for i in range(8))

    def shut_down_contradictions(self, b):
        changed = False
        for _, _, c in list(self.complementors(b)):
            for i in range(8):
                s, now = c.snap[i], c.inc[i]
                if s != now and s and not (s == 7 and not now):
                    c.off = 1
                    changed = True
        return changed

    def gates(self, b):
        fired = False
        for y in range(N):
            for x in range(N):
                c = b.at(x, y)
                if c.type in (16, 22):
                    both = c.inc[(c.dir - 1) & 7] & c.inc[(c.dir + 1) & 7]
                    if c.type == 22 and both not in (1, 2, 4):
                        both = 0
                    e = both & ~c.out[c.dir] & 0xff
                    if e:
                        Tracer(b, self).run(x, y, c.dir, e)
                        fired = True
        return fired

    def snapshot(self, b):
        for row in b.cells:
            for c in row:
                c.snap = list(c.inc)

    def run(self, b):
        for row in b.cells:
            for c in row:
                c.off = 0
        while True:
            self.clear_beams(b)
            self.snapshot(b)
            self.trace_lasers(b)
            while True:
                self.snapshot(b)
                again = self.gates(b)
                self.emit_complements(b)
                if self.got_new_input(b):
                    again = True
                if self.gates(b) or again:
                    continue
                break
            if not self.shut_down_contradictions(b):
                return

    def won(self, b):
        for row in b.cells:
            for c in row:
                if c.type == 10:
                    lit = 0
                    for v in c.inc:
                        lit |= v
                    if lit != c.color:
                        return False
        return True


def trace(board, rules):
    rules.run(board)


def solved_board(level):
    b = Board()
    for p in level['board']:
        b.place(p['type'], p['x'], p['y'], p['dir'], p['color'])
    for t, s in zip(level['toolbox'], level['solution']):
        b.place(t['type'], s['x'], s['y'], s['dir'], t['color'])
    return b


def wins(level, rules, with_pieces=True):
    b = solved_board(level if with_pieces else dict(level, toolbox=[], solution=[]))
    trace(b, rules)
    return rules.won(b)


def main():
    data = json.load(open(sys.argv[1]))
    rules = Rules()
    lost = [lv.get('id', lv.get('title')) for lv in data['levels'] if not wins(lv, rules)]
    free = [lv.get('id', lv.get('title')) for lv in data['levels'] if wins(lv, rules, with_pieces=False)]
    print(f"{len(data['levels']) - len(lost)}/{len(data['levels'])} stored solutions win; "
          f'failing: {lost or "none"}; won with an empty toolbox: {free or "none"}')
    sys.exit(1 if lost or free else 0)


if __name__ == '__main__':
    main()
