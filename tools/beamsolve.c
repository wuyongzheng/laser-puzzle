/* Beam-level solver for Laser Puzzle levels (see beamsolve.py for the interface and guarantees).
 *
 * Every piece that matters stands on a beam. So instead of trying every piece on every lit square,
 * the search takes one beam segment at a time (light leaving a square in one direction) and
 * decides what the beam meets first: a new piece on one of the free squares along it, or nothing
 * new, so that it runs on to the obstacle that is already there. The squares the beam then
 * crosses are closed to later pieces. Teleporter jumps are decided the same way when the toolbox
 * holds teleporters. A new piece keeps the set of rotations that treat the light it gets alike;
 * when light that they treat differently arrives, the set is split (another decision).
 *
 * Only light that has passed through decided segments is traced (the "certain" light). Where the
 * rules are monotone (more light in never means less light out), certain light is part of the
 * final light of every completion, so a target that already gets a wrong colour ends the branch,
 * and so do the lower bounds below. Before branching, every option of the open items is tried;
 * an item with no surviving option ends the branch, otherwise the one with the fewest options is
 * branched on, options that bring the missing colours closest first.
 *
 * Input on stdin: the fastsim.c lines (fixed, kind), optional settings
 *   rounds 0|1        count rounds (1, sound) or turns (0, faster, misses light that turns twice
 *                     at the same new piece)
 *   lookahead 0|1, ordering 0|1, last 0|1      switch off parts of the search (for testing)
 *   want TYPE X Y DIR COLOR                    self-test: follow the branch of this solution only
 *   grade BUDGET      with want: at each step of that branch print a "grade" line: how many
 *                     options survive, the rank of the right one, and the search (at most
 *                     BUDGET nodes per option) it takes to refute the others
 * then
 *   bsolve SECONDS MAX_SHAPES      -> "sol N: TYPE X Y DIR COLOR; ..." for each new shape, then
 *                                     "done shapes=N complete=0|1 nodes=N evals=N monotone=0|1"
 * BEAMSOLVE_STATS=1 in the environment prints search statistics on stderr.
 */
#define FASTSIM_LIB
#include "fastsim.c"
#include <pthread.h>

#define MAXP 128                    /* most toolbox pieces */

static uint8_t rot_rep[32][8];      /* kind, rotation -> representative rotation */
static int monotone, tele_kinds, n_targets, targets[CELLS], target_at[CELLS];  /* index + 1, or 0 */

typedef struct { uint8_t dec_beam[CELLS], dec_jump[CELLS], bblock[CELLS], tblock[CELLS]; } State;
static State S;                     /* decided segments (by direction), squares closed to pieces
                                       (bblock) or to teleporters (tblock) */

typedef struct { uint8_t cell, d, kind, c; } Item;
#define BEAM 0                      /* light leaving `cell` in direction d, colour c */
#define JUMP 1                      /* light entering teleporter `cell` travelling d */
#define PIECE 2                     /* a placed piece whose rotation is still a set, reached by
                                       light that the rotations in the set treat differently */
static Item opens[CELLS * 8];
static int n_open;
static uint8_t open_b[CELLS], open_j[CELLS], open_p[CELLS];

static int transparent(int t) { return t == 0 || t == 10 || t == 21; }

static void clear_opens(void) {
    n_open = 0;
    memset(open_b, 0, sizeof open_b); memset(open_j, 0, sizeof open_j); memset(open_p, 0, sizeof open_p);
}

static void add_open(int cell, int d, int kind, int c) {
    uint8_t *mark = kind == PIECE ? open_p : kind == JUMP ? open_j : open_b;
    if (mark[cell] & 1 << d) {
        for (int i = 0; i < n_open; i++)
            if (opens[i].cell == cell && opens[i].d == d && opens[i].kind == kind) opens[i].c |= c;
        return;
    }
    mark[cell] |= 1 << d;
    opens[n_open++] = (Item){cell, d, kind, c};
}

static int stop_beam(int x, int y, int d, int c) {
    int cell = y * N + x;
    if (transparent(B[cell].type) || S.dec_beam[cell] & 1 << d) return 0;
    B[cell].out[d] |= c;         /* as if it had left: logic gates fire until it has */
    add_open(cell, d, BEAM, c);
    return 1;
}

static int stop_jump(int x, int y, int d, int c) {
    int cell = y * N + x;
    if (!tele_kinds || S.dec_jump[cell] & 1 << d) return 0;
    add_open(cell, d, JUMP, c);
    return 1;
}

static int stop_piece(int x, int y, int d, int c);

static void certain(int on) {
    beam_hook = on ? stop_beam : NULL;
    jump_hook = on ? stop_jump : NULL;
    clear_hook = on ? clear_opens : NULL;
    piece_hook = on ? stop_piece : NULL;
}

/* ---- what pieces do: rotation classes and per-input output tables ---- */

static void rotation_classes(void) {
    Cell save = B[0];
    for (int k = 0; k < n_kinds; k++) {
        int t = kinds[k].type;
        uint8_t sig[8][8 * 7 * 8];
        for (int r = 0; r < 8; r++) {
            memset(sig[r], 0, sizeof sig[r]);
            for (int d = 0; d < 8; d++)
                for (int c = 1; c < 8; c++) {
                    memset(&B[0], 0, sizeof B[0]);
                    B[0].type = t; B[0].color = kinds[k].color; B[0].dir = r;
                    next_q = qb; n_next = 0; ent_counter = 1;
                    process(0, 0, d, c, 0);
                    for (int i = 0; i < n_next; i++)
                        sig[r][(d * 7 + c - 1) * 8 + next_q[i].d] |= next_q[i].c | (next_q[i].e ? 8 : 0);
                }
            if (is_teleporter(t)) memset(sig[r], 0, sizeof sig[r]);
            if (t == 15) { memset(sig[r], 0, sizeof sig[r]); sig[r][0] = r & 1; }
            if (t == 16 || t == 22) { memset(sig[r], 0, sizeof sig[r]); sig[r][0] = r; }
            rot_rep[k][r] = r;
            for (int q = 0; q < r; q++)
                if (!memcmp(sig[q], sig[r], sizeof sig[r])) { rot_rep[k][r] = q; break; }
        }
    }
    B[0] = save;
}

