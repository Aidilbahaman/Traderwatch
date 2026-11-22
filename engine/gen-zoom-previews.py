#!/usr/bin/env python3
"""5 zoom preview — BLACKHOLE BETUL: teras HITAM, rim cahaya nipis.

Prinsip fizik: bila jatuh masuk blackhole, yang mengembang ialah KEGELAPAN,
bukan cahaya. Cahaya (rim/accretion) hanya nampak di pinggir dan makin nipis
sehingga hilang (light cannot escape). Akhir: skrin hitam penuh.

Setiap style mekanik berbeza tapi semua kekal hitam.
"""
import pathlib

OUT = pathlib.Path("/home/ubuntu/web/Traderwatch-repo/preview")

TPL = """<!doctype html><html lang="ms"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<style>
:root{--lime:#b7f36b;--card:#111612;--card2:#171e18;--line:#222b23;--muted:#8a978c;--text:#eef3ee;--onlime:#10150b;--red:#ff777d;--blue:#8ab4ff;--orange:#ffc16b}
*{box-sizing:border-box;margin:0}
body{background:#0a0e0b;color:var(--text);font:14px -apple-system,sans-serif}
.hint{position:fixed;top:0;left:0;right:0;z-index:999;background:#171e18ee;color:var(--muted);font-size:10.5px;padding:8px 14px;text-align:center;border-bottom:1px solid var(--line)}
.hint b{color:var(--lime)}
.replay{position:fixed;bottom:14px;right:14px;z-index:999;background:var(--card2);border:1px solid var(--line);color:var(--lime);font:700 10px inherit;padding:8px 14px;border-radius:99px;cursor:pointer}
.phone{width:390px;max-width:100%;height:800px;max-height:100vh;margin:0 auto;position:relative;overflow:hidden;background:#000}
#intro{position:absolute;inset:0;z-index:10;display:grid;place-items:center;cursor:pointer;overflow:hidden;background:#040705}
#decor{position:absolute;inset:0;z-index:2;pointer-events:none;overflow:hidden}
#decor.persp{perspective:700px;perspective-origin:50% 50%}
.dec{position:absolute;left:50%;top:50%;will-change:transform,opacity;transform-origin:50% 50%}
/* ===== BLACKHOLE: teras HITAM, rim cahaya nipis ===== */
#zh{position:relative;width:200px;height:200px;display:grid;place-items:center;z-index:6;
 will-change:transform;transform-origin:50% 50%}
#zh .core{position:relative;width:96px;height:96px;border-radius:50%;background:#000;z-index:7;
 box-shadow:0 0 0 1.6px #b7f36b, 0 0 14px 2px #b7f36baa, 0 0 60px 16px #b7f36b3d;
 will-change:transform,box-shadow}
#zh .photon{position:absolute;width:118px;height:118px;border-radius:50%;
 border:1px solid #b7f36b66;z-index:5;will-change:transform,opacity}
#zh .disk{position:absolute;width:164px;height:46px;border-radius:50%;z-index:4;
 background:conic-gradient(from 0deg,transparent,#b7f36b88,transparent 40%,#8ab4ff66,transparent 70%,#b7f36b66);
 filter:blur(7px);opacity:.65;will-change:transform,opacity}
#zlab{position:absolute;z-index:40;top:42%;left:0;right:0;text-align:center;
 font:900 14px monospace;letter-spacing:3px;color:#b7f36b;opacity:0;
 text-shadow:0 0 16px #b7f36b,0 0 36px #b7f36b77;pointer-events:none}
#zbar{position:absolute;z-index:40;bottom:70px;left:60px;right:60px;height:3px;border-radius:99px;
 background:#b7f36b1f;opacity:0;overflow:hidden}
#zbar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#b7f36b,#eaffc4);border-radius:99px}
.brand{position:absolute;top:58px;left:0;right:0;text-align:center;font-size:12px;font-weight:900;letter-spacing:2px;color:var(--lime);z-index:9}
.brand span{color:var(--text)}
.itxt{position:absolute;bottom:140px;text-align:center;z-index:9;padding:0 30px;left:0;right:0}
.itxt b{display:block;font-size:24px;font-weight:900}
.itxt small{display:block;color:var(--muted);font-size:11.5px;margin-top:8px;line-height:1.6}
.tap{position:absolute;bottom:44px;left:0;right:0;text-align:center;font-size:10.5px;color:var(--lime);font-weight:800;letter-spacing:1.5px;z-index:9}
#void{position:absolute;inset:0;z-index:15;background:#000;opacity:0;transition:opacity .25s;pointer-events:none}
#void.on{opacity:1}
#on{position:absolute;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:22px;
 background:rgba(0,0,0,.94);backdrop-filter:blur(10px);opacity:0;pointer-events:none;transition:opacity .5s}
#on.show{opacity:1;pointer-events:auto}
.card{width:100%;max-width:360px;background:#0d120e;border:1px solid #b7f36b3d;border-radius:24px;
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
%%CSSX%%
</style></head><body>
<div class="hint"><b>%%NAME%%</b> — %%HINT%%</div>
<button class="replay" onclick="location.reload()">↻ Replay</button>
<div class="phone">
 <div id="intro">
  <div id="decor" class="%%DECORCLS%%"></div>
  <div class="brand">✦ <span>TraderWatch</span></div>
  <div id="zh">
   <div class="disk"></div>
   <div class="photon"></div>
   <div class="core"></div>
  </div>
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
function nz(c,sec){var b=c.createBuffer(1,c.sampleRate*sec,c.sampleRate),d=b.getChannelData(0);
 for(var i=0;i<d.length;i++)d[i]=Math.random()*2-1;return b}
function sndTunnel(){var c=ac(),t=c.currentTime;
 var n=c.createBufferSource();n.buffer=nz(c,1.8);
 var bp=c.createBiquadFilter();bp.type='bandpass';bp.Q.value=1.4;
 bp.frequency.setValueAtTime(160,t);bp.frequency.exponentialRampToValueAtTime(2400,t+1.3);
 var g=c.createGain();g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.3,t+.2);
 g.gain.exponentialRampToValueAtTime(.001,t+1.8);
 n.connect(bp);bp.connect(g);g.connect(c.destination);n.start(t);n.stop(t+1.9);
 var o=c.createOscillator();o.type='sine';o.frequency.setValueAtTime(96,t);
 o.frequency.exponentialRampToValueAtTime(22,t+1.4);
 var og=c.createGain();og.gain.setValueAtTime(.0001,t);og.gain.exponentialRampToValueAtTime(.55,t+.12);
 og.gain.exponentialRampToValueAtTime(.001,t+1.7);
 o.connect(og);og.connect(c.destination);o.start(t);o.stop(t+1.8)}
function sndSwirl(){var c=ac(),t=c.currentTime;
 for(var i=0;i<4;i++){var o=c.createOscillator();o.type='triangle';
  var f0=520-i*90;o.frequency.setValueAtTime(f0,t);o.frequency.exponentialRampToValueAtTime(f0*0.35,t+1.4);
  var g=c.createGain();g.gain.setValueAtTime(.0001,t+i*.06);
  g.gain.exponentialRampToValueAtTime(.09,t+i*.06+.12);g.gain.exponentialRampToValueAtTime(.001,t+1.5);
  o.connect(g);g.connect(c.destination);o.start(t+i*.06);o.stop(t+i*.06+1.55)}
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(70,t);
 s.frequency.exponentialRampToValueAtTime(24,t+1.5);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.5,t+.2);
 sg.gain.exponentialRampToValueAtTime(.001,t+1.7);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+1.8)}
function sndCollapse(){var c=ac(),t=c.currentTime;
 var n=c.createBufferSource();n.buffer=nz(c,1.6);
 var lp=c.createBiquadFilter();lp.type='lowpass';lp.frequency.setValueAtTime(2800,t);
 lp.frequency.exponentialRampToValueAtTime(120,t+1.5);
 var g=c.createGain();g.gain.setValueAtTime(.001,t);g.gain.exponentialRampToValueAtTime(.24,t+.3);
 g.gain.exponentialRampToValueAtTime(.001,t+1.6);
 n.connect(lp);lp.connect(g);g.connect(c.destination);n.start(t);n.stop(t+1.7);
 var o=c.createOscillator();o.type='sine';o.frequency.setValueAtTime(58,t);
 o.frequency.exponentialRampToValueAtTime(20,t+1.5);
 var og=c.createGain();og.gain.setValueAtTime(.0001,t);og.gain.exponentialRampToValueAtTime(.55,t+.35);
 og.gain.exponentialRampToValueAtTime(.001,t+1.75);
 o.connect(og);og.connect(c.destination);o.start(t);o.stop(t+1.85)}
function sndShadow(){var c=ac(),t=c.currentTime;
 var o=c.createOscillator();o.type='sawtooth';o.frequency.setValueAtTime(320,t);
 o.frequency.exponentialRampToValueAtTime(44,t+1.3);
 var f=c.createBiquadFilter();f.type='lowpass';f.frequency.setValueAtTime(1800,t);
 f.frequency.exponentialRampToValueAtTime(200,t+1.3);
 var g=c.createGain();g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.14,t+.18);
 g.gain.exponentialRampToValueAtTime(.001,t+1.5);
 o.connect(f);f.connect(g);g.connect(c.destination);o.start(t);o.stop(t+1.55);
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(80,t);
 s.frequency.exponentialRampToValueAtTime(26,t+1.4);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.45,t+.25);
 sg.gain.exponentialRampToValueAtTime(.001,t+1.65);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+1.75)}
function sndFold(){var c=ac(),t=c.currentTime;
 for(var i=0;i<5;i++){var o=c.createOscillator();o.type='square';
  o.frequency.value=180+i*70;var g=c.createGain();var tt=t+i*.14;
  g.gain.setValueAtTime(.0001,tt);g.gain.exponentialRampToValueAtTime(.05,tt+.02);
  g.gain.exponentialRampToValueAtTime(.001,tt+.35);
  o.connect(g);g.connect(c.destination);o.start(tt);o.stop(tt+.38)}
 var s=c.createOscillator();s.type='sine';s.frequency.setValueAtTime(110,t);
 s.frequency.exponentialRampToValueAtTime(24,t+1.5);
 var sg=c.createGain();sg.gain.setValueAtTime(.0001,t);sg.gain.exponentialRampToValueAtTime(.5,t+.3);
 sg.gain.exponentialRampToValueAtTime(.001,t+1.75);
 s.connect(sg);sg.connect(c.destination);s.start(t);s.stop(t+1.85)}

var DECOR=document.getElementById('decor');
%%BUILD%%

var busy=false;
(function(){
 var zh=document.getElementById('zh'),
     core=zh.querySelector('.core'),photon=zh.querySelector('.photon'),disk=zh.querySelector('.disk'),
     zlab=document.getElementById('zlab'),zbar=document.getElementById('zbar'),zbarI=zbar.querySelector('i'),
     voidEl=document.getElementById('void'),on=document.getElementById('on'),intro=document.getElementById('intro');
 var DUR=%%DUR%%;
 intro.onclick=function(){
  if(busy)return;busy=true;
  try{%%SND%%()}catch(e){}
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

STYLES = [
    # ---------- Z1: cincin 3D lalu kamera, teras hitam mengembang ----------
    dict(key="z1-tunnel", title="Z1 — Event Horizon", name="Event Horizon",
         tag="Cross the horizon.", sub="Tiada apa yang kembali dari sini.",
         hint="9 cincin 3D + teras hitam menelan skrin. 🔊 bass drop", dur=2100,
         snd="sndTunnel", decorcls="persp", cssx="",
         build="""
