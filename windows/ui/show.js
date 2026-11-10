// The show page of the Windows app: plays show/fly-2016.webm (the site's file as is: VP9 with alpha + Opus,
// 2016x1310, 13.741 s, the pause between the two clips already in it) once, with sound (unless ?muted=1; Mute while it
// plays: setMuted), in a transparent window, then tells the app it is over. ?ready=1: the window was made in advance,
// hidden: the page loads the video, says 'ready' and plays on go(). With ?selftest=1 it also measures: frames,
// intervals between shown frames (and when the long ones came), the decoder running dry ('waiting'), the sound, and in
// the held frame (frames 640-720 = 10.67-12.0 s stand still) it sends the frame's alpha so the app can compare the
// screen's pixels with the desktop under the window.
'use strict';

const q = new URLSearchParams(location.search);
const ID = Number(q.get('id') || 0);
const SELFTEST = q.get('selftest') === '1';
const READY = q.get('ready') === '1';  // made in advance: load, wait for go()
const MUTED = q.get('muted') === '1';  // the panel's Mute
const LONG_MS = 25;                    // a frame interval longer than this is listed with its moment
const VIDEO = 'show/fly-2016.webm';
const PAUSE_AT = [11.3, 11.9];        // media time to take the pause's screenshot at (inside the held frames)
const CELL = 4;                       // frame px per cell of the alpha mask sent to the app
const FILE_FRAMES = 797;              // 60/s; the sound runs on after the last frame to 13.741 s
// Outside the app (a check in a browser) the calls are only kept, for the check to read.
const invoke = window.__TAURI__ ? window.__TAURI__.core.invoke
  : async (cmd, args) => { (window.__roadster = window.__roadster || []).push([cmd, args]); };

const v = document.getElementById('v');
const errors = [];
const t = {};                         // ms since the navigation started (performance.now)
const frames = [];                    // [now, mediaTime, presentedFrames] per frame callback
const audio = { play: 'not started', peak: 0, ctx: 'n/a', tracks: null, meter: null };
const waits = [];                     // [now, mediaTime, event] when the video ran out of decoded frames
let done = false, captured = false, captureIdx = -1, bytes = 0;

addEventListener('error', e => errors.push('js: ' + e.message));
addEventListener('unhandledrejection', e => errors.push('promise: ' + ((e.reason && e.reason.message) || e.reason)));
v.addEventListener('error', () => {
  errors.push('video: ' + (v.error ? v.error.code + ' ' + v.error.message : 'unknown'));
  finish();
});
v.addEventListener('ended', () => finish());
for (const ev of ['waiting', 'stalled']) v.addEventListener(ev, () => waits.push([performance.now(), v.currentTime, ev]));
window.setMuted = m => { v.muted = !!m; };

function onFrame(now, md) {
  frames.push([now, md.mediaTime, md.presentedFrames]);
  if (frames.length === 1) {
    t.first = now;
    invoke('show_event', { id: ID, kind: 'first_frame' });
  }
  if (SELFTEST && !captured && md.mediaTime >= PAUSE_AT[0] && md.mediaTime <= PAUSE_AT[1]) {
    captured = true;
    captureIdx = frames.length - 1;
    capturePause(md.mediaTime);
  }
  if (!done) v.requestVideoFrameCallback(onFrame);
}

// The frame on screen now, scaled to cells of CELL x CELL frame px: '0' = alpha 0 everywhere in the cell, '2' = 255
// everywhere, '1' = anything else (edges, smoke, the shadow). The app compares only cells whose neighbours agree.
function capturePause(mediaTime) {
  try {
    const cols = Math.round(v.videoWidth / CELL), rows = Math.round(v.videoHeight / CELL);
    const c = document.createElement('canvas');
    c.width = cols;
    c.height = rows;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.imageSmoothingQuality = 'high';
    g.drawImage(v, 0, 0, cols, rows);
    const d = g.getImageData(0, 0, cols, rows).data;
    const m = new Array(cols * rows);
    for (let i = 0; i < m.length; i++) {
      const a = d[i * 4 + 3];
      m[i] = a === 0 ? '0' : a === 255 ? '2' : '1';
    }
    invoke('pause_capture', { id: ID, mask: m.join(''), cols, rows, mediaTime })
      .catch(e => errors.push('pause_capture: ' + e));
  } catch (e) {
    errors.push('pause mask: ' + e.message);
  }
}

