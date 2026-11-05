/* Fast C port of sim.py (the Laser Puzzle beam rules) plus a brute-force solver.
 * sim.py is the reference; `fastsim.py --selftest` checks that the two agree.
 *
 * Input on stdin, one item per line:
 *   fixed TYPE X Y DIR COLOR          fixed piece
 *   place TYPE X Y DIR COLOR          movable piece already on the board (check mode)
 *   kind TYPE COLOR COUNT             toolbox pieces (solve mode)
 *   check                             -> "won W" and "field <hex of inc for all cells>"
 *   solve SECONDS MAX_SOLUTIONS       -> "sol N: TYPE X Y DIR COLOR; ..." lines, then
 *                                        "done solutions=N complete=0|1 evals=E"
 * See solve.py for what the search does and does not guarantee.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define N 15
#define CELLS (N * N)
#define QUEUE_MAX 32
#define GENERATIONS 0x400

static const int DX[8] = {0, 1, 1, 1, 0, -1, -1, -1};
static const int DY[8] = {-1, -1, 0, 1, 1, 1, 0, -1};
static const uint8_t DOPPLER_FWD[5] = {0, 2, 4, 0, 1};
static const uint8_t DOPPLER_REV[5] = {0, 4, 1, 0, 2};
static const uint8_t COMPLEMENT[8] = {0, 6, 5, 4, 3, 2, 1, 0};

typedef struct {
    uint8_t type, color, dir, off;
    uint8_t inc[8], out[8], snap[8];
} Cell;

static Cell B[CELLS];

typedef struct { int x, y, d, c, e; } Beam;
static Beam qa[QUEUE_MAX], qb[QUEUE_MAX];
static Beam *next_q;
static int n_next, ent_counter;

/* beamsolve.c: drop light leaving a square along a beam (or a teleporter jump) whose first
 * obstacle is still undecided. Nonzero return = drop. */
static int (*beam_hook)(int x, int y, int d, int c);
static int (*jump_hook)(int x, int y, int d, int c);
static void (*clear_hook)(void);
static int (*piece_hook)(int x, int y, int d, int c);

#define AT(x, y) (&B[(y) * N + (x)])

static void emit(int x, int y, int d, int c, int e) {
    if (beam_hook && beam_hook(x, y, d & 7, c)) return;
    if (n_next != QUEUE_MAX) {
        Beam *b = &next_q[n_next++];
        b->x = x; b->y = y; b->d = d & 7; b->c = c; b->e = e;
    }
}

static int is_teleporter(int t) { return t == 12 || t == 18; }

