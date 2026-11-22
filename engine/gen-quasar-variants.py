#!/usr/bin/env python3
"""5 variasi Quasar Beam — sama struktur (jet+corona+beam+zarah) tapi
karakter animasi BERBEZA:

Q1 Pulsar      : denyut tajam (sharp pulse) macam pulsar berdenyut
Q2 Nebula Flow : aliran lembut organik, zarah banyak, warna bergeser
Q3 Warp Drive  : jet memanjang laju, beam pecut, garis warp
Q4 Quantum     : zarah teleport rawak, flicker digital
Q5 Solar Wind  : angin suria berterusan, jet bergelombang sinus
"""
import pathlib

OUT = pathlib.Path("/home/ubuntu/web/Traderwatch-repo/preview")

TPL = """<!doctype html><html lang="ms"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<style>
:root{--lime:#b7f36b;--card:#0d120e;--card2:#171e18;--line:#222b23;--muted:#8a978c;--text:#eef3ee;--onlime:#10150b;--red:#ff777d;--blue:#8ab4ff;--orange:#ffc16b}
*{box-sizing:border-box;margin:0}
body{background:#080b09;color:var(--text);font:14px -apple-system,sans-serif}
.hint{position:fixed;top:0;left:0;right:0;z-index:999;background:#171e18ee;color:var(--muted);font-size:10.5px;padding:8px 14px;text-align:center;border-bottom:1px solid var(--line)}
.hint b{color:var(--lime)}
.replay{position:fixed;bottom:14px;right:14px;z-index:999;background:var(--card2);border:1px solid var(--line);color:var(--lime);font:700 10px inherit;padding:8px 14px;border-radius:99px;cursor:pointer}
.phone{width:390px;max-width:100%;height:800px;max-height:100vh;margin:0 auto;position:relative;overflow:hidden;background:#000}
#intro{position:absolute;inset:0;z-index:10;display:grid;place-items:center;cursor:pointer;overflow:hidden;background:#040605}
#decor{position:absolute;inset:0;z-index:2;pointer-events:none;overflow:hidden;display:grid;place-items:center}
.dec{position:absolute;left:50%;top:50%;will-change:transform,opacity;transform-origin:50% 50%}
#zh{position:relative;width:220px;height:220px;display:grid;place-items:center;z-index:6;
 will-change:transform;transform-origin:50% 50%}
#zh .core{position:relative;width:92px;height:92px;border-radius:50%;background:#000;z-index:9;
 box-shadow:0 0 0 1.8px #b7f36b,0 0 18px 3px #b7f36baa,0 0 70px 20px #b7f36b33;
 will-change:transform,box-shadow}
#zh .coreglow{position:absolute;width:140px;height:140px;border-radius:50%;z-index:1;pointer-events:none;
 background:radial-gradient(circle,#b7f36b40 18%,#b7f36b16 48%,transparent 72%);
 filter:blur(11px);will-change:transform,opacity}
.brand{position:absolute;top:58px;left:0;right:0;text-align:center;font-size:12px;font-weight:900;letter-spacing:2px;color:var(--lime);z-index:9}
.brand span{color:var(--text)}
.itxt{position:absolute;bottom:140px;text-align:center;z-index:9;padding:0 30px;left:0;right:0}
.itxt b{display:block;font-size:24px;font-weight:900}
.itxt small{display:block;color:var(--muted);font-size:11.5px;margin-top:8px;line-height:1.6}
.tap{position:absolute;bottom:44px;left:0;right:0;text-align:center;font-size:10.5px;color:var(--lime);font-weight:800;letter-spacing:1.5px;z-index:9}
#zlab{position:absolute;z-index:40;top:20%;left:0;right:0;text-align:center;
 font:900 13px monospace;letter-spacing:3px;color:#b7f36b;opacity:0;
 text-shadow:0 0 16px #b7f36b,0 0 36px #b7f36b77;pointer-events:none}
#zbar{position:absolute;z-index:40;bottom:70px;left:60px;right:60px;height:3px;border-radius:99px;
 background:#b7f36b1f;opacity:0;overflow:hidden}
#zbar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#b7f36b,#eaffc4);border-radius:99px}
#void{position:absolute;inset:0;z-index:15;background:#000;opacity:0;transition:opacity .25s;pointer-events:none}
#void.on{opacity:1}
#on{position:absolute;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:22px;
 background:rgba(0,0,0,.94);backdrop-filter:blur(10px);opacity:0;pointer-events:none;transition:opacity .5s}
#on.show{opacity:1;pointer-events:auto}
.card{width:100%;max-width:360px;background:var(--card);border:1px solid #b7f36b3d;border-radius:24px;
 padding:24px 20px 18px;text-align:center;box-shadow:0 24px 70px #0009}
.clogo{font-size:12px;font-weight:900;color:var(--lime);margin-bottom:14px}.clogo span{color:var(--text)}
.mini{width:60px;height:60px;margin:0 auto 14px;border-radius:50%;background:#000;
 box-shadow:0 0 0 1.5px var(--lime),0 0 18px 5px #b7f36b66}
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
/* ---- struktur quasar (sama untuk semua) ---- */
#zh .jet{position:absolute;width:8px;border-radius:99px;z-index:2;will-change:transform,height,opacity;
 background:linear-gradient(180deg,#eaffc4,#b7f36bdd 26%,#b7f36b66 62%,transparent);filter:blur(2.4px)}
#zh .jet .halo{position:absolute;left:50%;top:0;width:28px;height:100%;margin-left:-14px;
 background:linear-gradient(180deg,#b7f36b55,transparent);filter:blur(8px);border-radius:99px}
#zh .jet .p{position:absolute;left:50%;width:3px;height:3px;border-radius:50%;margin-left:-1.5px;
 background:#eaffc4;box-shadow:0 0 7px #b7f36b;will-change:transform,opacity}
#zh .corona{position:absolute;width:176px;height:176px;border-radius:50%;z-index:3;
 background:radial-gradient(circle,transparent 36%,#b7f36b66 46%,#b7f36b2e 60%,transparent 78%);
 filter:blur(6px);will-change:transform,opacity}
#zh .beam{position:absolute;width:230px;height:230px;border-radius:50%;z-index:4;
 background:conic-gradient(from 0deg,#b7f36b00 0deg,#b7f36bcc 16deg,#eaffc4 30deg,#b7f36b88 46deg,#b7f36b00 64deg,
   #b7f36b00 176deg,#8ab4ffcc 194deg,#eaffc4 208deg,#8ab4ff88 224deg,#b7f36b00 242deg);
 filter:blur(5px);opacity:.9;will-change:transform,opacity}
%%CSSX%%
</style></head><body>
<div class="hint"><b>%%NAME%%</b> — %%HINT%%</div>
<button class="replay" onclick="location.reload()">↻ Replay</button>
<div class="phone">
 <div id="intro">
  <div id="decor"></div>
  <div class="brand">✦ <span>TraderWatch</span></div>
  <div id="zh"><div class="coreglow"></div><div class="core"></div></div>
  <div id="zlab">ENTERING…</div>
  <div id="zbar"><i></i></div>
  <div class="itxt"><b>%%TAG%%</b><small>%%SUB%%</small></div>
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
var AC=null;
function ac(){if(!AC)AC=new (window.AudioContext||window.webkitAudioContext)();if(AC.state==='suspended')AC.resume();return AC}
function nz(c,s){var b=c.createBuffer(1,c.sampleRate*s,c.sampleRate),d=b.getChannelData(0);
 for(var i=0;i<d.length;i++)d[i]=Math.random()*2-1;return b}

function sndPulsar(){var c=ac(),t=c.currentTime;
 for(var i=0;i<5;i++){var o=c.createOscillator();o.type='square';
  o.frequency.value=140;var g=c.createGain();var tt=t+i*.34;
  g.gain.setValueAtTime(.0001,tt);g.gain.exponentialRampToValueAtTime(.18,tt+.02);
  g.gain.exponentialRampToValueAtTime(.001,tt+.16);
  o.connect(g);g.connect(c.destination);o.start(tt);o.stop(tt+.18)}
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(70,t);
 s.frequency.exponentialRampToValueAtTime(22,t+1.8);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.5,t+.2);
 sg.gain.exponentialRampToValueAtTime(.001,t+2);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+2.1)}
function sndNebula(){var c=ac(),t=c.currentTime;
 var n=c.createBufferSource();n.buffer=nz(c,2.2);
 var lp=c.createBiquadFilter();lp.type='lowpass';
 lp.frequency.setValueAtTime(600,t);lp.frequency.linearRampToValueAtTime(2600,t+1.4);
 lp.frequency.linearRampToValueAtTime(400,t+2.1);
 var g=c.createGain();g.gain.setValueAtTime(.001,t);g.gain.linearRampToValueAtTime(.2,t+.5);
 g.gain.exponentialRampToValueAtTime(.001,t+2.2);
 n.connect(lp);lp.connect(g);g.connect(c.destination);n.start(t);n.stop(t+2.3);
 [110,164.81,220].forEach(function(f,i){
  var o=c.createOscillator();o.type='triangle';o.frequency.setValueAtTime(f,t);
  o.frequency.linearRampToValueAtTime(f*0.55,t+2);
  var og=c.createGain();og.gain.setValueAtTime(.0001,t);og.gain.exponentialRampToValueAtTime(.09,t+.4+i*.2);
  og.gain.exponentialRampToValueAtTime(.001,t+2.1);
  o.connect(og);og.connect(c.destination);o.start(t);o.stop(t+2.2)})}
function sndWarp(){var c=ac(),t=c.currentTime;
 var n=c.createBufferSource();n.buffer=nz(c,1.7);
 var bp=c.createBiquadFilter();bp.type='bandpass';bp.Q.value=3;
 bp.frequency.setValueAtTime(200,t);bp.frequency.exponentialRampToValueAtTime(5000,t+1.3);
 var g=c.createGain();g.gain.setValueAtTime(.001,t);g.gain.exponentialRampToValueAtTime(.32,t+.3);
 g.gain.exponentialRampToValueAtTime(.001,t+1.7);
 n.connect(bp);bp.connect(g);g.connect(c.destination);n.start(t);n.stop(t+1.8);
 var o=c.createOscillator();o.type='sawtooth';o.frequency.setValueAtTime(180,t);
 o.frequency.exponentialRampToValueAtTime(40,t+1.4);
 var og=c.createGain();og.gain.setValueAtTime(.0001,t);og.gain.exponentialRampToValueAtTime(.22,t+.3);
 og.gain.exponentialRampToValueAtTime(.001,t+1.6);
 o.connect(og);og.connect(c.destination);o.start(t);o.stop(t+1.7)}
function sndQuantum(){var c=ac(),t=c.currentTime;
 for(var i=0;i<26;i++){var o=c.createOscillator();o.type='square';
  o.frequency.value=[880,1320,1760,660][i%4];
  var g=c.createGain();var tt=t+Math.random()*1.1;
  g.gain.setValueAtTime(.0001,tt);g.gain.exponentialRampToValueAtTime(.04,tt+.004);
  g.gain.exponentialRampToValueAtTime(.001,tt+.05);
  o.connect(g);g.connect(c.destination);o.start(tt);o.stop(tt+.06)}
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(100,t);
 s.frequency.exponentialRampToValueAtTime(24,t+1.6);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.42,t+.25);
 sg.gain.exponentialRampToValueAtTime(.001,t+1.8);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+1.9)}
function sndWind(){var c=ac(),t=c.currentTime;
 var n=c.createBufferSource();n.buffer=nz(c,2.4);
 var bp=c.createBiquadFilter();bp.type='bandpass';bp.Q.value=.6;
 bp.frequency.setValueAtTime(400,t);bp.frequency.linearRampToValueAtTime(1200,t+1.2);
 bp.frequency.linearRampToValueAtTime(300,t+2.2);
 var g=c.createGain();g.gain.setValueAtTime(.001,t);g.gain.linearRampToValueAtTime(.24,t+.6);
 g.gain.linearRampToValueAtTime(.001,t+2.4);
 n.connect(bp);bp.connect(g);g.connect(c.destination);n.start(t);n.stop(t+2.5);
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(58,t);
 s.frequency.linearRampToValueAtTime(20,t+2.2);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.45,t+.5);
 sg.gain.exponentialRampToValueAtTime(.001,t+2.4);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+2.5)}

var DECOR=document.getElementById('decor');
var zh=document.getElementById('zh'),core=zh.querySelector('.core'),CGLOW=zh.querySelector('.coreglow');
var JETS=[],CORONA=null,PARTS=[];
(function(){
 ['up','dn'].forEach(function(dir,ji){
  var j=document.createElement('div');j.className='jet';
  j.style.height='150px';
  if(dir==='up'){j.style.top='-62px'}else{j.style.bottom='-62px'}
  var halo=document.createElement('div');halo.className='halo';j.appendChild(halo);
  for(var i=0;i<16;i++){
   var pt=document.createElement('div');pt.className='p';j.appendChild(pt);
   PARTS.push({el:pt,jet:ji,off:Math.random(),spd:0.5+Math.random()*0.9,
               sz:2+Math.random()*2.4,sway:(Math.random()-0.5)*12,
               tp:Math.random()});
  }
  zh.appendChild(j);JETS.push({el:j,dir:dir});
 });
 var c=document.createElement('div');c.className='corona';zh.appendChild(c);CORONA=c;
 var b=document.createElement('div');b.className='beam';zh.appendChild(b);CORONA._beam=b;
})();

/* ===== IDLE LOOP — %%IDLENAME%% ===== */
var ZOOMING=false;
var _t0=performance.now();
(function idle(){
 var t=(performance.now()-_t0)/1000;
 if(!ZOOMING){ %%IDLE%% }
 /* zarah — %%PARTMODE%% */
 for(var k=0;k<PARTS.length;k++){ %%PARTICLE%% }
 requestAnimationFrame(idle);
})();

/* ===== ZOOM ===== */
var busy=false;
(function(){
 var zlab=document.getElementById('zlab'),zbar=document.getElementById('zbar'),zbarI=zbar.querySelector('i'),
     voidEl=document.getElementById('void'),on=document.getElementById('on'),intro=document.getElementById('intro');
 var DUR=%%DUR%%;
 intro.onclick=function(){
  if(busy)return;busy=true;ZOOMING=true;
  try{%%SNDFN%%()}catch(e){}
  zlab.style.opacity='1';zbar.style.opacity='1';
  var t0=null;
  function frame(ts){
   if(t0===null)t0=ts;
   var p=Math.min(1,(ts-t0)/DUR);
   var e=p<0.5?2*p*p:1-Math.pow(-2*p+2,2)/2;
   %%ANIM%%
   zbarI.style.width=(p*100).toFixed(1)+'%';
   zlab.textContent=p<.3?'ENTERING…':(p<.68?'FALLING…':'SWALLOWED');
   if(p<1){requestAnimationFrame(frame)}
   else{
    voidEl.classList.add('on');
    zlab.style.opacity='0';zbar.style.opacity='0';
    setTimeout(function(){
     intro.style.display='none';on.classList.add('show');
     setTimeout(function(){voidEl.style.transition='opacity .7s';voidEl.classList.remove('on')},140);
    },320);
   }
  }
  requestAnimationFrame(frame);
 };
})();
</script></body></html>
"""

