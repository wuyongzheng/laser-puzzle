# Solving levels

Two solvers find a level's solutions and check that it has no other one:

* `tools/beamsolve.py` (search in `beamsolve.c`) reasons about beams: what each beam meets
  first, and how many pieces the missing colours still need. See [the beam solver](#the-beam-solver).
* `tools/aspsolve.py` hands the rules to clingo, an answer-set solver. See
  [the answer-set solver](#the-answer-set-solver).

They succeed on different levels, so `beamsolve.other_shapes` runs both in turn, one process at a
time: the beam solver first (all of a budget up to 10 s, otherwise a third of it but at least
10 s), then clingo for the rest, unless the beam solver has already finished on a monotone
level. That is the main check in `design.py` and `generate.py`. The brute-force search in
`solve.py` still runs as a third opinion when neither finishes.

# The beam solver

## How it works

* **Beams, not squares.** Every piece that matters stands on a beam. The search takes one beam
  at a time (light leaving a square in one direction) and decides what it meets first: a new
  piece on one of the free squares along it, or nothing new. The squares the beam then crosses
  are closed to later pieces, so every placement is generated exactly once. Teleporter jumps are
  decided the same way.
* **Rotation sets.** A new piece keeps every rotation that treats the light it has received
  alike: a reflector hit from the west has 8 rotations but only a few different outcomes. When
  light arrives that the rotations in the set treat differently, the set is split, which is
  another decision. Solutions are reported once per shape.
* **Certain light.** Only light that has passed through decided beams is traced, with the exact
  simulator (`fastsim.c`, through hooks that hold light back at undecided beams). On a
  *monotone* level, where more light in never means less light out, this light is part of the
  final light of every way to finish the board. So a target that already has a wrong colour ends
  the branch. Levels with a quantum tangler, complementor or primary logic gate are not
  monotone; there the pruning below is off and the result is marked approximate.
* **Bound 1: pieces still needed.** A BFS follows single paths of light that may turn on any
  free square, in any way a remaining toolbox piece could turn it. It counts the pieces needed
  before every target could get every missing colour bit, along a path whose colour stays inside
  the target's. Pieces block nothing and toolbox counts are ignored, so this never overestimates,
  with one subtlety: light can return to a new piece and turn there a second time. So the count
  is in *rounds*: a square can hold a piece one round after light first reaches it, and from then
  on any light passing it may turn there.
* **Bound 2: where the last pieces go.** After the last new piece on its way, the light that
  brings a missing bit passes only straight lines and pieces already on the board. Walking
  backwards from the target gives the squares where that last piece can stand. With k pieces left
  they must also be lit within k − 1 rounds. If no k squares meet all these sets (exact for
  k ≤ 3, otherwise a count of disjoint sets), the branch ends. With one piece left, its options
  are restricted to the squares common to all the sets.
* **Lookahead and ordering.** Before branching, every option of every open beam is tried
  against the tests above. A beam with no surviving option ends the branch; otherwise the beam
  with the fewest options is branched on. Options closest to lighting everything (by the BFS
  levels) come first, which finds large many-solution levels in milliseconds.

## Validation

`beamsolve.py --selftest designs/episodes.json` follows each stored solution down the one branch
that leads to it. On a monotone level no test may prune that branch. Any miss on an approximate
level is only a spot check, because light that shrinks when more light arrives can make the
decided beams wrong.

**Known misses.** Two monotone levels with mobile teleporters in the toolbox fail this test: Crossing
Point and Request Stop. So the beam solver's pruning is not fully sound with mobile teleporters, and
a "proved by the beam solver" on such a level is weaker than it sounds. The cause has not been found.
Clingo alone was therefore run on all 25 levels with mobile teleporters in the toolbox, for up to 400 s
each. It found no second solution on any of them, and finished the search on 21, including those two.
It did not finish on Through the Looking-Glass, Level Crossing, Plumbing or Stopover, so those rest on
the beam solver's result or on a long run that found nothing.

The self-test caught three unsound steps while the solver was being built: counting turns instead
of rounds, treating a logic gate's output as its whole input, and leaving the exit square of a jump
to a new teleporter out of the "lit within k − 1 rounds" test.

## Where it fails

The bounds look at one missing colour at a time. Most of the search effort is spent with 1–2
pieces left, on boards where each target alone is still reachable but no single beam can serve
them all ("one blue beam and two benders cannot reach three blue targets"). Sound versions of
that reasoning have to allow for beams that share pieces or split, and are left for later.
Splitting the board into regions at chokepoints was tried and gave nothing.

# The answer-set solver

## How it works

* **Variables.** One choice per square: empty, or a toolbox piece in one of its distinct
  rotations (a splitter has 4, a reflector 8). Light is a yes/no fact per square, direction
  and colour bit: "red leaves (7,3) going east".
* **Rules.** Every rule in [RULES.md](RULES.md) is local to one square and works on each
  colour bit separately, so light becomes a set of rules of the form "red leaves (7,3) going
  east if red arrives going north and a reflector at rotation 1 stands there". These tables
  are generated by calling `sim.py`'s own `process` on a single piece, not typed in by hand.
* **Why answer sets.** In plain SAT the same rules also allow light that feeds itself in a loop
  with no laser behind it. A first version used CaDiCaL and blocked such loops one at a time, and
  kept finding new phantom loops, because the loop simply moves to another square. Answer-set
  semantics only accepts light derived from a laser, and clingo enforces that during the search.
* **Non-local rules.**
  * Teleporters are encoded as "the first teleporter along this line".
  * Complementors and logic gates are encoded as a fixed point of their final inputs.
    The iterative driver can leave stale light behind, so levels with them are marked
    *approximate*.
  * Entangled beams get a light layer of their own. A twin's colour change, caused by its
    partner crossing a doppler, may happen anywhere along the path. That is looser than the
    rules but never wrong.
* **Exact check.** Every solution clingo returns is replayed in `fastsim`. If the placement
  doesn't really win, it is blocked and the search continues.
* **Shapes.** Solutions are compared by shape: which pieces in which rotation class. Two
  placements with the same shape differ only in where the pieces stand, usually by sliding
  along a beam. "No other shape, search complete" is a proof that the level has no essentially
  different solution, including ones with fewer pieces. The approximations above are the only
  caveat. The encoding also never places a piece in the dark, so a solution that relies on a dark
  piece (one that steers the light making a complementor shut down) can be missed.

## Validation

`aspsolve.py --selftest designs/episodes.json` places each stored solution and checks two things: it
must be a model, and its light must equal `sim.py`'s on every square and direction. For entangled
and approximate levels, `sim.py`'s exact light must be among the models.

## What did not help

Tried on a 5-piece prism level that neither solver cracks in 120 s:
* All eight clingo preset configurations.
* A domain heuristic that decides squares in the order light reaches them.
* Splitting on where each laser's beam is first intercepted (cube and conquer).
* Native ASP rules and weight constraints instead of clauses, which was much slower.
* Failed-literal probing: try each piece on each square, and drop it if propagation alone
  contradicts it. This is how Sudoku-style "logic" solvers work. It placed almost nothing.

What does help is knowing the first pieces. With 2 of that level's 5 pieces given, clingo solves
it in under 2 s; with 1 given, it fails. The hard part is the opening: where to intercept each
laser. People settle that by reasoning about whole beams and colours ("yellow needs red and green
together, so…"), and neither solver does that.

## What this means for designing levels

* Small designs (up to about 4 pieces) are proved unique in seconds. Between 4 and about 8 pieces
  it depends on the level. A generator can simply discard candidates whose check doesn't finish.
* Above that, a search that doesn't finish is only a spot check for shortcuts. It finds the ones
  that either solver happens to reach, with no guarantee, so a playtest is still needed.
* Structure around the pieces is what makes bigger levels provable: see "Lessons" in
  [STUDIO.md](STUDIO.md).
