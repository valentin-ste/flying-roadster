#!/bin/sh
# Downloads what a re-render of the show needs and the repository does not keep (README "Re-render the show"):
#
#   assets/models/roadster/tesla-roadster-2020.glb   the car: "Tesla Roadster 2020" by metarex.4d, Sketchfab, CC BY 4.0
#   assets/hdri/studio_small_09_1k.hdr               the light: Poly Haven, CC0
#   work/blendkit/<asset>/extracted/caches/...       the jets and the clouds: three Blendkit volume assets by
#                                                    BleachedBroccoli Medvešek (Royalty Free license); 3.1 GB to
#                                                    download, 6.4 GB unpacked (the zips are kept next to them)
#   assets/bg/tahoe-day.jpg                          optional, the desktop behind the preview videos: a frame of
#                                                    macOS Tahoe's own "Tahoe Day" wallpaper, if this Mac has it
#
# The model and the Blendkit assets are free but need your own accounts. Their keys are read from the environment or
# from the macOS Keychain, and are never printed or written anywhere:
#   SKETCHFAB_API_TOKEN   Sketchfab: Settings -> Password & API -> API token   (or Keychain item sketchfab-api-token)
#   BLENDKIT_API_KEY      Blendkit: your profile -> API key                    (or Keychain item blendkit-api-key)
# e.g. security add-generic-password -a "$USER" -s sketchfab-api-token -w   (asks for the token)
# Without a key the script says what to download by hand and where to put it. A file already there is kept.
# ROADSTER_WORK: where the volumes go instead of work/ (they are big; the scripts read the same variable).
set -e
cd "$(dirname "$0")/.."
WORK=${ROADSTER_WORK:-work}
MISSING=0
need() { echo "fetch_assets: missing: $*" >&2; MISSING=1; }
json() { python3 -c "import json, sys; d = json.load(sys.stdin); print($1)"; }
auth() { printf 'header = "Authorization: %s"\n' "$1"; }  # for curl -K -: the key stays out of the process list

# the light (no account)
mkdir -p assets/hdri
[ -s assets/hdri/studio_small_09_1k.hdr ] || curl -fsSL -o assets/hdri/studio_small_09_1k.hdr \
  https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/studio_small_09_1k.hdr

# the desktop behind the preview videos (optional: plain grey without it)
WALL="/System/Library/Desktop Pictures/.wallpapers/Tahoe Day/Tahoe Day.mov"
if [ ! -s assets/bg/tahoe-day.jpg ] && [ -f "$WALL" ] && command -v ffmpeg >/dev/null; then
  mkdir -p assets/bg && ffmpeg -v error -ss 3 -i "$WALL" -frames:v 1 -vf scale=3024:-2 -q:v 2 assets/bg/tahoe-day.jpg
fi

# the car, through the Sketchfab API
GLB=assets/models/roadster/tesla-roadster-2020.glb
if [ ! -s "$GLB" ]; then
  TOKEN=${SKETCHFAB_API_TOKEN:-$(security find-generic-password -a "$USER" -s sketchfab-api-token -w 2>/dev/null || true)}
  if [ -n "$TOKEN" ]; then
    mkdir -p "$(dirname "$GLB")"
    URL=$(auth "Token $TOKEN" | curl -fsS -K - \
      https://api.sketchfab.com/v3/models/1fbf29e297bd4a17ac39a00a378441d8/download | json "d['glb']['url']")
    curl -fL --progress-bar -o "$GLB" "$URL"
  else
    need "$GLB: download the glTF binary (.glb) of https://sketchfab.com/3d-models/tesla-roadster-2020-1fbf29e297bd4a17ac39a00a378441d8"
  fi
  unset TOKEN URL
fi

# the jets and the clouds, through the Blendkit API: the asset -> its zip's download link -> a signed file link
blendkit() {  # blendkit NAME ASSET_BASE_ID CACHE_FOLDER
  DIR="$WORK/blendkit/$1"
  if ls "$DIR/extracted/caches/$3/" 2>/dev/null | grep -q '\.vdb$'; then return; fi
  if [ -z "$KEY" ]; then
    need "$DIR/extracted/caches/$3/: download https://www.blendkit.com/asset-gallery-detail/$2/ (free account) and unzip it into $DIR/extracted"
    return
  fi
  mkdir -p "$DIR"
  if [ ! -s "$DIR/$1.zip" ]; then
    DL=$(curl -fsS "https://www.blendkit.com/api/v1/search/?query=asset_base_id:$2" \
      | json "[f['downloadUrl'] for f in d['results'][0]['files'] if f['fileType'] == 'zip_file'][0]")
    FILE=$(auth "Bearer $KEY" | curl -fsS -K - "$DL?scene_uuid=$(uuidgen | tr 'A-Z' 'a-z')" | json "d['filePath']")
    echo "fetch_assets: $1 (Blendkit)"
    curl -fL --progress-bar -o "$DIR/$1.zip.part" "$FILE" && mv "$DIR/$1.zip.part" "$DIR/$1.zip"
  fi
  unzip -q -o "$DIR/$1.zip" -d "$DIR/extracted"
}
KEY=${BLENDKIT_API_KEY:-$(security find-generic-password -a "$USER" -s blendkit-api-key -w 2>/dev/null || true)}
blendkit pipe-leak 4f54310c-5e38-41dd-8240-1e0a353788ad "(A) Pipe Leak"
blendkit rolling-ground-smoke 1a80bc93-b28f-4425-8867-97d719d294e9 "(L) Rolling Ground Smoke"
blendkit chaotic-ground-smoke 082f8fbb-94a3-4acf-bc01-476b754582bb "(L) Ground Smoke"
unset KEY DL FILE

[ "$MISSING" = 0 ] && echo "fetch_assets: everything is in place"
exit "$MISSING"