# ============ Q1 PULSAR: denyut tajam ============
Q1_CSS = """
#zh .ring{position:absolute;width:160px;height:160px;border-radius:50%;z-index:5;
 border:1.5px solid #b7f36b;opacity:0;will-change:transform,opacity}
"""
Q1_IDLE = """
  /* denyut tajam: setiap denyut, jet meluru panjang sekejap */
  var beat=(t*1.55)%1;                       /* 0..1 kitar denyut */
  var sharp=beat<0.14?Math.sin(beat/0.14*Math.PI):0;   /* spike tajam */
  for(var i=0;i<JETS.length;i++){
   var j=JETS[i];
   var len=150+sharp*175;
   j.el.style.height=len.toFixed(0)+'px';
   j.el.style.opacity=(0.55+sharp*0.42).toFixed(2);
   j.el.style.transform='translateX(0px)';
  }
  if(CORONA){
   CORONA.style.transform='scale('+(1+sharp*0.24).toFixed(3)+')';
   CORONA.style.opacity=(0.4+sharp*0.5).toFixed(2);
   CORONA._beam.style.transform='rotate('+(t*22).toFixed(1)+'deg)';
   CORONA._beam.style.opacity=(0.35+sharp*0.6).toFixed(2);
  }
  if(CGLOW){
   CGLOW.style.transform='scale('+(1+sharp*0.32).toFixed(3)+')';
   CGLOW.style.opacity=(0.45+sharp*0.45).toFixed(2);
  }
  core.style.boxShadow='0 0 0 1.8px rgba(183,243,107,'+(0.85+sharp*0.15).toFixed(2)+
    '), 0 0 '+(18+sharp*30).toFixed(0)+'px 5px rgba(183,243,107,'+(0.45+sharp*0.45).toFixed(2)+
    '), 0 0 90px 28px rgba(183,243,107,0.2)';
  /* cincin denyut mengecut semula */
  if(RINGS1){
   for(var r=0;r<RINGS1.length;r++){
    var rp=(beat+r*0.33)%1;
    RINGS1[r].style.transform='scale('+(1+rp*2.6).toFixed(2)+')';
    RINGS1[r].style.opacity=((1-rp)*sharp*0.7).toFixed(2);
   }
  }
"""
Q1_PART = """
  var o=PARTS[k];
  /* zarah hanya bergerak bila denyut — pause antara beat */
  var beat0=(t*1.55)%1;
  if(beat0<0.5){o.off+=0.014*o.spd;}else{o.off+=0.001*o.spd;}
  if(o.off>1)o.off-=1;
  var jh=parseFloat(JETS[o.jet].el.style.height)||150;
  var dirSign=JETS[o.jet].dir==='up'?1:-1;
  var dist=o.off*jh*1.3;
  var fade=o.off<0.1?o.off/0.1:(o.off>0.86?(1-o.off)/0.14:1);
  o.el.style.width=o.sz+'px';o.el.style.height=o.sz+'px';
  o.el.style.transform='translate(0px,'+(dirSign*(dist-jh*0.15)).toFixed(1)+'px)';
  o.el.style.opacity=(fade*0.9).toFixed(2);
"""
Q1_ANIM = """
   for(var i=0;i<JETS.length;i++){
    var j=JETS[i];
    var jg=Math.min(1,p*2.2);
    j.el.style.height=(150+jg*430).toFixed(0)+'px';
    j.el.style.transform='translateX(0px)';
    j.el.style.opacity=(p<0.1?p*10:(1-Math.pow(p,2.4))*0.95).toFixed(2);
   }
   CORONA.style.transform='scale('+(1+e*2.6).toFixed(2)+')';
   CORONA.style.opacity=(0.8*(1-e*0.8)).toFixed(2);
   CORONA._beam.style.transform='rotate('+(p*520).toFixed(0)+'deg) scale('+(1+e*8).toFixed(2)+')';
   CORONA._beam.style.opacity=(0.9*(1-Math.pow(e,2))).toFixed(2);
   if(CGLOW){CGLOW.style.transform='scale('+(1+e*6).toFixed(2)+')';CGLOW.style.opacity=(0.7*(1-e)).toFixed(2)}
   core.style.transform='scale('+(1+e*24).toFixed(2)+')';
   core.style.boxShadow='0 0 0 '+(1.8*(1-e*0.85)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.8).toFixed(2)+'),0 0 '+(22+e*20).toFixed(0)+'px 5px rgba(183,243,107,'+(0.65*(1-e)).toFixed(2)+'),0 0 90px 28px rgba(183,243,107,'+(0.22*(1-e)).toFixed(2)+')';
"""
Q1_BUILD_EXTRA = """
var RINGS1=[];
(function(){
 for(var i=0;i<3;i++){
  var r=document.createElement('div');r.className='ring';
  zh.appendChild(r);RINGS1.push(r);
 }
})();
"""

