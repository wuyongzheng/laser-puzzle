// The .lvl sketch format of tools/studio.py, for import and export.
//
//   title: Twins            header lines "key: value"
//   ---
//   L 7 13 0 r              one piece per line: [*]TYPE X Y DIR COLOR
//   *Q 7 7 6 k              '*' marks a toolbox piece; its place is the intended solution
//   T 11 7 0 ?              '?' (targets): the colour the intended solution gives it
//
// A level in the player is {t: title, x: text, b: [[type, x, y, dir, color]],
// m: [[type, color, x, y, dir]], meta: {other header keys}}, like web/episodes.js. Every level is
// played by the Laser Puzzle rules.
(function (root) {
  'use strict';
  var E = root.LaserEngine || (typeof require !== 'undefined' && require('./engine.js'));

  var GLYPHS = {
    '#': 'wall', 'L': 'laser', 'R': 'reflector', 'B': 'bender', 'F': 'filter', 'P': 'prism',
    'D': 'doppler', 'S': 'splitter', 'Q': 'tangler', 'T': 'target', 'C': 'conduit',
    'X': 'teleporter', 'M': 'multi_filter', 'W': 'twister', 'K': 'complementor',
    'G': 'logic_gate', 'x': 'mobile_teleporter', 'r': 'dual_reflector', 'b': 'quad_bender',
    'o': 'occupied', 'g': 'primary_logic_gate', 'Z': 'starburst'
  };
  var COLORS = 'krgybmcw';
  var GLYPH_OF = {};
  Object.keys(GLYPHS).forEach(function (g) { GLYPH_OF[E.T[GLYPHS[g]]] = g; });

  // text -> {level, problems}; throws Error on a line it can't read
  function parse(text) {
    var meta = {}, pieces = [], body = false;
    text.split(/\r?\n/).forEach(function (raw, n) {
      var line = raw.split('%')[0].trim();
      if (!line) return;
      if (!body) {
        if (line === '---') body = true;
        else if (line.indexOf(':') > 0) {
          var k = line.slice(0, line.indexOf(':')).trim();
          meta[k] = line.slice(line.indexOf(':') + 1).trim();
        }
        return;
      }
      var star = line[0] === '*';
      var f = line.replace(/^\*/, '').split(/\s+/);
      if (f.length !== 5) throw new Error('line ' + (n + 1) + ': expected "[*]TYPE X Y DIR COLOR", got "' + raw.trim() + '"');
      var name = GLYPHS[f[0]] || f[0];
      if (!(name in E.T) || name === 'empty') throw new Error('line ' + (n + 1) + ': unknown piece "' + f[0] + '"');
      var x = +f[1], y = +f[2], d = +f[3];
      if (!(x >= 0 && x < E.N && y >= 0 && y < E.N && d >= 0 && d < 8 && Math.floor(x) === x && Math.floor(y) === y))
        throw new Error('line ' + (n + 1) + ': position or direction out of range');
      var c = f[4] === '?' ? null : COLORS.indexOf(f[4]);
      if (c === -1) throw new Error('line ' + (n + 1) + ': unknown colour "' + f[4] + '" (use one of ' + COLORS + ' or ?)');
      pieces.push({ type: E.T[name], x: x, y: y, d: d, c: c, mov: star });
    });
    return fromPieces(meta, pieces);
  }

  // editor pieces {type, x, y, d, c (null: '?'), mov} -> {level, problems}
  function fromPieces(meta, pieces) {
    var problems = [], seen = {};
    pieces.forEach(function (p) {
      var k = p.x + ',' + p.y;
      if (seen[k]) problems.push('two pieces on (' + k + ')');
      seen[k] = true;
    });
    var colours = resolve(pieces);
    var level = { t: meta.title || '', x: meta.text || '', b: [], m: [], meta: {} };
    Object.keys(meta).forEach(function (k) {
      if (k !== 'title' && k !== 'text') level.meta[k] = meta[k];
    });
    pieces.forEach(function (p, i) {
      var c = colours[i];
      if (c === null) { c = 0; problems.push('target (' + p.x + ',' + p.y + ') marked ? gets no light; it would be black'); }
      if (p.mov) level.m.push([p.type, c, p.x, p.y, p.d]);
      else level.b.push([p.type, p.x, p.y, p.d, c]);
    });
    level.m.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });   // studio's toolbox order
    return { level: level, problems: problems };
  }

  // colours with '?' targets filled in from the light of the intended solution (null if unlit)
  function resolve(pieces) {
    var known = pieces.filter(function (p) { return !(p.type === E.T.target && p.c === null); });
    var b = E.trace(E.makeBoard(known.map(function (p) { return [p.type, p.x, p.y, p.d, p.c || 0]; })));
    return pieces.map(function (p) {
      if (p.c !== null) return p.c;
      var v = E.lit(E.at(b, p.x, p.y));
      return v || null;
    });
  }

  // level -> editor pieces (the toolbox at its stored solution)
  function toPieces(level) {
    return level.b.map(function (p) { return { type: p[0], x: p[1], y: p[2], d: p[3], c: p[4], mov: false }; })
      .concat(level.m.map(function (p) { return { type: p[0], x: p[2], y: p[3], d: p[4], c: p[1], mov: true }; }));
  }

  // header + pieces -> text; c === null is written as '?'
  function serialize(meta, pieces) {
    var lines = ['title: ' + oneLine(meta.title), 'text: ' + oneLine(meta.text)];
    Object.keys(meta).forEach(function (k) {
      if (k !== 'title' && k !== 'text' && meta[k] !== undefined && meta[k] !== '')
        lines.push(k + ': ' + oneLine(meta[k]));
    });
    lines.push('---');
    var fixed = pieces.filter(function (p) { return !p.mov; });
    var mov = pieces.filter(function (p) { return p.mov; });
    fixed.concat(mov).forEach(function (p) {
      lines.push((p.mov ? '*' : '') + GLYPH_OF[p.type] + ' ' + p.x + ' ' + p.y + ' ' + p.d + ' ' +
                 (p.c === null ? '?' : COLORS[p.c]));
    });
    return lines.join('\n') + '\n';
  }

  function levelToText(level) {
    var meta = { title: level.t, text: level.x };
    Object.keys(level.meta || {}).forEach(function (k) { meta[k] = level.meta[k]; });
    return serialize(meta, toPieces(level));
  }

  function oneLine(s) { return String(s || '').replace(/\s*\n\s*/g, ' ').trim(); }

  function nameOf(type) {
    for (var k in E.T) if (E.T[k] === type) return k.replace(/_/g, ' ');
    return 'type ' + type;
  }

  var api = { GLYPHS: GLYPHS, COLORS: COLORS, parse: parse, fromPieces: fromPieces, toPieces: toPieces,
              serialize: serialize, levelToText: levelToText, nameOf: nameOf, resolve: resolve };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.LaserLvl = api;
})(this);
