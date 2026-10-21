#ifndef OSLAB_COMMON_H
#define OSLAB_COMMON_H
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#endif
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static inline double seconds(clockid_t clock_id) {
    struct timespec t;
    if (clock_gettime(clock_id, &t)) { perror("clock_gettime"); exit(2); }
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static inline void pause_until(double deadline) {
    double remaining = deadline - seconds(CLOCK_MONOTONIC);
    if (remaining <= 0) return;
    struct timespec t = {(time_t)remaining, (long)((remaining - (time_t)remaining)*1e9)};
    while (nanosleep(&t, &t) && errno == EINTR) {}
}
static inline uint64_t number(const char *s) {
    char *end; errno = 0;
    if (!*s || *s == '-') { fprintf(stderr, "invalid unsigned integer\n"); exit(2); }
    uint64_t n = strtoull(s, &end, 10);
    if (errno || *end) { fprintf(stderr, "invalid unsigned integer: %s\n", s); exit(2); }
    return n;
}
static inline double real_number(const char *s) {
    char *end; errno = 0; double n = strtod(s, &end);
    if (errno || !*s || *end || !(n >= 0 && n < 1e8)) {
        fprintf(stderr, "invalid duration: %s\n", s); exit(2);
    }
    return n;
}
static inline uint64_t mix64(uint64_t x) {
    x += UINT64_C(0x9e3779b97f4a7c15);
    x = (x ^ (x >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)) * UINT64_C(0x94d049bb133111eb);
    return x ^ (x >> 31);
}
static inline const char *argument(int argc, char **argv, const char *key, const char *fallback) {
    for (int i=1; i<argc; ++i) if (!strcmp(argv[i], key)) {
        if (i+1 == argc) { fprintf(stderr, "missing value for %s\n", key); exit(2); }
        return argv[i+1];
    }
    return fallback;
}
static inline int flag(int argc, char **argv, const char *key) {
    for (int i=1; i<argc; ++i) if (!strcmp(argv[i], key)) return 1;
    return 0;
}
#endif