var RINGS=[];
(function(){
 for(var i=0;i<9;i++){
  var r=document.createElement('div');r.className='dec';
  r.style.width='250px';r.style.height='250px';
  r.style.marginLeft='-125px';r.style.marginTop='-125px';
  r.style.borderRadius='50%';
  r.style.border='1.5px solid rgba(183,243,107,'+(0.5-i*0.045)+')';
  r.style.opacity='0';
  DECOR.appendChild(r);RINGS.push(r);
 }
})();""",
         anim="""
   for(var i=0;i<RINGS.length;i++){
    var q=(p*1.5 - i*0.072);
    if(q<0||q>1){RINGS[i].style.opacity='0';continue}
    var z=-1000+q*1650, s=0.2+q*2.1;
    RINGS[i].style.transform='translateZ('+z.toFixed(0)+'px) scale('+s.toFixed(2)+')';
    RINGS[i].style.opacity=(q<0.1?q/0.1:(q>0.9?(1-q)/0.1:1)*0.75).toFixed(2);
   }
   /* teras HITAM mengembang — ini yang menelan skrin */
   core.style.transform='scale('+(1+e*26).toFixed(2)+')';
   photon.style.transform='scale('+(1+e*13).toFixed(2)+')';
   photon.style.opacity=(1-e).toFixed(2);
   disk.style.transform='rotate('+(p*420).toFixed(0)+'deg) scale('+(1+e*6).toFixed(2)+')';
   disk.style.opacity=(0.65*(1-e*0.95)).toFixed(2);"""),

    # ---------- Z2: accretion disk berpusar, zarah redshift jatuh masuk ----------
    dict(key="z2-swirl", title="Z2 — Accretion Swirl", name="Accretion Swirl",
         tag="Spiral inward.", sub="Jisim berputar sebelum lenyap.",
         hint="54 zarah orbit makin laju + redshift lime→merah. 🔊 swirl + bass", dur=2000,
         snd="sndSwirl", decorcls="", cssx="",
         build="""
