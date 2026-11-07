#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLENDER_EXT_DIR="$HOME/.config/blender/5.0/extensions/user_default"
USER_PRESETS="$HOME/.config/blender/5.0/config/auxlink/presets.yaml"

echo "[Auxlink] 1. Syncing user presets to default_presets.yaml..."
if [ -f "$USER_PRESETS" ]; then
    cp "$USER_PRESETS" "$REPO_DIR/default_presets.yaml"
    echo "  -> Presets synced from $USER_PRESETS"
fi

echo "[Auxlink] 2. Ensuring symlink into Blender 5.0 extensions..."
mkdir -p "$BLENDER_EXT_DIR"
ln -sfn "$REPO_DIR" "$BLENDER_EXT_DIR/auxlink"
echo "  -> Linked: $BLENDER_EXT_DIR/auxlink -> $REPO_DIR"

echo "[Auxlink] 3. Building release zips..."
cd "$REPO_DIR"
rm -f auxlink*.zip
blender --command extension build --output-filepath auxlink.zip
cp auxlink.zip auxlink-1.2.6.zip
echo "  -> Built auxlink.zip and auxlink-1.2.6.zip"

echo "[Auxlink] Done! Blender is ready."
