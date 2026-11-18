'use strict';
// Forest Map coordinate search (D6, 2026-11-18): WGS84 "lat, lon" with Latvian decimal comma tolerated.
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../assets/forest-map.js'),'utf8');
const grab=name=>{const m=src.match(new RegExp('function '+name+'\\([^)]*\\)\\{.*?\\}\\n','s'));assert.ok(m,name);return m[0];};
const parse=new Function(grab('parseCoordinates')+';return parseCoordinates;')();
const riga={lat:56.9496,lon:24.1052,inLatvia:true};

test('owner cases: decimal comma with space, dot with comma-space, decimal comma with semicolon',()=>{
 assert.deepEqual(parse('56,9496 24,1052'),riga);
 assert.deepEqual(parse('56.9496, 24.1052'),riga);
 assert.deepEqual(parse('56,9496; 24,1052'),riga);
});
test('other accepted spellings',()=>{
 assert.deepEqual(parse('56.9496,24.1052'),riga);
 assert.deepEqual(parse('56.9496 24.1052'),riga);
 assert.deepEqual(parse('  56,9496, 24,1052  '),riga);
 assert.deepEqual(parse('56.9496;24.1052'),riga);
 assert.deepEqual(parse('56,9496,24,1052'),riga);          // two decimal-comma numbers without spaces
 assert.deepEqual(parse('57 25'),{lat:57,lon:25,inLatvia:true});
});
test('invalid input -> null (never a guessed position)',()=>{
 for(const s of ['','   ','abc','56.9496','56.9496 24.1052 7','56,94,96 24,1052','56.9.4 24.1','56,9496;','N56 E24','1e1 24','56.9496/24.1052'])
  assert.equal(parse(s),null,JSON.stringify(s));
});
test('out of Latvia -> parsed but flagged (search shows the "in Latvia" message)',()=>{
 assert.equal(parse('52.52, 13.405').inLatvia,false);      // Berlin
 assert.equal(parse('24,1052 56,9496').inLatvia,false);    // swapped lat/lon
 assert.equal(parse('-56.9 24.1').inLatvia,false);
});
test('goCoordinates uses the parser and keeps the Latvia check',()=>{
 const go=grab('goCoordinates');
 assert.match(go,/parseCoordinates\(dom\('coordinates'\)\.value\)/);
 assert.match(go,/!p\|\|!p\.inLatvia\)\{message\(t\('invalidCoords'\)\)/);
 assert.doesNotMatch(src,/split\(\/\[,;\\s\]\+\/\)/);       // the old splitter is gone
});
