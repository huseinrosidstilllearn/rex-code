#!/bin/sh
# ============================================================
# Rex Code — Linux desktop integration
#
# Run from inside the extracted RexCode bundle:
#     cd RexCode
#     sh assets/linux/setup.sh              # install / update
#     sh assets/linux/setup.sh --uninstall  # remove app (keeps user data)
# ============================================================
set -e

BUNDLE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OPT_DIR="$HOME/.local/opt/rexcode"
BIN_LINK="$HOME/.local/bin/rex"
DESKTOP_SRC="$(dirname "$0")/../rexcode.desktop"
DESKTOP_DST="$HOME/.local/share/applications/rexcode.desktop"
DATA_DIR="$HOME/.local/share/RexCode"

die() { echo "setup.sh: $*" >&2; exit 1; }
log()  { echo "  $*"; }

[ -x "$BUNDLE_DIR/rex" ] || die "rex binary not found at $BUNDLE_DIR (run this script inside the extracted RexCode folder)"

# --- uninstall (user data is never touched) -------------------------------
if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$OPT_DIR"
    rm -f "$BIN_LINK" "$DESKTOP_DST"
    for f in "$HOME"/.local/share/icons/hicolor/*/apps/rexcode*.png; do
        if [ -e "$f" ]; then rm -f "$f"; fi
    done
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" || true
    command -v gtk-update-icon-cache  >/dev/null 2>&1 && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" || true
    echo "Rex Code removed. User data (config/sessions) kept at $DATA_DIR"
    exit 0
fi

# --- install --------------------------------------------------------------
VERSION="$("$BUNDLE_DIR/rex" --version 2>/dev/null || echo 'Rex Code')"
log "Installing $VERSION"

# 1) Copy the bundle to ~/.local/opt/rexcode (swapped atomically)
rm -rf "$OPT_DIR.tmp"
cp -a "$BUNDLE_DIR" "$OPT_DIR.tmp"
rm -rf "$OPT_DIR"
mv "$OPT_DIR.tmp" "$OPT_DIR"

# 2) 'rex' command in ~/.local/bin
mkdir -p "$HOME/.local/bin"
ln -sf "$OPT_DIR/rex" "$BIN_LINK"

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        echo "NOTE: ~/.local/bin is not on your PATH. To call 'rex' from any terminal, add:"
        echo "      export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

# 3) hicolor icons (the app menu shows the Rex Code mark at every size)
for f in "$BUNDLE_DIR"/assets/linux/icons/rexcode-*.png; do
    [ -e "$f" ] || continue
    size="${f##*-}"
    size="${size%.png}"
    dir="$HOME/.local/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$dir"
    cp -f "$f" "$dir/rexcode.png"
done

# 4) app-menu entry (concrete path — GUI sessions do not always see ~/.local/bin)
if [ -f "$DESKTOP_SRC" ]; then
    mkdir -p "$(dirname "$DESKTOP_DST")"
    sed "s|__REX_BIN__|\"$OPT_DIR/rex\"|" "$DESKTOP_SRC" > "$DESKTOP_DST"
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" || true
command -v gtk-update-icon-cache  >/dev/null 2>&1 && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" || true

echo
echo "Done. Launch Rex Code from your application menu, or type 'rex' in a terminal."
echo "First run: put GEMINI_API_KEY=... in $DATA_DIR/.env (Rex prints the exact path)."
