# Laser Puzzle

A free puzzle game about steering beams of coloured light: 276 levels in 18 episodes, with a level
editor. Place mirrors, prisms, splitters and stranger things so that every target gets exactly its
colour. Free of charge, no ads, no tracking, no accounts. It runs entirely in your browser.

**[Play it here](https://wuyongzheng.github.io/laser-puzzle/)**, on a phone or a desktop, or open
`web/index.html` from disk.

## Credit

Laser Puzzle is inspired by [Chromatron](https://www.silverspaceship.com/chromatron/) by Sean Barrett.
Its rules follow Chromatron 4. Chromatron's levels are not included: every level here is new. This
project is not affiliated with Sean Barrett.

The levels and tools were made mostly by AI agents, directed and playtested by Wu Yongzheng. Some
level titles are a nod to well-known topics of recent years.

## Playing

* Tap a toolbox piece, then a square. Tap a placed piece to select it, and tap it again to turn it
  45°. The ⟲ ⟳ ✕ buttons turn it or send it back to the toolbox. On a keyboard, Q/E turn, Delete takes
  back, the arrow keys move and Esc deselects.
* ☰ lists the episodes, with solved marks. Solving half of an episode's levels (rounded up) opens the
  next one.
* ⋯ has Reset, Show solution (a level solved this way isn't marked), Edit a copy, New level, Import,
  and "Unlock all episodes".
* Solved marks stay in your browser's localStorage.

The editor is meant for a desktop or tablet. You place pieces, tick "toolbox piece" for the ones the
player gets (they stand at their intended places), and test-play. It warns when the intended solution
doesn't win, when an empty toolbox wins, or when a piece isn't needed. Saved levels go to "My levels".
Export and Import use the `.lvl` sketch format, and an exported level can be proved with
`tools/studio.py check`, which the browser can't do.

## What's here

* `web/`: the player and editor. `engine.js` is the beam engine, `lvl.js` reads and writes `.lvl`,
  `render.js` draws the board, `app.js` is the player, `editor.js` the editor.
* `designs/levels/`: every level as a `.lvl` sketch, with `order.txt` sorting them into episodes.
  **The sketches and `designs/episodes.json` include the solutions**, and their headers explain each
  level's trick.
* `tools/`: the level design tools.
  * `sim.py`: the reference beam simulator.
  * `studio.py`: check a sketch, repair it, draw it, build the episodes.
  * `beamsolve.py`/`.c`, `aspsolve.py`, `solve.py`: solvers that prove a level has one solution.
  * `playersim.py`/`.c`: a model of how hard a level feels to a person.
  * `grade.py`, `design.py`, `dedup.py`, `generate.py`: design signals, checks, look-alikes, candidates.
  * `export_web.py`: turns the built episodes into `web/episodes.js`.
* `docs/`: [RULES.md](docs/RULES.md) (the rules), [STUDIO.md](docs/STUDIO.md) (how levels are made),
  [SOLVER.md](docs/SOLVER.md), [GRADER.md](docs/GRADER.md).

## Using the tools

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tools/studio.py check designs/levels/rainbow-bridge.lvl --png rainbow-bridge.png
.venv/bin/python tools/playersim.py designs/levels/rainbow-bridge.lvl
```

The C tools are built with gcc on first use. After adding a level to `designs/levels/` and
`order.txt`:

```
.venv/bin/python tools/studio.py build designs/levels designs/episodes.json "Laser Puzzle"
.venv/bin/python tools/export_web.py
```

## Tests

```
.venv/bin/python tools/export_web.py --golden g.json && node web/test/engine_test.js g.json
.venv/bin/python tools/solve.py --selftest designs/episodes.json
.venv/bin/python tools/beamsolve.py --selftest designs/episodes.json
.venv/bin/python tools/aspsolve.py --selftest designs/episodes.json
.venv/bin/python web/test/ui_test.py OUTDIR
```

## Licence

[MIT](LICENSE), for the code and the levels.
