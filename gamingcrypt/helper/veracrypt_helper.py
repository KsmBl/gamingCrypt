#!/usr/bin/python3 -I
"""Root helper for GamingCrypt (installed to /usr/local/lib/gamingcrypt/veracrypt-helper).

sudoers only allows *this* script, never ``veracrypt`` itself: an unrestricted
``veracrypt`` as root would let any user process mount a crafted volume over
e.g. /etc. This helper only forwards a fixed allow-list of arguments, forces
``nosuid,nodev`` and restricts where volumes may be mounted.

Must stay self-contained (runs as root, no imports from user-writable paths).
"""

import os
import pwd
import struct
import time
import re
import signal
import subprocess
import sys
import tempfile

VERACRYPT = "/usr/bin/veracrypt"  # replaced by install.sh
RYZENADJ = "/usr/bin/ryzenadj"
EFIBOOTMGR = ["/usr/bin/efibootmgr", "/usr/sbin/efibootmgr"]
SYS = "/sys"
MIN_POWER_W = 3
FS_OPTIONS = "--fs-options=nosuid,nodev"
EXACT = {"--text", "--non-interactive", "--stdin", "--protect-hidden=no", "--mount", "--list", "-C",
         "--random-source=/dev/urandom", FS_OPTIONS, "-d", "--force"}
PREFIXED = [
    re.compile(r"^--pim=\d{1,10}$"),
    re.compile(r"^--new-pim=\d{1,10}$"),
    re.compile(r"^--keyfiles=.*$", re.S),
    re.compile(r"^--new-keyfiles=.*$", re.S),
    re.compile(r"^--new-password=.*$", re.S),
]
# Only valid together with --create (fixed values: new ext4 file container).
CREATE_EXACT = {"--create", "--volume-type=normal", "--encryption=AES", "--hash=SHA-512",
                "--filesystem=ext4", "--quick", "--keyfiles="}
CREATE_PREFIXED = [re.compile(r"^--size=\d{1,6}[MG]$")]
OPERATIONS = {"--mount", "--list", "-C", "--create", "-d"}
MOUNT_ROOTS = ["/mnt", "/media", "/run/media"]


def allowed_mount_roots(user_home: str | None) -> list[str]:
    roots = list(MOUNT_ROOTS)
    if user_home and user_home not in ("/", ""):
        roots.append(user_home)
    return roots


def mount_point_ok(path: str, user_home: str | None) -> bool:
    real = os.path.realpath(path)
    for root in allowed_mount_roots(user_home):
        root = os.path.realpath(root)
        if real != root and real.startswith(root.rstrip("/") + "/"):
            return True
    return False


def create_target_ok(path: str, user_home: str | None, user_uid: int | None) -> str | None:
    """New containers: a not yet existing file in a directory the user owns, below the allowed roots."""
    if os.path.lexists(path):
        return "the container file already exists"
    parent = os.path.realpath(os.path.dirname(os.path.abspath(path)) or ".")
    if not os.path.isdir(parent):
        return "the target folder does not exist"
    inside = False
    for root in allowed_mount_roots(user_home):
        root = os.path.realpath(root)
        if parent == root or parent.startswith(root.rstrip("/") + "/"):
            inside = True
    if not inside:
        return "containers can only be created below " + ", ".join(MOUNT_ROOTS) + " or your home directory"
    if user_uid is None or os.stat(parent).st_uid != user_uid:
        return "the target folder must belong to you"
    return None


def validate(argv: list[str], user_home: str | None, user_uid: int | None = None) -> str | None:
    """Return an error message, or None when the arguments are acceptable."""
    positionals = []
    creating = "--create" in argv
    for arg in argv:
        if arg.startswith("-"):
            if arg in EXACT or any(p.match(arg) for p in PREFIXED):
                continue
            if creating and (arg in CREATE_EXACT or any(p.match(arg) for p in CREATE_PREFIXED)):
                continue
            return f"argument not allowed: {arg.split('=')[0]}"
        else:
            positionals.append(arg)
    operations = [a for a in argv if a in OPERATIONS]
    if len(operations) != 1:
        return "exactly one of --mount, --list, -C, --create, -d is required"
    if len(positionals) < 1 or len(positionals) > 2:
        return "expected a volume and an optional mount point"
    op = operations[0]
    if op == "--mount":
        if FS_OPTIONS not in argv:
            return "mounting requires " + FS_OPTIONS
        if len(positionals) == 2 and not mount_point_ok(positionals[1], user_home):
            return "mount point must be below " + ", ".join(MOUNT_ROOTS) + " or your home directory"
    elif len(positionals) != 1:
        return "this operation takes only the volume"
    elif op == "--create":
        if "--filesystem=ext4" not in argv or not any(a.startswith("--size=") for a in argv):
            return "creating requires --size and --filesystem=ext4"
        error = create_target_ok(positionals[0], user_home, user_uid)
        if error:
            return error
    if "--force" in argv and op != "-d":
        return "--force only allowed with -d (dismount)"
    if any(a.startswith(("--new-password=", "--new-pim=", "--new-keyfiles=")) for a in argv) and op != "-C":
        return "--new-password only allowed with -C"
    return None


