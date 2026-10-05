#!/usr/bin/env bash
# GamingCrypt installer - installs into your user account (~/.local).
#
#   ./install.sh               install / update
#   ./install.sh --autostart   also start GamingCrypt automatically after login
#   ./install.sh --session     also install the gaming session: boot straight into
#                              GamingCrypt on gamescope; "Desktop mode" switches to
#                              your desktop (e.g. tileWin), logging out returns
#                              (once installed, plain ./install.sh keeps it updated)
#   ./install.sh --no-sudo     skip the VeraCrypt sudo helper (you can't mount then
#                              unless VeraCrypt works without root for you)
#   ./install.sh --boot-setup  ask the boot questions again (GRUB menu, second OS)
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
VOLUME_RULE="/etc/udev/rules.d/72-gamingcrypt-volume-keys.rules"
SESSION_BIN="/usr/local/bin/gamingcrypt-session"
SESSION_FILE="/usr/share/wayland-sessions/gamingcrypt.desktop"
LIGHTDM_CONF="/etc/lightdm/lightdm.conf.d/50-gamingcrypt.conf"
GAMING_MODE_ENTRY="$DATA_HOME/applications/gamingcrypt-gaming-mode.desktop"
MODULES_CONF="/etc/modules-load.d/gamingcrypt-uinput.conf"

AUTOSTART=0
SESSION=0
WITH_SUDO=1
UNINSTALL=0
BOOT_SETUP=0
GRUB_DEFAULT_FILE="${GC_GRUB_DEFAULT:-/etc/default/grub}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        --session) SESSION=1 ;;
        --no-sudo) WITH_SUDO=0 ;;
        --uninstall) UNINSTALL=1 ;;
        --boot-setup) BOOT_SETUP=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "unknown option: $arg" ;;
    esac
done

[[ $EUID -eq 0 ]] && die "run this as your normal user, not as root (sudo is used only where needed)"

# Once the gaming session is installed, every update must update it too (session
# script, volume/Windows button access) - a plain ./install.sh must not skip it.
if [[ $UNINSTALL -eq 0 && $SESSION -eq 0 && -e $SESSION_BIN ]]; then
    SESSION=1
    info "Gaming session found - updating it as well"
fi

