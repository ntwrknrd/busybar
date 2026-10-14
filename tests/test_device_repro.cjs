const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const root=__dirname+'/../device-apps/app.ntwrknrd.repro';
const source=fs.readFileSync(root+'/scripts/main.js','utf8');
const settle=()=>new Promise(r=>setImmediate(r));
function boot(){
 const s={now:1800000000000,logs:[],draws:[],requests:0,cache:{},writes:0};
 class Clock extends Date{static now(){return s.now;}}
 s.ctx=vm.createContext({Date:Clock,console:{info:l=>s.logs.push(l)},setInterval(){},localStorage:{getItem:k=>s.cache[k]||null,setItem:(k,v)=>{s.cache[k]=v;s.writes++;}},fetch:(url,o)=>{
  if(o.method){s.draws.push(JSON.parse(o.body));return Promise.resolve({json:async()=>({result:'OK'})});}
  s.requests++;if(s.hold)return new Promise(r=>s.finish=r);
  return Promise.resolve({json:async()=>({chart:{result:[{meta:{regularMarketPrice:100},indicators:{quote:[{close:[99,100]}]}}]}})});
 }});vm.runInContext(source,s.ctx);return s;
}
test('six bounded phases keep cache writes isolated and exercise each workload',async()=>{
 const s=boot();await settle();
 for(let phase=0;phase<6;phase++){
  const requests=s.requests,draws=s.draws.length,writes=s.writes;
  for(let i=0;i<35;i++){s.now+=5000;vm.runInContext('tick()',s.ctx);await settle();}
  assert.equal(s.requests>requests,phase!==1);
  assert.equal(s.writes>writes,phase===4);
  assert.equal(s.draws.slice(draws).some(d=>d.elements.some(e=>e.type==='animation')),phase!==2);
  s.now+=5000;vm.runInContext('tick()',s.ctx);await settle();
 }
 assert.ok(s.logs.includes('REPRO COMPLETE'));
 assert.equal(s.logs.filter(l=>l.startsWith('REPRO END ')).length,6);
});
test('phase changes wait for the outstanding quote response',async()=>{
 const s=boot();await settle();s.hold=true;s.now+=5000;vm.runInContext('tick()',s.ctx);await settle();
 s.now+=180000;vm.runInContext('tick()',s.ctx);assert.equal(vm.runInContext('phaseIndex',s.ctx),0);
 s.finish({json:async()=>({chart:{result:[{meta:{regularMarketPrice:100},indicators:{quote:[{close:[99,100]}]}}]}})});await settle();
 vm.runInContext('tick()',s.ctx);assert.equal(vm.runInContext('phaseIndex',s.ctx),1);
});
test('slow asset changes only the frame rate of the original reveal',()=>{
 const original=fs.readFileSync(__dirname+'/../device-apps/app.ntwrknrd.stocks/scripts/reveal.anim');
 const normal=fs.readFileSync(root+'/scripts/reveal24.anim'),slow=fs.readFileSync(root+'/scripts/reveal6.anim');
 assert.deepEqual(normal,original);assert.equal(slow[12],6);slow[12]=24;assert.deepEqual(slow,normal);
});
