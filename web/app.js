// The player: level menu, progress, and tap-to-place play. The editor (editor.js) shares the
// board, the header and the text dialog through App.
//
// Taps: a toolbox piece selects it; an empty square then receives it (or the selected placed
// piece moves there); tapping a placed piece selects it, and tapping it again turns it 45
// degrees clockwise. Keys: Q/E turn, Delete takes back, arrows move, Esc deselects.
//
// Progress (solved marks, levels made or imported here) is kept in localStorage. Solved marks
// are keyed by pack id and the level's id (its sketch name) where it has one, else its index.
//
// Episodes unlock in order: solving half of an episode's levels (rounded up) opens the next one.
// "Unlock all episodes" in the ⋯ menu opens them all.
(function (root) {
  'use strict';
  var E = root.LaserEngine, R = root.LaserRender, Lvl = root.LaserLvl;
  var KEY = 'laser-puzzle-v1';
  var $ = function (id) { return document.getElementById(id); };

  // ---- storage ----

  var store = load();
  function load() {
    var s = null;
    try { s = JSON.parse(localStorage.getItem(KEY)); } catch (e) { /* private mode, blocked storage */ }
    s = s || {};
    s.solved = s.solved || {};
    s.mine = s.mine || [];
    s.custom = s.custom || [];
    return s;
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { /* progress just isn't kept */ }
  }

  // ---- packs ----

  var packs = [];
  function buildPacks() {
    packs = (root.LASER_PUZZLE_EPISODES || []).map(function (p) {
      return { id: p.id, name: p.name, desc: p.desc, episode: true, levels: p.levels };
    });
    store.custom.forEach(function (p) {
      packs.push({ id: p.id, name: p.name, desc: p.desc, custom: true, levels: p.levels });
    });
    packs.push({ id: 'mine', name: 'My levels', desc: 'made in the editor or imported', mine: true,
                 levels: store.mine.map(function (text) {
                   try { return Lvl.parse(text).level; } catch (e) { return { t: '(unreadable: ' + e.message + ')', x: '', b: [], m: [] }; }
                 }) });
  }
  function packIndex(id) {
    for (var i = 0; i < packs.length; i++) if (packs[i].id === id) return i;
    return -1;
  }
  function levelKey(pi, li) {
    var lv = packs[pi].levels[li];
    return lv.id || String(li);
  }
  function isSolved(pi, li) {
    var s = store.solved[packs[pi].id];
    return !!(s && s[levelKey(pi, li)]);
  }
  function solvedCount(pi) {
    return packs[pi].levels.filter(function (_, li) { return isSolved(pi, li); }).length;
  }
  function needed(pi) { return Math.ceil(packs[pi].levels.length / 2); }
  // an episode is locked until half of the one before it is solved; other packs never are
  function locked(pi) {
    if (!packs[pi].episode || store.unlockAll) return false;
    for (var k = 1; k <= pi; k++) {
      if (solvedCount(k - 1) < needed(k - 1)) return true;
    }
    return false;
  }

  // ---- play state ----

  var S = {
    pi: 0, li: 0, level: null,
    pos: [],            // per toolbox piece: null (in the toolbox) or [x, y]
    dirs: [],           // per toolbox piece: its direction
    sel: null,          // selected toolbox piece
    revealed: false,    // solution shown: a win doesn't count
    opened: null,       // the episode this level's win opened, for the banner
    testing: null       // a level being tested from the editor
  };

  function open(pi, li) {
    if (App.mode === 'edit' && !App.editor.canLeave()) return;
    if (locked(pi)) return;
    S.pi = pi; S.li = li; S.testing = null;
    store.last = { id: packs[pi].id, li: li };
    save();
    start(packs[pi].levels[li]);
  }
  function start(level) {
    S.level = level;
    S.pos = level.m.map(function () { return null; });
    S.dirs = level.m.map(function () { return 0; });
    S.sel = null;
    S.revealed = false;
    S.opened = null;
    App.mode = 'play';
    showPanels();
    $('hint').classList.remove('open');
    render();
  }

  function pieces() {
    var out = S.level.b.map(function (p) { return [p[0], p[1], p[2], p[3], p[4], false]; });
    S.level.m.forEach(function (m, i) {
      if (S.pos[i]) out.push([m[0], S.pos[i][0], S.pos[i][1], S.dirs[i], m[1], true]);
    });
    return out;
  }
  function traced() {
    return E.trace(E.makeBoard(pieces()));
  }
  function occupant(x, y) {
    for (var i = 0; i < S.level.b.length; i++) {
      if (S.level.b[i][1] === x && S.level.b[i][2] === y) return { fixed: S.level.b[i] };
    }
    for (var j = 0; j < S.pos.length; j++) {
      if (S.pos[j] && S.pos[j][0] === x && S.pos[j][1] === y) return { movable: j };
    }
    return null;
  }

  function render() {
    var b = traced();
    var won = E.won(b) && S.level.b.some(function (p) { return p[0] === E.T.target; });
    var sel = S.sel !== null && S.pos[S.sel] ? S.pos[S.sel] : null;
    $('board').innerHTML = R.board(pieces(), b, { selected: sel });
    header();
    var tb = $('toolbox');
    tb.innerHTML = '';
    S.level.m.forEach(function (m, i) {
      var btn = document.createElement('button');
      btn.className = 'tool' + (S.sel === i ? ' sel' : '') + (S.pos[i] ? ' placed' : '');
      btn.title = Lvl.nameOf(m[0]);
      btn.innerHTML = R.icon(m[0], m[1], S.pos[i] ? 0 : S.dirs[i]);
      btn.onclick = function () { S.sel = S.sel === i ? null : i; render(); };
      tb.appendChild(btn);
    });
    $('rotL').disabled = $('rotR').disabled = S.sel === null;
    $('takeBack').disabled = S.sel === null || !S.pos[S.sel];
    $('backToEditor').hidden = !S.testing;
    banner(won);
  }

  function header() {
    if (S.testing) {
      $('packName').textContent = 'Testing (editor)';
    } else {
      var p = packs[S.pi];
      $('packName').textContent = p.name + (p.episode ? ': ' + p.desc : '') + ' · ' + (S.li + 1) + ' of ' + p.levels.length;
    }
    var t = S.level.t || 'Level ' + (S.li + 1);
    $('levelTitle').textContent = t + (!S.testing && isSolved(S.pi, S.li) ? '  ✓' : '');
    $('hint').textContent = S.level.x || '';
    $('hint').hidden = !S.level.x;
    $('prevBtn').disabled = !!S.testing || !neighbour(-1);
    $('nextBtn').disabled = !!S.testing || !neighbour(1);
  }

  function banner(won) {
    var el = $('banner');
    if (!won) { el.hidden = true; return; }
    if (!S.revealed && !S.testing && !isSolved(S.pi, S.li)) {
      var id = packs[S.pi].id, was = S.pi + 1 < packs.length && locked(S.pi + 1);
      store.solved[id] = store.solved[id] || {};
      store.solved[id][levelKey(S.pi, S.li)] = 1;
      save();
      header();
      if (was && !locked(S.pi + 1)) S.opened = packs[S.pi + 1];
    }
    el.innerHTML = '';
    var msg = document.createElement('span');
    msg.textContent = S.revealed ? 'Solution shown' : S.opened ? 'Solved! ' + S.opened.name + ' is open.' : 'Solved!';
    el.appendChild(msg);
    var nb = neighbour(1);
    if (nb && !S.testing) {
      var btn = document.createElement('button');
      btn.className = 'text-btn primary';
      btn.textContent = 'Next ›';
      btn.onclick = function () { open(nb[0], nb[1]); };
      el.appendChild(btn);
    }
    el.hidden = false;
  }

  function neighbour(step) {
    var pi = S.pi, li = S.li + step;
    while (pi >= 0 && pi < packs.length) {
      if (li >= 0 && li < packs[pi].levels.length) return [pi, li];
      pi += step;
      if (pi < 0 || pi >= packs.length || locked(pi)) return null;
      li = step > 0 ? 0 : packs[pi].levels.length - 1;
    }
    return null;
  }

  // ---- input ----

  function cellAt(evt, svg) {
    var pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    var p = pt.matrixTransform(svg.getScreenCTM().inverse());
    var x = Math.floor(p.x), y = Math.floor(p.y);
    return x >= 0 && x < E.N && y >= 0 && y < E.N ? [x, y] : null;
  }

  function tapPlay(x, y) {
    var o = occupant(x, y);
    if (o && o.movable !== undefined) {
      if (S.sel === o.movable) S.dirs[o.movable] = (S.dirs[o.movable] + 1) & 7;
      else S.sel = o.movable;
    } else if (o) {
      S.sel = null;
    } else if (S.sel !== null) {
      S.pos[S.sel] = [x, y];
    }
    render();
  }

  function turn(step) {
    if (S.sel === null) return;
    S.dirs[S.sel] = (S.dirs[S.sel] + step) & 7;
    render();
  }
  function takeBack() {
    if (S.sel === null) return;
    S.pos[S.sel] = null;
    render();
  }
  function move(dx, dy) {
    if (S.sel === null || !S.pos[S.sel]) return;
    var x = S.pos[S.sel][0] + dx, y = S.pos[S.sel][1] + dy;
    if (x < 0 || y < 0 || x >= E.N || y >= E.N || occupant(x, y)) return;
    S.pos[S.sel] = [x, y];
    render();
  }
  function reset() {
    S.pos = S.pos.map(function () { return null; });
    S.dirs = S.dirs.map(function () { return 0; });
    S.sel = null;
    S.revealed = false;
    render();
  }
  function showSolution() {
    S.level.m.forEach(function (m, i) { S.pos[i] = [m[2], m[3]]; S.dirs[i] = m[4]; });
    S.sel = null;
    S.revealed = true;
    render();
  }

  // ---- menus ----

  function showPanels() {
    $('playPanel').hidden = App.mode !== 'play';
    $('editPanel').hidden = App.mode !== 'edit';
  }

  function moreMenu() {
    var items = [];
    if (App.mode === 'play') {
      items.push(['Reset', reset], ['Show solution', showSolution], null);
      if (S.testing) {
        items.push(['Back to editor', function () { App.editor.resume(); }]);
      } else {
        var mine = packs[S.pi].mine;
        items.push([mine ? 'Edit level' : 'Edit a copy', function () {
          App.editor.open(S.level, mine ? S.li : null);
        }]);
        if (mine) items.push(['Delete level', deleteMine]);
      }
    }
    items.push(['New level', function () { App.editor.open(null, null); }],
               ['Import level or pack…', importDialog], null,
               [(store.unlockAll ? '☑' : '☐') + ' Unlock all episodes', function () {
                 store.unlockAll = !store.unlockAll;
                 save();
                 if (locked(S.pi)) open(0, 0); else render();
               }]);
    var menu = $('moreMenu');
    menu.innerHTML = '';
    items.forEach(function (it) {
      if (!it) { menu.appendChild(document.createElement('hr')); return; }
      var b = document.createElement('button');
      b.textContent = it[0];
      b.onclick = function () { menu.hidden = true; it[1](); };
      menu.appendChild(b);
    });
    menu.appendChild(document.createElement('hr'));
    var credit = document.createElement('p');
    credit.className = 'credit';
    credit.innerHTML = 'Inspired by <a href="https://www.silverspaceship.com/chromatron/" target="_blank" ' +
                       'rel="noopener">Chromatron</a> by Sean Barrett';
    menu.appendChild(credit);
    menu.hidden = false;
  }

  function deleteMine() {
    if (!confirm('Delete "' + (S.level.t || 'this level') + '" from My levels?')) return;
    store.mine.splice(S.li, 1);
    var sv = store.solved.mine;
    if (sv) {   // these levels have no id, so marks are by index: shift the later ones down
      var next = {};
      Object.keys(sv).forEach(function (k) { k = +k; if (k < S.li) next[k] = 1; else if (k > S.li) next[k - 1] = 1; });
      store.solved.mine = next;
    }
    save();
    buildPacks();
    var pi = packIndex('mine');
    if (packs[pi].levels.length) open(pi, Math.min(S.li, packs[pi].levels.length - 1));
    else open(0, 0);
  }

  function drawer() {
    var list = $('packList');
    list.innerHTML = '';
    packs.forEach(function (p, pi) {
      var d = document.createElement('details');
      var shut = locked(pi);
      d.className = 'pack' + (shut ? ' locked' : '');
      d.open = pi === S.pi && !S.testing;
      var done = solvedCount(pi);
      var sum = document.createElement('summary');
      sum.innerHTML = '<span class="count"></span><strong></strong> <span class="desc"></span>';
      sum.querySelector('strong').textContent = p.name;
      sum.querySelector('.desc').textContent = p.desc ? '· ' + p.desc : '';
      sum.querySelector('.count').textContent = shut ? 'locked' : done + ' / ' + p.levels.length;
      d.appendChild(sum);
      if (shut && !locked(pi - 1)) {
        var note = document.createElement('p');
        note.className = 'lock-note';
        var more = needed(pi - 1) - solvedCount(pi - 1);
        note.textContent = 'Solve ' + more + ' more level' + (more === 1 ? '' : 's') + ' in ' + packs[pi - 1].name + ' to open this episode.';
        d.appendChild(note);
      }
      var grid = document.createElement('div');
      grid.className = 'levels';
      p.levels.forEach(function (lv, li) {
        var b = document.createElement('button');
        b.textContent = li + 1;
        b.title = lv.t || 'Level ' + (li + 1);
        b.className = (isSolved(pi, li) ? 'solved' : '') + (pi === S.pi && li === S.li && !S.testing ? ' current' : '');
        b.disabled = shut;
        b.onclick = function () { $('drawer').hidden = true; open(pi, li); };
        grid.appendChild(b);
      });
      d.appendChild(grid);
      if (p.mine || p.custom) {
        var tools = document.createElement('div');
        tools.className = 'pack-tools';
        var add = function (label, fn) {
          var b = document.createElement('button');
          b.className = 'text-btn'; b.textContent = label;
          b.onclick = function () { $('drawer').hidden = true; fn(); };
          tools.appendChild(b);
        };
        if (p.mine) {
          add('New level', function () { App.editor.open(null, null); });
          add('Import…', importDialog);
        } else {
          add('Remove pack', function () {
            if (!confirm('Remove the pack "' + p.name + '"?')) return;
            store.custom = store.custom.filter(function (c) { return c.id !== p.id; });
            delete store.solved[p.id];
            save(); buildPacks(); open(0, 0);
          });
        }
        d.appendChild(tools);
      }
      list.appendChild(d);
    });
    $('drawer').hidden = false;
  }

  // ---- text dialog (import / export) ----

  // opts: {title, note, text, readOnly, filename, ok(text) -> error string or nothing}
  function textDialog(opts) {
    var dlg = $('textDialog');
    $('textDialogTitle').textContent = opts.title;
    $('textDialogNote').textContent = opts.note || '';
    var ta = $('textDialogText');
    ta.value = opts.text || '';
    ta.readOnly = !!opts.readOnly;
    $('textDialogError').textContent = '';
    $('textDialogPick').hidden = !!opts.readOnly;
    $('textDialogCopy').hidden = $('textDialogDownload').hidden = !opts.readOnly;
    $('textDialogOk').hidden = !opts.ok;
    $('textDialogOk').onclick = function () {
      var err = opts.ok(ta.value);
      if (err) $('textDialogError').textContent = err;
      else dlg.close();
    };
    $('textDialogCopy').onclick = function () {
      ta.select();
      var done = function () { $('textDialogError').textContent = 'Copied.'; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(ta.value).then(done, function () { document.execCommand('copy'); done(); });
      } else { document.execCommand('copy'); done(); }
    };
    $('textDialogDownload').onclick = function () {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([ta.value], { type: 'text/plain' }));
      a.download = opts.filename || 'level.lvl';
      document.body.appendChild(a); a.click(); a.remove();
    };
    $('textDialogFile').value = '';
    $('textDialogFile').onchange = function () {
      var f = this.files[0];
      if (!f) return;
      var r = new FileReader();
      r.onload = function () { ta.value = r.result; };
      r.readAsText(f);
    };
    $('textDialogPick').onclick = function () { $('textDialogFile').click(); };
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
    if (!opts.readOnly) ta.focus();
  }

  function importDialog() {
    textDialog({
      title: 'Import',
      note: 'Paste a level in .lvl format (as exported by the editor or written for tools/studio.py), ' +
            'or choose a .lvl file or a pack .json (the format of designs/episodes.json).',
      ok: function (text) {
        text = text.trim();
        if (!text) return 'Nothing to import.';
        if (text[0] === '{') return importPack(text);
        try {
          var r = Lvl.parse(text);
          store.mine.push(text + '\n');
          save(); buildPacks();
          open(packIndex('mine'), store.mine.length - 1);
          if (r.problems.length) alert('Imported, with problems:\n' + r.problems.join('\n'));
        } catch (e) { return e.message; }
      }
    });
  }

  // a pack in the JSON format of designs/episodes.json -> a custom pack in the compact form of episodes.js
  function importPack(text) {
    var data;
    try { data = JSON.parse(text); } catch (e) { return 'Not valid JSON: ' + e.message; }
    if (!data.levels || !data.levels.length) return 'No "levels" list in this JSON.';
    var levels = [];
    try {
      data.levels.forEach(function (lv) {
        levels.push({
          t: lv.title || '', x: lv.text || '',
          b: lv.board.map(function (p) { return [typeId(p.type), p.x, p.y, p.dir, p.color]; }),
          m: lv.toolbox.map(function (t, i) {
            var s = lv.solution[i];
            return [typeId(t.type), t.color, s.x, s.y, s.dir];
          })
        });
      });
    } catch (e) { return e.message; }
    var id = 'custom-' + Date.now();
    store.custom.push({ id: id, name: data.name || 'Imported pack', desc: 'imported', levels: levels });
    save(); buildPacks();
    open(packIndex(id), 0);
  }
  function typeId(name) {
    if (!(name in E.T)) throw new Error('unknown piece type "' + name + '"');
    return E.T[name];
  }

  // ---- wiring ----

  function keys(e) {
    if (e.target.closest('input, textarea, select, dialog')) return;
    if (App.mode === 'edit') { App.editor.key(e); return; }
    var k = e.key;
    if (k === 'q' || k === 'Q') turn(-1);
    else if (k === 'e' || k === 'E') turn(1);
    else if (k === 'Delete' || k === 'Backspace') takeBack();
    else if (k === 'Escape') { S.sel = null; render(); }
    else if (k === 'ArrowLeft') move(-1, 0);
    else if (k === 'ArrowRight') move(1, 0);
    else if (k === 'ArrowUp') move(0, -1);
    else if (k === 'ArrowDown') move(0, 1);
    else return;
    e.preventDefault();
  }

  function init() {
    buildPacks();
    $('board').addEventListener('click', function (e) {
      var c = cellAt(e, this);
      if (!c) return;
      if (App.mode === 'edit') App.editor.tap(c[0], c[1]);
      else tapPlay(c[0], c[1]);
    });
    $('rotL').onclick = function () { turn(-1); };
    $('rotR').onclick = function () { turn(1); };
    $('takeBack').onclick = takeBack;
    $('resetBtn').onclick = reset;
    $('backToEditor').onclick = function () { App.editor.resume(); };
    $('hint').onclick = function () { this.classList.toggle('open'); };
    $('menuBtn').onclick = drawer;
    $('drawerClose').onclick = function () { $('drawer').hidden = true; };
    $('prevBtn').onclick = function () { var n = neighbour(-1); if (n) open(n[0], n[1]); };
    $('nextBtn').onclick = function () { var n = neighbour(1); if (n) open(n[0], n[1]); };
    $('moreBtn').onclick = function (e) {
      e.stopPropagation();
      if ($('moreMenu').hidden) moreMenu(); else $('moreMenu').hidden = true;
    };
    document.addEventListener('click', function (e) {
      if (!$('moreMenu').hidden && !e.target.closest('#moreMenu')) $('moreMenu').hidden = true;
    });
    document.addEventListener('keydown', keys);
    var last = store.last && packIndex(store.last.id);
    if (last >= 0 && store.last.li < packs[last].levels.length && !locked(last)) open(last, store.last.li);
    else open(0, 0);
  }

  var App = root.LaserApp = {
    mode: 'play', store: store, save: save, $: $,
    packs: function () { return packs; }, buildPacks: buildPacks, packIndex: packIndex,
    open: open, showPanels: showPanels, header: header, textDialog: textDialog, importDialog: importDialog,
    // play a level from the editor; the editor comes back with resume()
    test: function (level) { start(level); S.testing = level; render(); },
    current: function () { return { pi: S.pi, li: S.li, level: S.level, testing: S.testing }; },
    editor: null
  };
  document.addEventListener('DOMContentLoaded', init);
})(this);