static uint32_t kind_turn[32][8][8][8];      /* kind, rotation, d, colour -> mask of (d' * 3 + bit) */
static uint32_t cell_turn[CELLS][8][8];      /* fixed pieces */
static uint64_t kind_st[32][8][8][8], cell_st[CELLS][8][8];  /* as masks of BFS states d' * 8 + S' */

static uint32_t lone_outputs(int t, int color, int r, int d, int set) {
    Cell save = B[0];
    memset(&B[0], 0, sizeof B[0]);
    B[0].type = t; B[0].color = color; B[0].dir = r;
    next_q = qb; n_next = 0; ent_counter = 1;
    process(0, 0, d, set, 0);
    uint32_t m = 0;
    for (int i = 0; i < n_next; i++)
        for (int b = 0; b < 3; b++)
            if (next_q[i].c & 1 << b) m |= 1u << (next_q[i].d * 3 + b);
    if (t == 16 || t == 22)                      /* gates fire on their two side inputs */
        m = (d == ((r + 1) & 7) || d == ((r - 1) & 7)) ? (uint32_t)set << (r * 3) : 0;
    B[0] = save;
    return m;
}

static uint64_t as_states(uint32_t m) {
    uint64_t r = 0;
    for (int d = 0; d < 8; d++, m >>= 3)
        if (m & 7) r |= 1ULL << (d * 8 + (m & 7));
    return r;
}

/* A logic gate sends out the AND of its two inputs: along one path of light, any part of it. */
static uint64_t gate_states(int r, int d, int x) {
    uint64_t m = 0;
    if (d == ((r + 1) & 7) || d == ((r - 1) & 7))
        for (int sub = 1; sub < 8; sub++)
            if (!(sub & ~x)) m |= 1ULL << (r * 8 + sub);
    return m;
}

static void turn_tables(void) {
    for (int k = 0; k < n_kinds; k++)
        for (int r = 0; r < 8; r++)
            for (int d = 0; d < 8; d++)
                for (int x = 1; x < 8; x++) {
                    int t = kinds[k].type;
                    kind_turn[k][r][d][x] = lone_outputs(t, kinds[k].color, r, d, x);
                    kind_st[k][r][d][x] = t == 16 || t == 22 ? gate_states(r, d, x) : as_states(kind_turn[k][r][d][x]);
                }
    for (int c = 0; c < CELLS; c++)
        for (int d = 0; d < 8; d++)
            for (int x = 1; x < 8; x++) {
                Cell *f = &TEMPLATE[c];
                cell_turn[c][d][x] = transparent(f->type) || is_teleporter(f->type) ? 0 :
                                     lone_outputs(f->type, f->color, f->dir, d, x);
                cell_st[c][d][x] = f->type == 16 || f->type == 22 ? gate_states(f->dir, d, x) :
                                   as_states(cell_turn[c][d][x]);
            }
}

/* ---- placed pieces keep a set of rotations until light tells them apart ---- */

static int lazy;                    /* rotation sets in use (monotone levels only) */
static uint8_t rset[MAXP];            /* placement index -> rotations still possible */
static int8_t piece_at[CELLS];      /* placement index, or -1 */
static const Placement *cur_pl;

static int lazy_kind(int k) { int t = kinds[k].type; return lazy && t != 15 && t != 16 && t != 22; }

static int stop_piece(int x, int y, int d, int c) {
    int cell = y * N + x, i = piece_at[cell];
    if (i < 0 || !(rset[i] & (rset[i] - 1))) return 0;
    int k = cur_pl[i].kind, r0 = cur_pl[i].d;
    for (int r = 0; r < 8; r++)
        if (rset[i] >> r & 1 && kind_turn[k][r][d][c] != kind_turn[k][r0][d][c]) {
            add_open(cell, 0, PIECE, 0);
            return 1;
        }
    return 0;
}

/* Trace the certain light of the board with pl[0..n) placed. */
static void eval(const Placement *pl, int n) {
    memset(piece_at, -1, sizeof piece_at);
    for (int i = 0; i < n; i++) piece_at[pl[i].y * N + pl[i].x] = i;
    cur_pl = pl;
    evaluate(pl, n);
}

static int pieces_left(void) {
    int left = 0;
    for (int k = 0; k < n_kinds; k++) left += kinds[k].count;
    return left;
}

/* ---- lower bound 1: pieces needed to bring each missing colour to its target ----
 * BFS over "light of colour set S leaves square c in direction d", following one path of the
 * light: S is what that path alone carries, a subset of the beam's real colour. Light runs
 * straight over empty squares and targets, follows the real behaviour of pieces already on the
 * board (a placed piece: any rotation in its set), and may turn on a free square in any way a
 * remaining toolbox piece can turn it. A target of colour T missing bit b needs a path arriving
 * with b in S and S inside T (the real beam holds S, and must not hold anything outside T).
 *
 * Counting one piece per turn would overestimate when light comes back to a piece and turns there
 * again. So the count is in rounds: a free square can take a piece one round after light
 * first reaches it, and from then on any light passing it may turn there. Each piece of a real
 * solution is first lit by light that needs fewer pieces, so k pieces reach at most what k rounds
 * reach. Pieces block nothing and toolbox counts are ignored, so the count never overestimates. */

