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
import re
import signal
import subprocess
import sys
import tempfile

VERACRYPT = "/usr/bin/veracrypt"  # replaced by install.sh
FS_OPTIONS = "--fs-options=nosuid,nodev"
EXACT = {"--text", "--non-interactive", "--stdin", "--protect-hidden=no", "--mount", "--list", "-C",
         "--random-source=/dev/urandom", FS_OPTIONS}
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
OPERATIONS = {"--mount", "--list", "-C", "--create"}
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
        return "exactly one of --mount, --list, -C, --create is required"
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


def main(argv: list[str]) -> int:
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
