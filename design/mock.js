// Roadster for Mac, design mock-ups (version 1): the menu bar and the panel in each state, built from the URL.
//   panel.html?state=off|pomo-ready|pomo-work|pomo-break|hourly|random|mute&theme=light|dark&mode=seg|radio&icon=wheels
// The look is in roadster.css; design/shoot.py takes the PNGs.

const Q = new URLSearchParams(location.search);

// Menu bar glyphs: our own simple drawings in currentColor, only to set the scene.
const GLYPH = {
  battery: `<svg width="27" height="13" viewBox="0 0 27 13" fill="none"><rect x="0.5" y="0.5" width="23" height="12" rx="3.5" stroke="currentColor" opacity="0.45"/><rect x="2.5" y="2.5" width="15" height="8" rx="1.8" fill="currentColor"/><path d="M25 4.5v4c.9-.3 1.5-1.1 1.5-2s-.6-1.7-1.5-2z" fill="currentColor" opacity="0.45"/></svg>`,
  wifi: `<svg width="18" height="14" viewBox="0 0 18 14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M1.6 5.2a10.6 10.6 0 0 1 14.8 0"/><path d="M4.3 8a6.7 6.7 0 0 1 9.4 0"/><path d="M6.9 10.7a3 3 0 0 1 4.2 0"/><circle cx="9" cy="12.6" r="0.6" fill="currentColor"/></svg>`,
  search: `<svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="6.2" cy="6.2" r="4.6"/><path d="M9.6 9.6l4 4"/></svg>`,
  cc: `<svg width="17" height="14" viewBox="0 0 17 14" fill="none" stroke="currentColor" stroke-width="1.3"><rect x="0.9" y="0.9" width="15.2" height="5.2" rx="2.6"/><circle cx="13.5" cy="3.5" r="1.6" fill="currentColor" stroke="none"/><rect x="0.9" y="7.9" width="15.2" height="5.2" rx="2.6"/><circle cx="3.5" cy="10.5" r="1.6" fill="currentColor" stroke="none"/></svg>`,
  play: `<svg width="13" height="14" viewBox="0 0 13 14"><path d="M2 1.6v10.8c0 .8.9 1.3 1.6.9l8.6-5.4c.6-.4.6-1.3 0-1.7L3.6.8C2.9.3 2 .8 2 1.6z" fill="currentColor"/></svg>`,
};

function menubar({ icon = "wheels", open = false, clock = "Mon 2 Nov  16:18", width } = {}) {
  const w = width ? ` style="width:${width}px"` : "";
  return `<div class="menubar"${w}>
    <div class="mb-item${open ? " open" : ""}"><img class="mb-car" src="icon/roadster-${icon}.svg" width="32" height="18" alt=""></div>
    <div class="mb-item">${GLYPH.battery}</div><div class="mb-item">${GLYPH.wifi}</div>
    <div class="mb-item">${GLYPH.search}</div><div class="mb-item">${GLYPH.cc}</div>
    <div class="mb-clock">${clock.replace(/ {2}/, "&nbsp;&nbsp;")}</div></div>`;
}

const sw = (on) => `<button class="switch" role="switch" aria-checked="${on}"><span class="track"><span class="knob"></span></span></button>`;

const MODES = [["pomo", "Pomodoro"], ["hourly", "Every hour"], ["random", "Random"]];

function modePicker(mode, style) {
  if (style === "radio") {
    return `<div class="card"><div class="radios">${MODES.map(([k, t]) =>
      `<span class="radio${k === mode ? " on" : ""}"><i></i>${t}</span>`).join("")}</div></div>`;
  }
  return `<div class="seg" role="radiogroup">${MODES.map(([k, t]) =>
    `<button role="radio" aria-checked="${k === mode}">${t}</button>`).join("")}</div>`;
}

function pomodoro(phase) {
  // phase: ready | work | break | paused (the master switch is off)
  const P = {
    ready:  { dot: "idle", name: "Work", time: "25:00", left: "", btns: `<button class="btn go">Start</button>`, idle: true },
    work:   { dot: "", name: "Work", time: "18:42", left: "left", btns: `<button class="btn">Pause</button><button class="btn">Reset</button>` },
    break:  { dot: "break", name: "Break", time: "3:12", left: "left", btns: `<button class="btn">Pause</button><button class="btn">Reset</button>` },
    paused: { dot: "", name: "Work · paused", time: "18:42", left: "left", btns: `<button class="btn">Resume</button><button class="btn">Reset</button>` },
  }[phase];
  return `<div class="card">
      <div class="line timer-line">
        <div class="timer grow">
          <div class="phase"><span class="dot ${P.dot}"></span>${P.name}</div>
          <div class="time${P.idle ? " idle" : ""}">${P.time}${P.left ? `<small>${P.left}</small>` : ""}</div>
        </div>
        <div class="btns">${P.btns}</div>
      </div>
      <div class="line"><div class="fields">Work <input class="num" value="25"> min<span class="gap"></span>Break <input class="num" value="5"> min</div></div>
    </div>
    <div class="note">The car flies out when work ends and when the break ends.</div>`;
}

const HOURLY = `<div class="card"><div class="line"><div class="text"><div class="label">Next show at 17:00</div>
    <div class="sub">On the hour, every hour</div></div></div></div>`;

const RANDOM = `<div class="card"><div class="line"><div class="fields">Every <input class="num" value="30"> – <input class="num" value="90"> min</div></div></div>
    <div class="note">The car comes at a random moment, from 30 to 90 minutes after the last show.</div>`;

function panel(state, { modeStyle = "seg" } = {}) {
  const S = {
    "off":        { on: false, mode: "pomo", body: pomodoro("paused") },
    "pomo-ready": { on: true, mode: "pomo", body: pomodoro("ready") },
    "pomo-work":  { on: true, mode: "pomo", body: pomodoro("work") },
    "pomo-break": { on: true, mode: "pomo", body: pomodoro("break") },
    "hourly":     { on: true, mode: "hourly", body: HOURLY },
    "random":     { on: true, mode: "random", body: RANDOM },
    "mute":       { on: true, mode: "hourly", body: HOURLY, mute: true },
  }[state];
  return `<div class="panel${S.on ? "" : " paused"}">
    <div class="head">
      <img class="logo" src="icon/app-icon-placeholder.svg" alt="">
      <div class="brand"><div class="brand-name">Roadster</div><div class="brand-tag">by VALENTIN STE</div></div>
      ${sw(S.on)}
    </div>
    <div class="groups">
      <div class="group"><h2 class="group-title">Mode</h2>${modePicker(S.mode, modeStyle)}</div>
      <div class="group">${S.body}</div>
    </div>
    <div class="card"><div class="line">
      <button class="btn play">${GLYPH.play}Play now</button><span class="grow"></span>
      <span class="label">Mute</span>${sw(!!S.mute)}
    </div></div>
    <div class="card"><div class="line"><span class="label grow">Open at login</span>${sw(true)}</div></div>
    <div class="foot"><a href="#">About</a><a class="quit" href="#">Quit</a></div>
  </div>`;
}

function scene(inner, { icon = "wheels", open = true, width = 400 } = {}) {
  return `<div class="scene" id="board" style="width:${width}px">${menubar({ icon, open })}
    <div style="display:flex;justify-content:flex-end;padding:6px 8px 30px">${inner}</div></div>`;
}

const theme = Q.get("theme") === "dark" ? "dark" : "light";
const q = (k, d) => Q.get(k) ?? d;
