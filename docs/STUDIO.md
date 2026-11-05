# The design loop

Levels are made in a loop between a designer and the tools. The designer is an AI agent or a person.
It brings the idea, the layout, the title and the judgement of taste. The tools bring what an AI
is bad at: exact light, proof that there is no other solution, and repairs that keep the idea
intact. `tools/studio.py` is the tool side; this page is the designer's brief.

## The loop

1. **Choose a gap.** `studio.py coverage designs/levels/` lists the tricks, motifs and sizes made
   so far. Pick a trick and a size that an episode lacks, so it keeps teaching something new.
2. **Idea first.** Before placing anything, write down in one sentence the one thing the player
   must realise. Take it from the trick catalogue below, or combine two tricks. Choose a motif
   for the layout and a title, plus a one-line text that hints without telling.
3. **Sketch.** Write a `.lvl` file: walls and lasers, the intended solution (toolbox pieces with
   `*`), and targets. Mark target colours `?` to take whatever the solution delivers. Add an
   `expect:` line that states the trick in signals, e.g. `expect: merges>=1`.
4. **Check.** `studio.py check sketch.lvl --png sketch.png`. It reports:
   * whether the intended solution wins and every piece is needed;
   * other solutions, and ranked fixes that keep the intended one;
   * the grade (forced steps, trial and error);
   * the design signals, and whether the `expect:` lines hold;
   * an ASCII board and a picture.
5. **Look and revise.** Look at the picture.
   * Prefer fixes that look deliberate: a target on an intended beam reads as a clue, and a
     wall can extend a motif. Avoid stray black targets.
   * If the fixes would clutter the board, change the layout instead.
   * `--auto` applies the top fixes and appends them to the sketch, marked `% repair`.
6. **Accept or drop.** Accept the level when all of these hold:
   * it is proved unique, or, for a big level whose search can't finish, a long run finds no
     other solution (say so in a `proof:` header);
   * every piece is needed;
   * the `expect:` lines hold;
   * the picture looks intended.

   Drop it after a few rounds that don't converge; another idea is cheaper.
7. Move the sketch into `designs/levels/`, place it in an episode in `designs/levels/order.txt`,
   and rebuild (see "The episodes" below).

## Quality bar

* One idea per level, stated by the title and text without giving it away.
* No spare pieces, and an empty toolbox loses.
* Unique up to sliding a piece along its beam, and proved, not just "none found", where possible.
* Some forced steps, so the player has a foothold, but not all: a level that is all forced is a
  chore, and one with no forced step is guesswork.
* The board looks composed: structure, deliberate positions, no clutter.

For a **hard** level (`playersim.py` ≥ 15 bits):
* 5–10 pieces, with about one target per piece or fewer. Don't line the path with targets.
* A counter-intuitive key move. No long single-beam contour of targets, no symmetry that lets the
  player copy half, no set of independent per-laser sub-puzzles.
* Don't chase the number: equal-looking moves on symmetric or multi-laser boards, or near-forced
  routing pieces added only to raise the count, don't make a level hard.

## Lessons

* **Hard and hand-crafted.** Difficulty comes from a right move that does not look best, with few
  clues on the path. Levels made only for that were rated hard but felt randomly generated.
  Hand-crafted feel comes from the board:
  * a structure or picture: walls, rooms, a frame or a motif that shapes the board;
  * no stray patches: rule out second solutions with elements that are part of the structure (a
    wall of the room, a target of the picture), never a lone black target or wall block;
  * deliberate positions: aligned, balanced, using the space;
  * a board that explains the trick afterwards: once solved, the layout should make sense.

  Giving up clue targets for difficulty is right; giving up structure is not. Structure that bounds
  the space (rooms, corridors) without marking the path keeps both.
* **Walls are what make a level provable.** Open-field levels with 5 or more pieces rarely prove.
  Walling in the area where the pieces go fixes it: rooms, corridors, pockets, a walled laser slot.
  Adding about 8 free squares once turned a 117 s proof into no proof in 150 s. A board filled with
  occupied squares around a few free holes proves as fast as walls and keeps the look open, because
  light still crosses occupied squares. Targets that pin each beam's colour can also carry an open
  board: one 6-piece level with no walls proved in 0.4 s.
