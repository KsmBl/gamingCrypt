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
import sys

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
OPERATIONS = {"--mount", "--list", "-C"}
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


def validate(argv: list[str], user_home: str | None) -> str | None:
    """Return an error message, or None when the arguments are acceptable."""
    positionals = []
    for arg in argv:
        if arg.startswith("-"):
            if arg not in EXACT and not any(p.match(arg) for p in PREFIXED):
                return f"argument not allowed: {arg.split('=')[0]}"
        else:
            positionals.append(arg)
    operations = [a for a in argv if a in OPERATIONS]
    if len(operations) != 1:
        return "exactly one of --mount, --list, -C is required"
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
    if any(a.startswith(("--new-password=", "--new-pim=", "--new-keyfiles=")) for a in argv) and op != "-C":
        return "--new-password only allowed with -C"
    return None


def invoking_home() -> str | None:
    uid = os.environ.get("SUDO_UID")
    if not uid:
        return None
    try:
        return pwd.getpwuid(int(uid)).pw_dir
    except (KeyError, ValueError):
        return None


def main(argv: list[str]) -> int:
    error = validate(argv, invoking_home())
    if error:
        print(f"Error: gamingcrypt helper: {error}", file=sys.stderr)
        return 2
    os.execv(VERACRYPT, [VERACRYPT, *argv])
    return 1  # not reached


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