def invoking_user() -> tuple[int | None, int | None, str | None]:
    """uid, gid and home of the user who ran sudo."""
    try:
        uid = int(os.environ["SUDO_UID"])
        gid = int(os.environ.get("SUDO_GID", uid))
        return uid, gid, pwd.getpwuid(uid).pw_dir
    except (KeyError, ValueError):
        return None, None, None


STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def create_volume(argv, uid, gid, password, run=subprocess.run, popen=subprocess.Popen, chown=os.chown,
                  mkdtemp=tempfile.mkdtemp, rmdir=os.rmdir, remove=os.remove) -> int:
    """Create the container, then hand the file *and* its fresh ext4 root to the user.

    Without the second step the new filesystem would be owned by root and Steam
    couldn't install anything into it. A SIGTERM (the user pressed Cancel)
    during creation stops VeraCrypt and deletes the half-written file.
    """
    path = [a for a in argv if not a.startswith("-")][0]
    proc = popen([VERACRYPT, *argv], stdin=subprocess.PIPE, text=True)
    stopped = []

    def stop(signum, _frame):
        stopped.append(signum)
        proc.terminate()

    previous = {sig: signal.signal(sig, stop) for sig in STOP_SIGNALS}
    try:
        proc.communicate(password)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if stopped:
        try:
            remove(path)
        except OSError:
            pass
        return 128 + stopped[0]
    if proc.returncode != 0:
        return proc.returncode
    # Preparing the filesystem takes a moment; don't leave it half done.
    previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in STOP_SIGNALS}
    try:
        return _prepare_filesystem(path, uid, gid, password, run, chown, mkdtemp, rmdir)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _prepare_filesystem(path, uid, gid, password, run, chown, mkdtemp, rmdir) -> int:
    chown(path, uid, gid)
    mount_dir = mkdtemp(prefix="gamingcrypt-", dir="/run")
    try:
        mounted = run([VERACRYPT, "--text", "--non-interactive", "--stdin", "--pim=0", "--keyfiles=",
                       "--protect-hidden=no", FS_OPTIONS, "--mount", path, mount_dir],
                      input=password, text=True, capture_output=True)
        if mounted.returncode != 0:
            print("Error: created, but could not prepare the filesystem: " + (mounted.stderr or "").strip(),
                  file=sys.stderr)
            return mounted.returncode
        try:
            chown(mount_dir, uid, gid)
        finally:
            run([VERACRYPT, "--text", "--non-interactive", "-d", path], text=True, capture_output=True)
    finally:
        try:
            rmdir(mount_dir)
        except OSError:
            pass
    return 0


def _read_int(path: str) -> int | None:
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def power_targets(sys_root: str = SYS) -> list[tuple[str, int, int]]:
    """(file, min_uw, max_uw) for every power limit we may write."""
    import glob

    targets = []
    for cap in sorted(glob.glob(os.path.join(sys_root, "class/drm/card*/device/hwmon/hwmon*/power1_cap"))):
        current = _read_int(cap)
        if current is None:
            continue
        low = _read_int(cap + "_min") or 0
        high = _read_int(cap + "_max") or current
        targets.append((cap, max(low, MIN_POWER_W * 1_000_000), high))
    rapl = os.path.join(sys_root, "class/powercap/intel-rapl:0/constraint_0_power_limit_uw")
    current = _read_int(rapl)
    if current is not None:
        rated = _read_int(rapl.replace("power_limit_uw", "max_power_uw")) or 0
        targets.append((rapl, MIN_POWER_W * 1_000_000, max(rated, current)))
    return targets


