# Grading levels: difficulty and design signals

Two tools describe a level:

* `tools/playersim.py` models how hard a level feels to a person. **Use this one for difficulty.**
* `tools/grade.py` reports how the beam solver gets through a level, and a set of signals from the
  light of the stored solution. It is good for checking that a design uses its intended trick.

```
.venv/bin/python tools/playersim.py designs/levels/cactus.lvl     # bits and tier of a sketch
.venv/bin/python tools/playersim.py --all out.json                # every level
.venv/bin/python tools/grade.py designs/episodes.json 10          # one level, step by step
.venv/bin/python tools/grade.py --bench designs/episodes.json out.json 30   # every level, 4 at a time
```

## The player model (`playersim.py`)

A model of how a person looks for moves (`tools/playersim.c`, on fastsim's tracer). The player puts
a piece where light already passes (or on a line beyond a lit teleporter) and ranks the moves by the
board they make: + targets lit exactly right, + less for a target lit with part of its colour,
− targets lit wrong (black ones lit at all), + a little for unlit targets in sight of a lit free
square, and a bonus for satisfying a target that had few lit squares in sight of it (a person
handles the most constrained target first).

**bits** follows the stored solution: at each step the best-ranked move that is part of the
solution is played, and log2 of its rank is added (moves that look just as good count half: a
person picks among them at random). It counts how many better-looking wrong moves the right one
has to beat. A second measure, a depth-first search in the player's order with growing patience,
saturates its budget on almost every real level and is not used.

Against 34 levels rated by hand (solved without help where possible, scored 1–10; the ratings are
not in this repo), bits has a Spearman correlation of **+0.53**; piece count has −0.09. Solve time
followed the score closely (+0.79).

It is a **tier sorter**, not a ranking: easy < 6, medium 6–15, hard ≥ 15 bits. Known blind spots:
* a trick that is new to the player (Crossbow's head-on splitters: 4 bits, rated 8);
* symmetric or several-laser boards, where equal-looking moves inflate the count (Pegboard: 16 bits,
  rated 5).

What the ratings showed about hard levels: the right move is not the obvious one (a counter-intuitive
use of a piece, a piece used twice), many places stay possible even after the insight, and
backtracking on a crowded board is hard even when it is trivial for a solver. A level is easy when
the path can be read off the board (a contour of targets, symmetry to copy). Levels designed to reach
≥ 15 bits were all rated 8–10, though with no structure on the board they felt "randomly generated"
(see "Lessons" in [STUDIO.md](STUDIO.md)).

## What `grade.py` measures

**Solver steps.** `beamsolve.c` in `grade` mode follows the stored solution through the search.
At each step it takes the open beam with the fewest options that survive its deductions:
* a target already gets a wrong colour;
* the pieces left cannot bring a missing colour;
* no square can hold the last piece.

For each step it records:
* `forced`: only one option survives, so a player who sees the same deduction just plays it.
* `search` and `deepest`: otherwise every wrong option is searched until it is refuted (at most
  5,000 nodes each). These give the size and depth of that trial and error. An option still
  open at the budget counts as 5,000 nodes (`open`).
* `bits`: log2 of the surviving options, summed. This is the guessing without any lookahead, and is
  not the same as playersim's bits.
* `not_first`: steps where the solver's "closest to done" ordering liked a wrong option better.

**Design signals**, from the light of the stored solution:

| signal | meaning | the trick it catches |
|---|---|---|
| `merges` | placed pieces lit from two or more directions | a splitter or prism combining beams |
| `reversals` | pieces that send light straight back | a mirror used head-on |
| `recolours` | pieces whose output colour differs from their input | prisms, filters, dopplers |
| `shared` | placed pieces whose removal changes the light of two or more targets | one beam serving several targets |
| `blockers` | placed pieces whose light reaches no target | a piece that only stops light |
| `depth` | most placed pieces between a laser and one target | long chains |
| `black`, `walls`, `symmetry` | the fixed board | constraint style, look |

These don't measure difficulty. Solver-hard and human-hard differ: the solver's bounds see the whole
board at once, while a player reasons from one target at a time. Most levels with 7 or more pieces
also stop grading inside the first step, so `search` is often only a lower bound.
