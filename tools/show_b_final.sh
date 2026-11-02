#!/bin/zsh
# Show B, the final two clips rendered in layers as the landing (tools/landing_final.sh, README "landing in layers"):
# the whole 3024x1964 screen at 216 px/m (14 x 9.09 m, the floor at the bottom edge, its middle x = 7 m), the jets of
# all ten nozzles (down, side, back). Two finals, each in its own folder and video, neither touches the other:
#   tools/show_b_final.sh            no clouds (the fallback, git tag show-b-no-cloud): out/show-b/final, show-b.mp4
#   tools/show_b_final.sh --cloud    the take-off and landing clouds: out/show-b/final-cloud, show-b-cloud.mp4
#
#   tools/show_b_final.sh [--cloud] [--out DIR] [--range A:B[:STEP]] [--gas rigid|straight] [--car car-lit|car]
#                         [--smoke-samples N] [--smoke-step R (3; the cloud final 01.11: 8)] [--car-samples N] [--pause S] [--draft]
#
# Passes (each keeps the frames it has: run it again after a stop and it goes on; every Cycles frame waits while the
# Mac is on battery):
#   0. DIR/timeline.json  the cut, off the screen, the checks (landing_jets.py --list)
#   1. DIR/clip-mask/     the car's silhouette (Eevee)                                   -> the desktop shadow
#   2. DIR/car-lit/       the car at full size lit by the gas (--car car: the car alone)
#   3. DIR/smoke/         the jets (and the cloud) at half size, 108 px/m, the car a holdout
#   4. DIR/rgba/          smoke x2 over the car in linear light, AgX (tools/landing_merge.py)
#   5. DIR/shadow/, DIR/rgba-shadow/, DIR/wall/   tools/desktop.py layers; then the frames of DIR/rgba
#      unlike both their quiet neighbours are listed (tools/frame_blinks.py: look at them, nothing is re-rendered)
#   6. DIR/split.json, DIR/clip1/{rgba,shadow}/, DIR/clip2/{rgba,shadow}/ and out/show-b/show-b.mp4 (--cloud:
#      show-b-cloud.mp4; over the wallpaper, the cut held --pause s)                       tools/show_b.py
# --draft: 2 / 4 samples (a check that the chain runs end to end, not a look); a --range short of 0:<exit> stops
# after pass 5.
set -e
setopt pipefail
cd "${0:A:h}/.."
OUT="" RANGE="" GAS=rigid CAR=car-lit SMOKE_S=8 CAR_S=16 CAR_STEP=16 SMOKE_STEP=3 CLOUD=0 PAUSE=1 DRAFT=0
while (( $# )); do
  case $1 in
    --out) OUT=$2; shift 2 ;;
    --range) RANGE=$2; shift 2 ;;
    --gas) GAS=$2; shift 2 ;;
    --car) CAR=$2; shift 2 ;;
    --smoke-samples) SMOKE_S=$2; shift 2 ;;
    --smoke-step) SMOKE_STEP=$2; shift 2 ;;
    --car-samples) CAR_S=$2; shift 2 ;;
    --cloud) CLOUD=1; shift ;;
    --pause) PAUSE=$2; shift 2 ;;
    --draft) DRAFT=1; shift ;;
    *) echo "show_b_final: unknown option $1"; exit 2 ;;
  esac
done
[[ $CAR == car || $CAR == car-lit ]] || { echo "show_b_final: --car car-lit or car"; exit 2 }
if (( DRAFT )); then SMOKE_S=2 CAR_S=4; fi
if (( CLOUD )); then CLOUDARG=() NAME=show-b-cloud DEFOUT=out/show-b/final-cloud
else CLOUDARG=(--no-cloud) NAME=show-b DEFOUT=out/show-b/final; fi
[[ -n $OUT ]] || OUT=$DEFOUT
B=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
LJ=tools/blender/landing_jets.py
PY=${BLENDER_PYTHON:-${B:h:h}/Resources/5.2/python/bin/python3.13}   # Blender's Python: OpenImageIO + OpenColorIO
VPY=${PYTHON:-.venv/bin/python3}                                       # numpy, Pillow, scipy (README)
SHOW=(--motion out/show-b/motion.json --groups down,side,back --gas $GAS --ppm 216 --px 3024 --py 1964 --cx 7 $CLOUDARG)
mkdir -p $OUT
LOG=$OUT/render.log
step() { echo "show_b_final: $(date '+%H:%M:%S') $*" | tee -a $LOG; }
# twice each: Blender once died at start without a trace; the second pass renders only what the first did not
blender() { for k in 1 2; do $B -b --factory-startup --python-exit-code 1 -P $LJ -- $OUT --clip --range $RANGE $SHOW "$@" 2>&1 \
  | grep --line-buffered "landing_jets: frame\|landing_jets: clip\|on battery\|Error\|Traceback" | tee -a $LOG || step "a pass failed"; done }

step "0/6 timeline -> $OUT/timeline.json"
$B -b --factory-startup --python-exit-code 1 -P $LJ -- $OUT $SHOW --list 2>&1 | grep "^  " | tee -a $LOG
EXIT=$($VPY -c "import json,sys; print(json.load(open(sys.argv[1]))['exit'])" $OUT/timeline.json)
[[ -n $RANGE ]] || RANGE=0:$EXIT
step "1/6 silhouettes -> $OUT/clip-mask (frames $RANGE)"
blender --mask
step "2/6 car layer ($CAR, $CAR_S samples) -> $OUT/$CAR"
if [[ $CAR == car-lit ]]; then
  blender --layer car-lit --exr --samples $CAR_S --step-rate $CAR_STEP --bounces 8 --wait-ac
else
  blender --layer car --exr --samples 48 --wait-ac
fi
step "3/6 smoke layer ($SMOKE_S samples, half size, step rate $SMOKE_STEP, 8 bounces) -> $OUT/smoke"
blender --layer smoke --scale 50 --exr --samples $SMOKE_S --step-rate $SMOKE_STEP --bounces 8 --wait-ac
step "4/6 merge -> $OUT/rgba"
$PY tools/landing_merge.py --dir $OUT --car $CAR | tee -a $LOG
step "5/6 shadow, frames with the shadow -> $OUT/shadow, $OUT/rgba-shadow, $OUT/wall"
$VPY tools/desktop.py layers $OUT | tee -a $LOG
step "blink check: frames unlike both quiet neighbours (only a list to look at; nothing is changed)"
$VPY tools/frame_blinks.py $OUT/rgba | tee -a $LOG
if [[ $RANGE != 0:$EXIT ]]; then step "6/6 skipped: the two clips need all frames 0:$EXIT (rendered $RANGE)"; step "done"; exit 0; fi
step "6/6 the two clips, the pause, the video -> $OUT/split.json, $OUT/clip1, $OUT/clip2, out/show-b/$NAME.mp4"
$VPY tools/show_b.py split $OUT --frames rgba,shadow --pause $PAUSE | tee -a $LOG
$VPY tools/show_b.py video $OUT --frames rgba --ppm 216 --pause $PAUSE --name $NAME | tee -a $LOG
step "done"