# ============ Q2 NEBULA FLOW: aliran lembut organik ============
Q2_IDLE = """
  /* aliran lembut — sinus berganda, tiada denyut tajam */
  for(var i=0;i<JETS.length;i++){
   var j=JETS[i];
   var flow=1+Math.sin(t*0.9+i*2.1)*0.3+Math.sin(t*1.7+i)*0.12;
   j.el.style.height=(150*flow).toFixed(0)+'px';
   var drift=Math.sin(t*0.6+i*1.4)*7+Math.sin(t*1.1+i*3)*3;
   j.el.style.transform='translateX('+drift.toFixed(1)+'px)';
   j.el.style.opacity=(0.62+Math.sin(t*0.8+i*2.2)*0.24).toFixed(2);
  }
  if(CORONA){
   var cflow=1+Math.sin(t*0.75)*0.14+Math.sin(t*1.45)*0.05;
   CORONA.style.transform='scale('+cflow.toFixed(3)+')';
   CORONA.style.opacity=(0.48+Math.sin(t*0.7)*0.2).toFixed(2);
   CORONA._beam.style.transform='rotate('+(t*34+Math.sin(t*0.5)*14).toFixed(1)+'deg)';
   CORONA._beam.style.opacity=(0.55+Math.sin(t*0.65)*0.2).toFixed(2);
  }
  if(CGLOW){
   CGLOW.style.transform='scale('+(1+Math.sin(t*0.85)*0.16).toFixed(3)+')';
   CGLOW.style.opacity=(0.55+Math.sin(t*0.85+0.8)*0.22).toFixed(2);
  }
  core.style.boxShadow='0 0 0 1.8px rgba(183,243,107,'+(0.88+Math.sin(t*0.8)*0.1).toFixed(2)+
    '), 0 0 '+(20+Math.sin(t*0.75)*9).toFixed(0)+'px 5px rgba(183,243,107,'+(0.5+Math.sin(t*0.7)*0.16).toFixed(2)+
    '), 0 0 88px 26px rgba(183,243,107,0.22)';
"""
Q2_PART = """
  var o=PARTS[k];
  o.off+=0.0042*o.spd;
  if(o.off>1)o.off-=1;
  var jh=parseFloat(JETS[o.jet].el.style.height)||150;
  var dirSign=JETS[o.jet].dir==='up'?1:-1;
  var dist=o.off*jh*1.2;
  var fade=o.off<0.16?o.off/0.16:(o.off>0.8?(1-o.off)/0.2:1);
  /* warna bergeser lime → cyan langsir */
  var mix=(t*0.35+o.tp)%1;
  var r=Math.round(183-60*mix), g=Math.round(243-50*mix), b=Math.round(107+120*mix);
  o.el.style.background='rgb('+r+','+g+','+b+')';
  o.el.style.boxShadow='0 0 9px rgb('+r+','+g+','+b+')';
  o.el.style.width=(o.sz*1.1)+'px';o.el.style.height=(o.sz*1.1)+'px';
  o.el.style.transform='translate('+(Math.sin(t*1.1+o.off*8)*o.sway*1.4).toFixed(1)+'px,'+(dirSign*(dist-jh*0.15)).toFixed(1)+'px)';
  o.el.style.opacity=(fade*0.8).toFixed(2);
"""
Q2_ANIM = """
   for(var i=0;i<JETS.length;i++){
    var j=JETS[i];
    j.el.style.height=(150+Math.min(1,p*2)*420).toFixed(0)+'px';
    j.el.style.opacity=(p<0.12?p*8:(1-Math.pow(p,2.2))*0.9).toFixed(2);
   }
   CORONA.style.transform='scale('+(1+e*2.4).toFixed(2)+')';
   CORONA.style.opacity=(0.75*(1-e*0.75)).toFixed(2);
   CORONA._beam.style.transform='rotate('+(p*480).toFixed(0)+'deg) scale('+(1+e*7).toFixed(2)+')';
   CORONA._beam.style.opacity=(0.85*(1-Math.pow(e,2))).toFixed(2);
   if(CGLOW){CGLOW.style.transform='scale('+(1+e*5).toFixed(2)+')';CGLOW.style.opacity=(0.68*(1-e)).toFixed(2)}
   core.style.transform='scale('+(1+e*23).toFixed(2)+')';
   core.style.boxShadow='0 0 0 '+(1.8*(1-e*0.8)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.75).toFixed(2)+'),0 0 '+(22+e*18).toFixed(0)+'px 5px rgba(183,243,107,'+(0.6*(1-e)).toFixed(2)+'),0 0 88px 26px rgba(183,243,107,'+(0.2*(1-e)).toFixed(2)+')';
"""

