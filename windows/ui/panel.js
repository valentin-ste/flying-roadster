// The panel (design v1: design/mock.js's markup, roadster.css's look) and About inside it (design/about.html; Back
// returns). The app sends the state with render(state, seq) before it shows the window, and again whenever the schedule
// changes; every switch, field and button goes to the app (panel.rs, modes.rs), which keeps the setting, runs the
// schedule and answers with the new state. The page only shows it: the pomodoro's countdown is drawn from the `left`
// it was sent while `ticking`. Outside the app (a browser, windows/tools/check_panel.py) ?state=... shows the design's
// states from a stand-in state, ?theme=dark the dark theme.
'use strict';

const TAURI = window.__TAURI__;
const Q = new URLSearchParams(location.search);
const MODES = [['pomodoro', 'Pomodoro'], ['hourly', 'Every hour'], ['random', 'Random']];
const RANGES = { work: [1, 180], break: [1, 60], from: [1, 600], to: [1, 600] };
const PLAY = `<svg width="13" height="14" viewBox="0 0 13 14"><path d="M2 1.6v10.8c0 .8.9 1.3 1.6.9l8.6-5.4c.6-.4.6-1.3 0-1.7L3.6.8C2.9.3 2 .8 2 1.6z" fill="currentColor"/></svg>`;

// ---- the app, or a stand-in for the checks ----
const DEMO = {
  'off':         { enabled: false, pomo: { run: 'running', phase: 'work', left: 1122 } },
  'pomo-ready':  {},
  'pomo-work':   { pomo: { run: 'running', phase: 'work', left: 1122, ticking: true } },
  'pomo-break':  { pomo: { run: 'running', phase: 'rest', left: 192, ticking: true } },
  'pomo-paused': { pomo: { run: 'paused', phase: 'work', left: 1122 } },
  'pomo-widest': { work: 180, break: 60, pomo: { run: 'paused', phase: 'rest', left: 180 * 60 } }, // as the Mac's
  'hourly':      { mode: 'hourly' },
  'hourly-off':  { mode: 'hourly', enabled: false },
  'random':      { mode: 'random' },
  'mute':        { mode: 'hourly', muted: true },
  'about':       { about: true },
};
let demo = Object.assign({ enabled: true, mode: 'pomodoro', muted: false, work: 25, break: 5, from: 30, to: 90, login: true,
                           dark: Q.get('theme') === 'dark', nextHour: '17:00', version: '0.3.0',
                           pomo: { run: 'ready', phase: 'work', left: 0, ticking: false } },
                         DEMO[Q.get('state') || 'pomo-ready'] || {});
const DEMO_ABOUT = !!demo.about;
async function call(cmd, args) {
  if (TAURI) return TAURI.core.invoke(cmd, args);
  (window.__calls = window.__calls || []).push([cmd, args]);
  if (cmd === 'panel_set') {
    demo[args.key] = args.value;
    if (args.key === 'from' && demo.to < demo.from) demo.to = demo.from;
    if (args.key === 'to' && demo.from > demo.to) demo.from = demo.to;
  }
  if (cmd === 'panel_action') {
    const p = demo.pomo;
    if (args.name === 'start' && p.run === 'ready') { demo.enabled = true; demo.pomo = { run: 'running', phase: 'work', left: demo.work * 60, ticking: true }; }
    if (args.name === 'resume') { demo.enabled = true; demo.pomo = Object.assign({}, p, { run: 'running', ticking: true }); }
    if (args.name === 'pause') demo.pomo = Object.assign({}, p, { run: 'paused', ticking: false });
    if (args.name === 'reset') demo.pomo = { run: 'ready', phase: 'work', left: 0, ticking: false };
  }
  return JSON.parse(JSON.stringify(demo));
}

// ---- the markup: once; render() only changes what the state says ----
const sw = key => `<button class="switch" role="switch" aria-checked="false" data-key="${key}"><span class="track"><span class="knob"></span></span></button>`;
const num = key => `<input class="num" inputmode="numeric" maxlength="3" data-key="${key}" aria-label="${key} minutes">`;

const ABOUT = `
<div class="panel about-panel" hidden>
  <div class="about about-body">
    <img class="app-icon" src="app-icon.svg" alt="">
    <h1>Roadster</h1>
    <div class="ver" id="ver">Version</div>
    <div class="credits">
      <a class="brandline" href="https://x.com/valentinste_dev">VALENTIN STE</a>
      <div>Car model: “<a href="https://sketchfab.com/3d-models/tesla-roadster-2020-1fbf29e297bd4a17ac39a00a378441d8">Tesla Roadster 2020</a>” by <a href="https://sketchfab.com/metarex.4d">metarex.4d</a> on Sketchfab, licensed under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Changed: scaled, wheels rigged, materials tuned.</div>
      <div>Sounds: Freesound, CC0.</div>
      <div>Not affiliated with Tesla, Inc.</div>
    </div>
    <div class="copy">© 2026 VALENTIN STE</div>
  </div>
  <div class="foot"><a href="#" data-action="back">Back</a><a class="quit" href="#" data-action="quit">Quit</a></div>
</div>`;