# --- AMD APUs without a power1_cap file (e.g. Ryzen 4800U): the SMU mailbox, like
# RyzenAdj does it (github.com/FlyGoat/RyzenAdj, lib/nb_smu_ops.c + api.c). SMN
# registers are reached through the root complex's PCI config space (0xB8 index,
# 0xBC data). Keep this table in sync with gamingcrypt/system/power.py.
PCI_ROOT = "bus/pci/devices/0000:00:00.0/config"
SMN_INDEX, SMN_DATA = 0xB8, 0xBC
MAILBOXES = {1: (0x3B10528, 0x3B10564, 0x3B10998), 2: (0x3B10528, 0x3B10578, 0x3B10998)}
LIMIT_MSGS = {"raven": (0x1A, 0x1B, 0x1C), "renoir": (0x14, 0x15, 0x16)}
SMU_FAMILIES = {  # (cpu family, model) -> (name, mailbox, messages)
    (0x17, 17): ("Raven", 1, "raven"), (0x17, 24): ("Picasso", 1, "raven"), (0x17, 32): ("Dali", 1, "raven"),
    (0x17, 96): ("Renoir", 1, "renoir"), (0x17, 104): ("Lucienne", 1, "renoir"),
    (0x17, 144): ("Van Gogh", 2, "renoir"), (0x17, 145): ("Van Gogh", 2, "renoir"),
    (0x17, 160): ("Mendocino", 2, "renoir"), (0x19, 80): ("Cezanne", 1, "renoir"),
    (0x19, 64): ("Rembrandt", 2, "renoir"), (0x19, 68): ("Rembrandt", 2, "renoir"),
    (0x19, 116): ("Phoenix", 2, "renoir"), (0x19, 120): ("Phoenix", 2, "renoir"),
    (0x19, 117): ("Hawk Point", 2, "renoir"),
}
SMU_MIN_W = 5
SMU_TEST_MSG, SMU_OK = 0x1, 0x1
STATE_FILE = "/run/gamingcrypt-power-limit"


def cpu_info(text: str) -> tuple[int, int, str] | None:
    """(family, model, model name) of an AMD CPU from /proc/cpuinfo."""
    fields = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = (part.strip() for part in line.split(":", 1))
            fields.setdefault(key, value)
        elif fields:
            break  # first CPU is enough
    if fields.get("vendor_id") != "AuthenticAMD":
        return None
    try:
        return int(fields["cpu family"]), int(fields["model"]), fields.get("model name", "")
    except (KeyError, ValueError):
        return None


def smu_range(family: int, model: int, name: str) -> tuple[int, int] | None:
    """Allowed watts: U chips (handhelds, thin laptops) up to 28 W, Steam Deck-class 20 W, others 45 W."""
    if (family, model) not in SMU_FAMILIES:
        return None
    word = name.split(" with ")[0].split()[-1] if name else ""
    if SMU_FAMILIES[(family, model)][0] == "Van Gogh":
        return SMU_MIN_W, 20
    if word.upper().endswith("U"):
        return SMU_MIN_W, 28
    return SMU_MIN_W, 45


class Smu:
    def __init__(self, family: int, model: int, sys_root: str = SYS, timeout: float = 1.0):
        _name, box, msgs = SMU_FAMILIES[(family, model)]
        self.msg_addr, self.rep_addr, self.arg_addr = MAILBOXES[box]
        self.limit_msgs = LIMIT_MSGS[msgs]
        self.timeout = timeout
        self.fd = os.open(os.path.join(sys_root, PCI_ROOT), os.O_RDWR)

    def close(self) -> None:
        os.close(self.fd)

    def write(self, addr: int, value: int) -> None:
        os.pwrite(self.fd, struct.pack("<I", addr), SMN_INDEX)
        os.pwrite(self.fd, struct.pack("<I", value & 0xFFFFFFFF), SMN_DATA)

    def read(self, addr: int) -> int:
        os.pwrite(self.fd, struct.pack("<I", addr & ~0x3), SMN_INDEX)
        return struct.unpack("<I", os.pread(self.fd, 4, SMN_DATA))[0]

    def send(self, msg: int, arg: int = 0) -> int:
        self.write(self.rep_addr, 0)
        for i in range(6):
            self.write(self.arg_addr + 4 * i, arg if i == 0 else 0)
        self.write(self.msg_addr, msg)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:  # RyzenAdj waits forever - we don't
            response = self.read(self.rep_addr)
            if response:
                return response
            time.sleep(0.001)
        return 0

    def check(self) -> str | None:
        self.write(self.rep_addr, 0)
        self.write(self.arg_addr, 0x47)
        if self.read(self.arg_addr) != 0x47:
            return "the CPU's power controller isn't writable (Secure Boot lockdown?)"
        if self.send(SMU_TEST_MSG) != SMU_OK:
            return "the CPU's power controller didn't answer"
        return None

    def set_limit(self, watts: int) -> str | None:
        error = self.check()
        if error:
            return error
        for msg in self.limit_msgs:  # sustained (STAPM), fast, slow - in mW
            response = self.send(msg, watts * 1000)
            if response != SMU_OK:
                return f"the CPU's power controller refused the limit (0x{response:x})"
        return None