static void process(int x, int y, int d, int c, int e) {
    Cell *cell = AT(x, y);
    int k = cell->type;
    if (k > 21) { cell->inc[d] |= c; return; }
    if (k == 21) k = 0;                              /* occupied square: like empty */
    int rot = cell->dir;
    cell->inc[d] |= c;
    if (piece_hook && piece_hook(x, y, d, c)) return;
    int rel = (d - rot) & 7;
    switch (k) {
    case 0: case 10:
        emit(x, y, d, c, e); break;
    case 3:
        if (rel >= 1 && rel <= 3) emit(x, y, rot - rel, c, e);
        break;
    case 4:
        if (rel <= 3) emit(x, y, rot - rel - 1, c, e);
        break;
    case 5:
        if ((rel == 2 || rel == 6) && (cell->color & c)) emit(x, y, d, cell->color & c, e);
        break;
    case 6: {
        static const int8_t BL[8] = {99, 1, 2, 99, 99, -3, -2, 99};
        static const int8_t GR[8] = {1, 99, 3, 99, 99, -4, 99, -2};
        static const int8_t RD[8] = {-2, 99, -4, 99, 99, 3, 99, 1};
        if ((c & 4) && BL[rel] != 99) emit(x, y, rot + BL[rel], 4, e);
        if ((c & 2) && GR[rel] != 99) emit(x, y, rot + GR[rel], 2, e);
        if ((c & 1) && RD[rel] != 99) emit(x, y, rot + RD[rel], 1, e);
        break;
    }
    case 7:
        if (rel == 2) {
            int n = ((c & 4) ? 2 : 0) | ((c & 2) ? 1 : 0) | ((c & 1) ? 4 : 0);
            emit(x, y, d, e ? c : n, e);
        } else if (rel == 6) {
            int n = ((c & 4) ? 1 : 0) | ((c & 2) ? 4 : 0) | ((c & 1) ? 2 : 0);
            emit(x, y, d, e ? c : n, e);
        }
        break;
    case 8:
        if (rel == 0 || rel == 4) break;
        {
            static const int8_t R2[8] = {0, -1, -2, -3, 0, 3, 2, 1};
            emit(x, y, d, c, 0);
            emit(x, y, rot + R2[rel], c, 0);
        }
        break;
    case 9:
        if (rel == 2)
            for (int p = 1; p <= 4; p <<= 1)
                if (c & p) {
                    emit(x, y, rot, p, ent_counter);
                    emit(x, y, rot - 4, p, ent_counter);
                    ent_counter++;
                }
        break;
    case 11:
        if (rel == 0 || rel == 4) emit(x, y, d, c, e);
        break;
    case 12: case 18:
        if (jump_hook && jump_hook(x, y, d, c)) break;
        for (int tx = x + DX[d], ty = y + DY[d]; tx >= 0 && tx < N && ty >= 0 && ty < N;
             tx += DX[d], ty += DY[d])
            if (is_teleporter(AT(tx, ty)->type)) { emit(tx, ty, d, c, e); break; }
        break;
    case 13:
        {
            static const int8_t KEEP[8] = {1, 2, 4, 0, 1, 2, 4, 0};
            int keep = KEEP[rel];
            if (!keep) emit(x, y, d, c, e);
            else if (c & keep) emit(x, y, d, keep, e);
        }
        break;
    case 14:
        emit(x, y, d - 2, c, e);
        break;
    case 17:
        if ((d & 1) == 0) { emit(x, y, 1, c, 0); emit(x, y, 7, c, 0); emit(x, y, 3, c, 0); emit(x, y, 5, c, 0); }
        else { emit(x, y, 0, c, 0); emit(x, y, 2, c, 0); emit(x, y, 4, c, 0); emit(x, y, 6, c, 0); }
        break;
    case 19:
        {
            static const int8_t O[8] = {99, -1, -2, -3, 99, 3, 2, 1};
            if (O[rel] != 99) emit(x, y, rot + O[rel], c, e);
        }
        break;
    case 20:
        {
            static const int8_t O[8] = {-1, -2, -3, -4, 3, 2, 1, 0};
            emit(x, y, rot + O[rel], c, e);
        }
        break;
    default:
        break;                                       /* absorbed */
    }
}

static void after_generation(void) {
    for (int i = 0; i < n_next; i++) {
        Beam *bi = &next_q[i];
        if (bi->x < N && bi->y < N && bi->e && AT(bi->x, bi->y)->type == 7) {
            int fwd = ((bi->d - AT(bi->x, bi->y)->dir) & 7) == 2;
            for (int j = 0; j < n_next; j++)
                if (next_q[j].e == bi->e) {
                    const uint8_t *t = ((i == j) == fwd) ? DOPPLER_REV : DOPPLER_FWD;
                    next_q[j].c = t[next_q[j].c];
                }
        }
    }
}

static void trace(int x, int y, int d, int c) {
    Beam *cur = qa;
    next_q = qb; n_next = 0; ent_counter = 1;
    emit(x, y, d, c, 0);
    int left = GENERATIONS;
    while (n_next) {
        if (--left == 0) break;
        Beam *t = cur; cur = next_q; next_q = t;
        int n = n_next; n_next = 0;
        for (int i = 0; i < n; i++) {
            Beam b = cur[i];
            AT(b.x, b.y)->out[b.d] |= b.c;
            int nx = (b.x + DX[b.d]) & 0xff, ny = (b.y + DY[b.d]) & 0xff;
            if (nx < N && ny < N) process(nx, ny, b.d, b.c, b.e);
        }
        after_generation();
    }
}

static void clear_beams(void) {
    if (clear_hook) clear_hook();
    for (int i = 0; i < CELLS; i++) { memset(B[i].inc, 0, 8); memset(B[i].out, 0, 8); }
}

static void snapshot(void) {
    for (int i = 0; i < CELLS; i++) memcpy(B[i].snap, B[i].inc, 8);
}

static void trace_lasers(void) {
    for (int i = 0; i < CELLS; i++)
        if (B[i].type == 2) trace(i % N, i / N, B[i].dir, B[i].color);
}