#define STATES (CELLS * 64)
static uint8_t dist[STATES];
static int bucket[64][STATES], n_bucket[64];     /* a state enters each level at most once */
static uint8_t placed_kind[CELLS], placed_set[CELLS];     /* kind + 1, or 0 */
static uint8_t first_lit[CELLS];                 /* free squares: level light first gets there */
static uint8_t reached_at[CELLS][3];             /* (target index, bit): level it was reached at */
static int rounds = 1, full_bfs, score;          /* score: sum of those levels (for ordering) */

/* Pieces after which every target could have all its colours: the exact count if it is at most
 * `limit`, otherwise limit + 1. With full_bfs set, every level up to `limit` is explored. */
static int pieces_needed(const Placement *pl, int n, int limit) {
    uint8_t missing[CELLS];
    int n_missing = 0, need = -1;
    score = 0;
    for (int i = 0; i < n_targets; i++) {
        Cell *tc = &B[targets[i]];
        int lit = 0;
        for (int d = 0; d < 8; d++) lit |= tc->inc[d];
        missing[i] = tc->color & ~lit;
        n_missing += __builtin_popcount(missing[i]);
    }
    if (!n_missing && !full_bfs) return 0;
    if (limit > 62) limit = 62;
    uint64_t turn[8][8] = {{0}};
    int tele_left = 0;
    for (int k = 0; k < n_kinds; k++) {
        if (!kinds[k].count) continue;
        if (is_teleporter(kinds[k].type)) tele_left = 1;
        for (int r = 0; r < 8; r++)
            for (int d = 0; d < 8; d++)
                for (int x = 1; x < 8; x++) turn[d][x] |= kind_st[k][r][d][x];
    }
    memset(placed_kind, 0, sizeof placed_kind);
    for (int i = 0; i < n; i++) {
        int c = pl[i].y * N + pl[i].x;
        placed_kind[c] = pl[i].kind + 1; placed_set[c] = rset[i];
    }
    memset(dist, 255, sizeof dist);
    memset(first_lit, 255, sizeof first_lit);
    memset(n_bucket, 0, (limit + 2) * sizeof *n_bucket);
#define PUSH(st, dv) do { int s_ = (st), v_ = (dv); if (v_ <= limit && v_ < dist[s_]) { \
        dist[s_] = v_; bucket[v_][n_bucket[v_]++] = s_; } } while (0)
#define LAND(c, dv) do { if (B[c].type == 0 && first_lit[c] > (dv)) first_lit[c] = (dv); } while (0)  /* a new exit teleporter: lit with the light that jumps to it */
    for (int i = 0; i < n_open; i++) {
        const Item *o = &opens[i];
        if (o->kind == BEAM) { PUSH((o->cell * 8 + o->d) * 8 + o->c, 0); continue; }
        if (o->kind == PIECE) {                  /* light held up at a piece: any rotation in its set */
            int c = o->cell;
            for (int din = 0; din < 8; din++) {
                int x = B[c].inc[din];
                if (!x) continue;
                for (int r = 0; r < 8; r++)
                    if (placed_set[c] >> r & 1)
                        for (uint64_t out = kind_st[placed_kind[c] - 1][r][din][x]; out; out &= out - 1)
                            PUSH(c * 64 + __builtin_ctzll(out), 0);
            }
            continue;
        }
        int x = o->cell % N, y = o->cell / N;    /* JUMP: to the next teleporter, or a new one */
        for (x += DX[o->d], y += DY[o->d]; x >= 0 && x < N && y >= 0 && y < N; x += DX[o->d], y += DY[o->d]) {
            int c = y * N + x;
            if (is_teleporter(B[c].type)) { PUSH((c * 8 + o->d) * 8 + o->c, 0); break; }
            if (tele_left) { PUSH((c * 8 + o->d) * 8 + o->c, 1); LAND(c, 0); }
        }
    }
    for (int v = 0; v <= limit; v++)
        for (int qi = 0; qi < n_bucket[v]; qi++) {
            int st = bucket[v][qi];
            if (dist[st] != v) continue;
            int set = st & 7, d = st / 8 % 8, cell = st / 64;
            int x = cell % N + DX[d], y = cell / N + DY[d];
            if (x < 0 || x >= N || y < 0 || y >= N) continue;
            int c = y * N + x, t = B[c].type;
            uint64_t out;
            if (target_at[c]) {
                int i = target_at[c] - 1, got = missing[i] & set;
                if (got && !(set & ~B[c].color)) {
                    missing[i] &= ~got;
                    for (int b = 0; b < 3; b++) if (got >> b & 1) reached_at[i][b] = v;
                    n_missing -= __builtin_popcount(got);
                    score += v * __builtin_popcount(got);
                    if (!n_missing && need < 0) { need = v; if (!full_bfs) return v; }
                }
            }
            if (transparent(t)) {
                PUSH((c * 8 + d) * 8 + set, v);
                if (t != 0 || S.bblock[c]) continue;
                if (first_lit[c] > v) first_lit[c] = v;
                int cost = rounds && first_lit[c] < v ? v : v + 1;
                for (out = turn[d][set]; out; out &= out - 1) PUSH(c * 64 + __builtin_ctzll(out), cost);
                if (tele_left && !S.tblock[c])
                    for (int tx = x + DX[d], ty = y + DY[d]; tx >= 0 && tx < N && ty >= 0 && ty < N; tx += DX[d], ty += DY[d])
                    { PUSH(((ty * N + tx) * 8 + d) * 8 + set, cost); if (cost <= limit) LAND(ty * N + tx, v); }
                continue;
            }
            if (is_teleporter(t)) {
                for (int tx = x + DX[d], ty = y + DY[d]; tx >= 0 && tx < N && ty >= 0 && ty < N; tx += DX[d], ty += DY[d]) {
                    int c2 = ty * N + tx;
                    if (is_teleporter(B[c2].type)) { PUSH((c2 * 8 + d) * 8 + set, v); break; }
                    if (tele_left && !(S.dec_jump[c] & 1 << d)) { PUSH((c2 * 8 + d) * 8 + set, v + 1); if (v < limit) LAND(c2, v); }
                }
                continue;
            }
            if (placed_kind[c]) {
                out = 0;
                for (int r = 0; r < 8; r++)
                    if (placed_set[c] >> r & 1) out |= kind_st[placed_kind[c] - 1][r][d][set];
            } else
                out = cell_st[c][d][set];
            for (; out; out &= out - 1) PUSH(c * 64 + __builtin_ctzll(out), v);
        }
