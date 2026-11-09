'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../assets/lvm-geodata.js'),'utf8');
test('existing LVM page delegates local vectors to the dedicated module before live capability discovery',async()=>{
 const load=source.slice(source.indexOf('async function loadLvmLayers()'),source.indexOf('function renderLvmLayers()'));
 assert(!load.includes('refreshLvmCapabilities()'));assert.match(load,/await loadVmdTestCompartments/);
 assert.match(load,/tile.openstreetmap.org/);assert.equal((load.match(/L\.map\(/g)||[]).length,1);
 const calls=[],map={existing:true};const ctx=vm.createContext({window:{VmdLocalDataset:{attach:async m=>calls.push(m)}}});vm.runInContext(source,ctx);
 await ctx.loadVmdTestCompartments(map);assert.deepEqual(calls,[map]);
});
test('shared preview and import dispatch to local data without requesting live services',async()=>{
 let preview=0,imports=0;const ctx=vm.createContext({window:{VmdLocalDataset:{active:true,preview(){preview++;},importSelected(){imports++;}}},fetch(){throw Error('No live request allowed');}});
 vm.runInContext(source,ctx);await ctx.importLvmFeatures();assert.equal(imports,1);
});
test('page labels local data independently and retains existing WMS module',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
 assert.match(html,/VMD meža nogabali/);assert.match(html,/VMD datu avots/);
 assert.match(html,/VMD atvērtie dati/);assert.match(html,/vmd-production.js/);assert.match(html,/lvm-wms-map.js/);assert.match(html,/ForestLvmWms.attach\(map\)/);
});
