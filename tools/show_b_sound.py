"""Sound of show B (02.11): a track per clip for the program and the approved video with each variant's sound under it.

Every variant is one block of numbers in tools/show_b_sound.toml: which files, the level of each kind of event, attacks
and tails. Change a number and rebuild in seconds (.venv/bin/python3, README):
  tools/show_b_sound.py              # every variant in the file
  tools/show_b_sound.py b            # some of them: b c
  tools/show_b_sound.py b --no-video # only the tracks
Writes out/show-b/sound/<v>/clip1.wav and clip2.wav (48 kHz, stereo, 24 bit; each starts with its clip's first frame;
clip 1 is silent before its last frame, clip 2 runs tail_s past its last frame while the car fades out to the right) and
out/show-b/sound/show-b-cloud-<v>.mp4: the picture of out/show-b/show-b-cloud.mp4 copied as it is, the two tracks under
it with the pause the video holds between the clips. Prints the loudness, the true peak, every layer's level and the
level around every event: the numbers stand in for the ears.

All from out/show-b/motion.json: the hiss of each jet group follows the group's summed thrust (an attack at the
ignition, a tail after the cutoff) and darkens as the thrust falls; a valve crack and thump at each ignition, a chuff at
each cutoff; hits at the lift-off and the dash; tyres, brakes and the motor follow the speed while the wheels touch the
floor; a thud per axle at the touchdown and the suspension's whump; each layer panned by where its source is on the
screen and fading off it; a small synthetic room; the whole show brought to one loudness (EBU R128) under a peak
ceiling. The recordings are in sounds/ (CC0, CREDITS.md); decoded copies are cached in out/show-b/sound/cache.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import tomllib
import zlib
from fractions import Fraction

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOW = ROOT / "out" / "show-b"
CONF = ROOT / "tools" / "show_b_sound.toml"
SR, CR = 48000, 1000  # audio rate, control rate of the envelopes
SCREEN_W = 14.0  # m: the 3024 px screen at 216 px/m, x = 0 at its left edge (README, show B)
SOURCE_X = {"down": 0.07, "side": 0.07, "back": -1.98}  # where each jet group sits along the car (its nozzles), m
SETTLE_FRAMES = 12  # the physics drops the car onto its springs in the first frames, off the screen: no sound for that
GUARD_S = 0.25  # clip 1 fades to zero over its last 0.25 s whatever the numbers say: nothing crosses the cut
KW = np.vstack([signal.tf2sos([1.53512485958697, -2.69169618940638, 1.19839281085285],
                              [1.0, -1.69065929318241, 0.73248077421585]),
                signal.tf2sos([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])])  # BS.1770 K, 48 kHz


def amp(db):
    return 0.0 if db <= -99 else 10 ** (db / 20)


def dbfs(v):
    return 20 * np.log10(max(float(v), 1e-10))


def band(x, lo=None, hi=None, order=2):
    if lo and hi and hi < SR / 2:
        sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    elif lo:
        sos = signal.butter(order, lo, btype="high", fs=SR, output="sos")
    elif hi and hi < SR / 2:
        sos = signal.butter(order, hi, btype="low", fs=SR, output="sos")
    else:
        return x
    return signal.sosfilt(sos, x, axis=0)


def rms_norm(x):
    return x / (np.sqrt(np.mean(x * x)) + 1e-12)


def decode(path):
    """A sound file as mono float at 48 kHz, cached next to the outputs (out/ is outside git)."""
    path = ROOT / os.path.expanduser(path)  # a relative path is in this repository (sounds/)
    st = path.stat()
    cache = SHOW / "sound" / "cache" / f"{path.stem}-{st.st_size}-{int(st.st_mtime)}.npy"
    if cache.exists():
        return np.load(cache)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, x)
    return x


class Sources:
    def __init__(self, table):
        self.table = table

    def raw(self, name, pitch=1.0):
        s = self.table[name]
        x = decode(s["file"])
        if "trim" in s:
            x = x[int(s["trim"][0] * SR):int(s["trim"][1] * SR)]
        if pitch != 1.0:  # played back faster or slower: every frequency times pitch
            fr = Fraction(1 / pitch).limit_denominator(24)
            x = signal.resample_poly(x, fr.numerator, fr.denominator)
        return x

    def bed(self, name, pitch=1.0):
        """A recording for looping: its slow level swings taken out (the thrust sets the level), RMS 1."""
        x = self.raw(name, pitch)
        env = np.sqrt(uniform_filter1d(x * x, int(0.25 * SR)))
        return rms_norm(x / np.maximum(env, 0.1 * env.max()))

    def shot(self, name, lowpass=None):
        """A one-shot, peak 1, and where it starts (s, -20 dB of its peak): placed with its start on the event."""
        x = self.raw(name)
        if lowpass:
            x = band(x, hi=lowpass, order=4)
        x = x / (np.abs(x).max() + 1e-12)
        e = uniform_filter1d(np.abs(x), int(0.002 * SR))
        return x, int(np.argmax(e >= 0.1 * e.max())) / SR


def loop(x, n, rng, fade=0.25):
    """A recording looped to n samples from shifting start points, equal-power crossfades."""
    f = max(16, min(int(fade * SR), len(x) // 5))
    w_in, w_out = np.sin(np.linspace(0, np.pi / 2, f)), np.cos(np.linspace(0, np.pi / 2, f))
    out, pos = np.zeros(n + len(x)), 0
    while pos < n:
        seg = x[int(rng.uniform(0, len(x) // 2)):].copy()
        seg[:f] *= w_in
        seg[-f:] *= w_out
        out[pos:pos + len(seg)] += seg
        pos += len(seg) - f
    return out[:n]


def follow(d, attack_ms, release_ms):
    """Control-rate drive -> envelope: rises with attack_ms, falls with release_ms (one pole each way)."""
    ka = np.exp(-1000 / (max(attack_ms, 0.1) * CR))
    kr = np.exp(-1000 / (max(release_ms, 0.1) * CR))
    out, y = np.empty(len(d)), 0.0
    for i, v in enumerate(d):
        k = ka if v > y else kr
        y = k * y + (1 - k) * v
        out[i] = y
    return out


def place(buf, x, t, gain, start=0.0):
    """Add x to buf so that the point start s into it lands at t s (cut at the clip's start with a 3 ms fade)."""
    k = int(round((t - start) * SR))
    if k < 0:
        x = x[-k:].copy()
        f = min(len(x), int(0.003 * SR))
        x[:f] *= np.linspace(0, 1, f)
        k = 0
    n = min(len(x), len(buf) - k)
    if n > 0 and gain:
        buf[k:k + n] += gain * x[:n]


def pop(rng, I):
    """A valve opening: a short broadband crack and a low thump."""
    n = int(max(I["crack_ms"] * 8, I["thump_ms"] * 6) / 1000 * SR)
    t = np.arange(n) / SR
    crack = band(rng.standard_normal(n), 400, 9000) * np.exp(-t / (I["crack_ms"] / 1000))
    thump = np.sin(2 * np.pi * I["thump_hz"] * t) * np.exp(-t / (I["thump_ms"] / 1000)) * (1 - np.exp(-t / 0.002))
    return amp(I["crack_db"]) * crack / (np.abs(crack).max() + 1e-12) + amp(I["thump_db"]) * thump


def chuff(rng, ms):
    """A valve shutting: a soft dull puff."""
    n = int(ms * 6 / 1000 * SR)
    t = np.arange(n) / SR
    x = band(rng.standard_normal(n), 150, 2500) * (1 - np.exp(-t / 0.004)) * np.exp(-t / (ms / 1000))
    return x / (np.abs(x).max() + 1e-12)


def crack(rng):
    """The whip of a hit: a very short bright crack."""
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    x = band(rng.standard_normal(n), 1500, 11000) * (1 - np.exp(-t / 0.0008)) * np.exp(-t / 0.018)
    return x / (np.abs(x).max() + 1e-12)


class Motion:
    """out/show-b/motion.json as arrays per frame, the on-state of every jet group, the event clusters."""

    def __init__(self, path):
        m = json.loads(path.read_text())
        self.fps, F, self.marks, self.events = m["fps"], m["frames"], m["marks"], m["events"]
        groups = [nz["group"] for nz in m["nozzles"]]
        self.count = {g: groups.count(g) for g in dict.fromkeys(groups)}
        th = np.array([f["thrust"] for f in F])
        self.T = {g: th[:, [i for i, gg in enumerate(groups) if gg == g]].sum(1) for g in self.count}
        self.x = np.array([f["pos"][0] for f in F])
        self.cw = np.array([[w["contact"] for w in f["wheels"]] for f in F], bool)
        self.contact = self.cw.mean(1)
        self.contact[:SETTLE_FRAMES] = self.contact[SETTLE_FRAMES]
        self.up = np.array([[w["up"] for w in f["wheels"]] for f in F])
        self.spin = np.array([np.mean([w["spin"] for w in f["wheels"]]) for f in F])
        group_of = {nz["name"]: nz["group"] for nz in m["nozzles"]}
        state, self.on = {}, {g: np.zeros(len(F)) for g in self.count}
        by_frame = {}
        for e in self.events:
            by_frame.setdefault(e["frame"], []).append(e)
        for f in range(len(F)):
            for e in by_frame.get(f, []):
                if e["type"] in ("ignite", "cutoff"):
                    state[e["nozzle"]] = e["type"] == "ignite"
            for g in self.count:
                self.on[g][f] = any(v for nz, v in state.items() if group_of[nz] == g)
        self.n = len(F)

    def clusters(self, kind, group, gap=4):
        """Ignitions or cutoffs of one group within gap frames of the first: one sound, [frame, nozzles]."""
        out = []
        for f in sorted(e["frame"] for e in self.events if e["type"] == kind and e.get("group") == group):
            if out and f - out[-1][0] <= gap:
                out[-1][1] += 1
            else:
                out.append([f, 1])
        return out

    def axles(self):
        """The touchdown: [frame, wheels meeting the floor, |vz| m/s] per frame the wheels land on."""
        td = next((e for e in self.events if e["type"] == "touchdown"), None)
        if not td:
            return []
        out = []
        for f in range(max(1, td["frame"] - 3), min(self.n, td["frame"] + 30)):
            k = int(np.sum(self.cw[f] & ~self.cw[f - 1]))
            if k:
                out.append([f, k, abs(td.get("vz", 0.5))])
        return out

    def take(self, arr, fr):
        """Values at frames fr; past the motion's end everything holds, x goes on at the last speed."""
        v = arr[np.clip(fr, 0, self.n - 1)]
        if arr is self.x:
            v = v + np.maximum(fr - (self.n - 1), 0) * (self.x[-1] - self.x[-2])
        return v


class Clip:
    """One clip's timeline: frames a..b (+ the tail), control and audio time grids."""

    def __init__(self, M, a, b, tail_s):
        self.M, self.a, self.b = M, a, b
        self.fr = np.arange(a, b + int(np.ceil(tail_s * M.fps)) + 1)  # only the clip's frames: nothing from the other
        self.tf = (self.fr - a) / M.fps
        self.N = int(round(((b - a + 1) / M.fps + tail_s) * SR))
        self.tc = np.arange(int(self.N / SR * CR) + 2) / CR
        self.ta = np.arange(self.N) / SR
        fps = M.fps
        vx = np.gradient(M.take(M.x, self.fr)) * fps
        self.speed = np.abs(vx)
        self.acc = np.gradient(uniform_filter1d(vx, 5, mode="nearest")) * fps * np.sign(vx + 1e-9)  # along the motion
        self.susp = np.abs(np.gradient(M.take(M.up, self.fr), axis=0)).mean(1) * fps  # m/s of the springs
        self.susp[self.fr < SETTLE_FRAMES] = 0

    def ctl(self, arr, step=False, own=False):
        v = arr if own else self.M.take(arr, self.fr)  # a motion array or one of the clip's own (speed, acc, susp)
        if step:
            return v[np.clip((self.tc * self.M.fps).astype(int), 0, len(v) - 1)]
        return np.interp(self.tc, self.tf, v)

    def aud(self, c):
        return np.interp(self.ta, self.tc, c)

    def t(self, frame):
        return (frame - self.a) / self.M.fps

    def has(self, frame):
        return self.a <= frame <= self.b


def quiet(d, eps=0.02):
    """No sound for a drive under eps (the numerical dust of a standing car: the stand is silent)."""
    return np.maximum(d - eps, 0) / (1 - eps)


def offscreen(xs, V):
    d = np.maximum(0, np.maximum(-xs, xs - SCREEN_W))
    return 1 / (1 + (d / V["offscreen_m"]) ** 2)


def build(V, S, M, a, b, tail_s, seed):
    """One clip of one variant -> the stereo mix (before the master gain) and every layer panned (for the numbers)."""
    C = Clip(M, a, b, tail_s)
    rng = np.random.default_rng(seed)
    noise = lambda: rng.standard_normal(C.N)  # noqa: E731
    x_c = C.ctl(M.x)
    layers = {}  # name -> (mono, source x at control rate)

    for g in ("down", "side", "back"):
        L, xs = V[g], x_c + SOURCE_X[g]
        on = C.ctl(M.on[g], step=True)
        if not on.any():
            continue
        T = np.clip(C.ctl(M.T[g]) / L["thrust_ref"], 0, 2)
        drive = on * np.maximum(L["on_floor"], T ** L["curve"])
        env = C.aud(follow(drive, L["attack_ms"], L["release_ms"]))
        bed = sum(amp(f.get("db", 0)) * loop(S.bed(f["src"], f.get("pitch", 1.0)), C.N, rng) for f in L["files"])
        bed = rms_norm(band(bed, L["highpass_hz"], L["lowpass_hz"], 4))
        dark = rms_norm(band(bed, hi=L["dark_hz"], order=4))
        bright = C.aud(np.clip(T / L["bright_at"], 0, 1) * offscreen(xs, V))
        mono = env * (bright * bed + (1 - bright) * dark)
        mono += amp(L["air_db"]) * env * rms_norm(band(noise(), 6000, 16000, 4))
        if L["rumble_db"] > -99:
            rumble = rms_norm(band(np.cumsum(noise()), 25, L["rumble_hz"], 4))
            mono += amp(L["rumble_db"]) * env ** 1.5 * rumble
        layers[g] = (0.1 * amp(L["gain_db"]) * mono, xs)

        hits = np.zeros(C.N)
        I, n_all = V["ignite"], M.count[g]
        for f, k in M.clusters("ignite", g):
            if C.has(f):
                place(hits, pop(rng, I), C.t(f), amp(I[g + "_db"]) * np.sqrt(k / n_all))
        for f, k in M.clusters("cutoff", g):
            if C.has(f):
                place(hits, chuff(rng, V["cutoff"]["ms"]), C.t(f), amp(V["cutoff"][g + "_db"]) * np.sqrt(k / n_all))
        H, mark = {"down": (V["hit_lift"], "lift"), "back": (V["hit_dash"], "launch")}.get(g, (None, None))
        first = [f for f, _ in M.clusters("ignite", g) if H and f >= M.marks[mark] - 2]
        if first and C.has(first[0]) and H["gain_db"] > -99:  # the lift-off, the dash
            for f_ in H["files"]:
                x, start = S.shot(f_["src"], H.get("lowpass_hz"))
                place(hits, x, C.t(first[0]), amp(H["gain_db"] + f_.get("db", 0)), start)
            if H["crack_db"] > -99:
                place(hits, crack(rng), C.t(first[0]), amp(H["gain_db"] + H["crack_db"]))
        if hits.any():
            layers[g + " hits"] = (0.5 * hits, xs)

    ground = C.ctl(M.contact)
    speed, acc = C.ctl(C.speed, own=True), C.ctl(C.acc, own=True)
    L = V["tyres"]
    drive = ground * np.clip(speed / L["speed_ref"], 0, L["max"]) ** L["curve"]
    am = 1 + L["rotation_am"] * np.sin(C.aud(C.ctl(M.spin)))
    tyres = rms_norm(band(noise(), L["band_hz"][0], L["band_hz"][1], 2))
    env = C.aud(follow(quiet(drive), L["attack_ms"], L["release_ms"]))
    layers["tyres"] = (0.1 * amp(L["gain_db"]) * env * am * tyres, x_c)

    L = V["brake"]
    drive = ground * np.clip(-acc / L["decel_ref"], 0, 1) * np.clip(speed / 0.3, 0, 1)
    scrub = rms_norm(band(noise(), L["band_hz"][0], L["band_hz"][1], 2))
    env = C.aud(follow(quiet(drive), L["attack_ms"], L["release_ms"]))
    layers["brake"] = (0.1 * amp(L["gain_db"]) * env * scrub, x_c)

    L = V["motor"]
    drive = ground * (L["by_speed"] * np.clip(speed / L["speed_ref"], 0, 1.5)
                      + (1 - L["by_speed"]) * np.clip(np.abs(acc) / L["accel_ref"], 0, 1.5))
    phase = np.cumsum(2 * np.pi * C.aud(L["hz"] + L["hz_per_ms"] * speed) / SR)
    whine = sum(h * np.sin((i + 1) * phase) for i, h in enumerate(L["harmonics"]))
    env = C.aud(follow(quiet(drive), L["attack_ms"], L["release_ms"]))
    layers["motor"] = (0.1 * amp(L["gain_db"]) * env * rms_norm(whine), x_c)

    L = V["touchdown"]
    td = np.zeros(C.N)
    for f, k, vz in M.axles():  # the louder the faster it lands (0.54 m/s here) and the more wheels at once
        if C.has(f):
            for f_ in L["files"]:
                x, start = S.shot(f_["src"])
                g = 0.5 * amp(L["gain_db"] + f_.get("db", 0)) * np.sqrt(k / 2) * min(vz / 0.5, 2) ** 0.7
                place(td, x, C.t(f), g, start)
    whump = rms_norm(band(noise(), 30, 160, 4))
    env = C.aud(follow(quiet(np.clip(C.ctl(C.susp, own=True) / 0.25, 0, 1.5)), 8, 90))
    td += 0.1 * amp(L["suspension_db"]) * env * whump
    layers["touchdown"] = (td, x_c)

    width = V["pan_width"]
    dry, panned = np.zeros((C.N, 2)), {}
    for name, (mono, xs) in layers.items():
        p = np.clip((xs - SCREEN_W / 2) / (SCREEN_W / 2), -1, 1) * width
        gd = offscreen(xs, V) * np.sqrt(2)
        gl, gr = C.aud(np.cos((p + 1) * np.pi / 4) * gd), C.aud(np.sin((p + 1) * np.pi / 4) * gd)
        panned[name] = np.stack([mono * gl, mono * gr], 1)
        dry += panned[name]
    R = V["room"]
    n_ir = int((R["decay_s"] * 1.2 + 0.03) * SR)
    t = np.arange(n_ir) / SR
    ir = band(rng.standard_normal((n_ir, 2)), 200, 7000, 2) * np.exp(-6.91 * t / R["decay_s"])[:, None]
    ir[:int(0.012 * SR)] = 0
    ir /= np.sqrt((ir ** 2).sum(0))
    wet = np.stack([signal.fftconvolve(dry[:, c], ir[:, c])[:C.N] for c in (0, 1)], 1)
    return dry + amp(R["wet_db"]) * wet, panned


def blocks(st, win=0.4, hop=0.1):
    """K-weighted energy of 400 ms blocks every 100 ms, both channels summed (BS.1770)."""
    y = signal.sosfilt(KW, st, axis=0)
    e = (y * y).sum(1)
    c = np.concatenate([[0], np.cumsum(e)])
    w, h = min(int(win * SR), len(e)), int(hop * SR)
    starts = np.arange(0, len(e) - w + 1, h)
    return (c[starts + w] - c[starts]) / w


def lufs(st):
    z = blocks(st)
    z = z[-0.691 + 10 * np.log10(z + 1e-20) > -70]
    if not len(z):
        return -99.0
    z = z[-0.691 + 10 * np.log10(z + 1e-20) > -0.691 + 10 * np.log10(z.mean()) - 10]
    return -0.691 + 10 * np.log10(z.mean())


def loudest(st):
    return -0.691 + 10 * np.log10(blocks(st).max() + 1e-20)


def true_peak(st):
    return dbfs(np.abs(signal.resample_poly(st, 4, 1, axis=0)).max())


def limit(st, ceiling_db, look_ms=4):
    """Brick-wall: the gain at every sample at most what keeps the peak under the ceiling, smoothed over look_ms."""
    g = np.minimum(1.0, amp(ceiling_db) / np.maximum(np.abs(st).max(1), 1e-12))
    k = int(look_ms / 1000 * SR)
    g = uniform_filter1d(minimum_filter1d(g, 2 * k + 1), k + 1)  # the average of minima never exceeds the minimum
    return st * g[:, None]


def write_wav(path, st):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s24le", str(path)], input=st.astype("<f4").tobytes(), check=True)


def video_frames(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout
    return int(out.strip())


def variant(name, V, S, M, split, video, args):
    t0 = time.time()
    c1, c2 = split["clip1"], split["clip2"]
    seed = zlib.crc32(name.encode())
    mix1, lay1 = build(V, S, M, c1["first"], c1["last"], 0.0, seed)
    mix2, lay2 = build(V, S, M, c2["first"], c2["last"], V["tail_s"], seed + 1)
    before = dbfs(np.abs(mix1[-int((GUARD_S + 0.5) * SR):]).max())  # level just before the cut, relative
    f = int(GUARD_S * SR)
    mix1[-f:] *= np.cos(np.linspace(0, np.pi / 2, f))[:, None] ** 2
    f = min(int(0.15 * SR), len(mix2) // 4)
    mix2[-f:] *= np.cos(np.linspace(0, np.pi / 2, f))[:, None] ** 2
    gain = V["loudness_lufs"] - lufs(np.concatenate([mix1, mix2]))
    ceiling = V["peak_dbfs"]
    over = max(dbfs(np.abs(mix1).max()), dbfs(np.abs(mix2).max())) + gain - ceiling  # what the limiter takes off
    for _ in range(4):  # loudness after the limiter, true peak under -1 dBTP
        o1, o2 = limit(mix1 * amp(gain), ceiling), limit(mix2 * amp(gain), ceiling)
        both = np.concatenate([o1, o2])
        err, tp = V["loudness_lufs"] - lufs(both), true_peak(both)
        if abs(err) < 0.1 and tp < -1.0:
            break
        gain += err
        ceiling -= max(0.0, tp + 1.05)
    out = SHOW / "sound" / name
    write_wav(out / "clip1.wav", o1)
    write_wav(out / "clip2.wav", o2)
    k0, k1 = (int((M.marks["stop"] + 30 - c1["first"]) / M.fps * SR), int((c1["last"] - c1["first"]) / M.fps * SR))
    print(f"{name}: {lufs(both):.1f} LUFS (target {V['loudness_lufs']}), true peak {tp:.1f} dBTP, loudest 400 ms "
          f"{loudest(both):.1f} LUFS, the limiter takes up to {max(over, 0):.1f} dB; clip 1 {len(o1) / SR:.3f} s: the "
          f"stand from frame {M.marks['stop'] + 30} peaks at {dbfs(np.abs(o1[k0:k1]).max()):.0f} dBFS, its last "
          f"{GUARD_S + 0.5:.2f} s at {before + gain:.0f} dBFS before the guard fade; clip 2 {len(o2) / SR:.3f} s")
    g = amp(gain)
    print("  layers, loudest 400 ms (LUFS): " + ", ".join(
        f"{k} {loudest(v * g):.0f}" for k, v in list(lay1.items()) + [(k + " (2)", v) for k, v in lay2.items()]
        if np.abs(v).max() > 0))
    if args.events:
        report_events(M, split, o1, o2)
    if video:
        P = video_frames(video) - (c2["last"] - c1["first"] + 1)
        if P != round(split["pause_s"] * split["fps"]):
            print(f"  note: the video holds the cut {P} frames, split.json says {split['pause_s']} s")
        start2 = int(round((split["cut"] + P - c1["first"]) / split["fps"] * SR))
        full = np.zeros((max(start2 + len(o2), len(o1)), 2))
        full[:len(o1)] += o1
        full[start2:start2 + len(o2)] += o2
        tmp = out / "show.wav"
        write_wav(tmp, full)
        dst = SHOW / "sound" / f"show-b-cloud-{name}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(tmp), "-map", "0:v:0",
                        "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart",
                        str(dst)], check=True)
        tmp.unlink()
        print(f"  -> {dst.relative_to(ROOT)} ({len(full) / SR:.2f} s of sound, the pause {P} frames)")
    print(f"  {time.time() - t0:.1f} s")


def report_events(M, split, o1, o2):
    """The level 60 ms before and 20 ms after every event (dBFS RMS over 40 ms) and the right-left balance."""
    def level(st, t):
        k = max(int(t * SR), 0)
        seg = st[k:k + int(0.04 * SR)]
        if not len(seg):
            return -99.0, 0.0
        l, r = np.sqrt(np.mean(seg[:, 0] ** 2)), np.sqrt(np.mean(seg[:, 1] ** 2))
        return dbfs(np.sqrt((l * l + r * r) / 2)), dbfs(r) - dbfs(l)
    rows = [(e["frame"], e["type"] + " " + (e.get("group") or e.get("phase") or "")) for e in M.events]
    last = split["clip2"]["last"]
    rows += [(last - 30, "(the dash)"), (last - 10, "(at the edge)"), (last, "(clip 2 ends)")]
    seen = set()
    for f, what in sorted(rows):
        if (f, what) in seen:
            continue
        seen.add((f, what))
        c, st, a = (1, o1, split["clip1"]["first"]) if f <= split["cut"] else (2, o2, split["clip2"]["first"])
        t = (f - a) / split["fps"]
        b, _ = level(st, t - 0.06)
        af, lr = level(st, t + 0.02)
        print(f"    {f:4d} clip {c} {what:16s} {b:6.1f} -> {af:6.1f} dBFS, right-left {lr:+5.1f} dB")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("variants", nargs="*", help="variant names from the .toml (default: all)")
    p.add_argument("--conf", default=str(CONF))
    p.add_argument("--motion", default=str(SHOW / "motion.json"))
    p.add_argument("--split", default=str(SHOW / "final-cloud" / "split.json"))
    p.add_argument("--video", default=str(SHOW / "show-b-cloud.mp4"))
    p.add_argument("--no-video", action="store_true")
    p.add_argument("--events", action="store_true", help="print the level around every event")
    a = p.parse_args()
    conf = tomllib.loads(pathlib.Path(a.conf).read_text())
    S = Sources(conf.pop("sources"))
    M = Motion(pathlib.Path(a.motion))
    split = json.loads(pathlib.Path(a.split).read_text())
    for name in a.variants or list(conf):
        if name not in conf:
            sys.exit(f"show_b_sound: no variant '{name}' in {a.conf}")
        variant(name, conf[name], S, M, split, None if a.no_video else pathlib.Path(a.video), a)


if __name__ == "__main__":
    main()
