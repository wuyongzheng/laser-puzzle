// Checks engine.js against light computed by tools/sim.py (the reference), and that every
// episode level's stored solution wins.
//   cd tools && ../.venv/bin/python export_web.py --golden /tmp/golden.json
//   node web/test/engine_test.js /tmp/golden.json
'use strict';
var fs = require('fs');
var E = require('../engine.js');

var cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
var bad = 0;
cases.forEach(function (c) {
  var b = E.trace(E.makeBoard(c.pieces));
  var cells = b.map(function (cell) { return cell.inc.join('') + cell.out.join(''); }).join('');
  var won = E.won(b);
  // every episode level's stored solution must win
  if (/^ep\d+ .* solved$/.test(c.name) && !won) {
    bad += 1;
    console.log('NOT WON ' + c.name);
  }
  if (cells !== c.cells || won !== c.won) {
    bad += 1;
    if (bad <= 10) {
      var i = 0;
      while (cells[i] === c.cells[i]) i++;
      var sq = Math.floor(i / 16);
      console.log('MISMATCH ' + c.name + ': won ' + won + '/' + c.won + ', first difference at (' +
                  (sq % 15) + ',' + Math.floor(sq / 15) + ')');
    }
  }
});
console.log(cases.length + ' cases, ' + bad + ' mismatches');
process.exit(bad ? 1 : 0);
