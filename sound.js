/* TraderWatch sound engine — Web Audio synthesized UI feedback.
 * Subtle, premium tones (no audio assets). Default ON, mute toggle persisted.
 * Audio only starts after a user gesture (browser autoplay-safe).
 * Usage: TWSound.play('success'|'error'|'notify'|'copy'|'trade'|'click').
 * Toggle buttons: add attribute data-sound-toggle to any <button>.
 */
(function () {
  var KEY = 'tw_sound_muted';
  var ctx = null, master = null, muted = false;
  try { muted = localStorage.getItem(KEY) === '1'; } catch (_) {}

  var ICON_ON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>';
  var ICON_OFF = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="m16 9 5 6"/><path d="m21 9-5 6"/></svg>';

  function ensureCtx() {
    if (!ctx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = 0.5;           // master subtle
      master.connect(ctx.destination);
    }
    if (ctx.state === 'suspended') { try { ctx.resume(); } catch (_) {} }
    return ctx;
  }

  function tone(freq, dur, type, vol, when, slideTo) {
    var c = ensureCtx(); if (!c || muted) return;
    var t0 = c.currentTime + (when || 0);
    var osc = c.createOscillator(), g = c.createGain();
    osc.type = type || 'sine';
    osc.frequency.setValueAtTime(freq, t0);
    if (slideTo) osc.frequency.exponentialRampToValueAtTime(slideTo, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol || 0.25, t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g); g.connect(master);
    osc.start(t0); osc.stop(t0 + dur + 0.03);
  }

  function clickNoise() {
    var c = ensureCtx(); if (!c || muted) return;
    var len = Math.floor(c.sampleRate * 0.03);
    var buf = c.createBuffer(1, len, c.sampleRate);
    var d = buf.getChannelData(0);
    for (var i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.2);
    var src = c.createBufferSource(); src.buffer = buf;
    var bp = c.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 2400; bp.Q.value = 1.2;
    var g = c.createGain(); g.gain.value = 0.22;
    src.connect(bp); bp.connect(g); g.connect(master);
    src.start();
  }

  // IQ Option-style noise swoosh (filter sweep) for trade open.
  function noiseSweep(dur, fromFreq, toFreq, vol) {
    var c = ensureCtx(); if (!c || muted) return;
    var t0 = c.currentTime;
    var len = Math.floor(c.sampleRate * dur);
    var buf = c.createBuffer(1, len, c.sampleRate);
    var d = buf.getChannelData(0);
    for (var i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 1.4);
    var src = c.createBufferSource(); src.buffer = buf;
    var bp = c.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 2.2;
    bp.frequency.setValueAtTime(fromFreq, t0);
    bp.frequency.exponentialRampToValueAtTime(toFreq, t0 + dur);
    var g = c.createGain(); g.gain.setValueAtTime(vol, t0);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    src.connect(bp); bp.connect(g); g.connect(master); src.start(t0);
  }

  // IQ Option-inspired trading palette: punchy electronic, bright profit,
  // dull descending loss, crisp dry clicks.
  // Soft pleasant UI tap (mellow sine pop — not harsh square/noise).
  function softPop(freq, vol) {
    var c = ensureCtx(); if (!c || muted) return;
    var t0 = c.currentTime;
    var osc = c.createOscillator(), g = c.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, t0);
    osc.frequency.exponentialRampToValueAtTime(freq * 0.7, t0 + 0.06);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.075);
    osc.connect(g); g.connect(master); osc.start(t0); osc.stop(t0 + 0.09);
  }
  var sounds = {
    click:   function () { softPop(660, 0.12); },
    tick:    function () { tone(2600, 0.018, 'sine', 0.09); },
    toggle:  function () { tone(950, 0.045, 'triangle', 0.16); tone(1400, 0.05, 'sine', 0.1, 0.03); },
    // trade open: swoosh + confirmation blip
    trade:   function () { noiseSweep(0.13, 3200, 420, 0.26); tone(620, 0.09, 'sine', 0.2, 0.02, 940); },
    // profit: bright ascending sparkle arpeggio
    success: function () { tone(880, 0.1, 'sine', 0.22); tone(1108, 0.1, 'sine', 0.2, 0.07); tone(1318, 0.12, 'sine', 0.2, 0.14); tone(1760, 0.22, 'sine', 0.16, 0.21); tone(2637, 0.18, 'sine', 0.06, 0.21); },
    // loss: dull descending womp
    error:   function () { tone(330, 0.16, 'sine', 0.22, 0, 230); tone(230, 0.26, 'sine', 0.17, 0.12, 150); },
    notify:  function () { tone(1046, 0.09, 'square', 0.13); tone(1568, 0.16, 'square', 0.11, 0.09); },
    copy:    function () { tone(820, 0.06, 'triangle', 0.2, 0, 1250); }
  };
  sounds.profit = sounds.success;
  sounds.loss = sounds.error;
  sounds.open = sounds.trade;

  function play(name) {
    if (muted) return;
    try { (sounds[name] || sounds.click)(); } catch (_) {}
  }

  function updateButtons() {
    var btns = document.querySelectorAll('[data-sound-toggle]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].innerHTML = muted ? ICON_OFF : ICON_ON;
      btns[i].setAttribute('aria-pressed', muted ? 'false' : 'true');
      btns[i].setAttribute('aria-label', muted ? 'Turn sound on' : 'Turn sound off');
      btns[i].title = muted ? 'Sound off' : 'Sound on';
    }
  }

  function setMuted(m) {
    muted = !!m;
    try { localStorage.setItem(KEY, muted ? '1' : '0'); } catch (_) {}
    updateButtons();
    if (!muted) play('toggle');
  }

  // Global tap feedback for interactive elements (capture phase = low latency).
  document.addEventListener('pointerdown', function (e) {
    if (muted) return;
    var el = e.target.closest && e.target.closest('button, a, [role="button"], .clickable, .mysig-row, .nav, .tab, summary, input[type="submit"], input[type="checkbox"], select');
    if (el && !el.hasAttribute('data-sound-toggle') && !el.hasAttribute('data-no-sound')) play('click');
  }, true);

  // Mute toggle buttons.
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-sound-toggle]');
    if (b) { e.preventDefault(); setMuted(!muted); }
  });

  function init() { updateButtons(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  window.TWSound = { play: play, toggle: function () { setMuted(!muted); }, setMuted: setMuted, isMuted: function () { return muted; } };
})();