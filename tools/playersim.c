/* A model of a human player, for estimating how hard a level feels (see playersim.py).
 *
 * The player places pieces one at a time where light already passes (or, for a mobile
 * teleporter, on a line beyond a lit teleporter), and always tries the move that looks best
 * first. "Looks best" is a score of the board after the move:
 *   + targets lit with exactly their colour,
 *   + (less) targets lit with part of their colour (a mix still being built),
 *   - targets lit with a colour they can't use, and black targets lit at all,
 *   + (a little) unsatisfied targets in sight of a lit free square: one more piece could reach them.
 * When a line of moves runs out of pieces without winning, the player backs up and tries the
 * next-best move: a depth-first search in that order, counting every board looked at. Easy
 * levels are solved by mostly first choices; a level whose solution starts with moves that look
 * worse than others, or that gives no guidance, costs many boards. The count is cut at a budget.
 *
 * Input: the fastsim lines (fixed, kind), then
 *   weights W_CORRECT W_PARTIAL W_WRONG W_SIGHT W_URGENT    (optional)
 *   play BUDGET            -> "play found=F evals=E expansions=X first=K"
 * where first is how many of the winning line's moves were the top-ranked move at their step.
 *   want TYPE X Y DIR COLOR   (one per solution piece), then
 *   follow                 -> "follow steps=S bits=B maxrank=M notfirst=K hidden=H"
 * follows the solution instead of searching: at each step the player's moves are ranked, and the
 * best-ranked move that is part of the solution is played. bits = sum of log2(rank): how many
 * better-looking wrong moves the right one had to beat. A solution piece that is never among the
 * player's moves (it stands where no light passes yet) is placed last and counts as hidden.
 */
#define FASTSIM_LIB
#include "fastsim.c"
#include <math.h>

static double w_correct = 4, w_partial = 2, w_wrong = 4, w_sight = 1, w_urgent = 8;
static long budget;
static long expansions;
static int found, first_choices;
static Set seen_p;

static int transparent(int t) { return t == 0 || t == 10 || t == 21; }

static int lit_of(const Cell *c) {
    int l = 0;
    for (int d = 0; d < 8; d++) l |= c->inc[d];
    return l;
}

/* Per target cell: the number of lit free squares in sight of it (ways a single piece could
 * bring it light), and its state (0 unlit/wrong, 1 partial, 2 exactly right). */
static int ways[CELLS], state[CELLS];

static void survey(void) {
    for (int i = 0; i < CELLS; i++) {
        if (B[i].type != 10) continue;
        int c = B[i].color, l = lit_of(&B[i]);
        state[i] = l == c ? 2 : (l && !(l & ~c)) ? 1 : 0;
        int x0 = i % N, y0 = i / N, w = 0;
        for (int d = 0; d < 8; d++)
            for (int x = x0 + DX[d], y = y0 + DY[d]; x >= 0 && x < N && y >= 0 && y < N; x += DX[d], y += DY[d]) {
                Cell *q = AT(x, y);
                if (!transparent(q->type)) break;
                if (q->type == 0 && lit_of(q)) w++;
            }
        ways[i] = w;
    }
}

/* How much the board after a move relieves targets that had few ways to be lit before it:
 * a player deals with the most constrained target first. */
static double urgency(void) {
    double u = 0;
    for (int i = 0; i < CELLS; i++) {
        if (B[i].type != 10 || B[i].color == 0 || state[i] == 2) continue;
        int c = B[i].color, l = lit_of(&B[i]);
        int st = l == c ? 2 : (l && !(l & ~c)) ? 1 : 0;
        if (st > state[i]) u += 1.0 / (ways[i] ? ways[i] : 1);
    }
    return u;
}

static double score_board(void) {
    int correct = 0, partial = 0, wrong = 0, sight = 0;
    for (int i = 0; i < CELLS; i++) {
        if (B[i].type != 10) continue;
        int c = B[i].color, l = lit_of(&B[i]);
        if (c == 0) { wrong += l != 0; continue; }
        if (l == c) { correct++; continue; }
        if (l && !(l & ~c)) partial++;
        else if (l) { wrong++; continue; }
        int x0 = i % N, y0 = i / N, seen_lit = 0;
        for (int d = 0; d < 8 && !seen_lit; d++) {
            int x = x0 + DX[d], y = y0 + DY[d];
            while (x >= 0 && x < N && y >= 0 && y < N) {
                Cell *q = AT(x, y);
                if (!transparent(q->type)) break;
                if (q->type == 0 && lit_of(q)) { seen_lit = 1; break; }
                x += DX[d]; y += DY[d];
            }
        }
        sight += seen_lit;
    }
    return w_correct * correct + w_partial * partial - w_wrong * wrong + w_sight * sight;
}

typedef struct { Placement p; double score, key; int order; } Move;

