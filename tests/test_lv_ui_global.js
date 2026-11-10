'use strict';
// Latvian sidebar labels and lv-LV header time on every page (not only LVM GEO).
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const fnSrc=html.slice(html.indexOf('const geodataNavigationText=new Map();'),html.indexOf('\nfunction nav(id, push=true)'));
const navSrc=html.slice(html.indexOf('function nav(id, push=true) {'),html.indexOf('\nfunction refreshCurrent()'));

function sidebar(labels){
 // Each item: an icon <span> plus one text node, as in index.html.
 return labels.map(text=>({childNodes:[{nodeType:1,textContent:'◈'},{nodeType:3,textContent:' '+text}]}));
}
function make(i18nLang){
 const items=sidebar(['Overview','Objects','Sectors','Risks','GPS Sessions','Truck Reports','Timber','Photos','AI Inspector','Satellite','LVM GEO','Integrations']);
 const groups=sidebar(['Monitor','Operations','AI','Admin']);
 const document={querySelectorAll:sel=>sel==='.sidebar .nav-item,.sidebar .nav-group'?[...items,...groups]:[]};
 const window={ForestI18n:i18nLang?{lang:i18nLang}:undefined};
 const localize=new Function('document','window',fnSrc+';return localizeGeodataNavigation;')(document,window);
 const text=list=>list.map(i=>i.childNodes[1].textContent.trim());
 return {localize,items:()=>text(items),groups:()=>text(groups)};
}

test('nav() localizes the sidebar for every route, not only LVM GEO',()=>{
 assert.match(navSrc,/\n  localizeGeodataNavigation\(true\);/);
 assert.doesNotMatch(navSrc,/localizeGeodataNavigation\(id===/);
});
test('init localizes before opening the first route (deep links to sector/object/risk)',()=>{
 const init=html.slice(html.indexOf('// INIT'));
 assert.ok(init.indexOf('localizeGeodataNavigation(true);')>-1);
 assert.ok(init.indexOf('localizeGeodataNavigation(true);')<init.indexOf('openRoute(initRoute);'));
});
test('Latvian labels applied; repeated calls are idempotent; unknown labels untouched',()=>{
 const m=make();m.localize(true);m.localize(true);
 assert.deepEqual(m.items(),['Pārskats','Objekti','Sektori','Riski','GPS sesijas','Kokvedēju atskaites','Kokmateriāli','Foto','AI inspektors','Satelīts','LVM GEO','Integrācijas']);
 assert.deepEqual(m.groups(),['Monitorings','Operācijas','AI','Administrēšana']);
});
test('client instances with the i18n-lv overlay are left alone',()=>{
 const m=make('lv');m.localize(true);assert.equal(m.items()[0],'Overview');
});
test('header time is lv-LV on every route (nav and object detail)',()=>{
 assert.match(navSrc,/getElementById\('page-sub'\)\.textContent = new Date\(\)\.toLocaleString\('lv-LV'\);/);
 const writes=[...html.matchAll(/getElementById\('page-sub'\)\.textContent = (new Date\(\)\.toLocaleString\([^)]*\))/g)].map(m=>m[1]);
 assert.ok(writes.length>=2);for(const w of writes)assert.equal(w,"new Date().toLocaleString('lv-LV')");
 assert.match(new Date(Date.UTC(2026,10,10,8,30,5)).toLocaleString('lv-LV',{timeZone:'UTC'}),/^10\.11\.2026\.? 08:30:05$/);
});
