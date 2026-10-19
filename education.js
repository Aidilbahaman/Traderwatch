/* TraderWatch Education — hub rendering, plan gating, progress.
   Plan source of truth: profiles.plan (read by loadMember() in common.js).
   members.html publishes it on <body data-tier="free|pro|max">, the same value
   that drives the plan badge — this script only reads that attribute.
   lesson.html has no badge, so bootLesson() publishes the same attribute from
   the member object it gets back from requireMember().
   No frameworks, no inline handlers, no external requests. */
(function () {
  "use strict";

  var STORE = "tw_edu_progress";
  var RANK = { free: 0, pro: 1, max: 2 };
  var THRESHOLDS = [25, 50, 75];
  var lessons = Array.isArray(window.TW_LESSONS) ? window.TW_LESSONS : [];
  var activeCat = "All";
  var memory = null;               // fallback when storage is blocked
  var canStore = (function () {
    try {
      var k = "__tw_edu_probe";
      localStorage.setItem(k, "1");
      localStorage.removeItem(k);
      return true;
    } catch (e) { return false; }
  })();

  /* ---------- progress ---------- */
  function readAll() {
    if (!canStore) return memory || (memory = {});
    try {
      var raw = localStorage.getItem(STORE);
      var obj = raw ? JSON.parse(raw) : {};
      return obj && typeof obj === "object" ? obj : {};
    } catch (e) { return {}; }
  }
  function writeAll(obj) {
    memory = obj;
    if (!canStore) return;
    try { localStorage.setItem(STORE, JSON.stringify(obj)); } catch (e) { /* quota / private mode */ }
  }
  function getProgress() { return readAll(); }
  function getOne(id) {
    var rec = readAll()[id];
    return rec && typeof rec.pct === "number" ? rec : null;
  }
  function setProgress(id, pct) {
    if (!id) return null;
    var next = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    var all = readAll();
    var cur = all[id] && typeof all[id].pct === "number" ? all[id].pct : 0;
    if (next <= cur) return all[id] || null;      // never downgrade
    all[id] = { pct: next, at: Date.now() };
    writeAll(all);
    try {
      document.dispatchEvent(new CustomEvent("tw:edu-progress", { detail: { id: id, pct: next } }));
    } catch (e) { /* older browsers */ }
    return all[id];
  }

  /* ---------- plan ---------- */
  function normalizeTier(v) {
    var t = String(v == null ? "" : v).toLowerCase();
    return RANK[t] === undefined ? "free" : t;
  }
  function plan() {
    var t = document.body && document.body.dataset ? document.body.dataset.tier : "";
    return t ? normalizeTier(t) : "free";
  }
  function tierOf(lesson) { return normalizeTier(lesson && lesson.tier); }
  function tierLabel(t) { return t === "max" ? "Max" : t === "pro" ? "Pro" : "Free"; }
  function isLocked(lesson) { return RANK[tierOf(lesson)] > RANK[plan()]; }

  /* ---------- tiny DOM helpers ---------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function bar(pct, label) {
    var wrap = el("span", "edu-bar");
    if (label) {
      wrap.setAttribute("role", "progressbar");
      wrap.setAttribute("aria-valuemin", "0");
      wrap.setAttribute("aria-valuemax", "100");
      wrap.setAttribute("aria-valuenow", String(Math.round(pct)));
      wrap.setAttribute("aria-label", label);
    } else {
      wrap.setAttribute("aria-hidden", "true");
    }
    var fill = el("i");
    fill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    wrap.appendChild(fill);
    return wrap;
  }
  function summaryOf(lesson) {
    var block = (lesson.body || []).filter(function (b) { return b && b.t === "p"; })[0];
    var text = block && block.text ? String(block.text) : "";
    text = text.replace(/^TODO:\s*replace with final copy\.?\s*/i, "");
    if (text.length > 150) {
      text = text.slice(0, 147).replace(/\s+\S*$/, "") + "…";
    }
    return text;
  }

  /* ---------- category tabs ---------- */
  function categories() {
    var seen = {}, out = [];
    lessons.forEach(function (l) {
      var c = l.category || "Lessons";
      if (!seen[c]) { seen[c] = true; out.push(c); }
    });
    return out;
  }

  function onTabKey(e) {
    var tabs = Array.prototype.slice.call(e.currentTarget.parentNode.querySelectorAll('[role="tab"]'));
    var i = tabs.indexOf(e.currentTarget), next = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    e.preventDefault();
    tabs[next].focus();
    selectTab(tabs[next]);
  }

  function selectTab(btn) {
    var list = btn.parentNode.querySelectorAll('[role="tab"]');
    Array.prototype.forEach.call(list, function (b) {
      var on = b === btn;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    });
    activeCat = btn.dataset.cat || "All";
    var grid = document.getElementById("eduGrid");
    if (grid) grid.setAttribute("aria-labelledby", btn.id);
    renderGrid();
  }

  function buildTabs() {
    var wrap = document.getElementById("eduTabs");
    if (!wrap || !lessons.length) return;
    wrap.innerHTML = "";
    wrap.setAttribute("role", "tablist");
    wrap.setAttribute("aria-label", "Lesson category");
    ["All"].concat(categories()).forEach(function (cat, i) {
      var b = el("button", "edu-tab", cat);
      b.type = "button";
      b.id = "eduTab" + i;
      b.dataset.cat = cat;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", i === 0 ? "true" : "false");
      b.setAttribute("aria-controls", "eduGrid");
      b.tabIndex = i === 0 ? 0 : -1;
      b.addEventListener("click", function () { selectTab(b); });
      b.addEventListener("keydown", onTabKey);
      wrap.appendChild(b);
    });
  }

  /* ---------- lesson cards ---------- */
  function card(lesson) {
    var rec = getOne(lesson.id);
    var pct = rec ? rec.pct : 0;
    var done = pct >= 100;
    var locked = isLocked(lesson);
    var tier = tierOf(lesson);
    var href = "lesson.html?id=" + encodeURIComponent(lesson.id);

    var art = el("article", "edu-card");
    art.dataset.id = lesson.id;
    art.dataset.tier = tier;

    var top = el("div", "edu-card-top");
    top.appendChild(el("span", "edu-cat", lesson.category || "Lesson"));
    var pill = el("span", "edu-pill " + (done ? "done" : tier), done ? "Done" : tierLabel(tier));
    top.appendChild(pill);
    art.appendChild(top);

    var h = el("h3", "edu-card-title");
    var a = el("a", null, lesson.title);
    a.href = href;
    h.appendChild(a);
    art.appendChild(h);

    var sum = summaryOf(lesson);
    if (sum) art.appendChild(el("p", "edu-card-sum", sum));

    var foot = el("div", "edu-card-foot");
    var meta = el("div", "edu-foot-meta");
    if (pct > 0 && !done) {
      meta.appendChild(bar(pct));
      meta.appendChild(el("span", "edu-min", pct + "% complete"));
    } else {
      meta.appendChild(el("span", "edu-min", (lesson.minutes || 5) + " min read"));
    }
    foot.appendChild(meta);

    if (locked) {
      var unlock = el("a", "edu-cta", "Unlock with " + tierLabel(tier));
      unlock.href = "subscribe.html?plan=" + tier;
      foot.appendChild(unlock);
    } else if (done) {
      var review = el("a", "edu-cta ghost", "Review");
      review.href = href;
      foot.appendChild(review);
    } else if (pct > 0) {
      var resume = el("a", "edu-cta", "Continue");
      resume.href = href;
      foot.appendChild(resume);
    } else {
      var start = el("a", "edu-cta ghost", "Start lesson");
      start.href = href;
      foot.appendChild(start);
    }
    art.appendChild(foot);
    return art;
  }

  function renderGrid() {
    var grid = document.getElementById("eduGrid");
    var empty = document.getElementById("eduEmpty");
    if (!grid) return;
    var list = lessons.filter(function (l) {
      return activeCat === "All" || (l.category || "Lessons") === activeCat;
    });
    grid.innerHTML = "";
    list.forEach(function (l) { grid.appendChild(card(l)); });
    if (empty) empty.hidden = list.length > 0;
  }

  /* ---------- continue learning ---------- */
  function renderContinue() {
    var box = document.getElementById("eduContinue");
    if (!box) return;
    var candidates = lessons.filter(function (l) {
      var r = getOne(l.id);
      return r && r.pct > 0 && r.pct < 100 && !isLocked(l);
    }).sort(function (a, b) { return getOne(b.id).at - getOne(a.id).at; });

    var lesson = candidates[0];
    box.innerHTML = "";
    if (!lesson) { box.hidden = true; return; }

    var pct = getOne(lesson.id).pct;
    var copy = el("div");
    copy.appendChild(el("p", "edu-continue-kicker", "Continue learning"));
    copy.appendChild(el("h3", null, lesson.title));
    copy.appendChild(el("p", null, (lesson.category || "Lesson") + " · " + pct + "% complete"));
    copy.appendChild(bar(pct, "Lesson progress"));
    box.appendChild(copy);

    var go = el("a", "edu-cta", "Resume lesson");
    go.href = "lesson.html?id=" + encodeURIComponent(lesson.id);
    box.appendChild(go);
    box.hidden = false;
  }

  function renderMeta() {
    var meta = document.getElementById("eduMeta");
    if (!meta) return;
    var done = 0, started = 0;
    lessons.forEach(function (l) {
      var r = getOne(l.id);
      if (!r) return;
      if (r.pct >= 100) done++;
      else if (r.pct > 0) started++;
    });
    meta.textContent = done + " of " + lessons.length + " lessons complete" +
      (started ? " · " + started + " in progress" : "");
  }

  function render() {
    renderContinue();
    renderGrid();
    renderMeta();
  }

  /* ---------- hub boot ---------- */
  function whenTierKnown(cb) {
    if (document.body.dataset.tier) return cb();
    var tries = 0;
    var timer = setInterval(function () {
      if (document.body.dataset.tier || ++tries > 30) {
        clearInterval(timer);
        cb();
      }
    }, 50);
  }

  function initHub() {
    buildTabs();
    whenTierKnown(function () {
      render();
      if ("MutationObserver" in window) {
        new MutationObserver(function (muts) {
          if (muts.some(function (m) { return m.attributeName === "data-tier"; })) render();
        }).observe(document.body, { attributes: true, attributeFilter: ["data-tier"] });
      }
      document.addEventListener("tw:edu-progress", function () { render(); });
      window.addEventListener("pageshow", function (e) { if (e.persisted) render(); });
    });
  }

  /* ---------- lesson page ---------- */
  function announce(msg) {
    var live = document.getElementById("eduLive");
    if (!live) return;
    live.textContent = "";
    setTimeout(function () { live.textContent = msg; }, 30);
  }

  function publishTier(member) {
    var t = normalizeTier(member && member.plan);
    document.body.dataset.tier = t;
    var badge = document.getElementById("planBadge");
    if (badge) {
      badge.textContent = tierLabel(t);
      badge.classList.toggle("pro", t !== "free");
    }
    return t;
  }

  function lessonHead(lesson, idx) {
    var head = el("header", "edu-lesson-head");
    var tags = el("div", "edu-lesson-tags");
    tags.appendChild(el("span", "edu-pill", lesson.category || "Lesson"));
    var tier = tierOf(lesson);
    tags.appendChild(el("span", "edu-pill " + tier, tierLabel(tier) + " lesson"));
    head.appendChild(tags);
    head.appendChild(el("h1", null, lesson.title));
    head.appendChild(el("p", "edu-lesson-meta",
      (lesson.minutes || 5) + " min read · Lesson " + (idx + 1) + " of " + lessons.length));

    var rec = getOne(lesson.id);
    var pct = rec ? rec.pct : 0;
    var wrap = el("div", "edu-lesson-progress");
    wrap.appendChild(bar(pct));
    wrap.appendChild(el("span", null, pct >= 100 ? "Completed" : pct > 0 ? pct + "% complete" : "Not started"));
    head.appendChild(wrap);
    return head;
  }

  function renderUpgrade(root, lesson) {
    var tier = tierOf(lesson);
    var box = el("div", "edu-upgrade");
    var tags = el("div", "edu-lesson-tags");
    tags.appendChild(el("span", "edu-pill " + tier, tierLabel(tier) + " lesson"));
    box.appendChild(tags);
    box.appendChild(el("h1", null, lesson.title));
    box.appendChild(el("p", null, "This lesson is part of " + tierLabel(tier) +
      ". Your current plan is " + tierLabel(plan()) + "."));

    var ul = el("ul");
    [
      "Every lesson in this tier, unlocked in your dashboard",
      "Progress tracking and the Continue learning card",
      "New lessons as they are added"
    ].forEach(function (t) { ul.appendChild(el("li", null, t)); });
    box.appendChild(ul);

    var actions = el("div", "edu-lesson-actions");
    var up = el("a", "edu-cta", "Upgrade to " + tierLabel(tier));
    up.href = "subscribe.html?plan=" + tier;
    actions.appendChild(up);
    var back = el("a", "edu-cta ghost", "Back to Education");
    back.href = "education.html";
    actions.appendChild(back);
    box.appendChild(actions);
    root.appendChild(box);
  }

  function renderBody(root, lesson) {
    var prose = el("div", "edu-prose");
    (lesson.body || []).forEach(function (b) {
      if (!b || !b.t) return;
      if (b.t === "h") prose.appendChild(el("h2", null, b.text || ""));
      else if (b.t === "p") prose.appendChild(el("p", null, b.text || ""));
      else if (b.t === "ul") {
        var ul = el("ul");
        (b.items || []).forEach(function (it) { ul.appendChild(el("li", null, it)); });
        prose.appendChild(ul);
      } else if (b.t === "callout") {
        prose.appendChild(el("p", "edu-callout", b.text || ""));
      }
    });
    root.appendChild(prose);
  }

  function renderLessonActions(root, lesson) {
    var actions = el("div", "edu-lesson-actions");
    var btn = el("button", "edu-cta");
    btn.type = "button";
    function sync() {
      var rec = getOne(lesson.id);
      var done = !!(rec && rec.pct >= 100);
      btn.textContent = done ? "Completed ✓" : "Mark complete";
      btn.setAttribute("aria-pressed", done ? "true" : "false");
    }
    btn.addEventListener("click", function () {
      setProgress(lesson.id, 100);
      sync();
      var rec = getOne(lesson.id);
      var label = document.querySelector(".edu-lesson-progress span");
      if (label && rec) label.textContent = "Completed";
      var fill = document.querySelector(".edu-lesson-progress .edu-bar > i");
      if (fill && rec) fill.style.width = "100%";
      announce("Lesson marked complete.");
    });
    sync();
    actions.appendChild(btn);

    var back = el("a", "edu-cta ghost", "Back to Education");
    back.href = "education.html";
    actions.appendChild(back);
    root.appendChild(actions);
  }

  function renderNav(root, idx) {
    var prev = lessons[idx - 1], next = lessons[idx + 1];
    if (!prev && !next) return;
    var nav = el("nav", "edu-lesson-nav");
    nav.setAttribute("aria-label", "Lesson navigation");
    if (prev) {
      var a = el("a", "edu-navlink");
      a.href = "lesson.html?id=" + encodeURIComponent(prev.id);
      a.appendChild(el("span", null, "Previous"));
      a.appendChild(el("b", null, prev.title));
      nav.appendChild(a);
    }
    if (next) {
      var b = el("a", "edu-navlink next");
      b.href = "lesson.html?id=" + encodeURIComponent(next.id);
      b.appendChild(el("span", null, "Next"));
      b.appendChild(el("b", null, next.title));
      nav.appendChild(b);
    }
    root.appendChild(nav);
  }

  function trackReading(lesson, article) {
    var ticking = false;
    function measure() {
      ticking = false;
      var rect = article.getBoundingClientRect();
      if (!rect.height) return;
      var seen = ((window.innerHeight - rect.top) / rect.height) * 100;
      seen = Math.max(0, Math.min(100, seen));
      THRESHOLDS.forEach(function (t) {
        if (seen >= t) {
          var rec = getOne(lesson.id);
          if (!rec || rec.pct < t) {
            setProgress(lesson.id, t);
            var label = document.querySelector(".edu-lesson-progress span");
            var fill = document.querySelector(".edu-lesson-progress .edu-bar > i");
            var cur = getOne(lesson.id);
            if (cur) {
              if (label && cur.pct < 100) label.textContent = cur.pct + "% complete";
              if (fill && cur.pct < 100) fill.style.width = cur.pct + "%";
            }
          }
        }
      });
    }
    window.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      measure();
    }, { passive: true });
  }

  function renderLesson(root, lesson, idx) {
    root.innerHTML = "";
    root.appendChild(lessonHead(lesson, idx));
    if (isLocked(lesson)) {
      renderUpgrade(root, lesson);
      return;
    }
    renderBody(root, lesson);
    renderLessonActions(root, lesson);
    renderNav(root, idx);
    trackReading(lesson, root);
  }

  function renderMissing(root) {
    root.innerHTML = "";
    root.appendChild(el("h1", null, "Lesson not found"));
    var p = el("p", null, "That lesson link is out of date. Browse the full library instead.");
    p.style.color = "#33465c";
    p.style.margin = "10px 0 20px";
    root.appendChild(p);
    var a = el("a", "edu-cta", "Back to Education");
    a.href = "education.html";
    root.appendChild(a);
  }

  function bootLesson() {
    var root = document.getElementById("lessonRoot");
    if (!root) return;
    var id = new URLSearchParams(location.search).get("id");
    var idx = -1;
    lessons.forEach(function (l, i) { if (l.id === id) idx = i; });
    if (idx < 0) { renderMissing(root); return; }

    var lesson = lessons[idx];
    var memberPromise;
    try {
      memberPromise = typeof window.requireMember === "function"
        ? window.requireMember(location.pathname + location.search)
        : Promise.resolve(null);
    } catch (e) {
      memberPromise = Promise.resolve(null);
    }

    Promise.resolve(memberPromise).then(function (member) {
      if (member) publishTier(member);
      document.title = lesson.title + " – Education – TraderWatch";
      renderLesson(root, lesson, idx);
    }).catch(function () {
      document.title = lesson.title + " – Education – TraderWatch";
      renderLesson(root, lesson, idx);
    });
  }

  /* ---------- public API ---------- */
  window.TWEdu = {
    plan: plan,
    lessons: lessons,
    tierLabel: tierLabel,
    isLocked: isLocked,
    getProgress: getProgress,
    getLessonProgress: getOne,
    setProgress: setProgress
  };

  function bootHub() {
    var p = typeof window.requireMember === "function"
      ? window.requireMember(location.pathname)
      : Promise.resolve(null);
    Promise.resolve(p).then(function (member) {
      if (member) publishTier(member);
    }).catch(function () {}).then(function () {
      initHub();
    });
  }

  function init() {
    if (document.getElementById("education")) bootHub();
    if (document.getElementById("lessonRoot")) bootLesson();
    var logout = document.getElementById("eduLogout");
    if (logout) {
      logout.addEventListener("click", function () {
        if (typeof window.logOut === "function") window.logOut();
      });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