# ============ Q3 WARP DRIVE: jet memanjang laju + garis warp ============
Q3_CSS = """
#zh .warp{position:absolute;left:50%;top:0;width:1px;height:0;z-index:1;
 background:linear-gradient(180deg,#b7f36b00,#b7f36b99,#eaffc4,#b7f36b00);will-change:height,transform,opacity}
"""
Q3_BUILD_EXTRA = """
var WARP=[];
(function(){
 for(var i=0;i<10;i++){
  var w=document.createElement('div');w.className='warp';
  w.style.left=(40+Math.random()*140)+'px';
  zh.appendChild(w);WARP.push({el:w,y:Math.random(),spd:1.2+Math.random()*2.2,h:30+Math.random()*70});
 }
})();
"""
Q3_IDLE = """
  /* warp: jet berdenyut laju, getaran halus */
  for(var i=0;i<JETS.length;i++){
   var j=JETS[i];
   var rpm=1+Math.sin(t*4.5+i*3.1)*0.14;
   j.el.style.height=(150*rpm).toFixed(0)+'px';
   j.el.style.transform='translateX('+(Math.sin(t*9+i)*1.2).toFixed(2)+'px)';
   j.el.style.opacity=(0.66+Math.sin(t*3.4+i*2)*0.26).toFixed(2);
  }
  if(CORONA){
   CORONA.style.transform='scale('+(1+Math.sin(t*2.2)*0.05).toFixed(3)+')';
   CORONA.style.opacity=0.55;
   CORONA._beam.style.transform='rotate('+(t*140).toFixed(1)+'deg)';
   CORONA._beam.style.opacity=(0.7+Math.sin(t*2.8)*0.16).toFixed(2);
  }
  if(CGLOW){
   CGLOW.style.transform='scale('+(1+Math.sin(t*2.6)*0.1).toFixed(3)+')';
   CGLOW.style.opacity=(0.6+Math.sin(t*2.6+1)*0.18).toFixed(2);
  }
  core.style.boxShadow='0 0 0 1.8px rgba(183,243,107,0.95), 0 0 '+(22+Math.sin(t*3)*6).toFixed(0)+'px 5px rgba(183,243,107,'+(0.55+Math.sin(t*3)*0.12).toFixed(2)+'), 0 0 90px 28px rgba(183,243,107,0.22)';
"""
Q3_PART = """
  var o=PARTS[k];
  o.off+=0.016*o.spd;                          /* LAJU — warp */
  if(o.off>1)o.off-=1;
  var jh=parseFloat(JETS[o.jet].el.style.height)||150;
  var dirSign=JETS[o.jet].dir==='up'?1:-1;
  var dist=o.off*jh*1.35;
  /* zarah jadi GARIS panjang masa warp */
  var stretch=1+o.off*4.2;
  var fade=o.off<0.08?o.off/0.08:(o.off>0.9?(1-o.off)/0.1:1);
  o.el.style.width=(o.sz*0.9)+'px';
  o.el.style.height=(o.sz*stretch).toFixed(1)+'px';
  o.el.style.borderRadius='99px';
  o.el.style.transform='translate('+(Math.sin(t*4+o.off*5)*o.sway*0.5).toFixed(1)+'px,'+(dirSign*(dist-jh*0.15)).toFixed(1)+'px)';
  o.el.style.opacity=(fade*0.9).toFixed(2);
"""
Q3_ANIM = """
   for(var i=0;i<JETS.length;i++){
    var j=JETS[i];
    var jg=Math.min(1,p*3);
    j.el.style.height=(150+jg*520).toFixed(0)+'px';
    j.el.style.opacity=(p<0.08?p*12:(1-Math.pow(p,2.2))*0.95).toFixed(2);
   }
   /* garis warp memanjang */
   for(var wi=0;wi<WARP.length;wi++){
    var w=WARP[wi];
    var wq=(p*w.spd+w.y)%1;
    w.el.style.height=(w.h*(1+wq*6)).toFixed(0)+'px';
    w.el.style.top=(wq*100).toFixed(1)+'%';
    w.el.style.opacity=(wq<0.2?wq/0.2:(1-wq)*0.75).toFixed(2);
   }
   CORONA.style.transform='scale('+(1+e*2.8).toFixed(2)+')';
   CORONA.style.opacity=(0.8*(1-e*0.8)).toFixed(2);
   CORONA._beam.style.transform='rotate('+(p*900).toFixed(0)+'deg) scale('+(1+e*9).toFixed(2)+')';
   CORONA._beam.style.opacity=(0.92*(1-Math.pow(e,2))).toFixed(2);
   if(CGLOW){CGLOW.style.transform='scale('+(1+e*6).toFixed(2)+')';CGLOW.style.opacity=(0.7*(1-e)).toFixed(2)}
   core.style.transform='scale('+(1+e*26).toFixed(2)+')';
   core.style.boxShadow='0 0 0 '+(1.8*(1-e*0.85)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.8).toFixed(2)+'),0 0 '+(24+e*22).toFixed(0)+'px 6px rgba(183,243,107,'+(0.68*(1-e)).toFixed(2)+'),0 0 95px 30px rgba(183,243,107,'+(0.24*(1-e)).toFixed(2)+')';
"""

