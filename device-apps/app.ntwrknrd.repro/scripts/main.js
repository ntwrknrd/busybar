// Diagnostic only: no Stocks files, quote cache, or network settings are changed.
const APP_ID = "app.ntwrknrd.repro";
const PHASES = [
    {name:"BOTH 24FPS",animation:"reveal24.anim",network:true},
    {name:"ANIM ONLY",animation:"reveal24.anim",network:false},
    {name:"FETCH ONLY",animation:null,network:true},
    {name:"BOTH 6FPS",animation:"reveal6.anim",network:true},
    {name:"CACHE 24FPS",animation:"reveal24.anim",network:true,cache:true},
    {name:"REBUILD 24FPS",animation:"reveal24.anim",network:true,rebuild:true}
];
const PHASE_MS = 180000;
const START_PHASE = 0;
let phaseIndex=START_PHASE, phaseStart=Date.now(), drawing=false, fetching=false;
let draws=0, replies=0, failures=0, lastDraw=0, lastReveal=0, lastFetch=0;
let done=false;
// Fixed bitmap normally; the final phase repeats this allocation/work each draw.
function buildBitmap() {
    const pixels=[];
    for(let i=0;i<72*16;i++)pixels.push(".");
    for(let x=28;x<72;x++)pixels[(15-Math.floor((x-28)*15/43))*72+x]="G";
    let result="! XPM2\n72 16 2 1\n. c #000000\nG c #32D17C\n";
    for(let y=0;y<16;y++)result+=pixels.slice(y*72,y*72+72).join("")+"\n";
    return result;
}
const bitmap=buildBitmap();
function log(s) {console.info("REPRO "+s);}
function text(id,s,y,display) {
    return {id:id,type:"text",text:s,x:0,y:y,font:"small",color:"#FFFFFFFF",
        align:"top_left",display:display,timeout:30};
}
function draw(now, phase) {
    if(drawing || now-lastDraw<5000)return;
    drawing=true;lastDraw=now;
    if(phase.cache) {
        try{JSON.parse(localStorage.getItem("probe"));}
        catch(e){failures++;log("cache read failed "+String(e));}
    }
    const elements=[{id:"chart",type:"xpmbitmap",data:phase.rebuild?buildBitmap():bitmap,x:0,y:0,align:"top_left",timeout:30,z_index:0},
        text("mode",phase.name,0,"back"),text("count","Draw "+draws+" Fetch "+replies,20,"back"),
        text("time","Seconds "+Math.floor((now-phaseStart)/1000),40,"back"),
        text("errors","Errors "+failures,60,"back")];
    if(phase.animation && now-lastReveal>=10000) {
        lastReveal=now;
        elements.push({id:"reveal",type:"animation",path:"scripts/"+phase.animation,
            x:28,y:0,z_index:1,align:"top_left",loop:false,
            timeout:phase.animation==="reveal6.anim"?5:2});
    }
    fetch("http://127.0.0.1/api/display/draw",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({application_name:APP_ID,priority:50,elements:elements})})
    .then(function(r){return r.json();}).then(function(r){
        if(r.result!=="OK")throw new Error("Display rejected");draws++;
    }).catch(function(e){failures++;log("draw failed "+String(e));})
    .then(function(){drawing=false;});
}
function quote(now, phase) {
    if(fetching || now-lastFetch<5000)return;
    fetching=true;lastFetch=now;
    fetch("https://query2.finance.yahoo.com/v8/finance/chart/AAPL?interval=5m&range=1d",
        {headers:{"User-Agent":"busybar/0.1","Accept":"application/json"}})
    .then(function(r){return r.json();}).then(function(body){
        if(!body.chart || body.chart.error || !body.chart.result[0])throw new Error("Bad quote");
        if(phase.cache) {
            const result=body.chart.result[0];
            try {
                localStorage.setItem("probe",JSON.stringify({time:now,
                    price:result.meta.regularMarketPrice,
                    points:result.indicators.quote[0].close.slice(0,72)}));
            } catch(e){failures++;log("cache write failed "+String(e));}
        }
        replies++;
    }).catch(function(e){failures++;log("fetch failed "+String(e));})
    .then(function(){fetching=false;});
}
function tick() {
    if(done)return;
    const now=Date.now();
    if(now-phaseStart>=PHASE_MS) {
        // Drain outstanding operations before switching; do not mix phases.
        if(drawing || fetching)return;
        log("END "+PHASES[phaseIndex].name+" draws="+draws+" replies="+replies+" errors="+failures);
        phaseIndex++;
        if(phaseIndex===PHASES.length){done=true;log("COMPLETE");lastDraw=0;draw(now,{name:"COMPLETE",animation:null});return;}
        phaseStart=now;draws=0;replies=0;failures=0;lastDraw=0;lastReveal=0;lastFetch=0;
        log("BEGIN "+PHASES[phaseIndex].name);
    }
    const phase=PHASES[phaseIndex];
    draw(now,phase);
    if(phase.network)quote(now,phase);
}
log("BEGIN "+PHASES[START_PHASE].name);
tick();
setInterval(tick,250);
setInterval(function(){if(!done)log("LIVE "+PHASES[phaseIndex].name+" draws="+draws+" replies="+replies+" errors="+failures);},30000);