#undef PUSH
#undef LAND
    return need >= 0 ? need : n_missing ? limit + 1 : 0;
}

/* ---- lower bound 2: where the last pieces can go ----
 * The light that brings a missing bit to a target passes, after the last new piece on its way,
 * only straight lines and pieces already on the board. Walking backwards from the target along
 * those gives the free squares where that last piece can stand; with k pieces left it must also
 * be lit within k - 1 rounds. If no k squares meet every such set, k pieces are not enough. */

static uint32_t stamp[STATES], stamp_now;
static int bq[STATES];

/* free squares (bitset) from which bit b can reach target t without new pieces */
static void last_squares(int t, int b, uint64_t *sq) {
    int col = B[t].color, n = 0;
    memset(sq, 0, 4 * sizeof *sq);
    stamp_now++;
#define VISIT(st) do { int s_ = (st); if (stamp[s_] != stamp_now) { stamp[s_] = stamp_now; bq[n++] = s_; } } while (0)
    for (int d = 0; d < 8; d++) {
        int px = t % N - DX[d], py = t / N - DY[d];
        if (px < 0 || px >= N || py < 0 || py >= N) continue;
        for (int set = 1; set < 8; set++)
            if (set >> b & 1 && !(set & ~col)) VISIT(((py * N + px) * 8 + d) * 8 + set);
    }
    for (int i = 0; i < n; i++) {
        int st = bq[i], set = st & 7, d = st / 8 % 8, c = st / 64, ty = B[c].type;
        if (transparent(ty)) {
            if (ty == 0 && !S.bblock[c]) sq[c >> 6] |= 1ULL << (c & 63);
            int px = c % N - DX[d], py = c / N - DY[d];
            if (px >= 0 && px < N && py >= 0 && py < N) VISIT(((py * N + px) * 8 + d) * 8 + set);
            continue;
        }
        if (is_teleporter(ty)) {                   /* came out of c: went into the teleporter behind */
            for (int x = c % N - DX[d], y = c / N - DY[d]; x >= 0 && x < N && y >= 0 && y < N; x -= DX[d], y -= DY[d])
                if (is_teleporter(B[y * N + x].type)) {
                    int px = x - DX[d], py = y - DY[d];
                    if (px >= 0 && px < N && py >= 0 && py < N) VISIT(((py * N + px) * 8 + d) * 8 + set);
                    break;
                }
            continue;
        }
        for (int din = 0; din < 8; din++) {
            int px = c % N - DX[din], py = c / N - DY[din];
            if (px < 0 || px >= N || py < 0 || py >= N) continue;
            for (int x = 1; x < 8; x++) {
                uint64_t out = 0;
                if (placed_kind[c]) {
                    for (int r = 0; r < 8; r++)
                        if (placed_set[c] >> r & 1) out |= kind_st[placed_kind[c] - 1][r][din][x];
                } else
                    out = cell_st[c][din][x];
                if (out >> (d * 8 + set) & 1) VISIT(((py * N + px) * 8 + din) * 8 + x);
            }
        }
    }
#undef VISIT
}

static int popcount4(const uint64_t *s) {
    return __builtin_popcountll(s[0]) + __builtin_popcountll(s[1]) + __builtin_popcountll(s[2]) + __builtin_popcountll(s[3]);
}

static int subset4(const uint64_t *a, const uint64_t *b) {
    return !(a[0] & ~b[0]) && !(a[1] & ~b[1]) && !(a[2] & ~b[2]) && !(a[3] & ~b[3]);
}

/* Drop the sets that contain another one (meeting the smaller one meets both): new count. */
static int minimal_sets(uint64_t (*sets)[4], int n) {
    int m = 0;
    for (int i = 0; i < n; i++) {
        int dominated = 0;
        for (int j = 0; j < n && !dominated; j++)
            if (j != i && subset4(sets[j], sets[i]) && (!subset4(sets[i], sets[j]) || j < i)) dominated = 1;
        if (!dominated) memcpy(sets[m++], sets[i], sizeof sets[i]);
    }
    return m;
}

/* Number of pairwise disjoint sets picked greedily, smallest first (a lower bound on the squares
 * needed to meet them all); 999 if a set is empty (nothing meets it). */
static int disjoint_count(uint64_t (*sets)[4], int n) {
    uint64_t used[4] = {0};
    int picked = 0;
    for (;;) {
        int best = -1, bc = 999;
        for (int i = 0; i < n; i++) {
            uint64_t *s = sets[i];
            if ((s[0] & used[0]) | (s[1] & used[1]) | (s[2] & used[2]) | (s[3] & used[3])) continue;
            int c = popcount4(s);
            if (!c) return 999;
            if (c < bc) { bc = c; best = i; }
        }
        if (best < 0) return picked;
        for (int w = 0; w < 4; w++) used[w] |= sets[best][w];
        picked++;
    }
}

/* Can `k` squares meet every set? Exact, by branching on the smallest set, until the work budget
 * runs out; then the answer is yes (no proof that they cannot). */
static long hit_budget;