static void emit_complements(void) {
    for (int p = 0; p < CELLS; p++) {
        Cell *c = &B[p];
        if (c->type != 15 || c->off) continue;
        for (int i = 0; i < 8; i++)
            if (c->inc[i] && (c->dir & 1) == (i & 1) && COMPLEMENT[c->inc[i]])
                trace(p % N, p / N, i, COMPLEMENT[c->inc[i]]);
    }
}

static int got_new_input(void) {
    for (int p = 0; p < CELLS; p++) {
        Cell *c = &B[p];
        if (c->type != 15 || c->off) continue;
        for (int i = 0; i < 8; i++)
            if (c->inc[i] && !c->snap[i]) return 1;
    }
    return 0;
}

static int contradictions(void) {
    int changed = 0;
    for (int p = 0; p < CELLS; p++) {
        Cell *c = &B[p];
        if (c->type != 15 || c->off) continue;
        for (int i = 0; i < 8; i++) {
            int s = c->snap[i], now = c->inc[i];
            if (s != now && s && !(s == 7 && !now)) {
                c->off = 1; changed = 1;
            }
        }
    }
    return changed;
}

static int gates(void) {
    int fired = 0;
    for (int p = 0; p < CELLS; p++) {
        Cell *c = &B[p];
        if (c->type != 16 && c->type != 22) continue;
        int both = c->inc[(c->dir - 1) & 7] & c->inc[(c->dir + 1) & 7];
        if (c->type == 22 && both != 1 && both != 2 && both != 4) both = 0;
        int e = both & ~c->out[c->dir] & 0xff;
        if (e) { trace(p % N, p / N, c->dir, e); fired = 1; }
    }
    return fired;
}

static void run(void) {
    for (int i = 0; i < CELLS; i++) B[i].off = 0;
    for (;;) {
        clear_beams(); snapshot(); trace_lasers();
        for (;;) {
            snapshot();
            int again = gates();
            emit_complements();
            if (got_new_input()) again = 1;
            if (gates() || again) continue;
            break;
        }
        if (!contradictions()) return;
    }
}

static int won(void) {
    for (int i = 0; i < CELLS; i++)
        if (B[i].type == 10) {
            int lit = 0;
            for (int d = 0; d < 8; d++) lit |= B[i].inc[d];
            if (lit != B[i].color) return 0;
        }
    return 1;
}

static uint64_t field_hash(void) {
    uint64_t h = 1469598103934665603ULL;
    for (int i = 0; i < CELLS; i++) {
        uint64_t w;
        memcpy(&w, B[i].inc, 8);
        h = (h ^ w) * 1099511628211ULL;
        h ^= h >> 29;
    }
    return h;
}

/* ---------------- search ---------------- */

typedef struct { int type, color, count; } Kind;
typedef struct { uint8_t x, y, kind, d; } Placement;

static Cell TEMPLATE[CELLS];
static Kind kinds[32];
static int n_kinds;
static long evals;
static double deadline;
static int max_solutions, n_solutions, cut_short;

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static void evaluate(const Placement *pl, int n) {
    memcpy(B, TEMPLATE, sizeof B);
    for (int i = 0; i < n; i++) {
        Cell *c = AT(pl[i].x, pl[i].y);
        c->type = kinds[pl[i].kind].type; c->color = kinds[pl[i].kind].color; c->dir = pl[i].d;
    }
    run();
    evals++;
}

/* open-addressing set of 64-bit keys */
typedef struct { uint64_t *k; size_t cap, n; } Set;
static int set_add(Set *s, uint64_t key) {          /* 1 if newly added */
    if (!key) key = 1;
    if (s->n * 2 >= s->cap) {
        Set t = {calloc(s->cap ? s->cap * 2 : 1 << 16, 8), s->cap ? s->cap * 2 : 1 << 16, 0};
        for (size_t i = 0; i < s->cap; i++) if (s->k[i]) set_add(&t, s->k[i]);
        free(s->k); *s = t;
    }
    size_t i = (key * 0x9E3779B97F4A7C15ULL) & (s->cap - 1);
    while (s->k[i]) { if (s->k[i] == key) return 0; i = (i + 1) & (s->cap - 1); }
    s->k[i] = key; s->n++;
    return 1;
}