var PARTS=[];
(function(){
 for(var i=0;i<54;i++){
  var sz=1.8+Math.random()*2.6;
  var d=document.createElement('div');d.className='dec';
  d.style.width=sz+'px';d.style.height=sz+'px';
  d.style.marginLeft=(-sz/2)+'px';d.style.marginTop=(-sz/2)+'px';
  d.style.borderRadius='50%';
  d.style.background='#b7f36b';d.style.opacity='0';d.style.zIndex='8';
  DECOR.appendChild(d);
  PARTS.push({el:d,a:Math.random()*Math.PI*2,r:88+Math.random()*95,
              sp:0.85+Math.random()*0.85,sz:sz});
 }
})();""",
         anim="""
   for(var i=0;i<PARTS.length;i++){
    var o=PARTS[i];
    /* orbit laju makin dalam */
    var ang=o.a + p*(5.5+o.sp*4);
    var rad=o.r*(1-p*0.96);
    var x=Math.cos(ang)*rad, y=Math.sin(ang)*rad*0.55;
    /* redshift: lime → orange → merah → hilang */
    var red=Math.min(1,p*1.5);
    var col='rgb('+Math.round(183+72*red)+','+Math.round(243-140*red)+','+Math.round(107-60*red)+')';
    o.el.style.background=col;
    o.el.style.boxShadow='0 0 '+ (4+red*10).toFixed(0) +'px '+col;
    o.el.style.transform='translate('+x.toFixed(1)+'px,'+y.toFixed(1)+'px) scale('+(1-p*0.6).toFixed(2)+')';
    o.el.style.opacity=(p<0.05?0.9:(0.9*(1-p))).toFixed(2);
   }
   /* teras hitam mengembang perlahan, disk berputar */
   core.style.transform='scale('+(1+e*24).toFixed(2)+')';
   disk.style.transform='rotate('+(p*540).toFixed(0)+'deg) scale('+(1+e*7).toFixed(2)+')';
   disk.style.opacity=(0.7*(1-e*0.9)).toFixed(2);
   photon.style.transform='scale('+(1+e*14).toFixed(2)+')';
   photon.style.opacity=(0.6*(1-e)).toFixed(2);"""),

    # ---------- Z3: photon ring collapse — cincin mengecil MASUK ke teras ----------
    dict(key="z3-collapse", title="Z3 — Photon Collapse", name="Photon Collapse",
         tag="Light gives way.", sub="Cahaya terakhir sebelum gelap.",
         hint="3 cincin photon menguncup masuk teras hitam. 🔊 collapse", dur=1900,
         snd="sndCollapse", decorcls="", cssx="",
         build="""