static int hit(uint64_t (*sets)[4], int n, int k) {
    if (!n) return 1;
    if (!k) return 0;
    if (--hit_budget < 0) return 1;
    n = minimal_sets(sets, n);
    if (disjoint_count(sets, n) > k) return 0;
    if (n <= k) return 1;
    int small = 0, best = 999;
    for (int i = 0; i < n; i++) {
        int c = popcount4(sets[i]);
        if (c < best) { best = c; small = i; }
    }
    if (!best) return 0;
    uint64_t (*rest)[4] = malloc(n * sizeof *rest);
    int ok = 0;
    for (int w = 0; w < 4 && !ok; w++)
        for (uint64_t m = sets[small][w]; m && !ok; m &= m - 1) {
            int q = w * 64 + __builtin_ctzll(m), r = 0;
            for (int i = 0; i < n; i++)
                if (!(sets[i][q >> 6] >> (q & 63) & 1)) memcpy(rest[r++], sets[i], sizeof sets[i]);
            ok = hit(rest, r, k - 1);
        }
    free(rest);
    return ok;
}

/* The last-square sets of the missing bits that need a piece. When there are more of them than
 * `limit`, only squares lit within limit - 1 rounds are kept. Call right after pieces_needed. */
static int last_sets(const Placement *pl, int n_pl, int limit, uint64_t (*sets)[4]) {
    int n = 0;
    for (int i = 0; i < n_targets; i++) {
        Cell *tc = &B[targets[i]];
        int lit = 0;
        for (int d = 0; d < 8; d++) lit |= tc->inc[d];
        for (int b = 0; b < 3; b++)
            if (tc->color & ~lit & 1 << b && reached_at[i][b] > 0) last_squares(targets[i], b, sets[n++]);
    }
    if (n <= limit) return n;
    uint64_t early[4] = {0};
    full_bfs = 1;
    pieces_needed(pl, n_pl, limit);
    full_bfs = 0;
    for (int c = 0; c < CELLS; c++)
        if (first_lit[c] < limit) early[c >> 6] |= 1ULL << (c & 63);
    for (int i = 0; i < n; i++)
        for (int w = 0; w < 4; w++) sets[i][w] &= early[w];
    return n;
}

/* Could `limit` new pieces be the last pieces of every missing bit? Exact for up to 3 pieces,
 * otherwise a count of pairwise disjoint sets. Call right after pieces_needed. */
static int last_pieces_fit(const Placement *pl, int n_pl, int limit) {
    static uint64_t sets[CELLS][4];
    int n = last_sets(pl, n_pl, limit, sets);
    if (n <= limit) return 1;
    if (limit <= 3) { hit_budget = 2000; return hit(sets, n, limit); }
    return disjoint_count(sets, n) <= limit;
}

/* With one piece left it is the last piece of every missing bit: the squares it can go on.
 * Returns 0 if nothing is missing (no restriction). Call right after pieces_needed. */
static int last_piece_squares(const Placement *pl, int n_pl, uint64_t *sq) {
    static uint64_t sets[CELLS][4];
    int n = last_sets(pl, n_pl, 1, sets);
    sq[0] = sq[1] = sq[2] = sq[3] = ~0ULL;
    for (int i = 0; i < n; i++)
        for (int w = 0; w < 4; w++) sq[w] &= sets[i][w];
    return n > 0;
}

/* ---- options of an open item ---- */

typedef struct { int16_t sq; uint8_t kind, set; uint16_t score; } Opt;   /* sq < 0: nothing new */

static int lowest(int set) { return __builtin_ctz(set); }

static int seg_squares(const Item *s, int *sq) {
    int n = 0, x = s->cell % N, y = s->cell / N;
    for (;;) {
        x += DX[s->d]; y += DY[s->d];
        if (x < 0 || x >= N || y < 0 || y >= N) break;
        int c = y * N + x, t = B[c].type;
        if (s->kind == JUMP ? is_teleporter(t) : !transparent(t)) break;
        sq[n++] = c;
    }
    return n;
}

/* Split `set` (rotations of kind k) into groups that treat the inputs inc[0..7] alike. */
static int split(int k, int set, const uint8_t *inc, uint8_t *groups) {
    int n = 0;
    uint8_t rep[8];
    for (int r = 0; r < 8; r++) {
        if (!(set >> r & 1)) continue;
        int g = 0;
        for (; g < n; g++) {
            int same = 1;
            for (int d = 0; d < 8 && same; d++)
                if (inc[d] && kind_turn[k][r][d][inc[d]] != kind_turn[k][rep[g]][d][inc[d]]) same = 0;
            if (same) break;
        }
        if (g == n) { rep[n] = r; groups[n++] = 0; }
        groups[g] |= 1 << r;
    }
    return n;
}

static int options(const Item *s, Opt *o, const Placement *pl) {
    int n = 0;
    if (s->kind == PIECE) {
        int i = piece_at[s->cell];
        uint8_t groups[8];
        int n_g = split(pl[i].kind, rset[i], B[s->cell].inc, groups);
        for (int g = 0; g < n_g; g++) o[n++] = (Opt){s->cell, pl[i].kind, groups[g], 0};
        return n;
    }
    int sq[N], n_sq = seg_squares(s, sq);
    o[n++] = (Opt){-1, 0, 0, 0};
    uint8_t inc[8] = {0};
    inc[s->d] = s->c ? s->c : 7;
    for (int i = 0; i < n_sq; i++) {
        int c = sq[i];
        if (B[c].type != 0 || S.bblock[c]) continue;
        for (int k = 0; k < n_kinds; k++) {
            if (!kinds[k].count) continue;
            int tele = is_teleporter(kinds[k].type);
            if (s->kind == JUMP && !tele) continue;
            if (tele && S.tblock[c]) continue;
            if (lazy_kind(k)) {
                uint8_t groups[8];
                int n_g = split(k, 0xff, inc, groups);
                for (int g = 0; g < n_g; g++) o[n++] = (Opt){c, k, groups[g], 0};
            } else {
                for (int r = 0; r < 8; r++)
                    if (rot_rep[k][r] == r) o[n++] = (Opt){c, k, 1 << r, 0};
            }
        }
    }
    return n;
}

