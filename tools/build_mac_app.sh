#!/bin/sh
# Builds the Mac app: dist/Roadster.app (universal: Apple Silicon + Intel, macOS 13+, signed ad hoc - there is no
# Apple developer account) and dist/Roadster.zip (ditto, the way Finder zips) for the site.
#   tools/build_mac_app.sh           # the show movies are packed once, then reused from out/show-b/app/
#   tools/build_mac_app.sh --video   # pack the movies again (after a new render or a new sound)
# The movies: tools/mac/show_video.swift, from out/show-b/final-cloud (frames rgba-shadow, split.json) and
# out/show-b/sound/b (clip1.wav, clip2.wav); it prints how close the movies are to the frames.
# Without the rendered frames (a fresh clone) the movies come from the release instead: roadster-clips.zip (clip1.mov,
# clip2.mov, split.json) from CLIPS_URL, checked against CLIPS_SHA256, unpacked into out/show-b/app/ once.
# ROADSTER_CLIPS_URL and ROADSTER_CLIPS_SHA256 override them (a check against a local server, a new release).
set -e
cd "$(dirname "$0")/.."
CLIPS_URL=${ROADSTER_CLIPS_URL:-https://github.com/valentin-ste/flying-roadster/releases/download/v1.0/roadster-clips.zip}
CLIPS_SHA256=${ROADSTER_CLIPS_SHA256:-f494f877ac125fb192389ccfcaa253056df81b4f0807a29f64fce4b4bf57dded}
SHOW=out/show-b/app
FRAMES=out/show-b/final-cloud
B=out/mac-build
mkdir -p "$B" dist
SDK=$(xcrun --show-sdk-path)
have_movies() { [ -f "$SHOW/clip1.mov" ] && [ -f "$SHOW/clip2.mov" ] && [ -f "$SHOW/split.json" ]; }

if [ "$1" = "--video" ] || { ! have_movies && [ -f "$FRAMES/split.json" ]; }; then
  xcrun swiftc -O -swift-version 5 tools/mac/show_video.swift -o "$B/show_video"
  "$B/show_video" encode --show "$FRAMES" --sound out/show-b/sound/b --out "$SHOW"
  "$B/show_video" check --show "$FRAMES" --out "$SHOW" --step 10
elif ! have_movies; then
  echo "build_mac_app: no rendered show here, the movies from the release: $CLIPS_URL"
  curl -fL --retry 3 --progress-bar -o "$B/roadster-clips.zip" "$CLIPS_URL"
  GOT=$(shasum -a 256 "$B/roadster-clips.zip" | cut -d" " -f1)
  [ "$GOT" = "$CLIPS_SHA256" ] || { echo "build_mac_app: roadster-clips.zip is not the expected file (SHA-256 $GOT)"; exit 1; }
  mkdir -p "$SHOW"
  unzip -o -q "$B/roadster-clips.zip" clip1.mov clip2.mov split.json -d "$SHOW"
fi

# the schedule's tests first (mac/Tests: the three modes on a clock of their own, ~1 s): a failure stops the build
xcrun swiftc -O -parse-as-library -swift-version 5 mac/Sources/Schedule.swift mac/Tests/ScheduleTests.swift -o "$B/schedule_tests"
"$B/schedule_tests" > "$B/schedule_tests.log" || { cat "$B/schedule_tests.log"; exit 1; }
tail -1 "$B/schedule_tests.log"

APP=dist/Roadster.app
rm -rf "$APP" dist/Roadster.zip "$B/AppIcon.iconset"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/show"
cp mac/Info.plist "$APP/Contents/Info.plist"
cp "$SHOW/clip1.mov" "$SHOW/clip2.mov" "$SHOW/split.json" "$APP/Contents/Resources/show/"
cp design/icon/png/roadster-solid.png "$APP/Contents/Resources/MenuBarIcon.png"
cp design/icon/png/roadster-solid@2x.png "$APP/Contents/Resources/MenuBarIcon@2x.png"
cp CREDITS.md "$APP/Contents/Resources/"

xcrun swiftc -O tools/mac/render_icon.swift -o "$B/render_icon"
"$B/render_icon" design/icon/app-icon-placeholder.svg "$B/AppIcon.iconset"
iconutil -c icns "$B/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"

for arch in arm64 x86_64; do
  xcrun swiftc -O -swift-version 5 -target "$arch-apple-macos13.0" -sdk "$SDK" mac/Sources/*.swift -o "$B/Roadster-$arch"
done
lipo -create "$B/Roadster-arm64" "$B/Roadster-x86_64" -output "$APP/Contents/MacOS/Roadster"

codesign --force --sign - "$APP"
codesign --verify --strict "$APP"
ditto -c -k --sequesterRsrc --keepParent "$APP" dist/Roadster.zip
lipo -archs "$APP/Contents/MacOS/Roadster"
du -sh "$APP" dist/Roadster.zip