document.getElementById('root').innerHTML = `
<div class="panel main-panel">
  <div class="head">
    <img class="logo" src="app-icon.svg" alt="">
    <div class="brand"><div class="brand-name">Roadster</div><div class="brand-tag">by VALENTIN STE</div></div>
    ${sw('enabled')}
  </div>
  <div class="groups">
    <div class="group"><h2 class="group-title">Mode</h2>
      <div class="seg" role="radiogroup" aria-label="Mode">${MODES.map(([k, t]) =>
        `<button role="radio" aria-checked="false" data-mode="${k}">${t}</button>`).join('')}</div>
    </div>
    <div class="modes">
      <div class="group" data-body="pomodoro">
        <div class="card">
          <div class="line timer-line">
            <div class="timer grow">
              <div class="phase"><span class="dot" id="dot"></span><span id="phase"></span></div>
              <div class="time" id="time"></div>
            </div>
            <div class="btns" id="btns"></div>
          </div>
          <div class="line"><div class="fields">Work ${num('work')} min<span class="gap"></span>Break ${num('break')} min</div></div>
        </div>
        <div class="note">The car flies out when work ends and when the break ends.</div>
      </div>
      <div class="group" data-body="hourly">
        <div class="card"><div class="line"><div class="text"><div class="label" id="next"></div>
          <div class="sub">On the hour, every hour</div></div></div></div>
      </div>
      <div class="group" data-body="random">
        <div class="card"><div class="line"><div class="fields">Every ${num('from')} – ${num('to')} min</div></div></div>
        <div class="note" id="random-note"></div>
      </div>
    </div>
  </div>
  <div class="card"><div class="line">
    <button class="btn play" data-action="play">${PLAY}Play now</button><span class="grow"></span>
    <span class="label">Mute</span>${sw('muted')}
  </div></div>
  <div class="card"><div class="line"><span class="label grow">Open at login</span>${sw('login')}</div></div>
  <div class="foot"><a href="#" data-action="about">About</a><a class="quit" href="#" data-action="quit">Quit</a></div>
</div>` + ABOUT;

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let state = demo;
let shown = false;
let received = performance.now(); // when `state` came: the countdown runs from its `left`
let flip = 0;
let lastSet = Promise.resolve();