/* B's pieces (not its light) = the board with pl[0..n) placed */
static void set_board(const Placement *pl, int n) {
    for (int i = 0; i < CELLS; i++) { B[i].type = TEMPLATE[i].type; B[i].dir = TEMPLATE[i].dir; B[i].color = TEMPLATE[i].color; }
    for (int i = 0; i < n; i++) {
        Cell *c = AT(pl[i].x, pl[i].y);
        c->type = kinds[pl[i].kind].type; c->color = kinds[pl[i].kind].color; c->dir = pl[i].d;
    }
}

/* Apply option o to item s: returns the new number of placements. Undo: restore S, rset and the
 * placements' rotations, then unapply(). */
static int apply(const Item *s, const Opt *o, Placement *pl, int n) {
    if (s->kind == PIECE) {
        int i = piece_at[s->cell];
        rset[i] = o->set; pl[i].d = lowest(o->set);
        return n;
    }
    set_board(pl, n);
    int sq[N], n_sq = seg_squares(s, sq);
    uint8_t *block = s->kind == JUMP ? S.tblock : S.bblock;
    (s->kind == JUMP ? S.dec_jump : S.dec_beam)[s->cell] |= 1 << s->d;
    for (int i = 0; i < n_sq && sq[i] != o->sq; i++) block[sq[i]] = 1;
    if (o->sq < 0) return n;
    pl[n] = (Placement){o->sq % N, o->sq / N, o->kind, lowest(o->set)};
    rset[n] = o->set;
    kinds[o->kind].count--;
    return n + 1;
}

static void unapply(const Item *s, const Opt *o) { if (s->kind != PIECE && o->sq >= 0) kinds[o->kind].count++; }

/* ---- self-test: follow the one branch that leads to a given solution ---- */

static int ptest, n_want;
static Placement want[MAXP];
static int8_t want_at[CELLS];                /* index into want, or -1 */

static int matches(const Item *s, const Opt *o, const Placement *pl) {
    if (s->kind == PIECE) {
        int i = piece_at[s->cell], w = want_at[s->cell];
        return w >= 0 && o->set >> want[w].d & 1 && pl[i].kind == want[w].kind;
    }
    int sq[N], n_sq = seg_squares(s, sq);
    for (int i = 0; i < n_sq; i++) {
        int w = want_at[sq[i]];
        if (w >= 0 && B[sq[i]].type == 0 && (s->kind != JUMP || is_teleporter(kinds[want[w].kind].type)))
            return o->sq == sq[i] && o->kind == want[w].kind && o->set >> want[w].d & 1;
    }
    return o->sq < 0;
}

static void ptest_fail(const char *why, const Item *s, const Placement *pl, int n) {
    printf("ptest: %s at depth %d", why, n);
    if (s) printf(", item (%d,%d) d %d kind %d", s->cell % N, s->cell / N, s->d, s->kind);
    printf("; placed:");
    for (int i = 0; i < n; i++) printf(" %d@(%d,%d)r%d/%02x", pl[i].kind, pl[i].x, pl[i].y, pl[i].d, rset[i]);
    printf("\n");
    cut_short = 1;
}

/* ---- search ---- */

static long nodes, depth_nodes[64], depth_branch[64], why[16][5];
/* grading (see grade_step): sub-searches count their wins instead of reporting them */
static int grade, quiet, sdepth, sub_maxdepth;
static long node_limit = -1, sub_wins, grade_budget = 20000;
static int lookahead = 1, ordering = 1, last_check = 1;
static int n_shapes;
static Set shapes_seen;

static int overlit(void) {
    if (!monotone) return 0;
    for (int i = 0; i < n_targets; i++) {
        Cell *c = &B[targets[i]];
        int lit = 0;
        for (int d = 0; d < 8; d++) lit |= c->inc[d];
        if (lit & ~c->color) return 1;
    }
    return 0;
}

/* After eval(): can this child still lead to a solution? (light with nowhere new to go is final) */
static int viable(const Placement *pl, int n) {
    int left = pieces_left(), w = left < 15 ? left : 15;   /* why[]: overlit, final, bounds 1, 2, ok */
    score = 0;
    if (overlit()) return why[w][0]++, 0;
    if (!monotone || !lookahead) return 1;
    if (!n_open) return won() ? 1 : (why[w][1]++, 0);
    if (pieces_needed(pl, n, left) > left) return why[w][2]++, 0;
    if (last_check && !last_pieces_fit(pl, n, left)) return why[w][3]++, 0;
    why[w][4]++;
    return 1;
}