# ============ Q4 QUANTUM: teleport rawak, flicker ============
Q4_IDLE = """
  /* flicker: kadang terang kadang malap secara rawak */
  var flick=0.55+Math.random()*0.45;
  flick=Math.round(flick*8)/8;                 /* quantize — rasa digital */
  for(var i=0;i<JETS.length;i++){
   var j=JETS[i];
   j.el.style.height=(150*(0.85+flick*0.3)).toFixed(0)+'px';
   j.el.style.opacity=(0.45+flick*0.45).toFixed(2);
   j.el.style.transform='translateX('+((Math.random()-0.5)*1.6).toFixed(2)+'px)';
  }
  if(CORONA){
   CORONA.style.transform='scale('+(1+(flick-0.6)*0.14).toFixed(3)+')';
   CORONA.style.opacity=(0.35+flick*0.4).toFixed(2);
   /* beam lompat rawak, bukan putar sekata */
   if(Math.random()<0.15)CORONA._beam._ang=Math.random()*360;
   CORONA._beam.style.transform='rotate('+((CORONA._beam._ang||0)).toFixed(0)+'deg)';
   CORONA._beam.style.opacity=(0.3+flick*0.5).toFixed(2);
  }
  if(CGLOW){
   CGLOW.style.transform='scale('+(0.9+flick*0.25).toFixed(3)+')';
   CGLOW.style.opacity=(0.35+flick*0.4).toFixed(2);
  }
  core.style.boxShadow='0 0 0 1.8px rgba(183,243,107,'+(0.5+flick*0.5).toFixed(2)+
    '), 0 0 '+(14+flick*24).toFixed(0)+'px 4px rgba(183,243,107,'+(0.3+flick*0.38).toFixed(2)+
    '), 0 0 88px 26px rgba(183,243,107,'+(0.08+flick*0.2).toFixed(2)+')';
"""
Q4_PART = """
  var o=PARTS[k];
  /* teleport: lompat posisi rawak, bukan aliran */
  if(Math.random()<0.06)o.off=Math.random();
  var jh=parseFloat(JETS[o.jet].el.style.height)||150;
  var dirSign=JETS[o.jet].dir==='up'?1:-1;
  var dist=o.off*jh*1.25;
  var fade=o.off<0.12?o.off/0.12:(o.off>0.88?(1-o.off)/0.12:1);
  o.el.style.width=o.sz+'px';o.el.style.height=o.sz+'px';
  o.el.style.borderRadius=Math.random()<0.3?'2px':'50%';
  o.el.style.background=Math.random()<0.25?'#8ab4ff':'#eaffc4';
  o.el.style.transform='translate('+((Math.random()-0.5)*3).toFixed(1)+'px,'+(dirSign*(dist-jh*0.15)).toFixed(1)+'px)';
  o.el.style.opacity=(fade*0.9).toFixed(2);
"""
Q4_ANIM = """
   for(var i=0;i<JETS.length;i++){
    var j=JETS[i];
    var jg=Math.min(1,p*2.4);
    j.el.style.height=(150+jg*400).toFixed(0)+'px';
    j.el.style.opacity=(p<0.1?p*10:(1-Math.pow(p,2.2))*0.9).toFixed(2);
    j.el.style.transform='translateX('+((Math.random()-0.5)*p*3).toFixed(2)+'px)';
   }
   CORONA.style.transform='scale('+(1+e*2.5).toFixed(2)+')';
   CORONA.style.opacity=(0.72*(1-e*0.78)).toFixed(2);
   CORONA._beam.style.transform='rotate('+((CORONA._beam._ang||0)+p*720).toFixed(0)+'deg) scale('+(1+e*8).toFixed(2)+')';
   CORONA._beam.style.opacity=(0.88*(1-Math.pow(e,2))).toFixed(2);
   if(CGLOW){CGLOW.style.transform='scale('+(1+e*5).toFixed(2)+')';CGLOW.style.opacity=(0.66*(1-e)).toFixed(2)}
   core.style.transform='scale('+(1+e*24).toFixed(2)+')';
   core.style.boxShadow='0 0 0 '+(1.8*(1-e*0.8)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.75).toFixed(2)+'),0 0 '+(20+e*18).toFixed(0)+'px 5px rgba(183,243,107,'+(0.6*(1-e)).toFixed(2)+'),0 0 88px 26px rgba(183,243,107,'+(0.2*(1-e)).toFixed(2)+')';
"""

