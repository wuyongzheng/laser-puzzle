// The level editor. A level is edited as its intended solution: toolbox pieces stand where they
// belong, framed in gold. Export gives the .lvl text that tools/studio.py checks (proof of
// uniqueness, grading); Import reads it back. Levels are saved to "My levels".
//
// Taps: with a piece brush, an empty square gets a new piece; with the arrow, the selected piece
// moves there; the eraser removes. Tapping a piece selects it, tapping it again turns it.
(function (root) {
  'use strict';
  var E = root.LaserEngine, R = root.LaserRender, Lvl = root.LaserLvl, App = root.LaserApp;
  var $ = App.$;
  var COLOURED = [E.T.laser, E.T.filter, E.T.target];      // pieces whose colour matters
  var SWATCHES = [0, 1, 2, 3, 4, 5, 6, 7, null];             // null: '?' for targets

  var ED = {
    meta: {}, pieces: [], sel: null, brush: 'select', colour: 1, movable: false,
    mine: null,          // index in My levels, or null for a level not saved yet
    back: null,          // where Close returns to: {pi, li}
    dirty: false, note: ''
  };

  function open(level, mine) {
    if (App.mode === 'edit' && !canLeave()) return;
    var cur = App.current();
    if (!cur.testing) ED.back = { pi: cur.pi, li: cur.li };
    ED.meta = { title: '', text: '' };
    ED.pieces = [];
    if (level) {
      ED.meta.title = level.t;
      ED.meta.text = level.x;
      Object.keys(level.meta || {}).forEach(function (k) { ED.meta[k] = level.meta[k]; });
      ED.pieces = Lvl.toPieces(level);
    }
    ED.mine = mine;
    ED.sel = null;
    ED.dirty = false;
    ED.note = '';
    resume();
  }

  function resume() {
    App.mode = 'edit';
    App.showPanels();
    $('banner').hidden = true;
    $('hint').hidden = true;
    $('edTitle').value = ED.meta.title || '';
    $('edText').value = ED.meta.text || '';
    palette();
    render();
  }

  function canLeave() {
    return !ED.dirty || confirm('Discard the changes to this level?');
  }

  function changed() { ED.dirty = true; ED.note = ''; render(); }

  // ---- drawing ----

  function render() {
    var colours = Lvl.resolve(ED.pieces);
    var list = ED.pieces.map(function (p, i) { return [p.type, p.x, p.y, p.d, colours[i] || 0, p.mov]; });
    var b = E.trace(E.makeBoard(list));
    var marks = ED.pieces.filter(function (p) { return p.type === E.T.target && p.c === null; })
      .map(function (p) { return [p.x, p.y, '#888']; });
    var sel = ED.sel !== null ? [ED.pieces[ED.sel].x, ED.pieces[ED.sel].y] : null;
    $('board').innerHTML = R.board(list, b, { selected: sel, highlight: marks });
    $('packName').textContent = 'Editor' + (ED.mine !== null ? ' · My levels ' + (ED.mine + 1) : ' · not saved') + (ED.dirty ? ' · changed' : '');
    $('levelTitle').textContent = ED.meta.title || 'Untitled';
    $('prevBtn').disabled = $('nextBtn').disabled = true;
    controls();
    status();
  }

  function palette() {
    var pal = $('edPalette');
    pal.innerHTML = '';
    var add = function (brush, html, title) {
      var b = document.createElement('button');
      b.innerHTML = html;
      b.title = title;
      b.className = ED.brush === brush ? 'sel' : '';
      b.onclick = function () { ED.brush = brush; palette(); };
      pal.appendChild(b);
    };
    add('select', '↖', 'Select and move');
    add('erase', '⌫', 'Erase');
    Object.keys(E.T).forEach(function (name) {
      var t = E.T[name];
      if (t === 0) return;
      var c = COLOURED.indexOf(t) >= 0 ? (ED.colour === null ? 7 : ED.colour || 7) : 0;
      add(t, R.icon(t, c), Lvl.nameOf(t));
    });
  }

  function controls() {
    var p = ED.sel !== null ? ED.pieces[ED.sel] : null;
    var current = p ? p.c : ED.colour;
    var box = $('edColours');
    box.innerHTML = '';
    SWATCHES.forEach(function (c) {
      var b = document.createElement('button');
      b.className = current === c ? 'sel' : '';
      if (c === null) { b.textContent = '?'; b.style.background = '#444'; b.title = 'target: take the colour of the light'; }
      else { b.style.background = c ? R.colour(c) : '#000'; b.title = 'krgybmcw'[c]; }
      b.onclick = function () {
        if (p) {
          if (c === null && p.type !== E.T.target) return;
          p.c = c; changed();
        } else { ED.colour = c; controls(); palette(); }
      };
      box.appendChild(b);
    });
    $('edMovable').checked = p ? p.mov : ED.movable;
    $('edRotL').disabled = $('edRotR').disabled = $('edDelete').disabled = !p;
  }

  function status() {
    var lines = [];
    var r = Lvl.fromPieces(ED.meta, ED.pieces);
    var lv = r.level;
    r.problems.forEach(function (p) { lines.push(['bad', p]); });
    var targets = lv.b.filter(function (p) { return p[0] === E.T.target; }).length;
    var wins = function (m) {
      var b = E.trace(E.makeBoard(lv.b.concat(m.map(function (p) { return [p[0], p[2], p[3], p[4], p[1]]; }))));
      return targets > 0 && E.won(b);
    };
    if (!targets) lines.push(['bad', 'no targets yet']);
    else if (!lv.m.length) lines.push(['bad', 'no toolbox pieces yet (tick "toolbox piece")']);
    else if (!wins(lv.m)) lines.push(['bad', 'the intended solution does not win']);
    else {
      lines.push(['ok', 'the intended solution wins (' + plural(lv.m.length, 'piece') + ', ' + plural(targets, 'target') + ')']);
      if (wins([])) lines.push(['bad', 'the empty toolbox wins too']);
      var spare = lv.m.filter(function (_, i) { return wins(lv.m.slice(0, i).concat(lv.m.slice(i + 1))); });
      if (spare.length) lines.push(['bad', 'not needed: ' + spare.map(function (m) { return Lvl.nameOf(m[0]); }).join(', ')]);
    }
    if (ED.note) lines.push(['ok', ED.note]);
    var el = $('edStatus');
    el.innerHTML = '';
    lines.forEach(function (l) {
      var d = document.createElement('div');
      d.className = l[0];
      d.textContent = l[1];
      el.appendChild(d);
    });
  }

  // ---- editing ----

  function at(x, y) {
    for (var i = 0; i < ED.pieces.length; i++) if (ED.pieces[i].x === x && ED.pieces[i].y === y) return i;
    return -1;
  }

  function tap(x, y) {
    var i = at(x, y);
    if (ED.brush === 'erase') {
      if (i >= 0) { ED.pieces.splice(i, 1); ED.sel = null; changed(); }
      return;
    }
    if (i >= 0) {
      if (ED.sel === i) { ED.pieces[i].d = (ED.pieces[i].d + 1) & 7; changed(); }
      else { ED.sel = i; render(); }
      return;
    }
    if (ED.brush === 'select') {
      if (ED.sel !== null) { ED.pieces[ED.sel].x = x; ED.pieces[ED.sel].y = y; changed(); }
      return;
    }
    var t = ED.brush;
    var c = COLOURED.indexOf(t) < 0 ? 0 : ED.colour === null ? (t === E.T.target ? null : 7) : ED.colour;
    ED.pieces.push({ type: t, x: x, y: y, d: 0, c: c, mov: ED.movable });
    ED.sel = ED.pieces.length - 1;
    changed();
  }

  function turn(step) {
    if (ED.sel === null) return;
    ED.pieces[ED.sel].d = (ED.pieces[ED.sel].d + step) & 7;
    changed();
  }
  function remove() {
    if (ED.sel === null) return;
    ED.pieces.splice(ED.sel, 1);
    ED.sel = null;
    changed();
  }
  function move(dx, dy) {
    if (ED.sel === null) return;
    var p = ED.pieces[ED.sel], x = p.x + dx, y = p.y + dy;
    if (x < 0 || y < 0 || x >= E.N || y >= E.N || at(x, y) >= 0) return;
    p.x = x; p.y = y;
    changed();
  }

  function key(e) {
    var k = e.key;
    if (k === 'q' || k === 'Q') turn(-1);
    else if (k === 'e' || k === 'E') turn(1);
    else if (k === 'Delete' || k === 'Backspace') remove();
    else if (k === 'Escape') { ED.sel = null; render(); }
    else if (k === 'ArrowLeft') move(-1, 0);
    else if (k === 'ArrowRight') move(1, 0);
    else if (k === 'ArrowUp') move(0, -1);
    else if (k === 'ArrowDown') move(0, 1);
    else return;
    e.preventDefault();
  }

  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  function text() { return Lvl.serialize(ED.meta, ED.pieces); }

  function saveLevel() {
    var store = App.store;
    if (ED.mine === null) { store.mine.push(text()); ED.mine = store.mine.length - 1; }
    else store.mine[ED.mine] = text();
    if (store.solved.mine) delete store.solved.mine[ED.mine];   // a changed level is unsolved
    App.save();
    App.buildPacks();
    ED.dirty = false;
    ED.note = 'saved as My levels ' + (ED.mine + 1);
    render();
  }

  function close() {
    if (!canLeave()) return;
    ED.dirty = false;
    var packs = App.packs();
    if (ED.mine !== null) App.open(App.packIndex('mine'), ED.mine);
    else if (ED.back && ED.back.pi < packs.length && ED.back.li < packs[ED.back.pi].levels.length) App.open(ED.back.pi, ED.back.li);
    else App.open(0, 0);
  }

  function init() {
    $('edTitle').oninput = function () { ED.meta.title = this.value; changed(); };
    $('edText').oninput = function () { ED.meta.text = this.value; changed(); };
    $('edMovable').onchange = function () {
      if (ED.sel !== null) { ED.pieces[ED.sel].mov = this.checked; changed(); }
      else ED.movable = this.checked;
    };
    $('edRotL').onclick = function () { turn(-1); };
    $('edRotR').onclick = function () { turn(1); };
    $('edDelete').onclick = remove;
    $('edTest').onclick = function () { App.test(Lvl.fromPieces(ED.meta, ED.pieces).level); };
    $('edSave').onclick = saveLevel;
    $('edClose').onclick = close;
    $('edClear').onclick = function () {
      if (ED.pieces.length && confirm('Remove every piece from the board?')) { ED.pieces = []; ED.sel = null; changed(); }
    };
    $('edExport').onclick = function () {
      var slug = (ED.meta.title || 'level').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'level';
      App.textDialog({ title: 'Export', readOnly: true, text: text(), filename: slug + '.lvl',
                       note: 'The level in .lvl format: paste it into Import, or check it with tools/studio.py check.' });
    };
    $('edImport').onclick = function () {
      App.textDialog({
        title: 'Import into the editor',
        note: 'Paste a level in .lvl format, or choose a .lvl file. It replaces what is on the board.',
        ok: function (t) {
          if (t.trim()[0] === '{') return 'That is a pack; use "Import level or pack…" in the ⋯ menu.';
          var r;
          try { r = Lvl.parse(t); } catch (e) { return e.message; }
          if (ED.dirty && !confirm('Replace the level being edited?')) return 'Cancelled.';
          var keep = ED.mine;
          ED.dirty = false;
          open(r.level, keep);
          ED.dirty = true;
          // keep '?' targets as '?' rather than the colours parse() resolved
          var fresh = [];
          t.split(/\r?\n/).forEach(function (line) {
            var f = line.split('%')[0].trim().replace(/^\*/, '').split(/\s+/);
            if (f.length === 5 && f[4] === '?') fresh.push(f[1] + ',' + f[2]);
          });
          ED.pieces.forEach(function (p) { if (fresh.indexOf(p.x + ',' + p.y) >= 0 && p.type === E.T.target) p.c = null; });
          render();
        }
      });
    };
  }

  App.editor = { open: open, resume: resume, tap: tap, key: key, canLeave: canLeave };
  document.addEventListener('DOMContentLoaded', init);
})(this);
