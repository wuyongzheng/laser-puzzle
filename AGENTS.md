# Notes for AI coding agents

* The player in `web/` is plain classic scripts with no build step and no ES modules, so
  `web/index.html` also works when opened from disk (`file://`).
* There is one rule set. `tools/sim.py` is the reference; `web/engine.js` and `tools/fastsim.c` are
  ports of it and must stay in step.

## After changing things

* Sketches in `designs/levels/` or its `order.txt`: rebuild with
  `.venv/bin/python tools/studio.py build designs/levels designs/episodes.json "Laser Puzzle"`,
  then regenerate the player's data with `.venv/bin/python tools/export_web.py`.
* `web/engine.js` or `tools/sim.py`: run the golden test
  (`.venv/bin/python tools/export_web.py --golden OUT.json`, then
  `node web/test/engine_test.js OUT.json`).
* `tools/fastsim.c`: `.venv/bin/python tools/solve.py --selftest designs/episodes.json`.
* Web UI: `.venv/bin/python web/test/ui_test.py OUTDIR` (Playwright; it fails on console errors).