# ============ Q5 SOLAR WIND: angin berterusan bergelombang ============
Q5_IDLE = """
  /* angin suria: gelombang sinus perlahan merambat sepanjang jet */
  for(var i=0;i<JETS.length;i++){
   var j=JETS[i];
   var wave=1+Math.sin(t*1.3+i*2.6)*0.2;
   j.el.style.height=(150*wave).toFixed(0)+'px';
   var sway=Math.sin(t*1.05+i*2.2)*11+Math.sin(t*0.6+i)*5;
   j.el.style.transform='translateX('+sway.toFixed(1)+'px)';
   j.el.style.opacity=(0.6+Math.sin(t*1.15+i*2.4)*0.28).toFixed(2);
  }
  if(CORONA){
   CORONA.style.transform='scale('+(1+Math.sin(t*1.1)*0.12).toFixed(3)+')';
   CORONA.style.opacity=(0.5+Math.sin(t*1.05)*0.22).toFixed(2);
   CORONA._beam.style.transform='rotate('+(t*40).toFixed(1)+'deg)';
   CORONA._beam.style.opacity=(0.58+Math.sin(t*0.95)*0.2).toFixed(2);
  }
  if(CGLOW){
   CGLOW.style.transform='scale('+(1+Math.sin(t*1.2)*0.14).toFixed(3)+')';
   CGLOW.style.opacity=(0.55+Math.sin(t*1.2+0.6)*0.22).toFixed(2);
  }
  core.style.boxShadow='0 0 0 1.8px rgba(183,243,107,'+(0.88+Math.sin(t*1.1)*0.1).toFixed(2)+
    '), 0 0 '+(20+Math.sin(t*1.05)*8).toFixed(0)+'px 5px rgba(183,243,107,'+(0.5+Math.sin(t*1)*0.16).toFixed(2)+
    '), 0 0 88px 26px rgba(183,243,107,0.21)';
"""
Q5_PART = """
  var o=PARTS[k];
  o.off+=0.0058*o.spd;
  if(o.off>1)o.off-=1;
  var jh=parseFloat(JETS[o.jet].el.style.height)||150;
  var dirSign=JETS[o.jet].dir==='up'?1:-1;
  var dist=o.off*jh*1.25;
  var fade=o.off<0.14?o.off/0.14:(o.off>0.86?(1-o.off)/0.14:1);
  /* gelombang lebar — angin */
  var wx=Math.sin(t*1.6+o.off*10)*o.sway*2.2;
  o.el.style.width=(o.sz*0.85)+'px';o.el.style.height=(o.sz*0.85)+'px';
  o.el.style.transform='translate('+wx.toFixed(1)+'px,'+(dirSign*(dist-jh*0.15)).toFixed(1)+'px)';
  o.el.style.opacity=(fade*0.78).toFixed(2);
"""
Q5_ANIM = """
   for(var i=0;i<JETS.length;i++){
    var j=JETS[i];
    var jg=Math.min(1,p*2.1);
    j.el.style.height=(150+jg*460).toFixed(0)+'px';
    j.el.style.opacity=(p<0.11?p*9:(1-Math.pow(p,2.3))*0.92).toFixed(2);
   }
   CORONA.style.transform='scale('+(1+e*2.7).toFixed(2)+')';
   CORONA.style.opacity=(0.78*(1-e*0.78)).toFixed(2);
   CORONA._beam.style.transform='rotate('+(p*560).toFixed(0)+'deg) scale('+(1+e*8).toFixed(2)+')';
   CORONA._beam.style.opacity=(0.88*(1-Math.pow(e,2))).toFixed(2);
   if(CGLOW){CGLOW.style.transform='scale('+(1+e*5.5).toFixed(2)+')';CGLOW.style.opacity=(0.68*(1-e)).toFixed(2)}
   core.style.transform='scale('+(1+e*25).toFixed(2)+')';
   core.style.boxShadow='0 0 0 '+(1.8*(1-e*0.85)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.78).toFixed(2)+'),0 0 '+(23+e*20).toFixed(0)+'px 5px rgba(183,243,107,'+(0.62*(1-e)).toFixed(2)+'),0 0 90px 27px rgba(183,243,107,'+(0.21*(1-e)).toFixed(2)+')';
"""