static int by_score(const void *a, const void *b) {
    const Move *x = a, *y = b;
    if (x->key != y->key) return x->key < y->key ? 1 : -1;
    return x->order - y->order;
}

static int has_mobile_teleporter(void) {
    for (int k = 0; k < n_kinds; k++) if (kinds[k].count && kinds[k].type == 18) return 1;
    return 0;
}

/* B holds the board for pl[0..n), whose score is `now_score`; `stall` moves in a row have not
 * improved the score. Returns 1 when a win was found below. */
static int patience;
static int play(Placement *pl, int n, double now_score, int stall) {
    if (found || evals >= budget) return 0;
    if (won()) { found = 1; return 1; }
    int any = 0;
    for (int k = 0; k < n_kinds; k++) any |= kinds[k].count;
    if (!any) return 0;
    expansions++;
    char mark[CELLS];
    memset(mark, 0, sizeof mark);
    for (int i = 0; i < CELLS; i++) if (B[i].type == 0 && lit_of(&B[i])) mark[i] = 1;
    if (has_mobile_teleporter()) {
        for (int i = 0; i < CELLS; i++) {
            if ((B[i].type != 12 && B[i].type != 18) || !lit_of(&B[i])) continue;
            for (int d = 0; d < 8; d++)
                for (int x = i % N + DX[d], y = i / N + DY[d]; x >= 0 && x < N && y >= 0 && y < N; x += DX[d], y += DY[d])
                    if (AT(x, y)->type == 0) mark[y * N + x] = 1;
        }
    }
    survey();
    int n_sq = 0, squares[CELLS];
    for (int i = 0; i < CELLS; i++) if (mark[i]) squares[n_sq++] = i;
    Move *moves = malloc(sizeof(Move) * (n_sq * n_kinds * 8 + 1));
    int n_m = 0;
    for (int s = 0; s < n_sq; s++)
        for (int k = 0; k < n_kinds; k++) {
            if (!kinds[k].count) continue;
            uint64_t fields[8];
            int n_f = 0;
            for (int d = 0; d < 8; d++) {
                pl[n] = (Placement){squares[s] % N, squares[s] / N, k, d};
                uint64_t key = placement_key(pl, n + 1);
                if (!set_add(&seen_p, key)) continue;
                evaluate(pl, n + 1);
                uint64_t f = field_hash();
                int dup = 0;
                for (int i = 0; i < n_f; i++) dup |= fields[i] == f;
                if (dup) continue;           /* a turn that changes no light is the same move */
                fields[n_f++] = f;
                double sc = score_board();
                moves[n_m] = (Move){pl[n], sc, sc + w_urgent * urgency(), n_m};
                n_m++;
                if (evals >= budget) goto done;
            }
        }
done:
    qsort(moves, n_m, sizeof(Move), by_score);
    int win = 0;
    for (int m = 0; m < n_m && !found && evals < budget; m++) {
        int st = moves[m].score > now_score ? 0 : stall + 1;
        if (st > patience) continue;          /* the player gives up on lines that stop improving */
        pl[n] = moves[m].p;
        kinds[pl[n].kind].count--;
        evaluate(pl, n + 1);
        if (play(pl, n + 1, moves[m].score, st)) { win = 1; first_choices += m == 0; }
        kinds[pl[n].kind].count++;
    }
    free(moves);
    return win;
}

typedef struct { int type, x, y, d, color, used; } Want;
static Want want[64];
static int n_want;