static void report_shape(const Placement *pl, int n) {
    uint32_t v[MAXP];
    for (int i = 0; i < n; i++) v[i] = pl[i].kind << 8 | rot_rep[pl[i].kind][pl[i].d];
    for (int i = 1; i < n; i++)
        for (int j = i; j > 0 && v[j - 1] > v[j]; j--) { uint32_t t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
    uint64_t h = 1469598103934665603ULL ^ (uint64_t)n << 50;
    for (int i = 0; i < n; i++) { h = (h ^ v[i]) * 1099511628211ULL; h ^= h >> 31; }
    if (!set_add(&shapes_seen, h)) return;
    printf("sol %d:", ++n_shapes);
    for (int i = 0; i < n; i++)
        printf(" %d %d %d %d %d;", kinds[pl[i].kind].type, pl[i].x, pl[i].y, pl[i].d, kinds[pl[i].kind].color);
    printf("\n");
    fflush(stdout);
    if (n_shapes >= max_solutions) cut_short = 1;
}

/* A won placement stands for every choice of rotation from the sets: report each shape. */
static void report_all(Placement *pl, int n, int i) {
    if (cut_short) return;
    if (i == n) { report_shape(pl, n); return; }
    int keep = pl[i].d, seen = 0;
    for (int r = 0; r < 8; r++) {
        int rep = rot_rep[pl[i].kind][r];
        if (!(rset[i] >> r & 1) || seen >> rep & 1) continue;
        seen |= 1 << rep;
        pl[i].d = r;
        report_all(pl, n, i + 1);
    }
    pl[i].d = keep;
}

/* The board is final when nothing is open: the real light decides. */
static void final(Placement *pl, int n) {
    if (won() && quiet) sub_wins++;
    else if (won()) report_all(pl, n, 0);
    else if (ptest) ptest_fail("final board does not win", NULL, pl, n);
}

static void search_body(Placement *pl, int n);

static void search(Placement *pl, int n) {
    if (cut_short) return;
    if ((++nodes & 63) == 0 && now() > deadline) { cut_short = 1; return; }
    if (node_limit >= 0 && nodes > node_limit) { cut_short = 1; return; }
    if (++sdepth > sub_maxdepth) sub_maxdepth = sdepth;
    search_body(pl, n);
    sdepth--;
}

static void search_body(Placement *pl, int n) {
    eval(pl, n);
    if (overlit()) { if (ptest) ptest_fail("wrong colour", NULL, pl, n); return; }
    if (!n_open) { final(pl, n); return; }
    if (!pieces_left()) {
        /* nothing left to place: the real light decides, unless it reaches a piece whose
         * rotations would treat it differently */
        int piece_items = 0;
        for (int i = 0; i < n_open; i++) piece_items += opens[i].kind == PIECE;
        if (!piece_items) {
            beam_hook = NULL; jump_hook = NULL;
            eval(pl, n);
            certain(1);
            if (!n_open) { final(pl, n); return; }
            eval(pl, n);
        }
    }
    int left = pieces_left();
    if (monotone && (pieces_needed(pl, n, left) > left || (last_check && !last_pieces_fit(pl, n, left)))) {
        if (ptest) ptest_fail("bound", NULL, pl, n);
        return;
    }
    uint64_t last_sq[4];
    int restrict_last = monotone && lookahead && last_check && left == 1 && last_piece_squares(pl, n, last_sq);
    if (restrict_last && !(last_sq[0] | last_sq[1] | last_sq[2] | last_sq[3])) {
        if (ptest) ptest_fail("no square for the last piece", NULL, pl, n);
        return;
    }

    int n_items = n_open;
    Item *items = malloc(n_items * sizeof *items);
    memcpy(items, opens, n_items * sizeof *items);
    Opt *all = malloc(4096 * sizeof *all), *best = malloc(4096 * sizeof *best);
    int n_best = -1, chosen = 0;
    State saved = S;
    uint8_t saved_set[MAXP], saved_d[MAXP];
    for (int i = 0; i < n; i++) { saved_set[i] = rset[i]; saved_d[i] = pl[i].d; }
#define RESTORE() do { S = saved; for (int i_ = 0; i_ < n; i_++) { rset[i_] = saved_set[i_]; pl[i_].d = saved_d[i_]; } } while (0)
    /* Items are tried in order of raw option count: once that count is no lower than the best
     * count after pruning, no later item can do better. */
    int *raw = malloc(2 * (n_items + 1) * sizeof *raw), *order = raw + n_items + 1;
    eval(pl, n);
    for (int i = 0; i < n_items; i++) { raw[i] = options(&items[i], all, pl); order[i] = i; }
    for (int i = 1; i < n_items; i++)
        for (int j = i; j > 0 && raw[order[j - 1]] > raw[order[j]]; j--) { int t = order[j]; order[j] = order[j - 1]; order[j - 1] = t; }
    for (int q = 0; q < n_items && n_best != 0 && !cut_short; q++) {
        int i = order[q];
        if (now() > deadline) { cut_short = 1; break; }
        if (n_best >= 0 && raw[i] >= n_best) break;
        eval(pl, n);                                 /* this node's board and light */
        int n_all = options(&items[i], all, pl), n_ok = 0;
        Opt *ok = malloc(n_all * sizeof *ok);
        for (int j = 0; j < n_all; j++) {
            if (restrict_last && items[i].kind != PIECE && all[j].sq >= 0 &&
                !(last_sq[all[j].sq >> 6] >> (all[j].sq & 63) & 1))
                continue;                            /* the last piece must light what is missing */
            int m = apply(&items[i], &all[j], pl, n);
            eval(pl, m);
            if (viable(pl, m)) { ok[n_ok] = all[j]; ok[n_ok++].score = score; }
            unapply(&items[i], &all[j]);
            RESTORE();
        }
        if (n_best < 0 || n_ok < n_best) {
            n_best = n_ok; chosen = i;
            memcpy(best, ok, n_ok * sizeof *ok);
        }
        free(ok);
    }
    if (ordering)                                    /* closest to lighting every target first */
        for (int i = 1; i < n_best; i++)
            for (int j = i; j > 0 && best[j - 1].score > best[j].score; j--) { Opt t = best[j]; best[j] = best[j - 1]; best[j - 1] = t; }
    if (ptest) {
        eval(pl, n);
        set_board(pl, n);
        int n_all = options(&items[chosen], all, pl), in_all = 0, in_best = -1;
        for (int j = 0; j < n_all; j++) in_all |= matches(&items[chosen], &all[j], pl);
        for (int j = 0; j < n_best && in_best < 0; j++) if (matches(&items[chosen], &best[j], pl)) in_best = j;
        if (in_best < 0) ptest_fail(in_all ? "pruned" : "no such option", &items[chosen], pl, n);
        else {
            if (grade) {
                /* every other surviving option: how much search refutes it (or finds it wins) */
                long refute = 0;
                int deepest = 0, open_ends = 0, wins = 0;
                for (int j = 0; j < n_best && !cut_short; j++) {
                    if (j == in_best) continue;
                    eval(pl, n);
                    int m = apply(&items[chosen], &best[j], pl, n);
                    long n0 = nodes;
                    int d0 = sdepth;
                    ptest = 0; quiet = 1; sub_wins = 0; sub_maxdepth = sdepth; node_limit = nodes + grade_budget;
                    search(pl, m);
                    ptest = 1; quiet = 0; node_limit = -1;
                    int hit_limit = cut_short && now() <= deadline;
                    if (hit_limit) cut_short = 0;
                    refute += nodes - n0;
                    if (sub_maxdepth - d0 > deepest) deepest = sub_maxdepth - d0;
                    open_ends += hit_limit && !sub_wins;
                    wins += sub_wins > 0;
                    unapply(&items[chosen], &best[j]);
                    RESTORE();
                }
                printf("grade placed=%d left=%d item=%d options=%d rank=%d refute_nodes=%ld refute_depth=%d open=%d wins=%d\n",
                       n, pieces_left(), items[chosen].kind, n_best, in_best, refute, deepest, open_ends, wins);
            }
            best[0] = best[in_best]; n_best = 1;
        }
    }
    if (n < 64) { depth_nodes[n]++; depth_branch[n] += n_best; }
    for (int j = 0; j < n_best && !cut_short; j++) {
        eval(pl, n);                                 /* piece_at for apply */
        int m = apply(&items[chosen], &best[j], pl, n);
        search(pl, m);
        unapply(&items[chosen], &best[j]);
        RESTORE();
    }
#undef RESTORE
    free(items); free(all); free(best); free(raw);
}

/* The search recurses once per decision, and some levels need very deep recursion: run
 * it on a thread with a large stack (reserved, only used as far as needed). */
static Placement root_pl[MAXP];

static void *search_thread(void *arg) { (void)arg; search(root_pl, 0); return NULL; }

static void run_search(void) {
    pthread_attr_t attr;
    pthread_t th;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, (size_t)1 << 30);
    if (pthread_create(&th, &attr, search_thread, NULL)) search(root_pl, 0);
    else pthread_join(th, NULL);
    pthread_attr_destroy(&attr);
}

