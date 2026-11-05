# Beam rules

`tools/sim.py` is the executable version of this document; `web/engine.js` and `tools/fastsim.c` are
ports of it, and the tests compare them. When this page and `sim.py` disagree, `sim.py` is right.

Notation:
* `dir` 0–7 = N, NE, E, SE, S, SW, W, NW, with `dx = [0,1,1,1,0,-1,-1,-1]` and
  `dy = [-1,-1,0,1,1,1,0,-1]`. The board is 15 × 15.
* Colours are RGB bitmasks: R = 1, G = 2, B = 4.
* For a beam travelling in direction `d` that enters a piece facing `rot`, define
  `rel = (d − rot) & 7`.
* "emit(dir, colour, ent)" queues a beam leaving the current square. All direction arithmetic
  is `& 7`.

## 1. Tracing one beam source

Each source (a laser, a complementor output or a gate output) is traced on its own:

* Every beam is a record `(x, y, dir, colour, ent)`, where `ent` is the entanglement id and
  0 means not entangled. The trace starts with one beam on the source's own square, with
  `ent = 0`. The entanglement counter starts at 1, separately for each trace.
* Beams advance in **generations**. For each beam in the current queue, in order:
  1. `out[x,y][dir] |= colour`;
  2. step to `(x+dx, y+dy)`; if that is off the board, the beam is gone;
  3. otherwise apply the piece rule (§3) on the new square. It first does
     `in[x,y][dir] |= colour`, then may emit beams on that square into the next queue.
* The next queue holds at most **32** beams; further emits are silently dropped.
* After a generation, the **entangled doppler** step (§4) runs over the next queue.
* The trace stops when the queue is empty or after **1023** generations, whichever comes
  first. Loops do occur, but `|=` marking makes the result the same.

## 2. What runs when

```
off[*] = 0
A: clear in/out; snap = in; trace all lasers
B: snap = in
   again = gates()
   emit_complements()
   if some live complementor has in[i] != 0 and snap[i] == 0: again = true
   if gates(): goto B          # gates() always runs a second time here
   if again: goto B
   if contradictions(): goto A
```

Lasers are traced in row-major order (y outer, x inner). Each emits on its own square with
`dir = rot` and its colour.

* `emit_complements` visits complementors row-major and skips any that are shut down (`off`). For
  each direction `i` with `in[i] != 0` **and** `(i & 1) == (rot & 1)`, it starts a new trace from
  the complementor's square in direction `i` with colour `complement(in[i])`, where the complement
  maps 1↔6, 2↔5, 3↔4 and white (7) emits nothing.
* `gates()` visits squares row-major and returns true if any gate fired. For a logic gate (16),
  take `a = in[rot−1]` and `b = in[rot+1]`, the beams arriving travelling at ±45° to the gate's
  direction. The gate then emits `e = (a & b) & ~out[rot]`; if `e` is non-zero, it starts a trace
  from its square in direction `rot` with colour `e`. The **primary logic gate** (22) is the same,
  but only when `a & b` is exactly 1, 2 or 4.
* `contradictions` applies to each live complementor and all 8 directions `i`. If
  `snap[i] != in[i]`, `snap[i] != 0`, and not (`snap[i] == 7` and `in[i] == 0`), the complementor
  is shut down (`off = 1`) and the function returns true. A shut-down complementor absorbs
  everything.

## 3. Piece rules

Each rule first does `in[dir] |= colour`. Any case not listed absorbs the beam. Walls (1), lasers
(2), complementors (15) and logic gates (16, 22) always absorb; complementors and gates are driven
only by §2.

| type | piece | rule |
|---:|---|---|
| 0 | empty | emit(d, c, ent) |
| 21 | occupied | like empty, but no piece can be placed on it |
| 3 | reflector | rel 1,2,3 → emit(rot−rel, c, ent) |
| 19 | dual reflector | rel 1,2,3 → rot−rel; rel 5,6,7 → rot+(8−rel) (i.e. +3,+2,+1); same c, ent |
| 4 | bender | rel 0,1,2,3 → emit(rot−rel−1, c, ent) |
| 20 | quad bender | rel 0–7 → rot + [−1,−2,−3,−4,+3,+2,+1,0][rel]; same c, ent |
| 5 | filter | rel 2 or 6, and `c & colour` ≠ 0 → emit(d, c & colour, ent) |
| 13 | multi-filter | rel 2,6 keep blue; rel 1,5 keep green; rel 0,4 keep red: emit(d, keep, ent) if `c & keep`; rel 3,7 → emit(d, c, ent) |
| 6 | prism | each primary separately, emitted with the original `ent`: **blue** rel 1→rot+1, 2→rot+2, 5→rot−3, 6→rot−2; **green** rel 0→rot+1, 2→rot+3, 5→rot−4, 7→rot−2; **red** rel 0→rot−2, 2→rot−4, 5→rot+3, 7→rot+1. Order of emits: blue, green, red. |
| 7 | doppler | rel 2: R→B, G→R, B→G; rel 6: R→G, G→B, B→R (per bit). Entangled beams (ent ≠ 0) leave **unchanged** here and are recoloured by §4. Other rel: absorbed. |
| 8 | splitter | rel 0,4: absorbed. Otherwise emit(d, c, 0), then emit(rot + {1:−1, 2:−2, 3:−3, 5:+3, 6:+2, 7:+1}[rel], c, 0). A head-on hit also reflects back, and the splitter always disentangles. |
| 9 | quantum tangler | rel 2 only. For each primary p in R, G, B present in c: emit(rot, p, k) and emit(rot−4, p, k), with k = counter, then counter += 1. |
| 10 | target | emit(d, c, ent): light passes through |
| 11 | conduit | rel 0 or 4 → emit(d, c, ent) |
| 12, 18 | teleporter, mobile teleporter | walk from the next square along d; at the first square holding either kind, emit(d, c, ent) **on that square**. If none is found before the edge, the beam is gone. Pieces in between are ignored and don't get `in` marks. |
| 14 | twister | emit(d−2, c, ent) for every incoming direction |
| 17 | starburst | d even: emit dirs 1,7,3,5; d odd: emit dirs 0,2,4,6. Same c, ent 0. |

## 4. Entangled doppler step (end of every generation)

Doppler tables: forward `F = {1→2, 2→4, 4→1}`, reverse `R = {1→4, 2→1, 4→2}`.

For each beam `i` in the next queue, in order, that is on the board, has `ent ≠ 0`, and sits
on a doppler square: let `fwd = ((dir_i − rot) & 7) == 2`. Then, for each beam `j` in the
queue with `ent_j == ent_i` (including `i` itself), set `colour_j = R[colour_j]` if
`(i == j) == fwd`, otherwise `F[colour_j]`. The changes are made in place, so later beams
see earlier recolourings. As a result, the beam through the doppler shifts the usual way and
its entangled twin shifts the opposite way.

## 5. Winning

The level is won when every target (type 10) on the board satisfies
`in[0] | in[1] | … | in[7] == target colour`. A black target (colour 0) therefore must not be
hit at all. Pieces in the toolbox play no part.
