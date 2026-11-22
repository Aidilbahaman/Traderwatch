#!/usr/bin/env python3
"""Generate 5 zoom previews — JS-driven zoom (works with Reduce Motion),
bright core during zoom (visible on dark bg), JS progress label."""
import pathlib

OUT = pathlib.Path("/home/ubuntu/web/Traderwatch-repo/preview")

STYLES = [
    dict(key="z1", title="Z1 — Wormhole Tunnel", name="Wormhole Tunnel",
         tagline="Enter the tunnel.", sub="Satu keputusan di hujung lorong.",
         maxscale=20, dur=1800,
         decor="rings", sound="tunnel",
         desc="9 cincin perspektif lalu kamera"),
    dict(key="z2", title="Z2 — Lens Flare Burst", name="Lens Flare Burst",
         tagline="Burst into insight.", sub="Satu tekan, terus ke dalam data.",
         maxscale=18, dur=1600,
         decor="rays", sound="flare",
         desc="White flash + chroma split + ular cahaya"),
    dict(key="z3", title="Z3 — Gravity Suck", name="Gravity Suck",
         tagline="Feel the pull.", sub="Data tertarik ke satu titik keputusan.",
         maxscale=15, dur=1800,
         decor="orbit", sound="gravity",
         desc="Orbit berputar + dot spiral mengecil"),
    dict(key="z4", title="Z4 — Pixel Dissolve", name="Pixel Dissolve",
         tagline="Decode the market.", sub="Setiap data dipecah, difahami.",
         maxscale=13, dur=1500,
         decor="pixels", sound="pixel",
         desc="720 pixel berpusar, chart decode"),
    dict(key="z5", title="Z5 — Candle Cascade", name="Candle Cascade",
         tagline="Every candle counts.", sub="Setiap lilin menuju satu keputusan.",
         maxscale=16, dur=1800,
         decor="candles", sound="candle",
         desc="28 candlestick hijau/merah jatuh spiral"),
]