int main(void) {
    char line[256];
    memset(TEMPLATE, 0, sizeof TEMPLATE);
    while (fgets(line, sizeof line, stdin)) {
        int t, x, y, d, c, n;
        double secs;
        if (sscanf(line, "fixed %d %d %d %d %d", &t, &x, &y, &d, &c) == 5) {
            place_into(TEMPLATE, t, x, y, d, c); continue;
        }
        if (sscanf(line, "kind %d %d %d", &t, &c, &n) == 3) {
            kinds[n_kinds++] = (Kind){t, c, n}; continue;
        }
        if (sscanf(line, "rounds %d", &rounds) == 1) continue;
        if (sscanf(line, "lookahead %d", &lookahead) == 1) continue;
        if (sscanf(line, "ordering %d", &ordering) == 1) continue;
        if (sscanf(line, "last %d", &last_check) == 1) continue;
        if (sscanf(line, "grade %ld", &grade_budget) == 1) { grade = 1; continue; }
        if (sscanf(line, "want %d %d %d %d %d", &t, &x, &y, &d, &c) == 5) {
            for (int k = 0; k < n_kinds; k++)
                if (kinds[k].type == t && kinds[k].color == c && n_want < MAXP) want[n_want++] = (Placement){x, y, k, d};
            ptest = 1;
            continue;
        }
        if (sscanf(line, "bsolve %lf %d", &secs, &max_solutions) == 2) {
            if (pieces_left() >= MAXP || n_want >= MAXP) {
                printf("done shapes=0 complete=0 nodes=0 evals=0 monotone=0 too_many_pieces=1\n");
                return 0;
            }
            monotone = 1;
            for (int i = 0; i < CELLS; i++) {
                int ty = TEMPLATE[i].type;
                if (ty == 10) { targets[n_targets++] = i; target_at[i] = n_targets; }
                if (ty == 9 || ty == 15 || ty == 22) monotone = 0;
            }
            for (int k = 0; k < n_kinds; k++) {
                int ty = kinds[k].type;
                if (ty == 9 || ty == 15 || ty == 22) monotone = 0;
                if (is_teleporter(ty)) tele_kinds = 1;
            }
            memset(want_at, -1, sizeof want_at);
            if (ptest) {
                for (int i = 0; i < n_want; i++) want_at[want[i].y * N + want[i].x] = i;
                evaluate(want, n_want);
                printf("ptest: solution %s\n", won() ? "wins" : "DOES NOT WIN");
            }
            memcpy(B, TEMPLATE, sizeof B);
            rotation_classes();
            turn_tables();
            lazy = monotone;
            deadline = now() + secs;
            certain(1);
            run_search();
            if (getenv("BEAMSOLVE_STATS")) {
                for (int i = 0; i < 16; i++)
                    if (why[i][0] + why[i][1] + why[i][2] + why[i][3] + why[i][4])
                        fprintf(stderr, "left %2d: wrong colour %8ld final %8ld bound1 %8ld bound2 %8ld kept %8ld\n",
                                i, why[i][0], why[i][1], why[i][2], why[i][3], why[i][4]);
                for (int i = 0; i < 64 && depth_nodes[i]; i++)
                    fprintf(stderr, "%2d placed: %8ld branching nodes, %.2f children on average\n",
                            i, depth_nodes[i], (double)depth_branch[i] / depth_nodes[i]);
            }
            printf("done shapes=%d complete=%d nodes=%ld evals=%ld monotone=%d\n",
                   n_shapes, !cut_short, nodes, evals, monotone);
        }
    }
    return 0;
}