def set_smu_power_limit(watts: int, sys_root: str = SYS, cpuinfo: str | None = None,
                        smu_factory=Smu, state_file: str | None = STATE_FILE) -> int:
    if cpuinfo is None:
        with open("/proc/cpuinfo") as fh:
            cpuinfo = fh.read()
    cpu = cpu_info(cpuinfo)
    limits = smu_range(*cpu) if cpu else None
    if limits is None:
        print("Error: gamingcrypt helper: no adjustable power limit found", file=sys.stderr)
        return 2
    if not limits[0] <= watts <= limits[1]:
        print(f"Error: gamingcrypt helper: {watts} W is outside {limits[0]}-{limits[1]} W", file=sys.stderr)
        return 2
    import fcntl

    with open(state_file + ".lock" if state_file else os.devnull, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one mailbox conversation at a time
        try:
            smu = smu_factory(cpu[0], cpu[1], sys_root)
        except OSError as exc:
            print(f"Error: gamingcrypt helper: can't reach the CPU's power controller: {exc}", file=sys.stderr)
            return 2
        try:
            error = smu.set_limit(watts)
        finally:
            smu.close()
    if error:
        print(f"Error: gamingcrypt helper: {error}", file=sys.stderr)
        return 2
    if state_file:
        with open(state_file, "w") as fh:  # readable: the UI shows the current value
            fh.write(f"{watts}\n")
    return 0


def set_power_limit(args: list[str], sys_root: str = SYS, run=subprocess.run,
                    ryzenadj: str | None = None, smu=set_smu_power_limit) -> int:
    if len(args) != 1 or not args[0].isdigit():
        print("Error: gamingcrypt helper: usage: power-limit <watts>", file=sys.stderr)
        return 2
    watts = int(args[0])
    targets = power_targets(sys_root)
    if not targets:
        return smu(watts, sys_root)
    uw = watts * 1_000_000
    for path, low, high in targets:
        if not low <= uw <= high:
            print(f"Error: gamingcrypt helper: {watts} W is outside {low // 10**6}-{high // 10**6} W", file=sys.stderr)
            return 2
    for path, _low, _high in targets:
        with open(path, "w") as fh:
            fh.write(str(uw))
    ryzenadj = RYZENADJ if ryzenadj is None else ryzenadj
    if ryzenadj and os.path.exists(ryzenadj) and any("power1_cap" in t[0] for t in targets):
        mw = str(watts * 1000)
        run([ryzenadj, f"--stapm-limit={mw}", f"--fast-limit={mw}", f"--slow-limit={mw}"],
            capture_output=True, text=True)
    return 0


def _efibootmgr() -> str | None:
    return next((p for p in EFIBOOTMGR if os.path.exists(p)), None)


def boot_entry_ok(listing: str, num: str) -> bool:
    """Only an existing, active entry that starts a boot loader from a disk - never USB,
    network or other firmware entries."""
    for line in listing.splitlines():
        match = re.match(r"^Boot([0-9A-Fa-f]{4})(\*?)\s+.*?\t(.*)$", line)
        if match and match.group(1).upper() == num:
            path = match.group(3)
            return bool(match.group(2)) and "HD(" in path and "\\efi\\" in path.lower()
    return False


def set_boot_next(args: list[str], run=subprocess.run, efibootmgr: str | None = None) -> int:
    """Start that system once on the next boot (UEFI BootNext)."""
    if len(args) != 1 or not re.fullmatch(r"[0-9A-Fa-f]{4}", args[0]):
        print("Error: gamingcrypt helper: usage: boot-next <4 hex digits>", file=sys.stderr)
        return 2
    num = args[0].upper()
    tool = efibootmgr or _efibootmgr()
    if tool is None:
        print("Error: gamingcrypt helper: efibootmgr is not installed", file=sys.stderr)
        return 2
    listing = run([tool], capture_output=True, text=True)
    if listing.returncode != 0 or not boot_entry_ok(listing.stdout, num):
        print(f"Error: gamingcrypt helper: Boot{num} is not a system on a disk", file=sys.stderr)
        return 2
    result = run([tool, "--bootnext", num], capture_output=True, text=True)
    if result.returncode != 0:
        print("Error: gamingcrypt helper: " + (result.stderr or "efibootmgr failed").strip(), file=sys.stderr)
    return result.returncode


# --- SMB share of the Emulation folder, only while the upload page is open ---------------
SMB_RUN = "/run/gamingcrypt-smb"
SMB_SHARE = "GamingCrypt"
SMB_TOOLS = {"smbd": ["/usr/bin/smbd", "/usr/sbin/smbd"], "smbpasswd": ["/usr/bin/smbpasswd", "/usr/sbin/smbpasswd"]}


def _tool(name: str) -> str | None:
    return next((p for p in SMB_TOOLS[name] if os.path.exists(p)), None)


def smb_config(path: str, user: str, run_dir: str = SMB_RUN) -> str:
    return f"""[global]
server string = GamingCrypt
workgroup = WORKGROUP
security = user
map to guest = never
passdb backend = tdbsam:{run_dir}/passdb.tdb
private dir = {run_dir}/private
lock directory = {run_dir}/lock
state directory = {run_dir}/state
cache directory = {run_dir}/cache
pid directory = {run_dir}
ncalrpc dir = {run_dir}/ncalrpc
log file = {run_dir}/log
disable netbios = yes
load printers = no
printing = bsd
printcap name = /dev/null
[{SMB_SHARE}]
path = {path}
valid users = {user}
force user = {user}
read only = no
create mask = 0644
directory mask = 0755
"""


def smb_stop(run_dir: str = SMB_RUN, kill=os.kill) -> int:
    try:
        with open(os.path.join(run_dir, "smbd.pid")) as fh:
            kill(int(fh.read().strip()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    import shutil

    shutil.rmtree(run_dir, ignore_errors=True)
    return 0


def smb_start(args: list[str], password: str, user_home: str | None, user_name: str | None,
              run=subprocess.run, run_dir: str = SMB_RUN) -> int:
    if len(args) != 1 or not user_home or not user_name:
        print("Error: gamingcrypt helper: usage: smb-start <folder in your home>", file=sys.stderr)
        return 2
    folder = os.path.realpath(args[0])
    home = os.path.realpath(user_home)
    if not folder.startswith(home.rstrip("/") + "/") or not os.path.isdir(folder):
        print("Error: gamingcrypt helper: only a folder inside your home can be shared", file=sys.stderr)
        return 2
    if not 8 <= len(password) <= 64 or "\n" in password:
        print("Error: gamingcrypt helper: bad password", file=sys.stderr)
        return 2
    smbd, smbpasswd = _tool("smbd"), _tool("smbpasswd")
    if smbd is None or smbpasswd is None:
        print("Error: gamingcrypt helper: Samba is not installed (run ./install.sh)", file=sys.stderr)
        return 2
    smb_stop(run_dir)
    for sub in ("private", "lock", "state", "cache", "ncalrpc"):
        os.makedirs(os.path.join(run_dir, sub), mode=0o700, exist_ok=True)
    conf = os.path.join(run_dir, "smb.conf")
    with open(conf, "w") as fh:
        fh.write(smb_config(folder, user_name, run_dir))
    added = run([smbpasswd, "-c", conf, "-s", "-a", user_name], input=f"{password}\n{password}\n",
                capture_output=True, text=True)
    if added.returncode != 0:
        print("Error: gamingcrypt helper: could not set the share password", file=sys.stderr)
        smb_stop(run_dir)
        return 2
    started = run([smbd, "-s", conf, "-D"], capture_output=True, text=True)
    if started.returncode != 0:
        print("Error: gamingcrypt helper: Samba didn't start (is another Samba running?)", file=sys.stderr)
        smb_stop(run_dir)
        return 2
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["power-limit"]:
        return set_power_limit(argv[1:])
    if argv[:1] == ["boot-next"]:
        return set_boot_next(argv[1:])
    if argv[:1] == ["smb-stop"]:
        return smb_stop()
    if argv[:1] == ["smb-start"]:
        uid, _gid, home = invoking_user()
        name = pwd.getpwuid(uid).pw_name if uid is not None else None
        return smb_start(argv[1:], sys.stdin.readline().rstrip("\n"), home, name)
    uid, gid, home = invoking_user()
    error = validate(argv, home, uid)
    if error:
        print(f"Error: gamingcrypt helper: {error}", file=sys.stderr)
        return 2
    if "--create" in argv:
        password = sys.stdin.readline()
        return create_volume(argv, uid, gid, password)
    os.execv(VERACRYPT, [VERACRYPT, *argv])
    return 1  # not reached


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
