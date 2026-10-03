#!/usr/bin/env bash
# GamingCrypt installer - installs into your user account (~/.local).
#
#   ./install.sh               install / update
#   ./install.sh --autostart   also start GamingCrypt automatically after login
#   ./install.sh --no-sudo     skip the VeraCrypt sudo helper (you can't mount then
#                              unless VeraCrypt works without root for you)
#   ./install.sh --uninstall   remove everything except your config and cache
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_DIR="$DATA_HOME/gamingcrypt"
VENV="$APP_DIR/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/gamingcrypt"
DESKTOP_FILE="$DATA_HOME/applications/gamingcrypt.desktop"
AUTOSTART_FILE="$CONFIG_HOME/autostart/gamingcrypt.desktop"
HELPER="/usr/local/lib/gamingcrypt/veracrypt-helper"
SUDOERS="/etc/sudoers.d/gamingcrypt"

AUTOSTART=0
WITH_SUDO=1
UNINSTALL=0

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        --no-sudo) WITH_SUDO=0 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "unknown option: $arg" ;;
    esac
done

[[ $EUID -eq 0 ]] && die "run this as your normal user, not as root (sudo is used only where needed)"

uninstall() {
    info "Removing GamingCrypt"
    rm -rf "$VENV"
    rmdir "$APP_DIR" 2>/dev/null || true
    rm -f "$LAUNCHER" "$DESKTOP_FILE" "$AUTOSTART_FILE"
    if [[ -e $HELPER || -e $SUDOERS ]]; then
        info "Removing the VeraCrypt sudo helper (needs sudo)"
        sudo rm -f "$SUDOERS" "$HELPER"
        sudo rmdir "$(dirname "$HELPER")" 2>/dev/null || true
    fi
    info "Done. Your config (~/.config/gamingcrypt) and cache (~/.cache/gamingcrypt) were kept."
}

check_python() {
    command -v python3 >/dev/null || die "python3 is required"
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10 or newer is required"
    python3 -c 'import venv, ensurepip' 2>/dev/null \
        || die "the Python venv module is missing (Debian/Ubuntu: sudo apt install python3-venv)"
}

check_tools() {
    command -v veracrypt >/dev/null || warn "veracrypt not found - install it (https://veracrypt.fr) to unlock your volume"
    command -v steam >/dev/null || command -v flatpak >/dev/null \
        || warn "Steam not found - install it to play, download and uninstall games"
}

install_app() {
    info "Creating virtual environment in $VENV"
    mkdir -p "$APP_DIR"
    # System site packages: reuse a distro PySide6 if there is one (saves a big download).
    python3 -m venv --system-site-packages "$VENV"
    info "Installing GamingCrypt and its dependencies"
    "$VENV/bin/python" -m pip install --quiet --upgrade "$SRC_DIR"

    info "Creating launcher $LAUNCHER"
    mkdir -p "$BIN_DIR"
    cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
exec "$VENV/bin/python" -m gamingcrypt "\$@"
LAUNCH
    chmod 755 "$LAUNCHER"

    mkdir -p "$(dirname "$DESKTOP_FILE")"
    cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=GamingCrypt
Comment=Encrypted touch game launcher
Exec=$LAUNCHER
Icon=applications-games
Terminal=false
Categories=Game;
DESKTOP

    if [[ $AUTOSTART -eq 1 ]]; then
        info "Enabling autostart"
        mkdir -p "$(dirname "$AUTOSTART_FILE")"
        cp "$DESKTOP_FILE" "$AUTOSTART_FILE"
    fi
}

install_helper() {
    local veracrypt python tmp_helper tmp_sudoers
    veracrypt="$(command -v veracrypt || true)"
    if [[ -z $veracrypt ]]; then
        warn "skipping the sudo helper because veracrypt is not installed - re-run install.sh afterwards"
        return
    fi
    veracrypt="$(readlink -f "$veracrypt")"
    python="$(command -v python3)"
    [[ $python == /usr/bin/* || $python == /bin/* ]] || python=/usr/bin/python3
    [[ -x $python ]] || die "$python not found (needed for the root helper)"

    info "Installing the restricted VeraCrypt helper (needs sudo)"
    echo "    Allows: sudo -n $HELPER  (mount / list / change password of a volume,"
    echo "    always nosuid,nodev, mount points only below /mnt, /media, /run/media or your home)"
    tmp_helper="$(mktemp)"
    tmp_sudoers="$(mktemp)"
    trap 'rm -f "$tmp_helper" "$tmp_sudoers"' RETURN
    sed -e "1s|.*|#!$python -I|" \
        -e "s|^VERACRYPT = .*|VERACRYPT = \"$veracrypt\"|" \
        "$SRC_DIR/gamingcrypt/helper/veracrypt_helper.py" > "$tmp_helper"
    printf '%s ALL=(root) NOPASSWD: %s\n' "$USER" "$HELPER" > "$tmp_sudoers"
    local visudo
    visudo="$(command -v visudo || echo /usr/sbin/visudo)"
    if [[ -x $visudo ]]; then
        "$visudo" -cf "$tmp_sudoers" >/dev/null || die "generated sudoers rule is invalid"
    else
        warn "visudo not found, cannot validate the sudoers rule"
    fi
    sudo install -d -o root -g root -m 0755 "$(dirname "$HELPER")"
    sudo install -o root -g root -m 0755 "$tmp_helper" "$HELPER"
    sudo install -o root -g root -m 0440 "$tmp_sudoers" "$SUDOERS"
}

if [[ $UNINSTALL -eq 1 ]]; then
    uninstall
    exit 0
fi

check_python
check_tools
install_app
if [[ $WITH_SUDO -eq 1 ]]; then
    install_helper
else
    info "Skipping the sudo helper (--no-sudo)"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in your PATH - start with $LAUNCHER" ;;
esac
info "Installed! Start it with: gamingcrypt   (or --windowed to try it in a window)"
info "On first start you choose your VeraCrypt volume and how to unlock it (PIN, password or pattern)."