// The sound's level as it leaves the decoder (a copy of the element's output; the element still plays to the
// speakers). Only in the self-test, so the normal show's sound path is not touched.
function audioMeter() {
  try {
    const stream = v.captureStream();
    const tracks = stream.getAudioTracks();
    audio.tracks = tracks.length;
    if (!tracks.length) { audio.meter = 'no audio track in the stream'; return; }
    const ac = new AudioContext();
    const an = ac.createAnalyser();
    an.fftSize = 2048;
    ac.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    audio.meter = 'on';
    const timer = setInterval(() => {
      audio.ctx = ac.state;
      if (done) { clearInterval(timer); ac.close(); return; }
      an.getFloatTimeDomainData(buf);
      for (const x of buf) audio.peak = Math.max(audio.peak, Math.abs(x));
    }, 50);
  } catch (e) {
    audio.meter = 'failed: ' + e.message;
  }
}

async function main() {
  t.script = performance.now();
  const r = await fetch(VIDEO);
  if (!r.ok) throw new Error(`fetch ${VIDEO}: ${r.status}`);
  const blob = await r.blob();          // a blob: URL plays and seeks from memory, whatever the app's protocol does
  bytes = blob.size;
  t.fetched = performance.now();
  v.src = URL.createObjectURL(blob);
  if (READY) {
    await new Promise((ok, no) => {
      v.addEventListener('canplay', ok, { once: true });
      v.addEventListener('error', no, { once: true });
      v.load();
    });
    t.ready = performance.now();
    invoke('show_event', { id: ID, kind: 'ready' });
    if (t.go) await start();          // Play came while the video was still loading
    return;
  }
  await start();
}

// A ready window plays on go() (the app calls it when it shows the window); before the video is loaded, as soon as it is.
window.go = () => {
  if (t.go) return;
  t.go = performance.now();
  if (t.ready) start().catch(e => { errors.push('start: ' + e.message); finish(); });
};

async function start() {
  v.muted = MUTED;
  v.volume = 1;
  v.requestVideoFrameCallback(onFrame);
  try {
    await v.play();
    audio.play = 'ok';
  } catch (e) {
    audio.play = `${e.name}: ${e.message}`;
    v.muted = true;                     // the picture all the same, so the rest can still be checked
    await v.play();
  }
  t.playing = performance.now();
  if (SELFTEST && !v.muted) audioMeter();
}

function finish() {
  if (done) return;
  done = true;
  invoke('show_done', { id: ID, lines: SELFTEST ? report() : {}, errors });
}

const f1 = x => x.toFixed(1);
const f2 = x => x.toFixed(2);