VARIANTS = [
    dict(key="q1-pulsar", title="Q1 — Pulsar", name="Pulsar Beat",
         tag="Beat of a dead star.", sub="Denyut pertama, denyut terakhir.",
         hint="denyut TAJAM — jet meluru sekejap setiap 0.65s + cincin denyut", dur=2000,
         snd="sndPulsar", cssx=Q1_CSS, idle=Q1_IDLE, part=Q1_PART, anim=Q1_ANIM,
         build_extra=Q1_BUILD_EXTRA, idlename="PULSAR SHARP PULSE", partmode="bergerak hanya masa denyut"),
    dict(key="q2-nebula", title="Q2 — Nebula Flow", name="Nebula Flow",
         tag="Flow like gas.", sub="Tiada denyut — hanya aliran.",
         hint="aliran LEMBUT organik, 32 zarah, warna bergeser lime→cyan", dur=2100,
         snd="sndNebula", cssx="", idle=Q2_IDLE, part=Q2_PART, anim=Q2_ANIM,
         build_extra="", idlename="NEBULA SMOOTH FLOW", partmode="aliran berterusan lembut"),
    dict(key="q3-warp", title="Q3 — Warp Drive", name="Warp Drive",
         tag="Faster than light.", sub="Jet memanjang, masa melengkung.",
         hint="jet LAJU + 10 garis warp memanjang + zarah jadi garis", dur=1900,
         snd="sndWarp", cssx=Q3_CSS, idle=Q3_IDLE, part=Q3_PART, anim=Q3_ANIM,
         build_extra=Q3_BUILD_EXTRA, idlename="WARP HIGH SPEED", partmode="garis stretch laju"),
    dict(key="q4-quantum", title="Q4 — Quantum", name="Quantum Flicker",
         tag="Neither here nor there.", sub="Zarah melompat antara keadaan.",
         hint="FLICKER digital + zarah teleport rawak (bukan aliran)", dur=1900,
         snd="sndQuantum", cssx="", idle=Q4_IDLE, part=Q4_PART, anim=Q4_ANIM,
         build_extra="", idlename="QUANTUM RANDOM FLICKER", partmode="teleport rawak"),
    dict(key="q5-wind", title="Q5 — Solar Wind", name="Solar Wind",
         tag="The wind never stops.", sub="Angin suria merambat tanpa henti.",
         hint="GELOMBANG sinus lebar — jet bergoyang 11px, zarah bergelombang", dur=2100,
         snd="sndWind", cssx="", idle=Q5_IDLE, part=Q5_PART, anim=Q5_ANIM,
         build_extra="", idlename="SOLAR WIND WAVE", partmode="gelombang lebar"),
]

