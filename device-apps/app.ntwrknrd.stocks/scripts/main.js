// BUSY Bar 1.2.4. Direct HTTPS, automatic rotation; no host required.
const SYMBOLS = ["AAPL", "AMZN", "AMD", "ANET", "AVGO", "CCJ", "CEG", "CSCO", "DBRG", "DELL", "DLR", "^DJI", "EQIX", "GOOG", "HPE", "IBM", "INTC", "LRCX", "META", "MU", "NVDA", "QTUM", "SMR", "^GSPC", "TSM", "VFIAX", "VIGAX", "VLXVX", "VWUAX", "VBTLX", "VWILX"];
const PIXEL_FONT = {"A":"010101111101101","B":"110101110101110","C":"011100100100011","D":"110101101101110","E":"111100110100111","F":"111100110100100","G":"011100101101011","H":"101101111101101","I":"111010010010111","J":"001001001101010","K":"101101110101101","L":"100100100100111","M":"101111111101101","N":"101111111111101","O":"010101101101010","P":"110101110100100","Q":"010101101111011","R":"110101110101101","S":"011100010001110","T":"111010010010010","U":"101101101101111","V":"101101101101010","W":"101101111111101","X":"101101010101101","Y":"101101010010010","Z":"111001010100111","0":"111101101101111","1":"010110010010111","2":"110001010100111","3":"110001010001110","4":"101101111001001","5":"111100110001110","6":"011100111101111","7":"111001010010010","8":"111101111101111","9":"111101111001110","+":"000010111010000","-":"000000111000000",".":"000000000000010","^":"010101000000000","/":"001001010100100","~":"000000010101000","%":"101001010100101","?":"110001010000010"," ":"000000000000000"};
const APP_ID = "app.ntwrknrd.stocks";
const REFRESH_MS = 5 * 60 * 1000;
const quotes = {};
const due = {};
const failed = {};
let fetching = false, drawing = false, cursor = 0;
let sceneSymbol = null, lastDrawAt = 0;
// Hold the last frame through slow requests; stopped apps still expire.
const DISPLAY_TIMEOUT = 60;
const startedAt = Date.now();

