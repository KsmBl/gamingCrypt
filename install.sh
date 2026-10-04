#!/usr/bin/env bash
# GamingCrypt installer - installs into your user account (~/.local).
#
#   ./install.sh               install / update
#   ./install.sh --autostart   also start GamingCrypt automatically after login
#   ./install.sh --session     also install the gaming session: boot straight into
#                              GamingCrypt on gamescope; "Desktop mode" switches to
#                              your desktop (e.g. tileWin), logging out returns
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
UDEV_RULE="/etc/udev/rules.d/71-gamingcrypt-uinput.rules"
SESSION_BIN="/usr/local/bin/gamingcrypt-session"
SESSION_FILE="/usr/share/wayland-sessions/gamingcrypt.desktop"
LIGHTDM_CONF="/etc/lightdm/lightdm.conf.d/50-gamingcrypt.conf"
GAMING_MODE_ENTRY="$DATA_HOME/applications/gamingcrypt-gaming-mode.desktop"
MODULES_CONF="/etc/modules-load.d/gamingcrypt-uinput.conf"

AUTOSTART=0
SESSION=0
WITH_SUDO=1
UNINSTALL=0

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        --session) SESSION=1 ;;
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
    rm -f "$LAUNCHER" "$DESKTOP_FILE" "$AUTOSTART_FILE" "$GAMING_MODE_ENTRY"
    if [[ -e $SESSION_BIN || -e $SESSION_FILE || -e $LIGHTDM_CONF ]]; then
        info "Removing the gaming session (needs sudo)"
        sudo rm -f "$SESSION_BIN" "$SESSION_FILE" "$LIGHTDM_CONF"
    fi
    if [[ -e $HELPER || -e $SUDOERS || -e $UDEV_RULE ]]; then
        info "Removing the sudo helper and controller rules (needs sudo)"
        sudo rm -f "$SUDOERS" "$HELPER" "$UDEV_RULE" "$MODULES_CONF"
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
    echo "    Allows: sudo -n $HELPER  (mount / list / create / change password of a volume,"
    echo "    always nosuid,nodev, only below /mnt, /media, /run/media or your home;"
    echo "    and setting the power limit within the range the hardware reports)"
    tmp_helper="$(mktemp)"
    tmp_sudoers="$(mktemp)"
    trap 'rm -f "$tmp_helper" "$tmp_sudoers"' RETURN
    local ryzenadj
    ryzenadj="$(command -v ryzenadj || echo /usr/bin/ryzenadj)"
    sed -e "1s|.*|#!$python -I|" \
        -e "s|^VERACRYPT = .*|VERACRYPT = \"$veracrypt\"|" \
        -e "s|^RYZENADJ = .*|RYZENADJ = \"$ryzenadj\"|" \
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
install_input_rules() {
    # The virtual controller (calibration + button mapping) is created through /dev/uinput.
    if [[ -w /dev/uinput && -e $UDEV_RULE ]]; then
        return
    fi
    info "Allowing the virtual controller (/dev/uinput for the logged-in user, needs sudo)"
    printf '%s\n' 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' \
        | sudo tee "$UDEV_RULE" >/dev/null
    echo uinput | sudo tee "$MODULES_CONF" >/dev/null
    sudo modprobe uinput 2>/dev/null || true
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger --name-match=uinput 2>/dev/null || true
}

desktop_session_exec() {
    # the desktop to switch to: tileWin if installed, otherwise the first other session
    local file
    for file in /usr/share/wayland-sessions/tilewin.desktop /usr/share/wayland-sessions/*.desktop \
                /usr/share/xsessions/*.desktop; do
        [[ -f $file && $file != "$SESSION_FILE" ]] || continue
        sed -n 's/^Exec=//p' "$file" | head -1
        return
    done
}

install_session() {
    command -v gamescope >/dev/null || warn "gamescope is not installed (Arch: sudo pacman -S gamescope) - the session falls back to the desktop until it is"
    # Inside gamescope Qt runs on X11 (xcb): ask its plugin what's missing
    local plugin missing
    plugin="$("$VENV/bin/python" -c 'import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), "Qt/plugins/platforms/libqxcb.so"))' 2>/dev/null)"
    if [[ -f $plugin ]]; then
        missing="$(ldd "$plugin" 2>/dev/null | awk '/not found/ {print $1}' | sort -u | tr '\n' ' ')"
        [[ -z $missing ]] || warn "Qt can't run inside gamescope, missing: $missing(Arch: sudo pacman -S xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm)"
    fi
    local desktop tmp
    desktop="$(desktop_session_exec)"
    [[ -n $desktop ]] || die "no desktop session found in /usr/share/wayland-sessions for Desktop mode"
    info "Installing the gaming session (needs sudo) - Desktop mode runs: $desktop"
    tmp="$(mktemp)"
    sed -e "s|@LAUNCHER@|$LAUNCHER|" -e "s|@DESKTOP_EXEC@|$desktop|" \
        "$SRC_DIR/gamingcrypt/session/gamingcrypt-session" > "$tmp"
    sudo install -o root -g root -m 0755 "$tmp" "$SESSION_BIN"
    sudo install -o root -g root -m 0644 "$SRC_DIR/gamingcrypt/session/gamingcrypt.desktop" "$SESSION_FILE"
    rm -f "$tmp"
    if [[ -d /etc/lightdm ]]; then
        info "LightDM: log in automatically into the gaming session"
        getent group autologin >/dev/null || sudo groupadd -r autologin
        id -nG "$USER" | grep -qw autologin || sudo gpasswd -a "$USER" autologin >/dev/null
        sudo install -d -m 0755 "$(dirname "$LIGHTDM_CONF")"
        printf '[Seat:*]\nautologin-user=%s\nautologin-session=gamingcrypt\n' "$USER" \
            | sudo tee "$LIGHTDM_CONF" >/dev/null
    else
        warn "LightDM not found - choose the \"GamingCrypt\" session at your login screen"
    fi
    mkdir -p "$(dirname "$GAMING_MODE_ENTRY")"
    cat > "$GAMING_MODE_ENTRY" <<ENTRY
[Desktop Entry]
Type=Application
Name=Gaming Mode
Comment=Back to GamingCrypt
Exec=$LAUNCHER --gaming-mode
Icon=applications-games
Categories=Game;
ENTRY
}

if [[ $WITH_SUDO -eq 1 ]]; then
    install_helper
    install_input_rules
    [[ $SESSION -eq 1 ]] && install_session
else
    info "Skipping the sudo helper (--no-sudo)"
    [[ $SESSION -eq 1 ]] && warn "--session needs sudo - not installed"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in your PATH - start with $LAUNCHER" ;;
esac
info "Installed! Start it with: gamingcrypt   (or --windowed to try it in a window)"
info "On first start you choose your VeraCrypt volume and how to unlock it (PIN, password or pattern)."