static uint64_t placement_key(const Placement *pl, int n) {
    uint32_t v[128];
    for (int i = 0; i < n; i++) v[i] = (pl[i].y * N + pl[i].x) << 16 | pl[i].kind << 8 | pl[i].d;
    for (int i = 1; i < n; i++)                      /* insertion sort: order-free key */
        for (int j = i; j > 0 && v[j - 1] > v[j]; j--) { uint32_t t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
    uint64_t h = 1469598103934665603ULL;
    for (int i = 0; i < n; i++) { h = (h ^ v[i]) * 1099511628211ULL; h ^= h >> 31; }
    return h ^ (uint64_t)n << 56;
}

static Set seen, solutions_seen;

static void report(const Placement *pl, int n) {
    /* Solutions that light the board identically on the same squares count once. */
    uint64_t h = field_hash();
    uint64_t sq = 0;
    for (int i = 0; i < n; i++) sq += (uint64_t)(pl[i].y * N + pl[i].x + 1) * 0x9E3779B97F4A7C15ULL;
    if (!set_add(&solutions_seen, h ^ sq * 31)) return;
    printf("sol %d:", ++n_solutions);
    for (int i = 0; i < n; i++)
        printf(" %d %d %d %d %d;", kinds[pl[i].kind].type, pl[i].x, pl[i].y, pl[i].d, kinds[pl[i].kind].color);
    printf("\n");
    fflush(stdout);
}

/* B must hold the evaluated board for pl[0..n). */
static void dfs(Placement *pl, int n) {
    if (n_solutions >= max_solutions || now() > deadline) { cut_short = 1; return; }
    if (won()) { report(pl, n); return; }
    int any = 0;
    for (int k = 0; k < n_kinds; k++) any |= kinds[k].count;
    if (!any) return;
    uint64_t before = field_hash();
    int squares[CELLS], n_sq = 0;
    for (int i = 0; i < CELLS; i++) {
        uint64_t w;
        memcpy(&w, B[i].inc, 8);
        if (B[i].type == 0 && w) squares[n_sq++] = i;
    }
    for (int s = 0; s < n_sq && !cut_short; s++)
        for (int k = 0; k < n_kinds && !cut_short; k++) {
            if (!kinds[k].count) continue;
            uint64_t fields[9];
            int n_f = 0;
            fields[n_f++] = before;
            for (int d = 0; d < 8 && !cut_short; d++) {
                pl[n] = (Placement){squares[s] % N, squares[s] / N, k, d};
                if (!set_add(&seen, placement_key(pl, n + 1))) continue;
                evaluate(pl, n + 1);
                uint64_t f = field_hash();
                int dup = 0;
                for (int i = 0; i < n_f; i++) dup |= fields[i] == f;
                if (dup) continue;
                fields[n_f++] = f;
                kinds[k].count--;
                dfs(pl, n + 1);              /* B still holds this placement's board */
                kinds[k].count++;
            }
        }
}

static int place_into(Cell *b, int t, int x, int y, int d, int c) {
    if (x < 0 || x >= N || y < 0 || y >= N) return 0;
    Cell *cell = &b[y * N + x];
    cell->type = t; cell->dir = d; cell->color = c;
    return 1;
}

#ifndef FASTSIM_LIB
int main(void) {
    char line[256];
    memset(TEMPLATE, 0, sizeof TEMPLATE);
    while (fgets(line, sizeof line, stdin)) {
        int t, x, y, d, c, n;
        double secs;
        if (sscanf(line, "fixed %d %d %d %d %d", &t, &x, &y, &d, &c) == 5 ||
            sscanf(line, "place %d %d %d %d %d", &t, &x, &y, &d, &c) == 5) {
            place_into(TEMPLATE, t, x, y, d, c); continue;
        }
        if (sscanf(line, "kind %d %d %d", &t, &c, &n) == 3) {
            kinds[n_kinds++] = (Kind){t, c, n}; continue;
        }
        if (!strncmp(line, "check", 5)) {
            evaluate(NULL, 0);
            printf("won %d\nfield ", won());
            for (int i = 0; i < CELLS; i++) for (int k = 0; k < 8; k++) printf("%x", B[i].inc[k]);
            printf("\n");
            continue;
        }
        if (sscanf(line, "solve %lf %d", &secs, &max_solutions) == 2) {
            Placement pl[128];
            deadline = now() + secs;
            evaluate(pl, 0);
            dfs(pl, 0);
            printf("done solutions=%d complete=%d evals=%ld\n", n_solutions, !cut_short, evals);
        }
    }
    return 0;
}
#endif
