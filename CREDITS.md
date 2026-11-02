# Credits

Everything the show is made of, who made it and under which licence. The licence of this repository's own code and
media is in [LICENSE](LICENSE) and [LICENSE-MEDIA.md](LICENSE-MEDIA.md).

## The car

**"Tesla Roadster 2020"** by [metarex.4d](https://sketchfab.com/metarex.4d) on Sketchfab —
https://sketchfab.com/3d-models/tesla-roadster-2020-1fbf29e297bd4a17ac39a00a378441d8 — licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Changed for the show (`tools/blender/car_shot.py`): scaled to the real car's 4.2 m length and turned to drive to the
right; the wheels rigged to spin about their own centres and to ride the suspension of our physics, the brake calipers
to follow the suspension only; the materials tuned for realism: the paint's clear coat polished (the paint is the
model's own silver), the tinted glass made smooth and kept out of the key light's reflection, the indicators switched
off, the lamps' glow toned down.

The model is not in this repository: `tools/fetch_assets.sh` downloads it with your own Sketchfab account.

## The steam and the clouds

Three volume (OpenVDB) assets by **BleachedBroccoli Medvešek** on Blendkit, free, under the Blendkit Royalty Free
license: they may be used in commercial work without credit (given here anyway), but not resold or redistributed.
The show's frames are our own renders of them; the volumes themselves are neither in this repository nor in the app.
`tools/fetch_assets.sh` downloads them with your own free Blendkit account.

- **"Pipe Leak Animated"** — https://www.blendkit.com/asset-gallery-detail/4f54310c-5e38-41dd-8240-1e0a353788ad/ —
  the jets. One simulated gas leak (550 frames at 60 per second) made into a 3 m jet: three frames averaged for motion
  smear, split into a bright core and a faint bluish haze with streaks along the flow (`tools/blender/jet_probe_a2.py`),
  then put on every nozzle of the car with its own timing and strength (`tools/blender/landing_jets.py`).
- **"Chaotic Ground Smoke Looped"** — https://www.blendkit.com/asset-gallery-detail/082f8fbb-94a3-4acf-bc01-476b754582bb/ —
  the churning middle of the cloud where the jets hit the floor.
- **"Rolling Ground Smoke Looped"** — https://www.blendkit.com/asset-gallery-detail/1a80bc93-b28f-4425-8867-97d719d294e9/ —
  the outer cloud rolling along the floor away from the jets.

## The light

**"Studio Small 09"** HDRI by Sergej Majboroda, [Poly Haven](https://polyhaven.com/a/studio_small_09),
[CC0](https://creativecommons.org/publicdomain/zero/1.0/) — the studio light around the car, with one big key light of
our own. Downloaded by `tools/fetch_assets.sh`.

## The sounds

Nine recordings from [Freesound](https://freesound.org), all [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
(public domain: any use, no credit required); the licence of each was checked on its Freesound page on 2 November
2026. Copies are in `sounds/`: the MP3s are Freesound's own high-quality previews (found through
[Openverse](https://openverse.org)), the WAVs short cuts of the original recordings. `tools/show_b_sound.py` loops,
pitches, filters and layers them by the numbers in `tools/show_b_sound.toml`; the app plays variant `b` of that file.

| File | Recording | Author | In the show |
|---|---|---|---|
| `sounds/hiss_large.mp3` | [R19-17 Large Air Hiss with Whistle](https://freesound.org/people/craigsmith/sounds/479294) | craigsmith | the hiss of every jet |
| `sounds/hiss_waves.mp3` | [R18-50 Air Hisses in Waves](https://freesound.org/people/craigsmith/sounds/479293) | craigsmith | a second layer of the jets |
| `sounds/steam.mp3` | [Steam.wav](https://freesound.org/people/SukritSen/sounds/398077) | SukritSen | the side jets' pulses in the flip |
| `sounds/rocket.mp3` | [Rocket Blast](https://freesound.org/people/magnuswaker/sounds/540091) | magnuswaker | the dash |
| `sounds/vent_lift.wav` | [Sfx Whoosh Deep Vent 1 12](https://freesound.org/people/Sheyvan/sounds/569414) | Sheyvan | the lift-off |
| `sounds/vent_dash.wav` | [Sfx Whoosh Deep Vent 1 1](https://freesound.org/people/Sheyvan/sounds/569417) | Sheyvan | the dash |
| `sounds/slam.wav` | [Seismic Slam](https://freesound.org/people/magnuswaker/sounds/531862) | magnuswaker | the bass of the lift-off and the dash |
| `sounds/thump.wav` | [Thump; close.wav](https://freesound.org/people/TylerAM/sounds/389665) | TylerAM | the touchdown |
| `sounds/thud.wav` | [thud2.wav](https://freesound.org/people/Topschool/sounds/443494) | Topschool | the touchdown |

Synthesised in `tools/show_b_sound.py`: the bright air on top of the jets, the low rumble, the valves' cracks and
chuffs, the whip-like crack of the hits, the tyres and the brakes, the motor's whine, the suspension's whump and the
room.

## Code and tools

- The Mac app uses Apple's frameworks only (AppKit, SwiftUI, AVFoundation, ServiceManagement, Security). Its move to
  the Applications folder finds the original of a translocated copy with Security.framework's SecTranslocate
  functions, the way the public-domain [LetsMove](https://github.com/potionfactory/LetsMove) library does; its code is
  not used.
- The physics runs on [Rapier](https://rapier.rs) (`@dimforge/rapier3d-compat`, Apache-2.0), installed by npm.
- The show is rendered with [Blender](https://www.blender.org) 5.2 (Cycles; Eevee for the car's silhouettes) and
  assembled with Blender's own Python (OpenImageIO, OpenColorIO and its AgX view), Python with numpy, Pillow and SciPy,
  Apple's VideoToolbox for the movies and [FFmpeg](https://ffmpeg.org) for the sound files and the preview videos.
  None of them is included here.

## Not used

- Tesla's own videos of the Roadster were the reference for the scale, the jets and the clouds, studied frame by
  frame. No frame and no sound of them is in the show, the app or this repository.
- The desktop behind the preview videos is a frame of Apple's macOS Tahoe wallpaper, taken from the Mac that renders
  (`tools/fetch_assets.sh`). It is never in this repository, the release or the app.

Not affiliated with or endorsed by Tesla, Inc. Tesla and Roadster are trademarks of Tesla, Inc.