var RINGS2=[];
(function(){
 for(var i=0;i<3;i++){
  var r=document.createElement('div');r.className='dec';
  var w=260-i*42;
  r.style.width=w+'px';r.style.height=w+'px';
  r.style.marginLeft=(-w/2)+'px';r.style.marginTop=(-w/2)+'px';
  r.style.borderRadius='50%';
  r.style.border='1.5px solid rgba(183,243,107,'+(0.45-i*0.1)+')';
  r.style.opacity='0.7';r.style.zIndex='4';
  DECOR.appendChild(r);RINGS2.push(r);
 }
})();""",
         anim="""
   /* cincin menguncup KE DALAM teras (bukan mengembang) */
   for(var i=0;i<RINGS2.length;i++){
    var delay=i*0.12;
    var q=Math.max(0,Math.min(1,(p-delay)/(1-delay)));
    var sc=1-q*0.94;
    RINGS2[i].style.transform='scale('+sc.toFixed(3)+') rotate('+(-q*220).toFixed(0)+'deg)';
    RINGS2[i].style.opacity=(0.7*Math.pow(1-q,2)).toFixed(2);
   }
   core.style.transform='scale('+(1+e*28).toFixed(2)+')';
   /* rim makin nipis sehingga hilang */
   core.style.boxShadow='0 0 0 '+(1.6*(1-e*0.9)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.85).toFixed(2)+'), 0 0 '+(14+e*10).toFixed(0)+'px 2px rgba(183,243,107,'+(0.55*(1-e)).toFixed(2)+'), 0 0 60px 16px rgba(183,243,107,'+(0.24*(1-e)).toFixed(2)+')';
   photon.style.transform='scale('+(1+e*18).toFixed(2)+')';
   photon.style.opacity=(0.65*Math.pow(1-e,1.5)).toFixed(2);
   disk.style.opacity=(0.6*(1-e*1.4)>0?0.6*(1-e*1.4):0).toFixed(2);"""),

    # ---------- Z4: shadow bloom — bayang hitam mekar + shockwave nipis ----------
    dict(key="z4-shadow", title="Z4 — Shadow Bloom", name="Shadow Bloom",
         tag="The dark takes hold.", sub="Bayang membesar dari satu titik.",
         hint="bayang hitam mekar + shockwave nipis. 🔊 dark swell", dur=1850,
         snd="sndShadow", decorcls="", cssx="",
         build="""
