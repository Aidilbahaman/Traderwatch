# Panduan Tukar Animasi Background

Fail: `members-apple-demo.html`
Blok animasi: **baris 912–958** (fungsi `tick`)
Spot CSS: **baris 54–61** (`.s1` … `.s4`)

---

## 3 tombol utama

### 1. Kelajuan — baris 929

```js
var durs = [11000, 14000, 12500, 16000];  // milisaat
```

| Nilai | Rasa |
|---|---|
| `7000–9000` | laju, hampir gelisah |
| `11000–16000` | **sekarang** — tenang tapi jelas |
| `20000–30000` | perlahan, mewah |
| `40000+` | hampir tak nampak |

Setiap spot ada tempoh sendiri. Jangan samakan semua — kalau sama, corak berulang serentak dan nampak mekanikal.

### 2. Laluan — baris 923–928

```js
var paths = [
  [[0,0,1.00], [30,21,1.20], [56,9,1.06]],
  //  mula        tengah        hujung
  //  [dx%, dy%, scale]
];
```

- `dx`, `dy` — peratus dari saiz spot sendiri (bukan skrin)
- `scale` — 0.88 hingga 1.20 selamat; lebih dari itu nampak melompat
- 3 titik = 2 segmen. Boleh tambah jadi 4–5 titik, tetapi perlu ubah `tick` (lihat bawah)

### 3. Rupa spot — baris 54–61

```css
#bgslate .s1{width:58vmax;height:58vmax;left:-16vmax;top:-18vmax;
  background:radial-gradient(circle at 50% 50%,
    rgba(74,168,255,.85) 0%,
    rgba(74,168,255,.42) 26%,
    rgba(74,168,255,.14) 52%,
    rgba(74,168,255,0) 74%)}
```

Ubah `rgba()` untuk tukar warna. Kekalkan 4 stop supaya tepi lembut — kalau guna 2 stop, nampak bulatan keras.

---

## Preset sedia guna

### A. Arus menegak (seperti asap naik)

```js
var paths = [
  [[0,40,1.00],[6,-10,1.10],[2,-55,1.04]],
  [[0,50,1.06],[-8,-8,0.94],[-4,-60,1.10]],
  [[0,45,0.96],[9,-14,1.14],[3,-58,1.00]],
  [[0,55,1.08],[-10,-6,0.92],[-5,-62,1.12]]
];
var durs = [14000, 17000, 15500, 19000];
```

### B. Putaran orbit (spot mengelilingi pusat)

Perlu ubah `tick` — ganti `translate3d` dengan `rotate`:

```js
function tick(now){
  if(paused){ requestAnimationFrame(tick); return; }
  for(var i=0;i<spots.length;i++){
    var ang = ((now - t0) / durs[i]) * Math.PI * 2 + i * 1.57;
    var r = 18 + i * 4;                        // radius %
    var x = Math.cos(ang) * r;
    var y = Math.sin(ang) * r;
    var sc = 1 + Math.sin(ang * 2) * 0.08;     // bernafas
    spots[i].style.transform =
      'translate3d('+x.toFixed(2)+'%,'+y.toFixed(2)+'%,0) scale('+sc.toFixed(3)+')';
  }
  requestAnimationFrame(tick);
}
```

### C. Denyut lembut (spot tak bergerak, cuma membesar-mengecil)

```js
function tick(now){
  if(paused){ requestAnimationFrame(tick); return; }
  for(var i=0;i<spots.length;i++){
    var t = ((now - t0) / durs[i]) % 1;
    var sc = 1 + Math.sin(t * Math.PI * 2) * 0.14;
    spots[i].style.transform = 'scale('+sc.toFixed(3)+')';
  }
  requestAnimationFrame(tick);
}
var durs = [6000, 7500, 6800, 8200];
```

### D. Ombak mendatar (spot bergerak kiri-kanan sahaja)

```js
var paths = [
  [[-22,0,1.00],[0,0,1.08],[22,0,1.00]],
  [[20,0,1.04],[-4,0,0.96],[-24,0,1.04]],
  [[-18,0,0.98],[2,0,1.10],[20,0,0.98]],
  [[24,0,1.06],[0,0,0.94],[-20,0,1.06]]
];
var durs = [9000, 11000, 10000, 13000];
```

---

## Kalau tambah titik laluan (4+ titik)

Tukar bahagian `seg` dalam `tick`:

```js
/* versi 3 titik (sekarang) */
var seg = e < 0.5 ? 0 : 1;
var lt = seg === 0 ? e*2 : (e-0.5)*2;

/* versi N titik */
var n = kf.length - 1;
var seg = Math.min(Math.floor(e * n), n - 1);
var lt = e * n - seg;
```

---

## Perkara yang JANGAN buat

| Jangan | Sebab |
|---|---|
| `contain: paint` pada spot | Chrome beku repaint — nampak statik walaupun animasi jalan |
| `filter: blur(72px)` besar | 4 spot × blur = FPS jatuh ke 8 |
| `mix-blend-mode` pada grain | Paksa compositing seluruh page setiap frame |
| `backdrop-filter` pada banyak kad | Setiap kad blur semula setiap frame |
| `animation:` CSS untuk spot | Chrome boleh beku pada sesetengah GPU/driver |
| `vmax` dalam `transform` keyframes | Chrome tak recompute konsisten |

---

## Ujian selepas ubah

```js
// tampal di console
const s = document.querySelector('#bgslate .s1');
let a = s.style.transform;
setTimeout(()=>{
  console.log('bergerak:', a !== s.style.transform);
  console.log('sebelum:', a);
  console.log('selepas:', s.style.transform);
}, 1500);
```

Ukur FPS:

```js
let f = 0, t = performance.now();
(function loop(){
  f++;
  if(performance.now() - t < 3000) requestAnimationFrame(loop);
  else console.log('FPS:', Math.round(f / 3));
})();
```

Sasaran: **55–60 fps**.