uninstall() {
    info "Removing GamingCrypt"
    rm -rf "$VENV"
    rmdir "$APP_DIR" 2>/dev/null || true
    rm -f "$LAUNCHER" "$DESKTOP_FILE" "$AUTOSTART_FILE" "$GAMING_MODE_ENTRY"
    if [[ -e $SESSION_BIN || -e $SESSION_FILE || -e $LIGHTDM_CONF ]]; then
        info "Removing the gaming session (needs sudo)"
        sudo rm -f "$SESSION_BIN" "$SESSION_FILE" "$LIGHTDM_CONF" "$VOLUME_RULE"
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

record_whats_new() {
    # GamingCrypt shows "What's new" once: the commit titles since the last install.
    local new old
    new="$(git -C "$SRC_DIR" rev-parse HEAD 2>/dev/null)" || return 0
    old="$(cat "$APP_DIR/installed-commit" 2>/dev/null || true)"
    if [[ -n $old && $old != "$new" ]] && git -C "$SRC_DIR" cat-file -e "$old^{commit}" 2>/dev/null; then
        git -C "$SRC_DIR" log --no-merges --format=%s "$old..$new" >> "$APP_DIR/whats-new.txt"
    fi
    echo "$new" > "$APP_DIR/installed-commit"
}

install_app() {
    info "Creating virtual environment in $VENV"
    mkdir -p "$APP_DIR"
    # System site packages: reuse a distro PySide6 if there is one (saves a big download).
    python3 -m venv --system-site-packages "$VENV"
    info "Installing GamingCrypt and its dependencies"
    "$VENV/bin/python" -m pip install --quiet --upgrade "$SRC_DIR"
    record_whats_new

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
    echo "    setting the power limit within the range the hardware reports,"
    echo "    and choosing another installed system (e.g. Windows) for the next start)"
    if [[ -d /sys/firmware/efi ]] && ! command -v efibootmgr >/dev/null && command -v pacman >/dev/null; then
        sudo pacman -S --needed --noconfirm efibootmgr || warn "efibootmgr missing - no 'Restart into Windows'"
    fi
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
install_fonts() {
    # The UI uses emoji / symbol icons (search, volume, trash, battery, ...). Without a
    # font that has them Qt draws a square with a question mark.
    command -v fc-list >/dev/null || return 0
    if [[ -n "$(fc-list ':charset=1f50b' family 2>/dev/null)" ]]; then
        return
    fi
    if command -v pacman >/dev/null; then
        info "Installing an emoji font for the icons (needs sudo)"
        sudo pacman -S --needed --noconfirm noto-fonts-emoji noto-fonts \
            || warn "could not install noto-fonts-emoji - icons show as squares until it is"
    elif command -v apt-get >/dev/null; then
        info "Installing an emoji font for the icons (needs sudo)"
        sudo apt-get install -y fonts-noto-color-emoji fonts-noto-core \
            || warn "could not install fonts-noto-color-emoji - icons show as squares until it is"
    elif command -v dnf >/dev/null; then
        info "Installing an emoji font for the icons (needs sudo)"
        sudo dnf install -y google-noto-emoji-color-fonts google-noto-sans-symbols2-fonts \
            || warn "could not install the Noto emoji font - icons show as squares until it is"
    else
        warn "no emoji font found - install Noto Color Emoji, otherwise icons show as squares"
    fi
}

# --- boot questions (only when someone answers them: a terminal) -----------------------
interactive() { [[ -t 0 || ${GC_ASSUME_TTY:-0} == 1 ]]; }

ask_yes_no() {  # ask_yes_no "question" -> 0 = yes
    local answer
    read -r -p "$1 [y/N] " answer || answer=""
    [[ $answer =~ ^[YyJj] ]]
}

grub_mkconfig() {
    local tool cfg
    tool="$(command -v grub-mkconfig || command -v grub2-mkconfig || true)"
    [[ -n $tool ]] || { warn "grub-mkconfig not found - run it yourself to apply GRUB_TIMEOUT"; return; }
    for cfg in /boot/grub/grub.cfg /boot/grub2/grub.cfg; do
        if sudo test -e "$cfg"; then
            sudo "$tool" -o "$cfg" >/dev/null 2>&1 && info "GRUB updated: Linux starts right away" \
                || warn "grub-mkconfig failed - GRUB_TIMEOUT is set but not applied yet"
            return
        fi
    done
    warn "grub.cfg not found - run grub-mkconfig yourself"
}

ask_grub_timeout() {
    # No GRUB menu wait: Linux (GamingCrypt) starts at once; the other system is reached
    # through "Restart into …" in GamingCrypt instead.
    [[ -f $GRUB_DEFAULT_FILE ]] || return 0
    local current declined="$APP_DIR/grub-timeout-declined"
    current="$(sed -n 's/^GRUB_TIMEOUT=\(.*\)/\1/p' "$GRUB_DEFAULT_FILE" | tr -d '"' | tail -1)"
    [[ $current == 0 ]] && return 0
    [[ $BOOT_SETUP -eq 0 && -e $declined ]] && return 0
    if ask_yes_no "Skip the GRUB boot menu so Linux starts right away (GRUB_TIMEOUT=${current:-?} -> 0)?"; then
        if grep -q '^GRUB_TIMEOUT=' "$GRUB_DEFAULT_FILE"; then
            sudo sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' "$GRUB_DEFAULT_FILE"
        else
            echo 'GRUB_TIMEOUT=0' | sudo tee -a "$GRUB_DEFAULT_FILE" >/dev/null
        fi
        rm -f "$declined"
        grub_mkconfig
    else
        mkdir -p "$APP_DIR" && touch "$declined"  # don't ask on every update
    fi
}

ask_other_os() {
    # Which other system "Restart into …" offers - or none (then there's no such button).
    local current entries choice i=0 nums=()
    current="$("$VENV/bin/python" -c 'from gamingcrypt.config import load_config
print(load_config().get("system", {}).get("other_os") or "")' 2>/dev/null || true)"
    [[ $BOOT_SETUP -eq 0 && -n $current ]] && return 0
    entries="$("$VENV/bin/python" -m gamingcrypt --list-boot-entries 2>/dev/null || true)"
    if [[ -z $entries ]]; then
        info "No second operating system found - no 'Restart into …' button"
        "$VENV/bin/python" -m gamingcrypt --other-os none
        return 0
    fi
    echo "Is there a second operating system to start from GamingCrypt (\"Restart into …\")?"
    echo "    0) No"
    while IFS=$'\t' read -r num name; do
        i=$((i + 1)); nums+=("$num")
        echo "    $i) $name (boot entry $num)"
    done <<< "$entries"
    read -r -p "Choose [0-$i]: " choice || choice=0
    if [[ $choice =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= i )); then
        "$VENV/bin/python" -m gamingcrypt --other-os "${nums[$((choice - 1))]}"
        info "\"Restart into …\" starts boot entry ${nums[$((choice - 1))]}"
    else
        "$VENV/bin/python" -m gamingcrypt --other-os none
        info "No second operating system - no 'Restart into …' button"
    fi
}

ask_boot_questions() {
    interactive || return 0
    ask_grub_timeout
    ask_other_os
}

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

install_volume_keys() {
    # gamescope doesn't handle the volume buttons - GamingCrypt reads them in gaming mode.
    # Give the logged-in user read access to exactly the built-in devices that have them.
    local names rules=""
    names="$("$VENV/bin/python" -m gamingcrypt --volume-key-devices 2>/dev/null)"
    if [[ -z $names ]]; then
        warn "no device with volume buttons found - they won't work in gaming mode"
        return
    fi
    while IFS= read -r name; do
        rules+="SUBSYSTEM==\"input\", KERNEL==\"event*\", ATTRS{name}==\"${name//\"/\\\"}\", TAG+=\"uaccess\""$'\n'
        echo "    volume buttons: $name"
    done <<< "$names"
    info "Allowing GamingCrypt to read the volume buttons (needs sudo)"
    printf '%s' "$rules" | sudo tee "$VOLUME_RULE" >/dev/null
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true
}

install_session() {
    command -v gamescope >/dev/null || warn "gamescope is not installed (Arch: sudo pacman -S gamescope) - the session falls back to the desktop until it is"
    # xprop: GamingCrypt tells gamescope which window belongs in front (and sees Big Picture)
    if ! command -v xprop >/dev/null; then
        if command -v pacman >/dev/null; then
            sudo pacman -S --needed --noconfirm xorg-xprop || true
        elif command -v apt-get >/dev/null; then
            sudo apt-get install -y x11-utils || true
        fi
        command -v xprop >/dev/null || warn "xprop is missing (Arch: xorg-xprop) - Steam windows may cover GamingCrypt in gaming mode"
    fi
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
    install_volume_keys
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
    install_fonts
    ask_boot_questions
    [[ $SESSION -eq 1 ]] && install_session
else
    info "Skipping the sudo helper (--no-sudo)"
    fc-list ':charset=1f50b' family 2>/dev/null | grep -q . \
        || warn "no emoji font found - install Noto Color Emoji, otherwise icons show as squares"
    [[ $SESSION -eq 1 ]] && warn "--session needs sudo - not installed"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in your PATH - start with $LAUNCHER" ;;
esac
info "Installed! Start it with: gamingcrypt   (or --windowed to try it in a window)"
info "On first start you choose your VeraCrypt volume and how to unlock it (PIN, password or pattern)."
