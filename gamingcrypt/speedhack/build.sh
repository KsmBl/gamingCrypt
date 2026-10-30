#!/bin/sh
# The speedhack, 64- and 32-bit (32-bit games, the Steam client): prebuilt into this folder, so
# the handheld needs no compiler. Only symbols of the oldest glibc (see speedhack.c).
set -eu
cd "$(dirname "$0")"
FLAGS="-O2 -fPIC -shared -fno-stack-protector -fvisibility=default -D_FORTIFY_SOURCE=0 -Wall -Wextra -Wl,--hash-style=both"
gcc -m64 $FLAGS -o libgamingcrypt-speed64.so speedhack.c -ldl
gcc -m32 $FLAGS -o libgamingcrypt-speed32.so speedhack.c -ldl
strip libgamingcrypt-speed64.so libgamingcrypt-speed32.so