function number(n) { return typeof n === "number" && isFinite(n); }
function valid(q, symbol) {
    return q && q.symbol === symbol && number(q.price) && q.price > 0 &&
        number(q.previous) && q.previous > 0 && number(q.quoteTime) && q.quoteTime > 0 &&
        number(q.fetchedAt) && q.fetchedAt > 0 && number(q.open) && number(q.close) &&
        q.close > q.open && typeof q.currency === "string" && /^[A-Z]{3}$/.test(q.currency) &&
        typeof q.fund === "boolean" && Array.isArray(q.points) && (q.fund || q.points.length > 0) &&
        q.points.length <= 72 && q.points.every(function (n) {return number(n) && n > 0;});
}
function parse(body, symbol, now) {
    if (!body.chart || body.chart.error || !body.chart.result || !body.chart.result[0]) {
        throw new Error("Quote unavailable");
    }
    const result = body.chart.result[0], m = result.meta;
    const raw = result.indicators.quote[0].close || [], times = result.timestamp || [];
    const clean = [];
    for (let i = 0; i < raw.length && i < times.length; i++) {
        if (number(raw[i]) && raw[i] > 0 && number(times[i])) clean.push(raw[i]);
    }
    const points = [];
    for (let i = 0; i < Math.min(72, clean.length); i++) {
        points.push(clean[Math.floor(i * (clean.length-1) / Math.max(1,Math.min(72,clean.length)-1))]);
    }
    const session = m.currentTradingPeriod.regular;
    const q = {symbol:m.symbol, currency:m.currency, price:m.regularMarketPrice,
        previous:m.chartPreviousClose || m.previousClose, quoteTime:m.regularMarketTime*1000,
        fetchedAt:now, open:session.start*1000, close:session.end*1000,
        fund:m.instrumentType === "MUTUALFUND", points:points};
    if (!valid(q,symbol) || q.quoteTime > now+300000) throw new Error("Invalid quote");
    return q;
}
function state(q, now) {
    if (failed[q.symbol] || now < q.fetchedAt || now-q.fetchedAt > REFRESH_MS*3) return "STALE";
    if (q.fund) return "DAILY NAV";
    if (now < q.open || now >= q.close) return "CLOSED";
    return now-q.quoteTime > 20*60000 ? "DELAYED" : "OPEN";
}
function change(q) {return (q.price/q.previous-1)*100;}
function percent(q) {const n=change(q); return (n>=0?"+":"")+n.toFixed(2)+"%";}
function frontPercent(q) {
    const n=change(q), sign=n>=0?"+":"-", a=Math.abs(n);
    return sign+(a>999?"999":a>=100?a.toFixed(0):a>=10?a.toFixed(1):a.toFixed(2))+"%";
}
function selection(now) {return Math.floor((now-startedAt)/10000)%SYMBOLS.length;}
function front(symbol, q, now) {
    const pixels = [];
    for (let i=0;i<72*16;i++) pixels.push(".");
    function dot(x,y,c) {if(x>=0&&x<72&&y>=0&&y<16) pixels[y*72+x]=c;}
    function label(value,x,y,c,scale) {
        for(let n=0;n<value.length;n++) {
            const glyph=PIXEL_FONT[value[n]]||PIXEL_FONT["?"];
            for(let r=0;r<5;r++) for(let col=0;col<3;col++) if(glyph[r*3+col]==="1") {
                for(let dy=0;dy<scale;dy++) for(let dx=0;dx<scale;dx++) dot(x+n*4*scale+col*scale+dx,y+r*scale+dy,c);
            }
        }
    }
    label(symbol,0,0,"W",1);
    if(!q) {
        label(failed[symbol]?"RETRYING":"LOADING",26,0,"Y",1);
        label("YAHOO FINANCE",0,10,"C",1);
    } else {
        const status=state(q,now), c=status==="STALE"?"Y":change(q)>=0?"G":"R";
        label(frontPercent(q),0,11,c,1);
        if(q.points.length < 2) {
            label(q.fund?"DAILY":"NO",28,2,"C",1);
            label(q.fund?"NAV":"CHART",28,10,"C",1);
        } else {
            const min=Math.min.apply(null,q.points), max=Math.max.apply(null,q.points);
            let last=null;
            for(let x=28;x<72;x++) {
                const v=q.points[Math.floor((x-28)*(q.points.length-1)/43)];
                const y=max===min?8:15-Math.round((v-min)/(max-min)*15);
                if(last!==null) for(let j=Math.min(last,y);j<=Math.max(last,y);j++) dot(x,j,c);
                dot(x,y,c);last=y;
            }
        }
    }
    let data="! XPM2\n72 16 6 1\n. c #000000\nW c #FFFFFF\nC c #899BAD\nG c #32D17C\nR c #FF6666\nY c #FFD43B\n";
    for(let y=0;y<16;y++) data+=pixels.slice(y*72,y*72+72).join("")+"\n";
    return data;
}
function text(id,value,y) {return {id:id,type:"text",text:value||" ",x:3,y:y,font:"small",color:"#FFFFFFFF",align:"top_left",display:"back",timeout:DISPLAY_TIMEOUT};}
function elements(now, reveal) {
    const symbol=SYMBOLS[selection(now)], q=quotes[symbol];
    const e=[{id:"front",type:"xpmbitmap",data:front(symbol,q,now),x:0,y:0,z_index:0,align:"top_left",timeout:DISPLAY_TIMEOUT},
        text("source",symbol+" / Yahoo Finance",2)];
    e.push(text("price",q?q.price.toFixed(2)+" "+q.currency+"  "+percent(q):"Waiting for quote",18));
    e.push(text("state",q?state(q,now):failed[symbol]?"Fetch failed; retrying":"Loading watchlist",34));
    e.push(text("stamp",q?"Quote UTC "+new Date(q.quoteTime).toISOString().slice(5,16).replace("T"," "):" ",50));
    e.push(text("range",q&&q.fund?"Daily NAV / prior close":"1D / vs prior close",66));
    if(reveal && q && q.points.length>=2) e.push({id:"reveal",type:"animation",
        path:"scripts/reveal.anim",x:28,y:0,z_index:1,align:"top_left",loop:false,timeout:2});
    return e;
}
function draw() {
    if(drawing)return;
    const now=Date.now(), symbol=SYMBOLS[selection(now)];
    const changed=symbol!==sceneSymbol;
    if(!changed && now-lastDrawAt<5000)return;
    drawing=true;
    fetch("http://127.0.0.1/api/display/draw",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({application_name:APP_ID,priority:50,elements:elements(now,changed)})})
    .then(function(r){return r.json();}).then(function(b){
        if(b.result!=="OK")throw new Error("Display rejected");
        sceneSymbol=symbol;lastDrawAt=now;
    })
    .catch(function(){console.error("Display unavailable");lastDrawAt=now;})
    .then(function(){drawing=false;});
}
function refresh() {
    if(fetching)return;
    const now=Date.now();
    let symbol=null;
    for(let i=0;i<SYMBOLS.length;i++) {
        const candidate=SYMBOLS[cursor];cursor=(cursor+1)%SYMBOLS.length;
        if(!due[candidate]||now>=due[candidate]){symbol=candidate;break;}
    }
    if(!symbol)return;
    fetching=true;
    fetch("https://query2.finance.yahoo.com/v8/finance/chart/"+encodeURIComponent(symbol)+"?interval=5m&range=1d",
        {headers:{"User-Agent":"busybar/0.1","Accept":"application/json"}})
    .then(function(r){return r.json();}).then(function(body){
        const q=parse(body,symbol,Date.now());quotes[symbol]=q;failed[symbol]=false;
        due[symbol]=Date.now()+REFRESH_MS;
        try{localStorage.setItem("quote-v1-"+symbol,JSON.stringify(q));}catch(_){console.error("Cache write failed");}
    }).catch(function(){failed[symbol]=true;due[symbol]=Date.now()+60000;console.error("Quote failed: "+symbol);})
    .then(function(){fetching=false;draw();});
}
SYMBOLS.forEach(function(symbol){
    try {const q=JSON.parse(localStorage.getItem("quote-v1-"+symbol));if(valid(q,symbol)){quotes[symbol]=q;failed[symbol]=true;}}
    catch(_){console.error("Cache unavailable: "+symbol);}
});
draw();refresh();
setInterval(refresh,5000);
setInterval(draw,250);