const mmss = t => { const s = Math.ceil(Math.max(0, t)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };

// The pomodoro's line as on the Mac (Panel.swift, pomodoroTimer): off, a started pomodoro shows as paused; Start and
// Resume switch the app on (the app does it).
const leftNow = s => { const p = s.pomo || {}; return p.ticking ? p.left - (performance.now() - received) / 1000 : (p.left || 0); };
function pomodoro(s) {
  const p = s.pomo || { run: 'ready', phase: 'work' };
  const ready = p.run === 'ready';
  const paused = p.run === 'paused' || (!ready && !s.enabled);
  $('#dot').className = 'dot' + (ready ? ' idle' : p.phase === 'work' ? '' : ' break');
  $('#phase').textContent = (p.phase === 'work' ? 'Work' : 'Break') + (paused ? ' · paused' : '');
  const time = $('#time');
  time.className = 'time' + (ready ? ' idle' : '');
  const html = mmss(ready ? s.work * 60 : leftNow(s)) + (ready ? '' : '<small>left</small>');
  if (time.innerHTML !== html) time.innerHTML = html;
  const btns = ready ? [['Start', 'start', true]]
    : [[paused ? 'Resume' : 'Pause', paused ? 'resume' : 'pause'], ['Reset', 'reset']];
  const bhtml = btns.map(([t, a, go]) => `<button class="btn${go ? ' go' : ''}" data-action="${a}">${t}</button>`).join('');
  if ($('#btns').innerHTML !== bhtml) $('#btns').innerHTML = bhtml;
}

// the countdown on the pomodoro's whole seconds (the Mac's nextFlip); at 0:00 the app sends the next phase
function countdown() {
  clearTimeout(flip);
  if (!(state.pomo && state.pomo.ticking) || state.mode !== 'pomodoro') return;
  const r = leftNow(state);
  if (r <= 0) return;
  const f = r - Math.floor(r);
  flip = setTimeout(() => { pomodoro(state); countdown(); }, (f < 0.001 ? 1 : f) * 1000 + 10);
}

function view(about) {
  $('.main-panel').hidden = about;
  $('.about-panel').hidden = !about;
}

window.render = (s, seq) => {
  if (!s) return;
  state = s;
  received = performance.now();
  document.documentElement.className = s.dark ? 'dark' : '';
  $('#ver').textContent = `Version ${s.version || ''}`;
  $('.panel').classList.toggle('paused', !s.enabled);
  for (const b of $$('.switch')) b.setAttribute('aria-checked', String(!!s[b.dataset.key]));
  for (const b of $$('.seg button')) b.setAttribute('aria-checked', String(b.dataset.mode === s.mode));
  for (const g of $$('.modes > .group')) g.setAttribute('aria-hidden', String(g.dataset.body !== s.mode));
  for (const f of $$('.num')) if (f !== document.activeElement) f.value = s[f.dataset.key];
  pomodoro(s);
  $('#next').textContent = s.enabled ? `Next show at ${s.nextHour}` : 'Paused';
  $('#random-note').textContent = `The car comes at a random moment, from ${s.from} to ${s.to} minutes after the last show.`;
  countdown();
  if (seq) call('panel_ready', { seq });
};

// ---- input ----
document.addEventListener('click', e => {
  const sw = e.target.closest('.switch');
  if (sw) return void call('panel_set', { key: sw.dataset.key, value: sw.getAttribute('aria-checked') !== 'true' }).then(render);
  const seg = e.target.closest('.seg button');
  if (seg) return void call('panel_set', { key: 'mode', value: seg.dataset.mode }).then(render);
  const link = e.target.closest('.about-body a[href]');
  if (link) { e.preventDefault(); return void call('open_url', { url: link.href }); } // the browser, never this window
  const act = e.target.closest('[data-action]');
  if (act) {
    e.preventDefault();
    const a = act.dataset.action;
    if (a === 'about' || a === 'back') return void view(a === 'about');
    return void call('panel_action', { name: a }).then(s => { if (s && a !== 'quit') render(s); });
  }
});

// A minutes field keeps whole minutes within its range on Enter, on leaving it and when the panel closes (700 -> 600,
// 0 -> 1); anything else (2.5, letters, empty) puts the kept number back, as on the Mac (MinutesField).
function commitField(f) {
  const [lo, hi] = RANGES[f.dataset.key];
  const kept = state[f.dataset.key];
  const t = f.value.trim();
  if (!/^[+-]?\d+$/.test(t)) { f.value = kept; return; }
  const n = Math.min(Math.max(parseInt(t, 10), lo), hi);
  f.value = n;
  if (n !== kept) lastSet = call('panel_set', { key: f.dataset.key, value: n }).then(render);
}
for (const f of $$('.num')) {
  f.addEventListener('keydown', e => { if (e.key === 'Enter') { commitField(f); f.select(); } });
  f.addEventListener('blur', () => commitField(f));
}
// The panel closes: a number being typed is kept; then (bye) the app may destroy the window.
window.commit = bye => {
  shown = false;
  clearTimeout(flip);
  if (document.activeElement && document.activeElement.classList.contains('num')) document.activeElement.blur();
  if (bye) lastSet.finally(() => call('panel_bye', {}));
};

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { e.preventDefault(); window.commit(); call('panel_action', { name: 'close' }); return; }
  // the browser's own keys (reload, print, find, save, source) mean nothing in a panel
  const k = e.key.toLowerCase();
  if (e.key === 'F5' || e.key === 'F3' || e.key === 'F7' || (e.ctrlKey && ['r', 'p', 'f', 'g', 's', 'u', 'j', 'h'].includes(k))) e.preventDefault();
});
document.addEventListener('contextmenu', e => { if (!e.target.closest('.num')) e.preventDefault(); });


// ---- the app's measurements: which fonts Windows has, the page's size, the first frame after the window appeared ----
function hasFont(name) {
  const c = document.createElement('canvas').getContext('2d');
  const text = 'Roadster by VALENTIN STE 0123456789';
  c.font = '20px monospace';
  const base = c.measureText(text).width;
  c.font = `20px "${name}", monospace`;
  return c.measureText(text).width !== base;
}

// the content's own height with the mode's block at its natural height (the window may be taller: the rest is empty)
function layout() {
  const panel = $('.panel'), groups = $('.groups');
  const natural = groups.firstElementChild.offsetHeight + 16 + $('.modes').offsetHeight;
  return { css: `${innerWidth}x${innerHeight}`, dpr: devicePixelRatio, content: panel.offsetHeight - groups.offsetHeight + natural,
           font: getComputedStyle($('.brand-name')).fontFamily.split(',')[0] };
}
window.__layout = layout;

window.painted = seq => {
  shown = true;
  requestAnimationFrame(() => call('panel_painted', { seq, layout: layout() }));
};

render(state);
view(DEMO_ABOUT);
call('panel_hello', { fonts: { 'Segoe UI Variable Text': hasFont('Segoe UI Variable Text'), 'Segoe UI': hasFont('Segoe UI') } });