static void follow(void) {
    Placement pl[128];
    int n = 0, hidden = 0, notfirst = 0, steps = 0;
    double maxrank = 0;
    double bits = 0;
    evaluate(pl, 0);
    for (;;) {
        if (won()) break;
        int left = 0;
        for (int w = 0; w < n_want; w++) left += !want[w].used;
        if (!left) break;
        double now_score = score_board();
        (void)now_score;
        survey();
        /* the player's candidate moves, as in play() but without the seen-set */
        char mark[CELLS];
        memset(mark, 0, sizeof mark);
        for (int i = 0; i < CELLS; i++) if (B[i].type == 0 && lit_of(&B[i])) mark[i] = 1;
        if (has_mobile_teleporter())
            for (int i = 0; i < CELLS; i++) {
                if ((B[i].type != 12 && B[i].type != 18) || !lit_of(&B[i])) continue;
                for (int d = 0; d < 8; d++)
                    for (int x = i % N + DX[d], y = i / N + DY[d]; x >= 0 && x < N && y >= 0 && y < N; x += DX[d], y += DY[d])
                        if (AT(x, y)->type == 0) mark[y * N + x] = 1;
            }
        int cap = 0;
        for (int i = 0; i < CELLS; i++) cap += mark[i];
        Move *moves = malloc(sizeof(Move) * (cap * n_kinds * 8 + 1));
        int *which = malloc(sizeof(int) * (cap * n_kinds * 8 + 1));
        int n_m = 0;
        for (int i = 0; i < CELLS; i++) {
            if (!mark[i]) continue;
            for (int k = 0; k < n_kinds; k++) {
                if (!kinds[k].count) continue;
                /* the field of the solution's own turn here, if a wanted piece of this kind stands here */
                int wi = -1;
                for (int w = 0; w < n_want; w++)
                    if (!want[w].used && want[w].x == i % N && want[w].y == i / N &&
                        want[w].type == kinds[k].type && want[w].color == kinds[k].color) wi = w;
                uint64_t wf = 0;
                if (wi >= 0) {
                    pl[n] = (Placement){i % N, i / N, k, want[wi].d};
                    evaluate(pl, n + 1);
                    wf = field_hash();
                }
                uint64_t fields[8];
                int n_f = 0;
                for (int d = 0; d < 8; d++) {
                    pl[n] = (Placement){i % N, i / N, k, d};
                    evaluate(pl, n + 1);
                    uint64_t f = field_hash();
                    int dup = 0;
                    for (int j = 0; j < n_f; j++) dup |= fields[j] == f;
                    if (dup) continue;
                    fields[n_f++] = f;
                    double sc = score_board();
                    moves[n_m] = (Move){pl[n], sc, sc + w_urgent * urgency(), n_m};
                    which[n_m] = wi >= 0 && f == wf ? wi : -1;
                    n_m++;
                }
            }
        }
        /* rank: 1 + the moves that look better than the best right one + half of those that look
         * just as good (a player picks among equals at random) */
        int best = -1;
        for (int m = 0; m < n_m; m++)
            if (which[m] >= 0 && (best < 0 || moves[m].key > moves[best].key)) best = m;
        if (best < 0) {                      /* no solution piece can be placed in the light */
            for (int w = 0; w < n_want; w++) if (!want[w].used) {
                for (int k = 0; k < n_kinds; k++)
                    if (kinds[k].count && kinds[k].type == want[w].type && kinds[k].color == want[w].color) {
                        pl[n++] = (Placement){want[w].x, want[w].y, k, want[w].d};
                        kinds[k].count--; want[w].used = 1; hidden++; break;
                    }
                break;
            }
            free(moves); free(which);
            evaluate(pl, n);
            continue;
        }
        double rank = 1;
        for (int m = 0; m < n_m; m++)
            if (m != best && which[m] < 0) rank += moves[m].key > moves[best].key ? 1 : moves[m].key == moves[best].key ? 0.5 : 0;
        bits += log2(rank);
        if (rank > maxrank) maxrank = rank;
        notfirst += rank >= 2;
        steps++;
        pl[n] = moves[best].p;
        pl[n].d = want[which[best]].d;       /* rotations giving this same light: the solution's, for later beams */
        kinds[pl[n].kind].count--;
        want[which[best]].used = 1;
        n++;
        free(moves); free(which);
        evaluate(pl, n);
    }
    printf("follow steps=%d bits=%.2f maxrank=%.1f notfirst=%d hidden=%d won=%d\n", steps, bits, maxrank,
           notfirst, hidden, won());
}

int main(void) {
    char line[256];
    memset(TEMPLATE, 0, sizeof TEMPLATE);
    while (fgets(line, sizeof line, stdin)) {
        int t, x, y, d, c, n;
        if (sscanf(line, "fixed %d %d %d %d %d", &t, &x, &y, &d, &c) == 5) { place_into(TEMPLATE, t, x, y, d, c); continue; }
        if (sscanf(line, "kind %d %d %d", &t, &c, &n) == 3) { kinds[n_kinds++] = (Kind){t, c, n}; continue; }
        if (sscanf(line, "weights %lf %lf %lf %lf %lf", &w_correct, &w_partial, &w_wrong, &w_sight, &w_urgent) == 5) continue;
        if (sscanf(line, "want %d %d %d %d %d", &t, &x, &y, &d, &c) == 5) { want[n_want++] = (Want){t, x, y, d, c, 0}; continue; }
        if (!strncmp(line, "follow", 6)) { follow(); continue; }
        if (sscanf(line, "play %ld", &budget) == 1) {
            Placement pl[128];
            /* the player first tries only moves that look like progress, then allows more and
             * more moves in a row that don't, until the level is solved or the budget is spent */
            for (patience = 0; patience <= 12 && !found && evals < budget; patience++) {
                free(seen_p.k); seen_p = (Set){0};
                evaluate(pl, 0);
                play(pl, 0, score_board(), 0);
            }
            printf("play found=%d evals=%ld expansions=%ld first=%d patience=%d\n", found, evals, expansions,
                   first_choices, patience - 1);
        }
    }
    return 0;
}