var SHOCK=[];
(function(){
 for(var i=0;i<2;i++){
  var s=document.createElement('div');s.className='dec';
  s.style.width='120px';s.style.height='120px';
  s.style.marginLeft='-60px';s.style.marginTop='-60px';
  s.style.borderRadius='50%';
  s.style.border='1.5px solid rgba(183,243,107,.55)';
  s.style.opacity='0';s.style.zIndex='8';
  DECOR.appendChild(s);SHOCK.push(s);
 }
 var sh=document.createElement('div');sh.className='dec';
 sh.style.width='70px';sh.style.height='70px';
 sh.style.marginLeft='-35px';sh.style.marginTop='-35px';
 sh.style.borderRadius='50%';
 sh.style.background='radial-gradient(circle, rgba(183,243,107,.28), transparent 70%)';
 sh.style.opacity='0';sh.style.zIndex='3';
 DECOR.appendChild(sh);SHOCK.push(sh);
})();""",
         anim="""
   /* shockwave: 2 denyut nipis memancar keluar */
   for(var i=0;i<2;i++){
    var q=Math.max(0,Math.min(1,(p-i*0.16)/0.7));
    var sc=1+q*9;
    SHOCK[i].style.transform='scale('+sc.toFixed(2)+')';
    SHOCK[i].style.opacity=(q<0.82?Math.min(1,q*4)*0.5*(1-q):0).toFixed(2);
   }
   /* halo mekar */
   if(SHOCK[2]){
    SHOCK[2].style.transform='scale('+(1+e*9).toFixed(2)+')';
    SHOCK[2].style.opacity=(0.5*(1-e*1.3)>0?0.5*(1-e*1.3):0).toFixed(2);
   }
   /* bayang HITAM utama mengembang */
   core.style.transform='scale('+(1+e*30).toFixed(2)+')';
   core.style.boxShadow='0 0 0 '+(1.6*(1-e*0.8)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.7).toFixed(2)+'), 0 0 '+(16+e*14).toFixed(0)+'px 3px rgba(183,243,107,'+(0.5*(1-e)).toFixed(2)+'), 0 0 70px 20px rgba(183,243,107,'+(0.2*(1-e)).toFixed(2)+')';
   photon.style.transform='scale('+(1+e*16).toFixed(2)+')';
   photon.style.opacity=(0.5*(1-e*1.2)>0?0.5*(1-e*1.2):0).toFixed(2);
   disk.style.opacity=(0.55*(1-e*1.1)>0?0.55*(1-e*1.1):0).toFixed(2);"""),

    # ---------- Z5: fold collapse — panel gelap berlipat masuk ----------
    dict(key="z5-fold", title="Z5 — Void Fold", name="Void Fold",
         tag="Fold into the void.", sub="Setiap lapisan dilipat, lalu lenyap.",
         hint="8 panel berlipat masuk + teras gelap. 🔊 panel snaps", dur=1950,
         snd="sndFold", decorcls="", cssx="",
         build="""