* **Solver limits.** Tangler + prism: neither solver finishes. Complementor and primary-gate results
  are approximate, so those levels carry a `proof: not proved` header. Prism levels above about 5
  pieces are slow to prove. 13 pieces is about the limit, and only with walls.
* **Two-sided pieces need two different beams.** A dual reflector or quad bender used by a single
  colour can be replaced by a plain one with the same light. A plain loop can be run backwards and
  is never unique; a prism or a second colour fixes the direction.
* **Idea-unique is enough sometimes.** With `accept: idea`, a level may have other solutions if the
  complete search lists all of them and each one meets the `expect` lines.
* **Pairs.** A partner on the same board, with one change that needs a new solution, works well, but
  a variant has to show something its original couldn't. Variants that only recolour rated poorly.
* **Assign themes.** Left to choose, several designers working in parallel pick the same topical
  theme. Titles and pictures may use topics that are well known worldwide, not insulting and not a
  trademark.

## Trick catalogue

| trick | the player must realise | signal |
|---|---|---|
| split | a prism splits white into red, green and blue, each going its own way | recolours |
| prism merge | a prism run backwards joins primaries into one beam | merges |
| splitter merge | a splitter joins two beams, and *both* outputs carry the mix | merges, shared |
| two-way splitter | one beam serves two targets through a splitter | shared |
| shared beam | targets in a row are lit by one beam: line them up | shared |
| mirror back | a reflector hit head-on sends light back the way it came | reversals |
| blocker | a piece whose only job is to stop or swallow a beam | blockers |
| doppler | a doppler shifts colour; which side it is hit from decides the shift | recolours |
| entangled twin | a doppler on one entangled beam recolours its twin elsewhere | recolours |
| filter | a filter keeps only part of a colour | recolours |
| long chain | the light has to visit many pieces in order | depth |
| teleport | fixed teleporters move a beam across a wall | (layout) |
| conduit | conduits pass light one way only, and nothing can be placed in them | (layout) |

## Motifs

* pocket: a walled target open on one side;
* fence: a wall or a line of black targets with a gap;
* corridors: walled lanes;
* rooms: walled areas joined by doors;
* symmetric frame: a mirror-symmetric wall picture;
* pictogram: walls that draw something that fits the title;
* open field: almost no walls, with the targets carrying all the constraints;
* diagonal: lasers and targets on diagonals.

## Tool reference

| command | what it does |
|---|---|
| `studio.py check X.lvl [--png X.png] [--auto] [--seconds S]` | the report of step 4; `--auto` appends the best fixes, marked `% repair`. A proof can need a large budget: a 60 s check may say "cut short" on a level a 300 s check proves in 22 s |
| `studio.py turn TYPE DIN [DOUT] [--color C]` | which rotations send light travelling DIN out in DOUT (directions 0 = N, clockwise) |
| `studio.py render X.lvl\|pack.json:N out.png [--puzzle]` | picture, solved or as the player first sees it |
| `studio.py build DIR out.json [name]` | the levels, in the episodes and order of `DIR/order.txt` (else file-name order) |
| `studio.py coverage DIR` | tricks, motifs and sizes made so far |
| `playersim.py X.lvl` | bits and difficulty tier ([GRADER.md](GRADER.md)) |
| `dedup.py SOURCE...` | duplicates and look-alikes |

Two solutions count as the same if one becomes the other by sliding pieces along their beams,
or by turning a piece in a way that changes no light at all. An example of the second: a
splitter hit only from two opposite sides gives the same light in two rotations.

## File formats

**Sketch (`.lvl`).** Header lines `key: value` (title, text, trick, motif, expect, ink, accept,
proof), then `---`, then one piece per line: `[*]TYPE X Y DIR COLOR`. `*` marks a toolbox piece, whose
position and direction are the intended solution. The `tools/studio.py` docstring has the glyphs.

