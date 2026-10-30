/* GamingCrypt's speedhack: a game's clock runs faster or slower - as Cheat Engine's does on
 * Windows. Preloaded into the game (LD_PRELOAD); Wine / Proton read their time the same way, so
 * Windows games follow too.
 *
 * Only the clocks games time their frames with are changed (CLOCK_MONOTONIC and its kin) - not
 * the time of day: network, saves and certificates keep the real one. The speed is read from a
 * small file GamingCrypt writes (/dev/shm/gamingcrypt-speed-<uid>: the speed and the game's app
 * id as text, e.g. "2.5 620"), whenever it changes, while the game runs: the game's clock goes on
 * from where it was at the new speed - it never jumps or runs backwards.
 *
 * Which game a process belongs to: GAMINGCRYPT_SPEED_APPID (games GamingCrypt starts), else
 * SteamAppId / SteamGameId (Steam's games - Steam itself is started with this preloaded too).
 * A process without one (the Steam client, its browser) is never touched; nor is a game the
 * file doesn't name, or with no file / "1": the real clocks, unchanged.
 *
 * Built without anything newer than the oldest glibc (see build.sh), so one file runs on every
 * distribution: dlsym of glibc 2.0 / 2.2.5, no stack protector.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#if defined(__x86_64__)
__asm__(".symver dlsym,dlsym@GLIBC_2.2.5");
#elif defined(__i386__)
__asm__(".symver dlsym,dlsym@GLIBC_2.0");
#endif

#define MIN_SPEED 0.05
#define MAX_SPEED 20.0
#define CHECK_NS 100000000LL /* the speed file looked at again at most every 0.1 s */
#define CLOCKS 8

typedef int (*gettime_fn)(clockid_t, struct timespec *);
typedef int (*sleep_fn)(clockid_t, int, const struct timespec *, struct timespec *);

static gettime_fn real_gettime;
static sleep_fn real_sleep;
static volatile int lock;
static double speed = 1.0;
static long long checked_at = -CHECK_NS * 2;
static char path[64];
static const char *own_appid; /* NULL: not a game - nothing changes */

__attribute__((constructor)) static void find_game(void)
{
    static const char *names[] = {"GAMINGCRYPT_SPEED_APPID", "SteamAppId", "SteamGameId"};
    unsigned i;
    for (i = 0; i < sizeof names / sizeof *names; i++) {
        const char *value = getenv(names[i]);
        if (value && value[0] && !(value[0] == '0' && !value[1])) { own_appid = value; return; }
    }
}

struct base {
    int set;
    double speed;
    long long real, fake; /* at the last change of speed */
};
static struct base bases[CLOCKS];

static int scaled(clockid_t clock)
{
    return clock == CLOCK_MONOTONIC || clock == CLOCK_MONOTONIC_RAW || clock == CLOCK_MONOTONIC_COARSE ||
           clock == CLOCK_BOOTTIME;
}

static long long ns(const struct timespec *t) { return (long long)t->tv_sec * 1000000000LL + t->tv_nsec; }

static void to_timespec(long long value, struct timespec *t)
{
    t->tv_sec = (time_t)(value / 1000000000LL);
    t->tv_nsec = (long)(value % 1000000000LL);
}

static void take(void) { while (__atomic_test_and_set(&lock, __ATOMIC_ACQUIRE)) {} }
static void give(void) { __atomic_clear(&lock, __ATOMIC_RELEASE); }

static void find_real(void)
{
    if (!real_gettime)
        real_gettime = (gettime_fn)dlsym(RTLD_NEXT, "clock_gettime");
    if (!real_sleep)
        real_sleep = (sleep_fn)dlsym(RTLD_NEXT, "clock_nanosleep");
}

static void make_path(void)
{
    static const char prefix[] = "/dev/shm/gamingcrypt-speed-";
    char digits[16];
    unsigned uid = (unsigned)getuid();
    int n = 0, i = 0;
    do { digits[n++] = (char)('0' + uid % 10); uid /= 10; } while (uid && n < 15);
    for (; prefix[i]; i++) path[i] = prefix[i];
    while (n) path[i++] = digits[--n];
    path[i] = 0;
}

