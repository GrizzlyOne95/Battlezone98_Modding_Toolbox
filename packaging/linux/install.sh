#!/bin/sh
# Install the Battlezone Modding Toolbox from the extracted Linux release.
#
#   ./install.sh               install for this user (~/.local), no root needed
#   sudo ./install.sh          install for every user (/opt, /usr/local)
#   ./install.sh --uninstall   remove it again (settings are kept)
#   ./install.sh --purge       remove it and this user's settings, project
#                              profiles and saved Steam API key
#
# Installs the program folder, a menu entry with its icon, and the
# BZModdingToolbox / bztoolbox commands. Settings live in
# ${XDG_CONFIG_HOME:-~/.config}/BattlezoneModdingToolbox, never in the
# program folder. Re-running the script upgrades in place.
set -eu

APP=BZModdingToolbox
DESKTOP_ID=io.github.grizzlyone95.bzmoddingtoolbox

if [ "$(id -u)" = 0 ]; then
    PREFIX=/opt/$APP
    BIN=/usr/local/bin
    SHARE=/usr/local/share
else
    DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
    PREFIX=$DATA_HOME/$APP
    BIN=$HOME/.local/bin
    SHARE=$DATA_HOME
fi
DESKTOP_FILE=$SHARE/applications/$DESKTOP_ID.desktop
ICON_FILE=$SHARE/icons/hicolor/512x512/apps/$DESKTOP_ID.png

refresh_menus() {
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$SHARE/applications" || true
    # refresh an existing icon cache; never create one (it would outlive an uninstall)
    if [ -f "$SHARE/icons/hicolor/icon-theme.cache" ] && command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t "$SHARE/icons/hicolor" || true
    fi
}

uninstall() {
    if [ "${1:-}" = purge ] && [ -x "$PREFIX/bztoolbox" ]; then
        "$PREFIX/bztoolbox" clean-user-data --yes || true
    fi
    for link in "$BIN/$APP" "$BIN/bztoolbox"; do
        # only our own links, never a same-named command installed by something else
        case "$(readlink "$link" 2>/dev/null || true)" in "$PREFIX"/*) rm -f "$link" ;; esac
    done
    rm -f "$DESKTOP_FILE" "$ICON_FILE"
    [ -f "$PREFIX/$APP" ] && rm -rf "$PREFIX"
    refresh_menus
    echo "Removed the Battlezone Modding Toolbox from $PREFIX."
}

case "${1:-}" in
    --uninstall) uninstall; exit 0 ;;
    --purge) uninstall purge; exit 0 ;;
    "") ;;
    *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

SRC=$(cd "$(dirname "$0")" && pwd)
[ -x "$SRC/$APP" ] || { echo "error: run install.sh from the extracted $APP folder" >&2; exit 1; }
if [ "$SRC" = "$PREFIX" ]; then
    echo "error: this is already the installed copy; run install.sh from a newly extracted release" >&2
    exit 1
fi

rm -rf "$PREFIX.new"
mkdir -p "$(dirname "$PREFIX")"
cp -R "$SRC" "$PREFIX.new"
rm -rf "$PREFIX"
mv "$PREFIX.new" "$PREFIX"

mkdir -p "$BIN" "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON_FILE")"
ln -sf "$PREFIX/$APP" "$BIN/$APP"
ln -sf "$PREFIX/bztoolbox" "$BIN/bztoolbox"
cp "$PREFIX/$DESKTOP_ID.png" "$ICON_FILE"
sed "s|@EXEC@|$PREFIX/$APP|" "$PREFIX/$DESKTOP_ID.desktop" > "$DESKTOP_FILE"
chmod 644 "$DESKTOP_FILE" "$ICON_FILE"
refresh_menus

echo "Installed $("$PREFIX/bztoolbox" --version 2>/dev/null || echo "the Battlezone Modding Toolbox") in $PREFIX."
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Add $BIN to PATH to run BZModdingToolbox and bztoolbox from a terminal." ;;
esac
echo "Uninstall with: $PREFIX/install.sh --uninstall"
