/* TraderWatch — Global reach globe.
   Real earth landmass from globe-land.js (0.5 deg RLE mask, Natural Earth).
   Continents with visitors glow and pulse; the rest of the world stays dim
   so the eye is drawn to where the audience actually is.

   Tuning:
     FLIP_Y  -> false = North up (standard), true = South up
     SPIN    -> radians per second around the polar axis
   */
(function () {
  var FLIP_Y = false;   // FIXED: North-up standard
  var SPIN = 0.22;     // polar rotation speed

  var D = window.TW_VISITORS || [];
  var TOTAL = window.TW_TOTAL || 0;

  // counter
  var el = document.getElementById("gTotal");
  if (el) {
    var n = 0, step = Math.max(1, Math.ceil(TOTAL / 45));
    var t = setInterval(function () {
      n += step;
      if (n >= TOTAL) { n = TOTAL; clearInterval(t); }
      el.textContent = n.toLocaleString();
    }, 28);
  }

  var cv = document.getElementById("gDots");
  if (!cv) return;
  var ctx = cv.getContext("2d"), W = cv.width, H = cv.height, R = W / 2;
  var LAND = window.TW_LAND;
  if (!LAND) return;

  // ---- continent of a coordinate ----
  function continent(lat, lon) {
    if (lat >= 36 && lon >= -12 && lon <= 45) return "EU";
    if (lat >= 36 && lon > 45) return "AS";
    if (lat >= 12 && lon >= -170 && lon <= -52) return "NA";
    if (lat < 12 && lon >= -82 && lon <= -33) return "SA";
    if (lat >= -36 && lat < 36 && lon >= -20 && lon <= 52) return "AF";
    if (lat >= -11 && lat <= 7 && lon >= 95 && lon <= 120) return "AS";
    if (lat >= -11 && lat <= 21 && lon >= 120 && lon <= 127) return "AS";
    if (lat >= 21 && lat <= 26 && lon >= 119 && lon <= 123) return "AS";
    if (lat >= 29 && lat <= 39 && lon >= 60 && lon <= 76) return "AS";
    if (lat < 12 && lon > 95) return "OC";
    if (lat < 12 && lon >= 52 && lon <= 95) return "AS";
    return "XX";
  }

  var P = []; var CONT = [];
  for (var r = 0; r < LAND.h; r++) {
    var runs = LAND.rows[r];
    var lat = 90 - (r + 0.5) * LAND.res;
    for (var k = 0; k < runs.length; k++) {
      var start = runs[k][0], len = runs[k][1];
      for (var c = start; c < start + len; c++) {
        var lon = -180 + (c + 0.5) * LAND.res;
        var phi = (90 - lat) * Math.PI / 180, the = (lon + 180) * Math.PI / 180;
        P.push(Math.sin(phi) * Math.cos(the), Math.cos(phi), Math.sin(phi) * Math.sin(the));
        CONT.push(continent(lat, lon));
      }
    }
  }
  var N = CONT.length;
  var px = new Float32Array(N), py = new Float32Array(N), pz = new Float32Array(N);

  var ACTIVE = {};
  D.forEach(function (d) { ACTIVE[continent(d.lat, d.lon)] = true; });

  var rot = 0;
  function draw() {
    ctx.clearRect(0, 0, W, H);
    rot = Date.now() / 1000 * SPIN;
    var ct = Math.cos(rot), st = Math.sin(rot);
    var pulse = 0.5 + 0.5 * Math.sin(Date.now() / 1000 * 1.9);

    var g = ctx.createRadialGradient(R * 0.66, R * 0.6, R * 0.06, R, R, R * 1.02);
    g.addColorStop(0, "#131c15"); g.addColorStop(0.7, "#0c120e"); g.addColorStop(1, "#060907");
    ctx.beginPath(); ctx.arc(R, R, R * 0.985, 0, 6.283); ctx.fillStyle = g; ctx.fill();

    for (var i = 0; i < N; i++) {
      var x0 = P[i * 3], y0 = P[i * 3 + 1], z0 = P[i * 3 + 2];
      var x = x0 * ct + z0 * st;
      var z = -x0 * st + z0 * ct;
      if (z < -0.9) { pz[i] = 0; continue; } 
      px[i] = R + x * R * 0.96;
      py[i] = (FLIP_Y ? R + y0 : R - y0) * R * 0.96;
      pz[i] = z;
    }

    ctx.beginPath();
    for (var i = 0; i < N; i++) {
      if (pz[i] <= -0.9 || !ACTIVE[CONT[i]]) continue;
      var z = pz[i], a = Math.min(1, (z + 0.5) * 1.6);
      var s = 1.5 * (0.42 + (z + 0.5) * 0.85) * (1 + 0.3 * pulse);
      ctx.moveTo(px[i]+s, py[i]); ctx.arc(px[i], py[i], s, 0, 6.283);
    }
    ctx.fillStyle = "rgba(150,255,175,0.72)"; ctx.fill();

    ctx.beginPath();
    for (var i = 0; i < N; i++) {
      if (pz[i] <= -0.9 || ACTIVE[CONT[i]]) continue;
      var z = pz[i], a = Math.min(1, (z + 0.5) * 1.6);
      var s = 1.5 * (0.42 + (z + 0.5) * 0.85);
      ctx.moveTo(px[i]+s, py[i]); ctx.arc(px[i], py[i], s, 0, 6.283);
    }
    ctx.fillStyle = "rgba(140,180,150,0.18)"; ctx.fill();

    ctx.strokeStyle = "rgba(198,243,107,.22)"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(R, R, R * 0.985, 0, 6.283); ctx.stroke();
    requestAnimationFrame(draw);
  }
  draw();

  function proj(lat, lon) {
    var phi = (90 - lat) * Math.PI / 180, the = (lon + 180) * Math.PI / 180;
    return { x: Math.sin(phi) * Math.cos(the), y: Math.cos(phi), z: Math.sin(phi) * Math.sin(the) };
  }
  var globe = document.querySelector(".globe"), pings = [];
  if (globe) {
    D.forEach(function (d, i) {
      var e = document.createElement("div");
      e.className = "gping " + (i % 2 ? "cy" : "lm");
      e.style.animationDelay = (i * 0.4) + "s";
      globe.appendChild(e);
      pings.push({ el: e, d: d });
    });
  }
  function placePings() {
    var rt = Date.now() / 1000 * SPIN;
    for (var i = 0; i < pings.length; i++) {
      var p = pings[i], q = proj(p.d.lat, p.d.lon);
      var x = q.x * Math.cos(rt) + q.z * Math.sin(rt);
      var hz = -q.x * Math.sin(rt) + q.z * Math.cos(rt);
      var vis = hz > 0.05;
      p.el.style.left = (50 + x * 45) + "%";
      p.el.style.top = (FLIP_Y ? 50 + q.y * 45 : 50 - q.y * 45) + "%";
      p.el.style.opacity = vis ? 1 : 0;
      p.el.style.transform = "scale(" + (vis ? 1 : 0.001) + ")";
    }
    requestAnimationFrame(placePings);
  }
  placePings();

  var svg = document.querySelector(".garc");
  if (svg) {
    var hub = proj(3.139, 101.687); // KL
    D.forEach(function (d, i) {
      var b = proj(d.lat, d.lon);
      var ax = 170 + hub.x * 164, ay = (FLIP_Y ? 170 + hub.y * 164 : 170 - hub.y * 164);
      var bx = 170 + b.x * 164, by = (FLIP_Y ? 170 + b.y * 164 : 170 - b.y * 164);
      var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", "M" + ax.toFixed(1) + " " + ay.toFixed(1) +
        " Q" + ((ax + bx) / 2).toFixed(1) + " " + (((ay + by) / 2) - 44).toFixed(1) +
        " " + bx.toFixed(1) + " " + by.toFixed(1));
      p.style.animationDelay = (i * 0.32) + "s";
      svg.appendChild(p);
    });
  }
})();