/* "2.5 620": 2.5 when 620 is this game, else 1 */
static double parse(const char *text, int length)
{
    double value = 0, scale = 0;
    int i = 0, any = 0, j;
    for (; i < length; i++) {
        char c = text[i];
        if (c >= '0' && c <= '9') {
            any = 1;
            if (scale) { value += (c - '0') * scale; scale /= 10; }
            else value = value * 10 + (c - '0');
        } else if (c == '.' && !scale) {
            scale = 0.1;
        } else {
            break;
        }
    }
    if (!any) return 1.0;
    while (i < length && text[i] == ' ') i++;
    for (j = 0; own_appid[j]; j++, i++)
        if (i >= length || text[i] != own_appid[j]) return 1.0; /* another game's */
    if (i < length && text[i] >= '0' && text[i] <= '9') return 1.0;
    return value < MIN_SPEED ? MIN_SPEED : value > MAX_SPEED ? MAX_SPEED : value;
}

/* (called with the lock held) */
static void read_speed(long long now)
{
    char text[32];
    int fd, length;
    if (now - checked_at < CHECK_NS) return;
    checked_at = now;
    if (!path[0]) make_path();
    fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) { speed = 1.0; return; }
    length = (int)read(fd, text, sizeof text);
    close(fd);
    speed = length > 0 ? parse(text, length) : 1.0;
}

/* the game's time on this clock for the real one (lock held) */
static long long fake_time(clockid_t clock, long long real)
{
    struct base *b = &bases[clock];
    if (!b->set) {
        b->set = 1;
        b->speed = speed;
        b->real = b->fake = real;
    } else if (b->speed != speed) {
        b->fake += (long long)((real - b->real) * b->speed);
        b->real = real;
        b->speed = speed;
    }
    return b->fake + (long long)((real - b->real) * b->speed);
}

int clock_gettime(clockid_t clock, struct timespec *t)
{
    struct timespec mono;
    int result;
    find_real();
    result = real_gettime(clock, t);
    if (result != 0 || !own_appid || clock < 0 || clock >= CLOCKS || !scaled(clock)) return result;
    take();
    if (clock == CLOCK_MONOTONIC) read_speed(ns(t));
    else if (real_gettime(CLOCK_MONOTONIC, &mono) == 0) read_speed(ns(&mono));
    to_timespec(fake_time(clock, ns(t)), t);
    give();
    return 0;
}

#if defined(__i386__)
/* glibc's 64-bit time on 32-bit systems (games built for after 2038): its own layout */
struct timespec64 { long long tv_sec; long tv_nsec; long pad; };
typedef int (*gettime64_fn)(clockid_t, struct timespec64 *);

int __clock_gettime64(clockid_t clock, struct timespec64 *t)
{
    static gettime64_fn real64;
    struct timespec mono;
    long long value;
    int result;
    if (!real64) real64 = (gettime64_fn)dlsym(RTLD_NEXT, "__clock_gettime64");
    if (!real64) return -1;
    result = real64(clock, t);
    if (result != 0 || !own_appid || clock < 0 || clock >= CLOCKS || !scaled(clock)) return result;
    find_real();
    take();
    if (real_gettime(CLOCK_MONOTONIC, &mono) == 0) read_speed(ns(&mono));
    value = fake_time(clock, t->tv_sec * 1000000000LL + t->tv_nsec);
    t->tv_sec = value / 1000000000LL;
    t->tv_nsec = (long)(value % 1000000000LL);
    give();
    return 0;
}
#endif

/* A sleep until a time on a changed clock: until the real time that is then. */
int clock_nanosleep(clockid_t clock, int flags, const struct timespec *until, struct timespec *left)
{
    find_real();
    if ((flags & TIMER_ABSTIME) && own_appid && clock >= 0 && clock < CLOCKS && scaled(clock)) {
        struct timespec real;
        struct base *b = &bases[clock];
        take();
        if (b->set && b->speed > 0) {
            to_timespec(b->real + (long long)((ns(until) - b->fake) / b->speed), &real);
            give();
            return real_sleep(clock, flags, &real, left);
        }
        give();
    }
    return real_sleep(clock, flags, until, left);
}