function report() {
  const out = { page: [], smooth: [], sound: [], errors };
  const dpr = devicePixelRatio, cw = innerWidth, ch = innerHeight, nw = v.videoWidth, nh = v.videoHeight;
  // object-fit: contain + object-position: 50% 100%: where the picture is inside the window
  const s = Math.min(cw / nw, ch / nh), dw = nw * s, dh = nh * s, dx = (cw - dw) / 2, dy = ch - dh;
  const now = new Date(), tz = -now.getTimezoneOffset() / 60;
  out.page.push(`time: ${now.toLocaleString('sv-SE')} (UTC${tz >= 0 ? '+' : ''}${tz})`);
  out.page.push(`page: ${cw}x${ch} CSS px, devicePixelRatio ${dpr}; video ${nw}x${nh}, shown ${f1(dw * dpr)}x${f1(dh * dpr)} px ` +
                `at (${f1(dx * dpr)}, ${f1(dy * dpr)}) in the window`);
  out.page.push(`video: ${(bytes / 1e6).toFixed(2)} MB, duration ${v.duration.toFixed(3)} s, played to ${v.currentTime.toFixed(3)} s, ` +
                `ended ${v.ended ? 'yes' : 'no'}`);

  const pq = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
  out.smooth.push(pq ? `frames (getVideoPlaybackQuality): total ${pq.totalVideoFrames}, dropped ${pq.droppedVideoFrames}, ` +
                       `corrupted ${pq.corruptedVideoFrames} (the file has ${FILE_FRAMES})`
                     : 'frames: getVideoPlaybackQuality not available');
  const iv = [];
  let skipped = 0;
  for (let i = 1; i < frames.length; i++) {
    iv.push(frames[i][0] - frames[i - 1][0]);
    const dp = frames[i][2] - frames[i - 1][2];
    if (dp > 1) skipped += dp - 1;
  }
  if (iv.length) {
    const sorted = [...iv].sort((a, b) => a - b);
    const mean = iv.reduce((a, b) => a + b, 0) / iv.length;
    const p99 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.99))];
    const over = iv.filter(x => x > LONG_MS).length;
    const cap = captureIdx >= 0 && captureIdx < iv.length ? `; the interval after the pause screenshot ${f1(iv[captureIdx])} ms` : '';
    out.smooth.push(`shown frames (requestVideoFrameCallback): ${frames.length}, interval mean ${f1(mean)} ms, ` +
                    `p99 ${f1(p99)} ms, max ${f1(sorted[sorted.length - 1])} ms, longer than ${LONG_MS} ms: ${over}`);
    out.smooth.push(`frames presented between callbacks (not seen by the page): ${skipped}${cap}`);
    // when: seconds from the first frame (the app's taskbar moments below use the same zero), the media time, the length
    const longs = [];
    for (let i = 0; i < iv.length; i++) {
      if (iv[i] > LONG_MS) longs.push(`${f2((frames[i + 1][0] - t.first) / 1000)} s (media ${f2(frames[i + 1][1])}) ${f1(iv[i])} ms`);
    }
    out.smooth.push(`long intervals at (seconds from the first frame): ${longs.length ? longs.join(', ') : 'none'}`);
  } else {
    out.smooth.push('shown frames (requestVideoFrameCallback): none');
  }
  out.smooth.push(`video ran out of decoded frames ('waiting'/'stalled'): ` + (waits.length
    ? waits.map(([n, m, e]) => `${e} at ${t.first ? f2((n - t.first) / 1000) + ' s' : 'before the first frame'} (media ${f2(m)})`).join(', ')
    : 'never'));
  out.smooth.push(`page timeline from navigation: script ${f1(t.script || 0)} ms, video fetched ${f1(t.fetched || 0)} ms, ` +
                  (READY ? `ready ${f1(t.ready || 0)} ms, go ${f1(t.go || 0)} ms, ` : '') +
                  `play() resolved ${f1(t.playing || 0)} ms, first frame ${f1(t.first || 0)} ms`);

  const decoded = v.webkitAudioDecodedByteCount;
  const db = audio.peak > 0 ? `${f1(20 * Math.log10(audio.peak))} dBFS` : 'silence';
  out.sound.push(`play() with sound: ${audio.play}; muted ${v.muted ? 'yes (the panel\'s Mute is on)' : 'no'}, volume ${v.volume}` +
                 (decoded !== undefined ? `, audio decoded ${(decoded / 1e3).toFixed(0)} kB` : ''));
  out.sound.push(`level meter: ${audio.meter || 'not started'}, AudioContext ${audio.ctx}, audio tracks ${audio.tracks}, peak ${db}`);
  let verdict;
  if (MUTED) verdict = 'MUTED by the panel\'s Mute (turn it off and run the self-test again to check the sound)';
  else if (audio.play !== 'ok') verdict = 'BLOCKED: the browser refused to play with sound without a click (autoplay policy); the show ran muted';
  else if (audio.peak > 0.001) verdict = 'PLAYED (the page played it unmuted and its level was above zero; whether the speakers were on is for the ear)';
  else if (audio.meter !== 'on') verdict = 'play() with sound was allowed; the level could not be measured';
  else verdict = 'play() with sound was allowed, but the level stayed at zero';
  out.sound.push('verdict: ' + verdict);
  return out;
}

main().catch(e => { errors.push('start: ' + e.message); finish(); });
