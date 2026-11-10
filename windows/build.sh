#!/bin/sh
# Roadster for Windows, cross-built on a Mac: Tauri 2 + cargo-xwin (Tauri's "Windows installer from Linux and macOS"),
# the NSIS installer -> windows/dist/Roadster-Setup.exe. Needs rustup (+ target x86_64-pc-windows-msvc), cargo-xwin,
# brew llvm and nsis. The first build downloads the MSVC CRT + Windows SDK (xwin cache, outside git).
#   windows/build.sh          the normal build
#   windows/build.sh --test   a test build: Self-test, Mode check and the tray icon's variants in the tray menu (the build
#                             for Valentin's checks)
# First the schedule's checks (windows/schedule: the Mac's mac/Tests/ScheduleTests.swift case for case) run on this Mac,
# as tools/build_mac_app.sh runs the Mac's: a failing check stops the build.
set -eu
cd "$(dirname "$0")"
unset ROADSTER_SELFTEST
if [ "${1:-}" = "--test" ]; then
  export ROADSTER_SELFTEST=1
  shift
fi
export PATH="/opt/homebrew/opt/llvm/bin:$HOME/.cargo/bin:$PATH"
# heavy downloads and build files outside git: ../work/ (in the lab a link to its work folder; in a clone a plain folder)
mkdir -p ../work/windows
export XWIN_CACHE_DIR="${XWIN_CACHE_DIR:-$(cd ../work/windows && pwd)/xwin-cache}"
cargo test --quiet --manifest-path schedule/Cargo.toml --target-dir ../work/windows/schedule-target
export ROADSTER_BUILD_TIME="$(date -u '+%Y-%m-%d %H:%M UTC')"
ROADSTER_GIT="git $(git rev-parse --short HEAD 2>/dev/null || echo none)"
[ -z "$(git status --porcelain -- . 2>/dev/null)" ] || ROADSTER_GIT="$ROADSTER_GIT+changes"
export ROADSTER_GIT
# the show: the landing's file as is (VP9 with alpha + Opus; not in git, as the other movies): downloaded once from the
# landing, checked by its SHA-256
VIDEO=ui/show/fly-2016.webm
if [ ! -f $VIDEO ]; then
  mkdir -p ui/show
  curl -fsSL -o $VIDEO https://flying-roadster-app.pages.dev/show/fly-2016.webm
fi
echo "890aecfe055c19907ddb53a40dd5aa005d327fe8e2892f9d9e13029874bddc63  $VIDEO" | shasum -a 256 -c -
# the panel's look is the design's: design/roadster.css and the app icon as they are (outside git here, as the video)
cp ../design/roadster.css ui/roadster.css
cp ../design/icon/app-icon-placeholder.svg ui/app-icon.svg
[ -d node_modules ] || npm ci   # the lock as committed
npx tauri build --runner cargo-xwin --target x86_64-pc-windows-msvc "$@"
mkdir -p dist
V=$(sed -n 's/^  "version": "\(.*\)",$/\1/p' src-tauri/tauri.conf.json)   # older versions' installers stay in the bundle folder
cp "src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/Roadster_${V}_x64-setup.exe" dist/Roadster-Setup.exe
echo "version $V"
if [ -n "${ROADSTER_SELFTEST:-}" ]; then echo "test build: Self-test, Mode check, Icon variant in the tray menu"; else echo "normal build"; fi
ls -l dist/Roadster-Setup.exe
shasum -a 256 dist/Roadster-Setup.exe
