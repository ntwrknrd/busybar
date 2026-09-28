const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const root=path.join(__dirname,'../device-apps/app.ntwrknrd.stocks');
const source=fs.readFileSync(root+'/scripts/main.js','utf8');
const epoch=1800000000000;
function payload(symbol='AAPL') {return {chart:{result:[{meta:{symbol,currency:'USD',regularMarketPrice:105,chartPreviousClose:100,regularMarketTime:epoch/1000,currentTradingPeriod:{regular:{start:epoch/1000-3600,end:epoch/1000+3600}},instrumentType:'EQUITY'},timestamp:[1,2,3],indicators:{quote:[{close:[100,null,105]}]}}]}};}
function boot(cache={},bad=false) {
 const s={now:epoch,cache:{...cache},draws:[],urls:[],bad};
 class Clock extends Date {static now(){return s.now;}}
 s.ctx=vm.createContext({Date:Clock,console:{info(){},error(){}},localStorage:{getItem:k=>s.cache[k]||null,setItem:(k,v)=>{if(s.diskFail)throw Error('full');s.cache[k]=v;}},setInterval:f=>s.tick=f,fetch:(url,options)=>{
 if(options&&options.method){s.draws.push(JSON.parse(options.body));return Promise.resolve({json:async()=>({result:'OK'})});}
 s.urls.push(url); if(s.bad)return Promise.reject(Error('offline'));
 const symbol=decodeURIComponent(url.split('/').pop().split('?')[0]);return Promise.resolve({json:async()=>payload(symbol)});
 }});vm.runInContext(source,s.ctx);return s;
}
const settle=()=>new Promise(r=>setImmediate(r));
const run=(s,code)=>vm.runInContext(code,s.ctx);
test('manifest and original watchlist',async()=>{const s=boot();await settle();assert.equal(run(s,'SYMBOLS.length'),31);assert.equal(JSON.parse(fs.readFileSync(root+'/appmeta/manifest.json')).heap_size_kib,256);assert.ok(fs.statSync(root+'/appmeta/manifest.json').size<=512);});
test('direct HTTPS fetch, cache and complete bitmap rendering',async()=>{const s=boot();await settle();assert.match(s.urls[0],/^https:\/\/query2/);const q=JSON.parse(s.cache['quote-v1-AAPL']);assert.equal(q.price,105);assert.deepEqual(q.points,[100,105]);assert.equal(run(s,'state(quotes.AAPL,Date.now())'),'OPEN');const bmp=s.draws.at(-1).elements[0].data.split('\n');assert.equal(bmp[1],'72 16 6 1');assert.ok(bmp.slice(8,24).every(l=>l.length===72));});
test('quote rotates every 10 seconds, chart at five seconds',async()=>{const s=boot();await settle();const a=run(s,'front("AAPL",quotes.AAPL,Date.now())');s.now+=5000;assert.notEqual(run(s,'front("AAPL",quotes.AAPL,Date.now())'),a);assert.equal(run(s,'selection(Date.now())'),0);s.now+=5000;assert.equal(run(s,'selection(Date.now())'),1);});
test('closed, delayed, stale and fund states differ',async()=>{const s=boot();await settle();assert.equal(run(s,'state(quotes.AAPL,quotes.AAPL.close)'), 'STALE');run(s,'quotes.AAPL.fetchedAt=quotes.AAPL.close');assert.equal(run(s,'state(quotes.AAPL,quotes.AAPL.close)'),'CLOSED');run(s,'quotes.AAPL.fetchedAt=Date.now(); quotes.AAPL.quoteTime=Date.now()-21*60000');assert.equal(run(s,'state(quotes.AAPL,Date.now())'),'DELAYED');run(s,'quotes.AAPL.fund=true');assert.equal(run(s,'state(quotes.AAPL,Date.now())'),'DAILY NAV');});
test('fund NAV may lack intraday chart, equities may not',async()=>{const s=boot();await settle();const p=payload();p.chart.result[0].meta.instrumentType='MUTUALFUND';delete p.chart.result[0].timestamp;p.chart.result[0].indicators.quote=[{}];s.ctx.body=p;assert.equal(run(s,'parse(body,"AAPL",Date.now()).points.length'),0);p.chart.result[0].meta.instrumentType='EQUITY';assert.throws(()=>run(s,'parse(body,"AAPL",Date.now())'));});
test('invalid, wrong-symbol and future quotes are rejected',async()=>{const s=boot();await settle();for(const mutate of [p=>p.chart.result[0].meta.symbol='MSFT',p=>p.chart.result[0].meta.regularMarketPrice=null,p=>p.chart.result[0].meta.regularMarketTime=epoch/1000+400,p=>p.chart.result[0].meta.chartPreviousClose=0]){const p=payload();mutate(p);s.ctx.body=p;assert.throws(()=>run(s,'parse(body,"AAPL",Date.now())'));}});
test('restart uses marked cache; fetch failure preserves it and recovery clears stale',async()=>{const a=boot();await settle();const s=boot(a.cache,true);await settle();assert.equal(run(s,'state(quotes.AAPL,Date.now())'),'STALE');assert.equal(JSON.parse(s.cache['quote-v1-AAPL']).price,105);s.bad=false;s.now+=60000;run(s,'cursor=0; due.AAPL=0');s.tick();await settle();assert.equal(run(s,'state(quotes.AAPL,Date.now())'),'OPEN');});
test('cache write failure retains quote; corrupted cache is ignored',async()=>{const s=boot({'quote-v1-MSFT':'bad'});s.diskFail=true;await settle();assert.equal(run(s,'quotes.AAPL.price'),105);assert.equal(run(s,'quotes.MSFT'),undefined);});
test('bounds chart samples and renders a flat series',async()=>{const s=boot();await settle();const p=payload();p.chart.result[0].timestamp=Array.from({length:400},(_,i)=>i);p.chart.result[0].indicators.quote[0].close=Array(400).fill(105);s.ctx.body=p;assert.equal(run(s,'parse(body,"AAPL",Date.now()).points.length'),72);run(s,'quotes.AAPL=parse(body,"AAPL",Date.now())');assert.match(run(s,'front("AAPL",quotes.AAPL,Date.now()+5000)'),/G/);});
test('refreshes sequentially without re-fetching fresh symbols',async()=>{const s=boot();await settle();for(let i=1;i<31;i++){s.now+=5000;s.tick();await settle();}assert.equal(s.urls.length,31);s.now+=5000;s.tick();await settle();assert.equal(s.urls.length,31);s.now=epoch+300000;s.tick();await settle();assert.equal(s.urls.length,32);});
