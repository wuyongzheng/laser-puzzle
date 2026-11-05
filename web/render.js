// SVG drawing of boards and pieces. Squares are 1 unit; a piece is drawn facing north in a
// unit square centred on (0, 0) and turned by dir * 45 degrees. Each shape follows its rule in
// engine.js: a reflector is a mirror along its axis with the silvered face to the west, a bender
// is a mirror turned -22.5 degrees (its turns are reflections about that axis), and so on.
(function (root) {
  'use strict';
  var E = root.LaserEngine, T = E.T, N = E.N;

  var RGB = ['#555', '#ff4040', '#3fe04f', '#ffe040', '#4a6cff', '#ff4dff', '#40f0ff', '#ffffff'];
  var MIRROR = '#e8ecf4', BACK = '#6a6a78', BODY = '#3a3a46', GOLD = '#e6be3c';

  function colour(c) { return RGB[c & 7]; }

  function mirror(back) {
    return '<rect x="-0.07" y="-0.4" width="0.08" height="0.8" fill="' + MIRROR + '"/>' +
      (back ? '<rect x="0.01" y="-0.4" width="0.07" height="0.8" fill="' + BACK + '"/>' : '');
  }

  // the piece's own shape, north up, without its square
  function shape(type, c) {
    switch (type) {
      case T.wall: return '<rect x="-0.47" y="-0.47" width="0.94" height="0.94" rx="0.04" fill="#62626e"/>';
      case T.laser:
        return '<rect x="-0.34" y="-0.3" width="0.68" height="0.68" rx="0.12" fill="' + BODY + '" stroke="' + colour(c) + '" stroke-width="0.07"/>' +
          '<rect x="-0.09" y="-0.47" width="0.18" height="0.22" fill="' + colour(c) + '"/>' +
          '<circle cx="0" cy="0.04" r="0.1" fill="' + colour(c) + '"/>';
      case T.reflector: return mirror(true);
      case T.dual_reflector: return mirror(false) + '<rect x="0.01" y="-0.4" width="0.07" height="0.8" fill="' + MIRROR + '"/>';
      case T.bender: return '<g transform="rotate(-22.5)">' + mirror(true) + '</g>';
      case T.quad_bender: return '<g transform="rotate(-22.5)">' + mirror(false) +
        '<rect x="0.01" y="-0.4" width="0.07" height="0.8" fill="' + MIRROR + '"/></g>';
      case T.splitter:
        return '<rect x="-0.05" y="-0.4" width="0.1" height="0.8" fill="' + MIRROR + '" opacity="0.55"/>' +
          '<line x1="0" y1="-0.4" x2="0" y2="0.4" stroke="' + MIRROR + '" stroke-width="0.03" stroke-dasharray="0.08 0.06"/>';
      case T.filter:
        return '<rect x="-0.09" y="-0.38" width="0.18" height="0.76" rx="0.03" fill="' + colour(c) + '" opacity="0.8" stroke="#ddd" stroke-width="0.03"/>';
      case T.doppler:   // lies along the beam (rel 2/6); light shifts to the next band the way it travels
        return '<rect x="-0.42" y="-0.15" width="0.84" height="0.3" rx="0.15" fill="#222" stroke="#ddd" stroke-width="0.04"/>' +
          '<rect x="-0.33" y="-0.08" width="0.2" height="0.16" fill="' + RGB[4] + '"/>' +
          '<rect x="-0.1" y="-0.08" width="0.2" height="0.16" fill="' + RGB[2] + '"/>' +
          '<rect x="0.13" y="-0.08" width="0.2" height="0.16" fill="' + RGB[1] + '"/>';
      case T.prism:
        return '<path d="M0 -0.38 L0.35 0.3 L-0.35 0.3 Z" fill="rgba(220,230,255,0.25)" stroke="#e8ecf4" stroke-width="0.05" stroke-linejoin="round"/>';
      case T.tangler:   // takes light only from the west side (rel 2), sends twins north and south
        return '<path d="M0 -0.44 L0 0.44 M-0.1 -0.32 L0 -0.44 L0.1 -0.32 M-0.1 0.32 L0 0.44 L0.1 0.32" stroke="#c9a0ff" stroke-width="0.05" fill="none"/>' +
          '<path d="M-0.47 0 H-0.2" stroke="#c9a0ff" stroke-width="0.06"/>' +
          '<path d="M-0.26 -0.09 L-0.13 0 L-0.26 0.09 Z" fill="#c9a0ff"/>' +
          '<circle r="0.13" fill="#2a2a40" stroke="#c9a0ff" stroke-width="0.05"/>';
      case T.target: return '';                       // drawn with its light, see target()
      case T.conduit:
        return '<rect x="-0.4" y="-0.4" width="0.8" height="0.8" fill="none" stroke="#8c8c9a" stroke-width="0.04"/>' +
          '<path d="M-0.14 -0.47 V0.47 M0.14 -0.47 V0.47" stroke="#8c8c9a" stroke-width="0.05"/>';
      case T.teleporter: case T.mobile_teleporter:
        return '<circle r="0.32" fill="none" stroke="#b07cff" stroke-width="0.05"/>' +
          '<circle r="0.2" fill="none" stroke="#b07cff" stroke-width="0.05"/>' +
          '<circle r="0.08" fill="#b07cff"/>';
      case T.multi_filter:
        return '<circle r="0.36" fill="#222" stroke="#999" stroke-width="0.03"/>' +
          '<path d="M0 -0.32 V0.32" stroke="' + RGB[1] + '" stroke-width="0.07"/>' +
          '<path d="M0.226 -0.226 L-0.226 0.226" stroke="' + RGB[2] + '" stroke-width="0.07"/>' +
          '<path d="M-0.32 0 H0.32" stroke="' + RGB[4] + '" stroke-width="0.07"/>' +
          '<path d="M-0.226 -0.226 L0.226 0.226" stroke="' + RGB[7] + '" stroke-width="0.07"/>';   // passes every colour
      case T.twister:
        return '<path d="M0.26 0.15 A0.3 0.3 0 1 1 0.15 -0.26" fill="none" stroke="#7fd0ff" stroke-width="0.07"/>' +
          '<path d="M0.02 -0.36 L0.2 -0.27 L0.06 -0.12 Z" fill="#7fd0ff"/>';
      case T.complementor:
        return '<circle r="0.33" fill="#eee"/><path d="M0 -0.33 A0.33 0.33 0 0 1 0 0.33 Z" fill="#111"/>' +
          '<path d="M0 -0.45 V-0.33 M0 0.33 V0.45 M-0.45 0 H-0.33 M0.33 0 H0.45" stroke="#eee" stroke-width="0.06"/>';
      case T.logic_gate: case T.primary_logic_gate:
        return '<path d="M-0.3 0.34 V0 A0.3 0.3 0 0 1 0.3 0 V0.34 Z" fill="' + BODY + '" stroke="#ffb347" stroke-width="0.05"/>' +
          '<path d="M0 -0.3 V-0.47" stroke="#ffb347" stroke-width="0.07"/>' +
          '<path d="M-0.42 0.46 L-0.22 0.26 M0.42 0.46 L0.22 0.26" stroke="#ffb347" stroke-width="0.05"/>' +
          (type === T.primary_logic_gate ? '<circle cy="0.12" r="0.08" fill="#ffb347"/>' : '');
      case T.starburst:
        return '<path d="M0 -0.42 L0.09 -0.09 L0.42 0 L0.09 0.09 L0 0.42 L-0.09 0.09 L-0.42 0 L-0.09 -0.09 Z" fill="#ffd27f"/>' +
          '<path d="M0.25 -0.25 L-0.25 0.25 M-0.25 -0.25 L0.25 0.25" stroke="#ffd27f" stroke-width="0.05"/>';
      case T.occupied: return '';
    }
    return '<text font-size="0.4" text-anchor="middle" dy="0.14" fill="#fff">?</text>';
  }

  function target(c, lit) {
    var ring = c ? colour(c) : '#9a9aa6';
    var s = '<circle r="0.32" fill="none" stroke="' + ring + '" stroke-width="0.08"' + (c ? '' : ' stroke-dasharray="0.12 0.08"') + '/>';
    if (lit === c) s += '<circle r="0.15" fill="' + ring + '"/>';
    else if (lit) s += '<circle r="0.13" fill="none" stroke="' + colour(lit) + '" stroke-width="0.05"/>';
    return s;
  }

  // one piece in its square; opts.movable draws the toolbox frame
  function piece(type, d, c, opts) {
    opts = opts || {};
    var s = '';
    var framed = opts.movable || (type !== T.wall && type !== T.target && type !== T.occupied && type !== T.conduit);
    if (framed) {
      s += '<rect x="-0.44" y="-0.44" width="0.88" height="0.88" rx="0.12" fill="' + (opts.movable ? '#34343f' : '#2b2b33') +
        '" stroke="' + (opts.movable ? GOLD : '#4a4a55') + '" stroke-width="' + (opts.movable ? 0.05 : 0.03) + '"/>';
    }
    if (type === T.target) return s + target(c, opts.lit === undefined ? -1 : opts.lit);
    if (type === T.wall) d = 0;     // a wall's stored direction means nothing (RULES.md section 3)
    return s + '<g transform="rotate(' + (d * 45) + ')">' + shape(type, c) + '</g>';
  }

  // a small standalone SVG for buttons
  function icon(type, c, d) {
    var body = type === T.occupied ? '<rect x="-0.44" y="-0.44" width="0.88" height="0.88" fill="#3a3a48" stroke="#555" stroke-width="0.03" stroke-dasharray="0.1 0.06"/>'
      : piece(type, d || 0, c, { movable: false, lit: c });
    return '<svg viewBox="-0.5 -0.5 1 1" aria-hidden="true">' + body + '</svg>';
  }

  // whole board: pieces = [[type, x, y, dir, color, movable]], b = traced engine board
  function board(pieces, b, opts) {
    opts = opts || {};
    var s = '<rect x="-0.25" y="-0.25" width="' + (N + 0.5) + '" height="' + (N + 0.5) + '" fill="#1f1f26"/>';
    var grid = '';
    for (var i = 0; i <= N; i++) grid += 'M' + i + ' 0V' + N + 'M0 ' + i + 'H' + N;
    s += '<path d="' + grid + '" stroke="#2e2e38" stroke-width="0.03"/>';
    pieces.forEach(function (p) {
      if (p[0] === T.occupied) s += '<rect x="' + (p[1] + 0.04) + '" y="' + (p[2] + 0.04) + '" width="0.92" height="0.92" fill="#30303b"/>';
    });
    if (opts.highlight) {
      opts.highlight.forEach(function (h) {
        s += '<rect x="' + (h[0] + 0.03) + '" y="' + (h[1] + 0.03) + '" width="0.94" height="0.94" fill="none" stroke="' + h[2] + '" stroke-width="0.06" rx="0.12"/>';
      });
    }
    // beams: from each square's centre one step along every direction light leaves it. Light
    // running both ways along one step (red east, blue west) is drawn once, in the mixed colour.
    var beams = '';
    for (var y = 0; y < N; y++) {
      for (var x = 0; x < N; x++) {
        var out = E.at(b, x, y).out;
        for (var k = 0; k < 8; k++) {
          var nx = x + E.DX[k], ny = y + E.DY[k];
          var inside = nx >= 0 && nx < N && ny >= 0 && ny < N;
          var back = inside ? E.at(b, nx, ny).out[(k + 4) & 7] : 0;
          if (k >= 4 && back) continue;            // drawn from the other square, with this light
          var c = out[k] | back;
          if (c) {
            beams += '<line x1="' + (x + 0.5) + '" y1="' + (y + 0.5) + '" x2="' + (nx + 0.5) + '" y2="' + (ny + 0.5) +
              '" stroke="' + colour(c) + '"/>';
          }
        }
      }
    }
    s += '<g stroke-width="0.09" stroke-linecap="round" opacity="0.9">' + beams + '</g>';
    pieces.forEach(function (p) {
      if (p[0] === T.occupied) return;
      var lit = p[0] === T.target ? E.lit(E.at(b, p[1], p[2])) : undefined;
      s += '<g transform="translate(' + (p[1] + 0.5) + ' ' + (p[2] + 0.5) + ')">' + piece(p[0], p[3], p[4], { movable: p[5], lit: lit }) + '</g>';
    });
    if (opts.selected) {
      s += '<rect x="' + (opts.selected[0] + 0.02) + '" y="' + (opts.selected[1] + 0.02) + '" width="0.96" height="0.96" rx="0.14" fill="none" stroke="#fff" stroke-width="0.07"/>';
    }
    return s;
  }

  root.LaserRender = { RGB: RGB, colour: colour, piece: piece, icon: icon, board: board };
})(this);
