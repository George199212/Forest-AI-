'use strict';
// Display precision of the "not fully inside its VZD land unit" reason: never 100% when < 100.
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../assets/forest-map.js'),'utf8');
const grab=name=>{const m=src.match(new RegExp('function '+name+'\\([^)]*\\)\\{.*?\\}\\n','s'));assert.ok(m,name);return m[0];};
function make(lang){const s={lang};const words={en:{outsideM2:' · {a} m² outside'},lv:{outsideM2:' · {a} m² ārpus'}};const t=k=>words[lang][k];const fmt=n=>Number(n).toLocaleString(lang==='en'?'en-US':'lv-LV');
 return new Function('s','t','fmt',[grab('percentBelow100'),grab('areaM2'),grab('overlapText'),grab('outsideText')].join('\n')+';return {percentBelow100,overlapText:v=>overlapText(v)+outsideText(v)};')(s,t,fmt);}
test('partial containment never shows 100',()=>{const {percentBelow100}=make('en');
 assert.equal(percentBelow100(99.987),'99.99');assert.equal(percentBelow100(99.99999324055673),'99.99999');assert.equal(percentBelow100(99.9999999999185),'99.9999999999');assert.equal(percentBelow100(99.996),'99.996');assert.equal(percentBelow100(100),'100');});
test('outside area in m² (EN / LV)',()=>{
 assert.equal(make('en').overlapText({overlap_percent:99.987,outside_area_m2:3.2}),'99.99% · 3.20 m² outside');
 assert.equal(make('en').overlapText({overlap_percent:99.99999324,outside_area_m2:0.000185}),'99.99999% · < 0.01 m² outside');
 assert.equal(make('lv').overlapText({overlap_percent:99.8568,outside_area_m2:9.52}),'99,86% · 9,52 m² ārpus');
 assert.equal(make('lv').overlapText({overlap_percent:0,outside_area_m2:1835.25}),'0,00% · 1835,3 m² ārpus'.replace('1835,3',(1835.3).toLocaleString('lv-LV',{minimumFractionDigits:1})));
 assert.equal(make('en').overlapText({overlap_percent:null}),'—');});
test('review reason template puts the outside area after the inside share',()=>{
 assert.ok(src.includes('({overlap} iekšā{outside})'));assert.ok(src.includes('({overlap} inside{outside})'));
 assert.ok(src.includes(".replace('{overlap}',overlapText(v)).replace('{outside}',outsideText(v))"));});
