// Beam engine: a line-by-line port of tools/sim.py (the reference; rules in docs/RULES.md).
// web/test/engine_test.js checks it against light computed by sim.py for every level.
//
// A board is an array of N*N cells {type, dir, color, off, inc[8], out[8], snap[8]}.
// Directions: 0 = N, clockwise in 45-degree steps. Colours: RGB bitmask (R=1, G=2, B=4).
(function (root) {
  'use strict';

  var N = 15;
  var DX = [0, 1, 1, 1, 0, -1, -1, -1];
  var DY = [-1, -1, 0, 1, 1, 1, 0, -1];
  var DOPPLER_FWD = [0, 2, 4, 0, 1];
  var DOPPLER_REV = [0, 4, 1, 0, 2];
  var QUEUE_MAX = 32;
  var GENERATIONS = 0x400;
  var COMPLEMENT = [0, 6, 5, 4, 3, 2, 1, 0];

  var T = {
    empty: 0, wall: 1, laser: 2, reflector: 3, bender: 4, filter: 5, prism: 6, doppler: 7,
    splitter: 8, tangler: 9, target: 10, conduit: 11, teleporter: 12, multi_filter: 13,
    twister: 14, complementor: 15, logic_gate: 16, starburst: 17, mobile_teleporter: 18,
    dual_reflector: 19, quad_bender: 20, occupied: 21, primary_logic_gate: 22
  };

  function newBoard() {
    var cells = new Array(N * N);
    for (var i = 0; i < N * N; i++) {
      cells[i] = { type: 0, dir: 0, color: 0, off: 0, inc: [0, 0, 0, 0, 0, 0, 0, 0],
                   out: [0, 0, 0, 0, 0, 0, 0, 0], snap: [0, 0, 0, 0, 0, 0, 0, 0] };
    }
    return cells;
  }

  // pieces: [[type, x, y, dir, color], ...]
  function makeBoard(pieces) {
    var b = newBoard();
    for (var i = 0; i < pieces.length; i++) {
      var p = pieces[i], c = b[p[2] * N + p[1]];
      c.type = p[0]; c.dir = p[3]; c.color = p[4];
    }
    return b;
  }

  function at(b, x, y) { return b[y * N + x]; }

  // ---- one trace (sim.Tracer) ----

  function Tracer(b) {
    this.b = b; this.next = []; this.ent = 1;
  }
  Tracer.prototype.emit = function (x, y, d, color, ent) {
    if (this.next.length !== QUEUE_MAX) this.next.push([x, y, d & 7, color, ent]);
  };
  Tracer.prototype.run = function (x, y, d, color) {
    this.emit(x, y, d, color, 0);
    var left = GENERATIONS;
    while (this.next.length) {
      left -= 1;
      if (left === 0) break;
      var cur = this.next;
      this.next = [];
      for (var i = 0; i < cur.length; i++) {
        var q = cur[i], bx = q[0], by = q[1], bd = q[2];
        at(this.b, bx, by).out[bd] |= q[3];
        bx = (bx + DX[bd]) & 0xff; by = (by + DY[bd]) & 0xff;
        if (bx < N && by < N) process(this, bx, by, bd, q[3], q[4]);
      }
      afterGeneration(this);
    }
  };

  // entangled beams that just left a doppler change colour together
  function afterGeneration(t) {
    var q = t.next;
    for (var i = 0; i < q.length; i++) {
      var x = q[i][0], y = q[i][1], d = q[i][2], e = q[i][4];
      if (x < N && y < N && e && at(t.b, x, y).type === 7) {
        var forward = ((d - at(t.b, x, y).dir) & 7) === 2;
        for (var j = 0; j < q.length; j++) {
          if (q[j][4] === e) {
            var table = ((i === j) === forward) ? DOPPLER_REV : DOPPLER_FWD;
            q[j][3] = table[q[j][3]];
          }
        }
      }
    }
  }

  // ---- per-square rules ----

  var PRISM_B = { 1: 1, 2: 2, 5: -3, 6: -2 };
  var PRISM_G = { 0: 1, 2: 3, 5: -4, 7: -2 };
  var PRISM_R = { 0: -2, 2: -4, 5: 3, 7: 1 };
  var TWO_FACED = { 1: -1, 2: -2, 3: -3, 5: 3, 6: 2, 7: 1 };   // splitter, dual reflector
  var MULTI = { 2: 4, 6: 4, 1: 2, 5: 2, 0: 1, 4: 1 };
  var QUAD = [-1, -2, -3, -4, 3, 2, 1, 0];

  function teleport(t, x, y, d, color, ent) {
    x += DX[d]; y += DY[d];
    while (x >= 0 && x < N && y >= 0 && y < N) {
      var k = at(t.b, x, y).type;
      if (k === 12 || k === 18) { t.emit(x, y, d, color, ent); return; }
      x += DX[d]; y += DY[d];
    }
  }

  function process(t, x, y, d, color, ent) {
    var cell = at(t.b, x, y), rot = cell.dir, k = cell.type, o, c;
    cell.inc[d] |= color;
    var rel = (d - rot) & 7;
    switch (k) {
      case 0: case 10: case 21: t.emit(x, y, d, color, ent); break;
      case 3: if (rel >= 1 && rel <= 3) t.emit(x, y, rot - rel, color, ent); break;
      case 4: if (rel <= 3) t.emit(x, y, rot - rel - 1, color, ent); break;
      case 5: if ((rel === 2 || rel === 6) && (cell.color & color)) t.emit(x, y, d, cell.color & color, ent); break;
      case 6:
        if (color & 4) { o = PRISM_B[rel]; if (o !== undefined) t.emit(x, y, rot + o, 4, ent); }
        if (color & 2) { o = PRISM_G[rel]; if (o !== undefined) t.emit(x, y, rot + o, 2, ent); }
        if (color & 1) { o = PRISM_R[rel]; if (o !== undefined) t.emit(x, y, rot + o, 1, ent); }
        break;
      case 7:
        if (rel === 2) {
          c = (color & 4 ? 2 : 0) | (color & 2 ? 1 : 0) | (color & 1 ? 4 : 0);
          t.emit(x, y, d, ent ? color : c, ent);
        } else if (rel === 6) {
          c = (color & 4 ? 1 : 0) | (color & 2 ? 4 : 0) | (color & 1 ? 2 : 0);
          t.emit(x, y, d, ent ? color : c, ent);
        }
        break;
      case 8:
        if (rel !== 0 && rel !== 4) {
          t.emit(x, y, d, color, 0);
          t.emit(x, y, rot + TWO_FACED[rel], color, 0);
        }
        break;
      case 9:
        if (rel === 2) {
          [1, 2, 4].forEach(function (p) {
            if (color & p) {
              t.emit(x, y, rot, p, t.ent);
              t.emit(x, y, rot - 4, p, t.ent);
              t.ent += 1;
            }
          });
        }
        break;
      case 11: if (rel === 0 || rel === 4) t.emit(x, y, d, color, ent); break;
      case 12: case 18: teleport(t, x, y, d, color, ent); break;
      case 13:
        c = MULTI[rel];
        if (c === undefined) t.emit(x, y, d, color, ent);
        else if (color & c) t.emit(x, y, d, c, ent);
        break;
      case 14: t.emit(x, y, d - 2, color, ent); break;
      case 17:
        var outs = (d & 1) === 0 ? [1, 7, 3, 5] : [0, 2, 4, 6];
        for (var i = 0; i < 4; i++) t.emit(x, y, outs[i], color, 0);
        break;
      case 19:
        o = TWO_FACED[rel];
        if (o !== undefined) t.emit(x, y, rot + o, color, ent);
        break;
      case 20: t.emit(x, y, rot + QUAD[rel], color, ent); break;
      // wall, laser, complementor, gates: absorbed
    }
  }

  // ---- drivers (what runs when) ----

  function clearBeams(b) {
    for (var i = 0; i < b.length; i++) {
      for (var k = 0; k < 8; k++) { b[i].inc[k] = 0; b[i].out[k] = 0; }
    }
  }
  function snapshot(b) {
    for (var i = 0; i < b.length; i++) b[i].snap = b[i].inc.slice();
  }
  function traceLasers(b) {
    var lasers = [];
    for (var i = 0; i < b.length; i++) {
      if (b[i].type === 2) lasers.push([i % N, (i / N) | 0, b[i].dir, b[i].color]);
    }
    lasers.forEach(function (l) { new Tracer(b).run(l[0], l[1], l[2], l[3]); });
  }
  function complementors(b) {
    var out = [];
    for (var i = 0; i < b.length; i++) {
      if (b[i].type === 15 && !b[i].off) out.push(i);
    }
    return out;
  }
  function emitComplements(b) {
    complementors(b).forEach(function (i) {
      var c = b[i];
      for (var k = 0; k < 8; k++) {
        if (c.inc[k] && (c.dir & 1) === (k & 1) && COMPLEMENT[c.inc[k]]) {
          new Tracer(b).run(i % N, (i / N) | 0, k, COMPLEMENT[c.inc[k]]);
        }
      }
    });
  }
  function gotNewInput(b) {
    return complementors(b).some(function (i) {
      for (var k = 0; k < 8; k++) if (b[i].inc[k] && !b[i].snap[k]) return true;
      return false;
    });
  }
  function shutDown(b) {
    var changed = false;
    complementors(b).forEach(function (i) {
      var c = b[i];
      for (var k = 0; k < 8; k++) {
        var s = c.snap[k], now = c.inc[k];
        if (s !== now && s && !(s === 7 && !now)) {
          c.off = 1; changed = true;
        }
      }
    });
    return changed;
  }
  function gates(b) {
    var fired = false;
    for (var i = 0; i < b.length; i++) {
      var c = b[i];
      if (c.type !== 16 && c.type !== 22) continue;
      var both = c.inc[(c.dir - 1) & 7] & c.inc[(c.dir + 1) & 7];
      if (c.type === 22 && both !== 1 && both !== 2 && both !== 4) both = 0;
      var e = both & ~c.out[c.dir] & 0xff;
      if (e) {
        new Tracer(b).run(i % N, (i / N) | 0, c.dir, e);
        fired = true;
      }
    }
    return fired;
  }
  function resetOff(b) { for (var i = 0; i < b.length; i++) b[i].off = 0; }

  function trace(b) {
    resetOff(b);
    for (;;) {
      clearBeams(b);
      snapshot(b);
      traceLasers(b);
      for (;;) {
        snapshot(b);
        var again = gates(b);
        emitComplements(b);
        if (gotNewInput(b)) again = true;
        if (gates(b) || again) continue;
        break;
      }
      if (!shutDown(b)) return b;
    }
  }

  function lit(cell) {
    var v = 0;
    for (var k = 0; k < 8; k++) v |= cell.inc[k];
    return v;
  }

  // every target gets exactly its colour (black: no light at all)
  function won(b) {
    for (var i = 0; i < b.length; i++) {
      if (b[i].type === 10 && lit(b[i]) !== b[i].color) return false;
    }
    return true;
  }

  var api = { N: N, DX: DX, DY: DY, T: T, makeBoard: makeBoard, at: at,
              trace: trace, won: won, lit: lit };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.LaserEngine = api;
})(this);
