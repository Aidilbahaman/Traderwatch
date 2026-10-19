/* TraderWatch — Education practice games.
   Four small, dependency-free exercises: read a candle, count pips, size a
   position, match the terms. Scores are kept in localStorage under
   tw_edu_games (best per game); storage failures fall back to memory.
   Educational only — no advice, no profit claims, no performance numbers. */
(function () {
  "use strict";

  var KEY = "tw_edu_games";
  var memory = null;
  var canStore = (function () {
    try { localStorage.setItem("__tw_game_probe", "1"); localStorage.removeItem("__tw_game_probe"); return true; }
    catch (e) { return false; }
  })();

  /* ---------- best-score storage ---------- */
  function all() {
    if (!canStore) return memory || (memory = {});
    try {
      var raw = localStorage.getItem(KEY);
      var obj = raw ? JSON.parse(raw) : {};
      return obj && typeof obj === "object" ? obj : {};
    } catch (e) { return {}; }
  }
  function bestOf(id) {
    var rec = all()[id];
    return rec && typeof rec.best === "number" ? rec : null;
  }
  function record(id, best, total) {
    var s = all(), cur = s[id];
    if (!cur || best > cur.best) {
      s[id] = { best: best, total: total, at: Date.now() };
      memory = s;
      if (canStore) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
    }
  }

  /* ---------- dom helpers ---------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function dots(total) {
    var wrap = el("div", "game-dots");
    wrap.setAttribute("aria-hidden", "true");
    for (var i = 0; i < total; i++) wrap.appendChild(el("i"));
    return wrap;
  }
  function paintDots(wrap, idx, results) {
    var items = wrap.querySelectorAll("i");
    for (var i = 0; i < items.length; i++) {
      items[i].className = i < idx ? (results[i] ? "ok" : "no") : (i === idx ? "on" : "");
    }
  }
  function scoreLabel(id, total) {
    var b = bestOf(id);
    return b ? "Best " + b.best + "/" + b.total : "Best —";
  }

  /* ---------- candlestick svg ---------- */
  function candleSvg(c) {
    var W = 200, H = 132, pad = 14;
    var hi = Math.max(c.o, c.c, c.h), lo = Math.min(c.o, c.c, c.l);
    var span = (hi - lo) || 0.0001;
    function y(v) { return pad + (H - pad * 2) * ((hi - v) / span); }
    var up = c.c >= c.o;
    var col = up ? "#27e08a" : "#ff5470";
    var bodyTop = y(Math.max(c.o, c.c));
    var bodyH = Math.max(3, Math.abs(y(c.o) - y(c.c)));
    var x = W / 2;
    var svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
      'aria-label="Candlestick: open ' + c.o.toFixed(4) + ', high ' + c.h.toFixed(4) +
      ', low ' + c.l.toFixed(4) + ', close ' + c.c.toFixed(4) + '">';
    svg += '<line x1="' + x + '" x2="' + x + '" y1="' + y(c.h).toFixed(1) + '" y2="' + y(c.l).toFixed(1) +
      '" stroke="' + col + '" stroke-width="2"/>';
    svg += '<rect x="' + (x - 16) + '" y="' + bodyTop.toFixed(1) + '" width="32" height="' + bodyH.toFixed(1) +
      '" rx="2" fill="' + col + '"/>';
    svg += "</svg>";
    return svg;
  }

  /* ---------- shared round engine ---------- */
  function roundGame(opts) {
    var root = opts.root, id = opts.id, rounds = opts.rounds, total = rounds.length;
    var idx = 0, score = 0, results = [], locked = false;

    clear(root);
    var bar = dots(total);
    var scoreEl = el("span", "game-score", scoreLabel(id, total));
    var top = el("div", "game-dots");
    top.style.justifyContent = "space-between";
    top.appendChild(bar);
    top.appendChild(scoreEl);

    var stage = el("div", "game-body");
    var live = el("p", "game-feedback");
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");
    root.appendChild(top);
    root.appendChild(stage);
    root.appendChild(live);

    function finish() {
      clear(stage);
      record(id, score, total);
      scoreEl.textContent = scoreLabel(id, total);
      var done = el("div", "game-done");
      done.appendChild(el("strong", null, score + " / " + total + " betul"));
      done.appendChild(el("p", null, opts.closing || "Main semula bila-bila masa."));
      var again = el("button", "game-btn", "Main lagi");
      again.type = "button";
      again.addEventListener("click", function () {
        idx = 0; score = 0; results = []; locked = false;
        live.textContent = ""; live.className = "game-feedback";
        paintDots(bar, 0, results);
        render();
      });
      done.appendChild(again);
      stage.appendChild(done);
      live.textContent = "Selesai. Skor " + score + " daripada " + total + ".";
      again.focus();
    }

    function next() {
      if (idx >= total - 1) { finish(); return; }
      idx++;
      locked = false;
      live.textContent = "";
      live.className = "game-feedback";
      paintDots(bar, idx, results);
      render();
    }

    function render() {
      clear(stage);
      var r = rounds[idx];
      if (r.candle) {
        var box = el("div", "game-candle");
        box.innerHTML = candleSvg(r.candle);
        stage.appendChild(box);
      }
      stage.appendChild(el("p", "game-q", r.q));

      if (r.kind === "number") {
        var form = el("form", "game-row");
        var field = el("div", "game-field");
        var lab = el("label", null, r.label || "Jawapan");
        var input = el("input");
        input.type = "number";
        input.step = r.step || "any";
        input.id = id + "-in-" + idx;
        input.placeholder = r.placeholder || "";
        input.setAttribute("inputmode", "decimal");
        lab.setAttribute("for", input.id);
        field.appendChild(lab);
        field.appendChild(input);
        var check = el("button", "game-btn", "Semak");
        check.type = "submit";
        form.appendChild(field);
        form.appendChild(check);
        stage.appendChild(form);

        var why = el("p", "game-why", r.why);
        why.hidden = true;
        stage.appendChild(why);

        form.addEventListener("submit", function (e) {
          e.preventDefault();
          if (locked) return;
          var val = parseFloat(input.value);
          if (!isFinite(val)) { live.textContent = "Isi nombor dulu."; input.focus(); return; }
          locked = true;
          var ok = Math.abs(val - r.ans) <= (r.tol || 0.01);
          if (ok) score++;
          results[idx] = ok;
          paintDots(bar, idx, results);
          live.textContent = ok ? "Betul." : "Belum tepat — jawapan: " + r.display + ".";
          live.className = "game-feedback " + (ok ? "ok" : "no");
          why.hidden = false;
          check.hidden = true;
          input.disabled = true;
          var nb = el("button", "game-btn", idx === total - 1 ? "Tengok skor" : "Seterusnya");
          nb.type = "button";
          nb.addEventListener("click", next);
          stage.appendChild(nb);
          nb.focus();
        });
        return;
      }

      var wrap = el("div", "game-options");
      var why2 = el("p", "game-why", r.why);
      why2.hidden = true;
      r.opts.forEach(function (label, i) {
        var b = el("button", "game-opt", label);
        b.type = "button";
        b.setAttribute("aria-pressed", "false");
        b.addEventListener("click", function () {
          if (locked) return;
          locked = true;
          var ok = i === r.ans;
          if (ok) score++;
          results[idx] = ok;
          paintDots(bar, idx, results);
          b.className = "game-opt " + (ok ? "is-right" : "is-wrong");
          b.setAttribute("aria-pressed", "true");
          if (!ok) {
            var right = wrap.children[r.ans];
            if (right) right.className = "game-opt is-right";
          }
          Array.prototype.forEach.call(wrap.children, function (c) { c.disabled = true; });
          live.textContent = ok ? "Betul." : "Bukan — jawapan yang tepat: " + r.opts[r.ans] + ".";
          live.className = "game-feedback " + (ok ? "ok" : "no");
          why2.hidden = false;
          var nb = el("button", "game-btn", idx === total - 1 ? "Tengok skor" : "Seterusnya");
          nb.type = "button";
          nb.addEventListener("click", next);
          stage.appendChild(nb);
          nb.focus();
        });
        wrap.appendChild(b);
      });
      stage.appendChild(wrap);
      stage.appendChild(why2);
    }

    paintDots(bar, 0, results);
    render();
  }

  /* ---------- game 1: candle reading ---------- */
  var CANDLE_ROUNDS = [
    { candle: { o: 1.0850, h: 1.0880, l: 1.0842, c: 1.0872 },
      q: "Which way did this candle close?",
      opts: ["Bullish — closed above the open", "Bearish — closed below the open"],
      ans: 0, why: "Close 1.0872 is above the open 1.0850, so the body is bullish." },
    { candle: { o: 1.2650, h: 1.2662, l: 1.2610, c: 1.2618 },
      q: "Which way did this candle close?",
      opts: ["Bullish — closed above the open", "Bearish — closed below the open"],
      ans: 1, why: "Close 1.2618 is below the open 1.2650, so the body is bearish." },
    { candle: { o: 149.20, h: 149.90, l: 149.05, c: 149.30 },
      q: "Which wick is longer?",
      opts: ["Upper wick", "Lower wick"],
      ans: 0, why: "Upper wick is 0.70 (149.90 − 149.20); lower wick is 0.15 (149.20 − 149.05)." },
    { candle: { o: 1.0900, h: 1.0906, l: 1.0894, c: 1.0901 },
      q: "What shape is this?",
      opts: ["Doji — tiny body, wicks both sides", "Marubozu — no wicks at all"],
      ans: 0, why: "The body is 0.0001 against a 0.0012 range — under a tenth of the range, which reads as a doji." },
    { candle: { o: 1.1000, h: 1.1010, l: 1.0950, c: 1.1008 },
      q: "Where does the body sit inside the range?",
      opts: ["Near the top", "Near the bottom"],
      ans: 0, why: "Open and close are both near 1.1000–1.1008 while the low reached 1.0950 — the long lower wick leaves the body near the top." }
  ];

  /* ---------- game 2: pip counting ---------- */
  var PIP_ROUNDS = [
    { q: "EUR/USD moved from 1.0850 to 1.0872. How many pips is that?", kind: "number",
      label: "Pips", ans: 22, tol: 0.5, display: "22 pips",
      why: "For most pairs a pip is the fourth decimal: 1.0872 − 1.0850 = 0.0022 = 22 pips." },
    { q: "USD/JPY moved from 149.20 to 149.55. How many pips is that?", kind: "number",
      label: "Pips", ans: 35, tol: 0.5, display: "35 pips",
      why: "Yen pairs are quoted to two decimals, so a pip is 0.01: 149.55 − 149.20 = 0.35 = 35 pips." },
    { q: "GBP/USD moved from 1.2650 down to 1.2618. How many pips is the move?", kind: "number",
      label: "Pips", ans: 32, tol: 0.5, display: "32 pips",
      why: "Direction does not change the count: 1.2650 − 1.2618 = 0.0032 = 32 pips." },
    { q: "AUD/USD moved from 0.6520 to 0.6488. How many pips?", kind: "number",
      label: "Pips", ans: 32, tol: 0.5, display: "32 pips",
      why: "0.6520 − 0.6488 = 0.0032. Same 32 pips, even though the price level is much lower." }
  ];

  /* ---------- game 3: position sizing ---------- */
  var SIZE_ROUNDS = [
    { q: "Account $10,000 · risk 1% · stop 25 pips · pip value $10. What lot size?",
      kind: "number", label: "Lots", ans: 0.4, tol: 0.02, step: "0.01", display: "0.40 lots",
      why: "Risk = 1% of $10,000 = $100. $100 ÷ (25 pips × $10) = 0.40 lots." },
    { q: "Account $5,000 · risk 2% · stop 40 pips · pip value $10. What lot size?",
      kind: "number", label: "Lots", ans: 0.25, tol: 0.02, step: "0.01", display: "0.25 lots",
      why: "Risk = 2% of $5,000 = $100. $100 ÷ (40 × $10) = 0.25 lots." },
    { q: "Account $20,000 · risk 0.5% · stop 20 pips · pip value $10. What lot size?",
      kind: "number", label: "Lots", ans: 0.5, tol: 0.02, step: "0.01", display: "0.50 lots",
      why: "Risk = 0.5% of $20,000 = $100. $100 ÷ (20 × $10) = 0.50 lots." }
  ];

  /* ---------- game 4: term match ---------- */
  var TERMS = [
    { t: "Pip", d: "Smallest standard price increment for a pair" },
    { t: "Lot", d: "Fixed quantity of currency, e.g. 100,000 units" },
    { t: "Leverage", d: "Lets a broker hold a position larger than your deposit" },
    { t: "Margin", d: "Capital set aside while a position is open" },
    { t: "Spread", d: "Difference between the bid and the ask" },
    { t: "Slippage", d: "Fill price differing from the price you expected" }
  ];

  function matchGame(root) {
    clear(root);
    var left = el("div", "game-col");
    var right = el("div", "game-col");
    var live = el("p", "game-feedback");
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");

    var head = el("div", "game-dots");
    head.style.justifyContent = "space-between";
    var counter = el("span", "game-score", "0 / " + TERMS.length);
    head.appendChild(counter);
    var reset = el("button", "game-btn ghost", "Susun semula");
    reset.type = "button";
    head.appendChild(reset);

    left.appendChild(el("p", "game-col-title", "Term"));
    right.appendChild(el("p", "game-col-title", "Meaning"));

    var picked = null, matched = 0, wrong = 0;
    var defs = TERMS.map(function (x, i) { return { d: x.d, i: i }; })
      .sort(function (a, b) { return (a.i * 7) % 5 - (b.i * 7) % 5; });

    TERMS.forEach(function (term, i) {
      var b = el("button", "game-chip", term.t);
      b.type = "button";
      b.dataset.term = String(i);
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", function () {
        if (b.classList.contains("is-matched")) return;
        if (picked) picked.setAttribute("aria-pressed", "false");
        picked = b;
        b.setAttribute("aria-pressed", "true");
        live.textContent = "Pilih maksud untuk \u201c" + term.t + "\u201d.";
        live.className = "game-feedback";
      });
      left.appendChild(b);
    });

    defs.forEach(function (def) {
      var b = el("button", "game-chip", def.d);
      b.type = "button";
      b.dataset.def = String(def.i);
      b.addEventListener("click", function () {
        if (b.classList.contains("is-matched")) return;
        if (!picked) { live.textContent = "Pilih satu term dulu."; live.className = "game-feedback"; return; }
        if (picked.dataset.term === b.dataset.def) {
          picked.classList.add("is-matched");
          picked.disabled = true;
          picked.removeAttribute("aria-pressed");
          b.classList.add("is-matched");
          b.disabled = true;
          matched++;
          counter.textContent = matched + " / " + TERMS.length;
          live.textContent = "Padan. " + matched + " daripada " + TERMS.length + " selesai.";
          live.className = "game-feedback ok";
          picked = null;
          if (matched === TERMS.length) {
            record("match", TERMS.length, TERMS.length);
            live.textContent = "Semua padan. Salah cubaan: " + wrong + ".";
          }
        } else {
          wrong++;
          b.classList.add("is-wrong");
          live.textContent = "Bukan padanan. Cuba lagi.";
          live.className = "game-feedback no";
          setTimeout(function () { b.classList.remove("is-wrong"); }, 700);
        }
      });
      right.appendChild(b);
    });

    var cols = el("div", "game-match");
    cols.appendChild(left);
    cols.appendChild(right);
    root.appendChild(head);
    root.appendChild(cols);
    root.appendChild(live);

    reset.addEventListener("click", function () { matchGame(root); });
  }


  /* ---------- game 5: sessions and Malaysian time ---------- */
  var SESSION_ROUNDS = [
    { q: "London opens around 07:00 UTC. What time is that in Malaysia (UTC+8)?",
      opts: ["15:00", "19:00"], ans: 0,
      why: "07:00 UTC + 8 hours = 15:00 in Malaysia. London is the afternoon session for us." },
    { q: "New York opens around 12:00 UTC. Malaysia time?",
      opts: ["16:00", "20:00"], ans: 1,
      why: "12:00 UTC + 8 = 20:00. The London–New York overlap therefore lands around 20:00–24:00 Malaysian time." },
    { q: "Tokyo opens around 00:00 UTC. Malaysia time?",
      opts: ["08:00", "12:00"], ans: 0,
      why: "00:00 UTC + 8 = 08:00. Tokyo runs through the Malaysian morning." },
    { q: "Which overlap is usually the busiest window of the day?",
      opts: ["London + New York", "Sydney + Tokyo"], ans: 0,
      why: "The London–New York overlap carries the most volume, so spreads are usually tightest and moves fastest then." },
    { q: "At 22:00 UTC, which session has just opened?",
      opts: ["Sydney", "London"], ans: 0,
      why: "Sydney opens around 21:00 UTC. London closed at 16:00 and New York closes around 21:00." }
  ];

  /* ---------- game 6: risk to reward ---------- */
  var RR_ROUNDS = [
    { q: "Entry 1.0850 · stop 1.0830 · target 1.0910. What is the reward-to-risk ratio?",
      kind: "number", label: "R:R (e.g. 3 for 1:3)", ans: 3, tol: 0.06, step: "0.1", display: "1:3",
      why: "Risk 20 pips (1.0850 − 1.0830), reward 60 pips (1.0910 − 1.0850). 60 ÷ 20 = 3." },
    { q: "Entry 149.20 · stop 148.80 · target 150.20. What is the reward-to-risk ratio?",
      kind: "number", label: "R:R", ans: 2.5, tol: 0.06, step: "0.1", display: "1:2.5",
      why: "Risk 40 pips, reward 100 pips. 100 ÷ 40 = 2.5." },
    { q: "Entry 1.2650 · stop 1.2680 · target 1.2590. What is the reward-to-risk ratio?",
      kind: "number", label: "R:R", ans: 2, tol: 0.06, step: "0.1", display: "1:2",
      why: "Risk 30 pips above entry, reward 60 pips below it. 60 ÷ 30 = 2." },
    { q: "Entry 0.6520 · stop 0.6495 · target 0.6555. What is the reward-to-risk ratio?",
      kind: "number", label: "R:R", ans: 1.4, tol: 0.06, step: "0.1", display: "1:1.4",
      why: "Risk 25 pips, reward 35 pips. 35 ÷ 25 = 1.4." }
  ];

  /* ---------- game 7: spot the zone ---------- */
  var CHART_ROUNDS = [
    { q: "Which zone did price keep bouncing from?",
      data: [1.0900,1.0912,1.0920,1.0918,1.0906,1.0894,1.0880,1.0866,1.0850,1.0834,1.0818,1.0802,1.0800,1.0814,1.0830,1.0846,1.0862,1.0878,1.0894,1.0908,1.0918,1.0910,1.0896,1.0882,1.0866,1.0850,1.0834,1.0818,1.0800,1.0800,1.0816,1.0832,1.0848,1.0864,1.0880,1.0896,1.0910,1.0918,1.0906,1.0892,1.0876,1.0860,1.0844,1.0828,1.0812,1.0800,1.0800,1.0818],
      bands: [{ label: "A", price: 1.0800 }, { label: "B", price: 1.0930 }, { label: "C", price: 1.0700 }],
      why: "A zone matters because price reacted there repeatedly, not because it looks tidy." },
    { q: "Which zone acted as resistance?",
      data: [1.0800,1.0820,1.0840,1.0860,1.0880,1.0900,1.0920,1.0938,1.0940,1.0925,1.0905,1.0885,1.0865,1.0845,1.0865,1.0885,1.0905,1.0925,1.0940,1.0935,1.0915,1.0895,1.0875,1.0895,1.0915,1.0935,1.0940,1.0920,1.0900,1.0880,1.0860,1.0840,1.0820,1.0840,1.0860,1.0880,1.0900,1.0920,1.0940,1.0925],
      bands: [{ label: "A", price: 1.0840 }, { label: "B", price: 1.0940 }, { label: "C", price: 1.1000 }],
      why: "Resistance is the same idea from above: a level price failed to close beyond." }
  ];

  function touches(data, price) {
    var tol = 0.0004, n = 0;
    for (var i = 0; i < data.length; i++) if (Math.abs(data[i] - price) <= tol) n++;
    return n;
  }

  function chartGame(root) {
    clear(root);
    var idx = 0, score = 0, locked = false;

    var bar = dots(CHART_ROUNDS.length);
    var scoreEl = el("span", "game-score", scoreLabel("zones", CHART_ROUNDS.length));
    var top = el("div", "game-dots");
    top.style.justifyContent = "space-between";
    top.appendChild(bar);
    top.appendChild(scoreEl);

    var stage = el("div", "game-body");
    var live = el("p", "game-feedback");
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");

    root.appendChild(top);
    root.appendChild(stage);
    root.appendChild(live);

    function chartSvg(r) {
      var W = 320, H = 168, pad = 16;
      var hi = Math.max.apply(null, r.data), lo = Math.min.apply(null, r.data);
      var span = hi - lo || 0.001;
      function y(v) { return pad + (H - pad * 2) * ((hi - v) / span); }
      var stepX = (W - pad * 2) / (r.data.length - 1);
      var pts = r.data.map(function (v, i) { return (pad + i * stepX).toFixed(1) + "," + y(v).toFixed(1); }).join(" ");
      var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" height="168" role="img" aria-label="Price line with three horizontal zones labelled A, B and C">';
      r.bands.forEach(function (b) {
        var by = y(b.price).toFixed(1);
        out += '<line x1="' + pad + '" x2="' + (W - pad) + '" y1="' + by + '" y2="' + by + '" stroke="#2a5b86" stroke-width="1" stroke-dasharray="5 4"/>';
        out += '<text x="' + (pad + 4) + '" y="' + (Number(by) - 5).toFixed(1) + '" fill="#9db6ca" font-size="10" font-weight="700">' + b.label + ' · ' + b.price.toFixed(4) + "</text>";
      });
      out += '<polyline points="' + pts + '" fill="none" stroke="#6aa8ff" stroke-width="1.8" stroke-linejoin="round"/>';
      out += "</svg>";
      return out;
    }

    function finish() {
      clear(stage);
      record("zones", score, CHART_ROUNDS.length);
      scoreEl.textContent = scoreLabel("zones", CHART_ROUNDS.length);
      var done = el("div", "game-done");
      done.appendChild(el("strong", null, score + " / " + CHART_ROUNDS.length + " betul"));
      done.appendChild(el("p", null, "Zon dikira dari berapa kali harga menyentuhnya."));
      var again = el("button", "game-btn", "Main lagi");
      again.type = "button";
      again.addEventListener("click", function () {
        idx = 0; score = 0; locked = false;
        live.textContent = ""; live.className = "game-feedback";
        paintDots(bar, 0, []);
        render();
        again.focus();
      });
      done.appendChild(again);
      stage.appendChild(done);
      live.textContent = "Selesai. Skor " + score + " daripada " + CHART_ROUNDS.length + ".";
      again.focus();
    }

    function next() {
      if (idx >= CHART_ROUNDS.length - 1) { finish(); return; }
      idx++; locked = false;
      live.textContent = ""; live.className = "game-feedback";
      paintDots(bar, idx, []);
      render();
    }

    function render() {
      clear(stage);
      var r = CHART_ROUNDS[idx];
      var counts = r.bands.map(function (b) { return touches(r.data, b.price); });
      var best = counts.indexOf(Math.max.apply(null, counts));

      var box = el("div", "game-candle");
      box.innerHTML = chartSvg(r);
      stage.appendChild(box);
      stage.appendChild(el("p", "game-q", r.q));

      var opts = el("div", "game-options");
      var why = el("p", "game-why", r.why);
      why.hidden = true;

      r.bands.forEach(function (b, i) {
        var btn = el("button", "game-opt", "Zone " + b.label + " · " + b.price.toFixed(4));
        btn.type = "button";
        btn.setAttribute("aria-pressed", "false");
        btn.addEventListener("click", function () {
          if (locked) return;
          locked = true;
          var ok = i === best;
          if (ok) score++;
          paintDots(bar, idx, []);
          btn.className = "game-opt " + (ok ? "is-right" : "is-wrong");
          btn.setAttribute("aria-pressed", "true");
          if (!ok && opts.children[best]) opts.children[best].className = "game-opt is-right";
          Array.prototype.forEach.call(opts.children, function (c) { c.disabled = true; });
          live.textContent = ok ? "Betul." : "Bukan — zon itu disentuh " + counts[i] + " kali, zon betul " + counts[best] + " kali.";
          live.className = "game-feedback " + (ok ? "ok" : "no");
          why.textContent = r.why + " Zon " + r.bands.map(function (b, j) {
            return b.label + " disentuh " + counts[j] + " kali";
          }).join(", ") + ".";
          why.hidden = false;
          var nb = el("button", "game-btn", idx === CHART_ROUNDS.length - 1 ? "Tengok skor" : "Seterusnya");
          nb.type = "button";
          nb.addEventListener("click", next);
          stage.appendChild(nb);
          nb.focus();
        });
        opts.appendChild(btn);
      });

      stage.appendChild(opts);
      stage.appendChild(why);
    }

    paintDots(bar, 0, []);
    render();
  }


  /* ---------- member session (badge + logout) ---------- */
  function normalizeTier(v) {
    var t = String(v == null ? "" : v).toLowerCase();
    return (t === "pro" || t === "max") ? t : "free";
  }
  function bootAuth() {
    var badge = document.getElementById("planBadge");
    var p = typeof window.requireMember === "function"
      ? window.requireMember(location.pathname)
      : Promise.resolve(null);
    Promise.resolve(p).then(function (member) {
      if (!member) return;
      var t = normalizeTier(member.plan);
      document.body.dataset.tier = t;
      if (badge) {
        badge.textContent = t === "max" ? "Max" : t === "pro" ? "Pro" : "Free";
        badge.classList.toggle("pro", t !== "free");
      }
    }).catch(function () {});

    var logout = document.getElementById("eduLogout");
    if (logout) {
      logout.addEventListener("click", function () {
        if (typeof window.logOut === "function") window.logOut();
      });
    }
  }

  /* ---------- boot ---------- */
  function init() {
    bootAuth();
    var c = document.querySelector('[data-game="candle"]');
    var p = document.querySelector('[data-game="pips"]');
    var s = document.querySelector('[data-game="size"]');
    var m = document.querySelector('[data-game="match"]');
    var se = document.querySelector('[data-game="sessions"]');
    var rr = document.querySelector('[data-game="rr"]');
    var zn = document.querySelector('[data-game="zones"]');
    if (c) roundGame({ root: c, id: "candle", rounds: CANDLE_ROUNDS, closing: "Cuba lagi — kelajuan bukan matlamat, faham dulu." });
    if (p) roundGame({ root: p, id: "pips", rounds: PIP_ROUNDS, closing: "Pip value berubah ikut pair dan saiz lot." });
    if (s) roundGame({ root: s, id: "size", rounds: SIZE_ROUNDS, closing: "Formula: (baki × % risiko) ÷ (stop pips × pip value)." });
    if (m) matchGame(m);
    if (se) roundGame({ root: se, id: "sessions", rounds: SESSION_ROUNDS, closing: "Waktu Malaysia = UTC + 8." });
    if (rr) roundGame({ root: rr, id: "rr", rounds: RR_ROUNDS, closing: "R:R = jarak target ÷ jarak stop." });
    if (zn) chartGame(zn);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