**Pack (`designs/episodes.json`).** Built from the sketches. Each level has `board` pieces (type, x,
y, dir, color), `toolbox` pieces (type, color) and a `solution` with the place of each toolbox piece
(x, y, dir). Directions are 0 = N, clockwise in 45° steps; colours are RGB bitmasks (R = 1, G = 2,
B = 4). `web/episodes.js` is the same data in a compact form for the player.

## The episodes

Finished levels live in one folder, `designs/levels/`, as `slug.lvl` sketches.
`designs/levels/order.txt` puts them into episodes:

```
# Mirrors               an episode title
chimney                 one sketch name per line, in play order
spillway                % comments are allowed
```

`studio.py build designs/levels designs/episodes.json "Laser Puzzle"` refuses an `order.txt` that
leaves out a sketch, lists one twice or names one that doesn't exist. `export_web.py` then turns each
episode into a pack of the web player.

| # | episode | new pieces, or theme | levels |
|---|---|---|---|
| 1 | Mirrors | reflector, bender, walls; red, green, blue | 12 |
| 2 | Mixing | splitter, mixed colours, white light, black targets | 17 |
| 3 | The Long Way Round | mixed: long routes | 12 |
| 4 | Filters | filter, multi-filter | 14 |
| 5 | Prisms | prism | 20 |
| 6 | Entanglement | doppler, tangler | 15 |
| 7 | Palette | mixed: building colours | 18 |
| 8 | Tunnels | conduit, occupied square | 20 |
| 9 | Two-Way Street | mixed: light both ways, and twins | 16 |
| 10 | Portals | teleporter, mobile teleporter | 18 |
| 11 | Crossfire | mixed: crossing beams | 14 |
| 12 | Twisters | twister | 18 |
| 13 | Two-Faced Mirrors | dual reflector, quad bender | 17 |
| 14 | Double Duty | mixed: one piece doing two jobs | 13 |
| 15 | Starbursts | starburst | 13 |
| 16 | Logic | logic gate, complementor | 18 |
| 17 | Return to Sender | mixed: head-on returns | 10 |
| 18 | Finale | mixed: the hardest | 11 |

**Which episode.** A mixed episode uses only pieces already introduced. An introduction episode opens
with tiny levels for its new pieces and then uses them with anything earlier. Keep every episode at
10–20 levels. Mixed colours and black targets count as introduced in Mixing.

**Ordering inside an episode.**
* Each new piece (or colour idea) has an introduction level: tiny, one idea, a hint `text` that
  explains the piece with its name in capitals. It stands just before the first level that uses
  the piece. Introduction levels must not look alike.
* Then difficulty climbs, by play ratings where a level has them and `playersim.py` bits otherwise.
  End an episode on a strong hard level, chosen by hand where the model overrates one. Hard levels at
  the end don't block anyone: a player needs only half of an episode to open the next.
* Variety: no runs of the same trick, piece or look. Look-alikes don't stay in the pool at all,
  and deliberate pairs (Unfurl → Furl) go back to back.

**The NP-complete levels.** Five levels are titled after an NP-complete problem, as a joke for players
who know computer science, and state the instance in their hint where it has a text form: 3-SAT,
Subset Sum and Hamiltonian Path in Crossfire, Vertex Cover in Starbursts, Graph Coloring in Logic.

**Duplicates and look-alikes.** `tools/dedup.py SOURCE...` (pack files or sketch folders) normalizes
each level: 8 board symmetries × 6 colour permutations, shifted to the origin. Piece directions are
mapped through each piece's behaviour, so any rotation, mirror or colour swap of a level gets the same
key. It reports:
* exact duplicates and title clashes;
* look-alike pairs, ranked by a score that combines:
  * the shape of the solved light graph;
  * the fixed board's picture (best of 8 orientations);
  * the mix of pieces.

`--sheet out.png` draws the top pairs side by side. The score finds candidates; the eye decides. Dense
fields of occupied squares give false alarms on the picture score.