var PANELS=[];
(function(){
 for(var i=0;i<8;i++){
  var pn=document.createElement('div');pn.className='dec';
  var w=150;
  pn.style.width=w+'px';pn.style.height=(w*0.52)+'px';
  pn.style.marginLeft=(-w/2)+'px';pn.style.marginTop=(-w*0.26)+'px';
  pn.style.background='linear-gradient(135deg, rgba(20,28,21,.95), rgba(8,12,9,.98))';
  pn.style.border='1px solid rgba(183,243,107,.22)';
  pn.style.borderRadius='10px';
  pn.style.opacity='0';pn.style.zIndex=String(3+i%3);
  DECOR.appendChild(pn);
  PANELS.push({el:pn,a:i*(Math.PI*2/8)});
 }
})();""",
         anim="""
   for(var i=0;i<PANELS.length;i++){
    var pn=PANELS[i];
    var q=Math.max(0,Math.min(1,(p-i*0.03)/0.8));
    /* panel berkumpul ke tengah sambil berputar */
    var ang=pn.a + q*2.2;
    var rad=190*(1-q*0.92);
    var x=Math.cos(ang)*rad, y=Math.sin(ang)*rad*0.85;
    /* lipat: rotateY mengecil (perspektif lipatan) */
    var fold=1-q*0.98;
    pn.el.style.transform='translate('+x.toFixed(1)+'px,'+y.toFixed(1)+'px) '
      +'rotate('+(q*55).toFixed(0)+'deg) rotateY('+(q*82).toFixed(0)+'deg) '
      +'scale('+(fold*0.9+0.1).toFixed(3)+')';
    pn.el.style.opacity=(q<0.05?0:(1-q*1.05)>0?(1-q*1.05):0).toFixed(2);
   }
   core.style.transform='scale('+(1+e*26).toFixed(2)+')';
   core.style.boxShadow='0 0 0 '+(1.6*(1-e*0.8)).toFixed(2)+'px rgba(183,243,107,'+(1-e*0.7).toFixed(2)+'), 0 0 '+(15+e*12).toFixed(0)+'px 3px rgba(183,243,107,'+(0.48*(1-e)).toFixed(2)+'), 0 0 65px 18px rgba(183,243,107,'+(0.18*(1-e)).toFixed(2)+')';
   photon.style.transform='scale('+(1+e*15).toFixed(2)+')';
   photon.style.opacity=(0.55*(1-e*1.2)>0?0.55*(1-e*1.2):0).toFixed(2);
   disk.style.transform='rotate('+(p*300).toFixed(0)+'deg)';
   disk.style.opacity=(0.5*(1-e*1.1)>0?0.5*(1-e*1.1):0).toFixed(2);"""),
]

for st in STYLES:
    html = (TPL
            .replace("%%CSSX%%", st["cssx"])
            .replace("%%TITLE%%", st["title"])
            .replace("%%NAME%%", st["name"])
            .replace("%%HINT%%", st["hint"])
            .replace("%%DECORCLS%%", st["decorcls"])
            .replace("%%TAG%%", st["tag"])
            .replace("%%SUB%%", st["sub"])
            .replace("%%BUILD%%", st["build"])
            .replace("%%ANIM%%", st["anim"])
            .replace("%%DUR%%", str(st["dur"]))
            .replace("%%SND%%", st["snd"]))
    assert "%%" not in html, "placeholder tinggal: " + st["key"]
    (OUT / f'zoom-{st["key"]}.html').write_text(html, encoding="utf-8")
    print("wrote", f'zoom-{st["key"]}.html')