for st in VARIANTS:
    html = (TPL
            .replace("%%CSSX%%", st["cssx"])
            .replace("%%TITLE%%", st["title"])
            .replace("%%NAME%%", st["name"])
            .replace("%%HINT%%", st["hint"])
            .replace("%%TAG%%", st["tag"])
            .replace("%%SUB%%", st["sub"])
            .replace("%%DUR%%", str(st["dur"]))
            .replace("%%SNDFN%%", st["snd"])
            .replace("%%BUILDEXTRA%%", st["build_extra"])
            .replace("%%IDLENAME%%", st["idlename"])
            .replace("%%IDLE%%", st["idle"])
            .replace("%%PARTMODE%%", st["partmode"])
            .replace("%%PARTICLE%%", st["part"])
            .replace("%%ANIM%%", st["anim"]))
    # inject build_extra selepas struktur quasar dibina
    html = html.replace("var c=document.createElement('div');c.className='corona';zh.appendChild(c);CORONA=c;",
                        "var c=document.createElement('div');c.className='corona';zh.appendChild(c);CORONA=c;", 1)
    assert "%%" not in html, "placeholder tinggal: " + st["key"]
    # selit build_extra sebelum idle loop
    html = html.replace("/* ===== IDLE LOOP",
                        st["build_extra"] + "\n/* ===== IDLE LOOP", 1)
    (OUT / f'zoom-{st["key"]}.html').write_text(html, encoding="utf-8")
    print("wrote", f'zoom-{st["key"]}.html')