BASE = """<!doctype html><html lang="ms"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--lime:#b7f36b;--card:#111612;--card2:#171e18;--line:#222b23;--muted:#8a978c;--text:#eef3ee;--onlime:#10150b;--red:#ff777d}
*{box-sizing:border-box;margin:0}
body{background:#0a0e0b;color:var(--text);font:14px -apple-system,sans-serif}
.hint{position:fixed;top:0;left:0;right:0;z-index:999;background:#171e18ee;color:var(--muted);font-size:10.5px;padding:8px 14px;text-align:center;border-bottom:1px solid var(--line)}
.hint b{color:var(--lime)}
.replay{position:fixed;bottom:14px;right:14px;z-index:999;background:var(--card2);border:1px solid var(--line);color:var(--lime);font:700 10px inherit;padding:8px 14px;border-radius:99px;cursor:pointer}
.phone{width:390px;max-width:100%;height:800px;max-height:100vh;margin:0 auto;position:relative;overflow:hidden;background:#050807}
#intro{position:absolute;inset:0;z-index:10;display:grid;place-items:center;cursor:pointer;overflow:hidden;
 background:radial-gradient(ellipse at 50% 50%,#0e150f,#030604 78%)}
/* decor layer */
#decor{position:absolute;inset:0;z-index:2;display:grid;place-items:center;pointer-events:none}
/* ZOOM TARGET — dibesarkan oleh JS, TERANG supaya jelas nampak */
#zh{position:relative;width:220px;height:220px;display:grid;place-items:center;z-index:6;
 will-change:transform;transform-origin:50% 50%}
#zh .glow{position:absolute;width:200px;height:200px;border-radius:50%;
 background:radial-gradient(circle,#b7f36b44 0%,#b7f36b14 45%,transparent 70%)}
#zh .core{position:relative;width:84px;height:84px;border-radius:50%;z-index:7;
 background:radial-gradient(circle,#eaffc4 0%,#b7f36b 26%,#5f9c22 55%,#000 100%);
 box-shadow:0 0 0 2px #b7f36b,0 0 44px 14px #b7f36baa,0 0 120px 44px #b7f36b44}
#zh .wv{position:absolute;width:120px;height:120px;border-radius:50%;border:1px solid #b7f36b88}
#zh .wv.b{width:150px;height:150px;border-color:#b7f36b55}
#zh .wv.c{width:180px;height:180px;border-color:#b7f36b33}
/* label JS progress */
#zlab{position:absolute;z-index:40;top:44%;left:0;right:0;text-align:center;
 font:900 15px monospace;letter-spacing:3px;color:#b7f36b;opacity:0;
 text-shadow:0 0 18px #b7f36b,0 0 40px #b7f36b88;pointer-events:none}
#zbar{position:absolute;z-index:40;bottom:70px;left:60px;right:60px;height:4px;border-radius:99px;
 background:#b7f36b22;opacity:0;overflow:hidden}
#zbar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#b7f36b,#eaffc4);border-radius:99px}
.brand{position:absolute;top:58px;font-size:12px;font-weight:900;letter-spacing:2px;color:var(--lime);z-index:9}
.brand span{color:var(--text)}
.itxt{position:absolute;bottom:140px;text-align:center;z-index:9;padding:0 30px;left:0;right:0}
.itxt b{display:block;font-size:24px;font-weight:900}
.itxt small{display:block;color:var(--muted);font-size:11.5px;margin-top:8px;line-height:1.6}
.tap{position:absolute;bottom:44px;left:0;right:0;text-align:center;font-size:10.5px;color:var(--lime);
 font-weight:800;letter-spacing:1.5px;z-index:9}
#void{position:absolute;inset:0;z-index:15;background:#000;opacity:0;transition:opacity .22s;pointer-events:none}
#void.on{opacity:1}
#on{position:absolute;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:22px;
 background:rgba(4,8,5,.92);backdrop-filter:blur(10px);opacity:0;pointer-events:none;transition:opacity .5s}
#on.show{opacity:1;pointer-events:auto}
.card{width:100%;max-width:360px;background:var(--card);border:1px solid #b7f36b3d;border-radius:24px;
 padding:24px 20px 18px;text-align:center;box-shadow:0 24px 70px #0009}
.clogo{font-size:12px;font-weight:900;color:var(--lime);margin-bottom:14px}.clogo span{color:var(--text)}
.mini{width:64px;height:64px;margin:0 auto 14px;border-radius:50%;
 background:radial-gradient(circle,#eaffc4,#b7f36b 30%,#000 78%);box-shadow:0 0 0 1.5px var(--lime),0 0 22px 7px #b7f36b77}
.ct{font-size:20px;font-weight:900}.cs{font-size:11px;color:var(--muted);margin:6px 0 18px;line-height:1.5}
.opt{display:flex;align-items:center;gap:11px;width:100%;text-align:left;background:var(--card2);
 border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:9px;color:var(--text);font:inherit;cursor:pointer}
.oi{width:34px;height:34px;flex:none;border-radius:10px;display:grid;place-items:center;background:#b7f36b18;color:var(--lime)}
.ot{flex:1;display:flex;flex-direction:column;gap:2px}.ot b{font-size:12px;font-weight:800}
.ot small{font-size:9.5px;color:var(--muted)}
.go{width:100%;border:0;border-radius:13px;padding:13px;font:800 12.5px inherit;cursor:pointer;
 background:linear-gradient(135deg,var(--lime),#8ed94e);color:var(--onlime);margin-top:7px}
.sk{display:block;margin:10px auto 0;border:0;background:none;color:var(--muted);cursor:pointer;
 font:600 10.5px inherit;text-decoration:underline;padding:5px}
/* decor timbul perlahan (JS-driven, no CSS animation) */
@keyframes none{}
</style></head><body>
<div class="hint"><b>__NAME__</b> — tekan blackhole → zoom masuk. 🔊 bunyi ON</div>
<button class="replay" onclick="location.reload()">↻ Replay</button>
<div class="phone">
 <div id="intro">
  <div id="decor">__DECOR__</div>
  <div class="brand">✦ <span>TraderWatch</span></div>
  <div id="zh">
   <div class="glow"></div>
   <div class="wv"></div><div class="wv b"></div><div class="wv c"></div>
   <div class="core"></div>
  </div>
  <div id="zlab">ENTERING…</div>
  <div id="zbar"><i></i></div>
  <div class="itxt"><b>__TAGLINE__</b><small>__SUB__</small></div>
  <div class="tap">TEKAN UNTUK MASUK →</div>
 </div>
 <div id="void"></div>
 <div id="on"><div class="card">
  <div class="clogo">✦ <span>TraderWatch</span></div><div class="mini"></div>
  <div class="ct">Selamat datang!</div><div class="cs">Sediakan app anda sebelum mula.</div>
  <button class="opt"><span class="oi"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/></svg></span><span class="ot"><b>Hidupkan notifikasi</b><small>Alert TP/SL</small></span></button>
  <button class="opt"><span class="oi"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="2" width="12" height="20" rx="2"/></svg></span><span class="ot"><b>Tambah ke skrin utama</b><small>Buka macam app</small></span></button>
  <button class="go">Mula trade →</button><button class="sk">Langkau dulu</button>
 </div></div>
</div>
<script>
/* ===== Web Audio (synth, no files) ===== */
var AC=null;
function ac(){if(!AC)AC=new (window.AudioContext||window.webkitAudioContext)();if(AC.state==='suspended')AC.resume();return AC}
function noise(c,sec){var b=c.createBuffer(1,c.sampleRate*sec,c.sampleRate),d=b.getChannelData(0);
 for(var i=0;i<d.length;i++)d[i]=Math.random()*2-1;return b}
function sndTunnel(){var c=ac(),t=c.currentTime;
 var n=c.createBufferSource();n.buffer=noise(c,1.6);
 var bp=c.createBiquadFilter();bp.type='bandpass';bp.Q.value=1.2;
 bp.frequency.setValueAtTime(180,t);bp.frequency.exponentialRampToValueAtTime(2600,t+1.1);
 var g=c.createGain();g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.3,t+.15);
 g.gain.exponentialRampToValueAtTime(.001,t+1.6);
 n.connect(bp);bp.connect(g);g.connect(c.destination);n.start(t);n.stop(t+1.7);
 var o=c.createOscillator();o.type='sine';o.frequency.setValueAtTime(110,t);
 o.frequency.exponentialRampToValueAtTime(28,t+1.2);
 var og=c.createGain();og.gain.setValueAtTime(.0001,t);og.gain.exponentialRampToValueAtTime(.5,t+.1);
 og.gain.exponentialRampToValueAtTime(.001,t+1.5);
 o.connect(og);og.connect(c.destination);o.start(t);o.stop(t+1.6)}
function sndFlare(){var c=ac(),t=c.currentTime;
 [0,7,12].forEach(function(off,i){var o=c.createOscillator();o.type='triangle';
  var base=440*Math.pow(2,off/12);o.frequency.setValueAtTime(base,t);
  o.frequency.exponentialRampToValueAtTime(base*4,t+.6);
  var g=c.createGain();g.gain.setValueAtTime(.0001,t);
  g.gain.exponentialRampToValueAtTime(.12,t+.1+i*.03);g.gain.exponentialRampToValueAtTime(.001,t+.85);
  o.connect(g);g.connect(c.destination);o.start(t);o.stop(t+.9)});
 var n=c.createBufferSource();n.buffer=noise(c,.5);
 var hp=c.createBiquadFilter();hp.type='highpass';hp.frequency.value=2000;
 var ng=c.createGain();ng.gain.setValueAtTime(.22,t);ng.gain.exponentialRampToValueAtTime(.001,t+.45);
 n.connect(hp);hp.connect(ng);ng.connect(c.destination);n.start(t);n.stop(t+.5)}
function sndGravity(){var c=ac(),t=c.currentTime;
 var o=c.createOscillator();o.type='sawtooth';o.frequency.setValueAtTime(620,t);
 o.frequency.exponentialRampToValueAtTime(90,t+.95);
 var f=c.createBiquadFilter();f.type='lowpass';f.frequency.setValueAtTime(2400,t);
 f.frequency.exponentialRampToValueAtTime(300,t+.95);
 var g=c.createGain();g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.15,t+.12);
 g.gain.exponentialRampToValueAtTime(.001,t+1.1);
 o.connect(f);f.connect(g);g.connect(c.destination);o.start(t);o.stop(t+1.15);
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(58,t);
 s.frequency.exponentialRampToValueAtTime(30,t+1);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.45,t+.15);
 sg.gain.exponentialRampToValueAtTime(.001,t+1.2);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+1.25)}
function sndPixel(){var c=ac(),t=c.currentTime;
 var n=c.createBufferSource(),b=c.createBuffer(1,c.sampleRate*.7,c.sampleRate),d=b.getChannelData(0);
 for(var i=0;i<d.length;i++)d[i]=((i%97)<40?1:-1)*(Math.random()*.5+.5);n.buffer=b;
 var bp=c.createBiquadFilter();bp.type='bandpass';bp.frequency.value=1200;bp.Q.value=.8;
 var g=c.createGain();g.gain.setValueAtTime(.001,t);g.gain.exponentialRampToValueAtTime(.18,t+.05);
 g.gain.exponentialRampToValueAtTime(.001,t+.75);
 n.connect(bp);bp.connect(g);g.connect(c.destination);n.start(t);n.stop(t+.8);
 [523,659,784,1047].forEach(function(f,i){var o=c.createOscillator();o.type='square';o.frequency.value=f;
  var og=c.createGain();var tt=t+i*.1;og.gain.setValueAtTime(.0001,tt);
  og.gain.exponentialRampToValueAtTime(.08,tt+.01);og.gain.exponentialRampToValueAtTime(.001,tt+.16);
  o.connect(og);og.connect(c.destination);o.start(tt);o.stop(tt+.18)})}
function sndCandle(){var c=ac(),t=c.currentTime;
 for(var i=0;i<14;i++){var o=c.createOscillator();o.type='square';
  o.frequency.value=700+Math.random()*900;var g=c.createGain();var tt=t+i*.05;
  g.gain.setValueAtTime(.0001,tt);g.gain.exponentialRampToValueAtTime(.05,tt+.005);
  g.gain.exponentialRampToValueAtTime(.001,tt+.07);
  o.connect(g);g.connect(c.destination);o.start(tt);o.stop(tt+.08)}
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(120,t);
 s.frequency.exponentialRampToValueAtTime(32,t+.9);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.5,t+.1);
 sg.gain.exponentialRampToValueAtTime(.001,t+1.15);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+1.2)}

/* ===== JS-DRIVEN ZOOM (works with Reduce Motion; no CSS animation) ===== */
var busy=false;
(function(){
 var zh=document.getElementById('zh'),zlab=document.getElementById('zlab'),
     zbar=document.getElementById('zbar'),zbarI=zbar.querySelector('i'),
     intro=document.getElementById('intro'),voidEl=document.getElementById('void'),
     on=document.getElementById('on');
 var MAX=__MAX__, DUR=__DUR__;
 intro.onclick=function(){
  if(busy)return;busy=true;
  try{__SND__()}catch(e){}
  zlab.style.opacity='1';zbar.style.opacity='1';
  var t0=null;
  function step(ts){
   if(t0===null)t0=ts;
   var p=Math.min(1,(ts-t0)/DUR);
   /* easeInOutQuad */
   var e=p<0.5?2*p*p:1-Math.pow(-2*p+2,2)/2;
   var sc=1+e*(MAX-1);
   zh.style.transform='scale('+sc+')';
   zbarI.style.width=(p*100).toFixed(1)+'%';
   /* label berubah ikut progress */
   if(p<0.35)zlab.textContent='ENTERING…';
   else if(p<0.7)zlab.textContent='DEEPER…';
   else zlab.textContent='INSIDE';
   /* core makin terang */
   zh.style.filter='brightness('+(1+e*1.8).toFixed(2)+')';
   if(p<1){requestAnimationFrame(step)}
   else{
    voidEl.classList.add('on');
    zlab.style.opacity='0';zbar.style.opacity='0';
    setTimeout(function(){
     intro.style.display='none';
     on.classList.add('show');
     setTimeout(function(){voidEl.style.transition='opacity .6s';voidEl.classList.remove('on')},130);
    },280);
   }
  }
  requestAnimationFrame(step);
 };
})();
</script></body></html>
"""

