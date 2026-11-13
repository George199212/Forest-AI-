const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.resolve(__dirname,'../assets/review-satellite.js'),'utf8');
class Element {
  constructor(){this.children=[];this.style={};this.isConnected=true;this.events={};this._text='';this.value='2024-06-01';}
  set textContent(value){this._text=value;this.children=[];}get textContent(){return this._text+this.children.map(n=>n.textContent||'').join(' ');}
  appendChild(value){this.children.push(value);return value;}append(...values){values.forEach(v=>this.appendChild(v));}
  replaceChildren(...values){this.children=values;this._text='';}
  addEventListener(name,fn){this.events[name]=fn;}
}
const dateFrom=new Element(),dateTo=new Element();
const requests=[];
let metadata={available:true,sector:'FIELD-TEST-01',product:'true_color',date_window:{from:'2026-09-01',to:'2026-09-30'},acquisition_date:'2026-09-14'};
const context={URLSearchParams,document:{readyState:'loading',addEventListener(){},createElement(){return new Element();},getElementById(id){return {'sat-date-from':dateFrom,'sat-date-to':dateTo}[id];}},
 window:{ForestInstance:{readOnly:true}},fetch:async url=>{requests.push(url);return {ok:true,json:async()=>metadata};}};
vm.createContext(context);vm.runInContext(source,context);
const layer=context.window.ForestReviewSatellite;
assert.equal(layer.caption(metadata),'Copernicus Sentinel-2 L2A · true colour · 2026-09-14 · 10 m resolution · contains modified Copernicus Sentinel data 2026');
assert(layer.caption({...metadata,acquisition_date:null}).includes('2026-09-01 – 2026-09-30'));
(async()=>{
 const target=new Element();await layer.render(target,'FIELD-TEST-01','image','sat');
 assert.equal(dateFrom.value,'2026-09-01');assert.equal(dateTo.value,'2026-09-30');assert(dateFrom.disabled && dateTo.disabled);
 const img=target.children[0].children[0];
 assert.equal(img.src,'/api/satellite/image/FIELD-TEST-01?date_from=2026-09-01&date_to=2026-09-30');
 assert(target.textContent.includes('contains modified Copernicus Sentinel data 2026'));
 assert(target.textContent.includes('Individual tree changes are below Sentinel-2 resolution'));
 img.events.error();assert(target.textContent.includes('Satellite image not available in review mode'));
 metadata={available:false};await layer.render(target,'FIELD-TEST-01','ndvi','sat');
 assert(target.textContent.includes('Satellite image not available in review mode'));assert(!target.textContent.includes('Error'));
 assert.equal(dateFrom.value,'');
 assert(requests.every(url=>url.startsWith('/api/review/satellite-cache/')));
 const normal={window:{ForestInstance:{readOnly:false}}};vm.createContext(normal);vm.runInContext(source,normal);assert(!normal.window.ForestReviewSatellite);
 console.log('Review-only activation, captions, attribution, cached query dates and neutral misses pass.');
})().catch(error=>{console.error(error);process.exitCode=1;});