DECOR = {
    "rings": "".join(
        f'<div style="position:absolute;width:{300-i*18}px;height:{300-i*18}px;border-radius:50%;'
        f'border:1px solid #b7f36b{["55","44","33"][i%3]};opacity:.6"></div>' for i in range(6)),
    "rays": "".join(
        f'<div style="position:absolute;width:3px;height:180px;background:linear-gradient(180deg,'
        f'transparent,#b7f36b99,transparent);transform:rotate({i*22.5}deg) translateY(-110px);'
        f'opacity:.5"></div>' for i in range(16)),
    "orbit": '<div style="position:absolute;width:280px;height:280px;border-radius:50%;'
             'border:1px dashed #b7f36b44"></div>'
             '<div style="position:absolute;width:230px;height:230px;border-radius:50%;'
             'border:1px solid #b7f36b33"></div>'
             '<div style="position:absolute;width:7px;height:7px;border-radius:50%;background:#eaffc4;'
             'box-shadow:0 0 10px #b7f36b;transform:translateY(-140px)"></div>',
    "pixels": "".join(
        f'<div style="position:absolute;width:4px;height:4px;background:'
        f'{["#b7f36b","#8ab4ff","#eaffc4"][i%3]};opacity:.7;'
        f'transform:translate({((i*37)%300)-150}px,{((i*53)%300)-150}px) rotate({i*17}deg)"></div>'
        for i in range(60)),
    "candles": "".join(
        f'<div style="position:absolute;width:5px;height:{14+(i*7)%44}px;border-radius:2px;'
        f'background:{"#b7f36b" if i%3 else "#ff777d"};opacity:.75;'
        f'transform:rotate({i*(360/28)}deg) translateY(-150px)"></div>' for i in range(28)),
}

for st in STYLES:
    html = (BASE
            .replace("__TITLE__", st["title"])
            .replace("__NAME__", st["name"])
            .replace("__TAGLINE__", st["tagline"])
            .replace("__SUB__", st["sub"])
            .replace("__DECOR__", DECOR[st["decor"]])
            .replace("__MAX__", str(st["maxscale"]))
            .replace("__DUR__", str(st["dur"]))
            .replace("__SND__", "snd" + st["sound"].capitalize()))
    (OUT / f'zoom-{st["key"]}-{st["sound"]}.html').write_text(html, encoding="utf-8")
    print("wrote", f'zoom-{st["key"]}-{st["sound"]}.html')
