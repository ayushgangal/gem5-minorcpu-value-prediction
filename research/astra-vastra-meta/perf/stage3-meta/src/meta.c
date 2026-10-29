/*
 * Workloads for the META selection tests (run_meta.sh).  Freestanding RV64G,
 * SE mode.  WORK selects the kernel; every kernel is a loop of laps, with a
 * warm-up of WARM laps before the region of interest of ROI laps (delimited
 * by the gem5 pseudo-instructions m5_reset_stats / m5_dump_stats).  The
 * output is a checksum.
 *
 * Chain kernels (1-5) walk four dependent loads per lap
 *
 *     P: ld t1,0(a0')   C: ld t2,0(t1)   E: ld t3,0(t2)   F: ld t4,0(t3)
 *
 * after four conflicting stores to the L1 set of every hot line (addresses
 * 16 KiB apart: same L1D set, same V$ index, another tag) and a fence: the
 * conflict stores evict the hot lines from the 4-way L1D without changing a
 * V$ entry (another tag), so every chain load is an L1 miss that hits the L2
 * (latency bound, no delay loop) while the V$ keeps the hot words.
 *
 *  1 stable    the same four addresses and values every lap.  V-ASTRA bypasses
 *              P (it is the oldest instruction in flight), LVP is confident
 *              too: V-ASTRA is pending when LVP could serve
 *  2 vcmiss    the chain lines are 4096 bytes apart: one V$ index, so each
 *              load replaces the V$ entry of the previous one and V-ASTRA
 *              falls back on a V$ tag miss; LVP sees stable values
 *  3 stableflip as 1, but every 32 laps the pointer P reads flips to a copy of
 *              the next node: LVP is wrong once after each flip, while the V$
 *              holds the new value (the flipping store retired long before)
 *  4 vcflip    as 2 with the same flips: LVP is wrong at each flip, V-ASTRA is
 *              never available (the existing LVP recovery squash)
 *  5 none      P's base is one of 8 lines picked by an LCG and every line holds
 *              another pointer: neither the base nor the value is predictable
 *
 * Forwarding kernels (6, 7): per lap a load M of a cold line (DRAM) holds the
 * head of the in-flight queue, P loads a pointer from one of 32 hot slots (V$
 * and L1 hits, stride 64 for ASTRA) and C loads from the cold line it points
 * to.  Without forwarding C waits for M to commit and then misses to DRAM too;
 * with it C's request is sent while M is outstanding.  No delay loop: laps
 * are memory latency bound.  P's value changes every lap, so LVP is never
 * confident.
 *
 *  6 fwdcold   that kernel alone
 *  7 mixed     the vcmiss chain (LVP) followed by the fwdcold kernel
 *              (V-ASTRA) in each lap: each source serves one of them
 *  9 fwdboth   an older cold load M holds the head; P reads one constant
 *              pointer (V$ hit, LVP confident) and C, E follow it (constant
 *              too): P's value is published and C, E are forwarded while LVP
 *              also has a prediction for each of them
 * 10 fwdflip   as 9, but every 32 laps the pointer P reads flips to a copy
 *              of the next node (the store retires before the next lap):
 *              LVP is wrong at P after each flip, the V$ holds the new value
 *  8 pdstore   the stable chain preceded in each lap by a store to a cold line
 *              (a write miss): the older store holds P's send, so P is the
 *              oldest instruction in flight and outstanding while its V-ASTRA
 *              record is still pending and its LVP prediction is confident
 */
#define SYS_write 64
#define SYS_exit_group 94

#ifndef WORK
#define WORK 1
#endif
#ifndef WARM
#define WARM 100
#endif
#ifndef ROI
#define ROI 200
#endif

typedef unsigned long u64;

static unsigned char big[7 * 16384] __attribute__((aligned(16384)));
/* the 32 slots of the forwarding kernels: lines 8..39 of the first 4 KiB
 * (L1 sets 8..39, none of those the chain uses), P reads 16 bytes into the
 * line (V$ index = 1 mod 4) */
static unsigned char slots[4096] __attribute__((aligned(4096)));
/* two 1 MiB regions of cold lines (M's and C's); a line's V$ index is 2 mod
 * 4 (offset 32 into the line), distinct from the slots' and the chain's */
static unsigned char farbuf[2 << 20] __attribute__((aligned(4096)));

static long
sys3(long num, long a0, long a1, long a2)
{
    register long x17 __asm__("a7") = num;
    register long x10 __asm__("a0") = a0;
    register long x11 __asm__("a1") = a1;
    register long x12 __asm__("a2") = a2;

    __asm__ volatile("ecall" : "+r"(x10) : "r"(x17), "r"(x11), "r"(x12)
                     : "memory");
    return x10;
}

static void
print_checksum(long value)
{
    char b[40];
    int pos = sizeof(b);
    unsigned long v = (unsigned long)value;

    b[--pos] = '\n';
    do {
        b[--pos] = '0' + v % 10;
        v /= 10;
    } while (v != 0);
    sys3(SYS_write, 1, (long)"checksum ", 9);
    sys3(SYS_write, 1, (long)(b + pos), sizeof(b) - pos);
}

#define M5_RESET() __asm__ volatile("mv a0,zero\n\tmv a1,zero\n\t" \
                                    ".long 0x8000007b" ::: "a0", "a1", "memory")
#define M5_DUMP() __asm__ volatile("mv a0,zero\n\tmv a1,zero\n\t" \
                                   ".long 0x8200007b" ::: "a0", "a1", "memory")

/* conflict stores for line j of the hot window: four lines 16 KiB apart */
#define POLL(j)                                                      \
    "\tsd zero," #j "*64(a2)\n\tsd zero," #j "*64(a3)\n"             \
    "\tsd zero," #j "*64(a4)\n\tsd zero," #j "*64(a5)\n"
#define POLLV(off)                                                   \
    "\tlui t0," #off "\n\tadd t1,a2,t0\n\tadd t2,a3,t0\n"           \
    "\tadd t3,a4,t0\n\tadd t4,a5,t0\n"                              \
    "\tsd zero,0(t1)\n\tsd zero,0(t2)\n\tsd zero,0(t3)\n\tsd zero,0(t4)\n"
#define FENCE "\tfence rw,rw\n"

/* kern(base, laps, far, k0): a0 = base, a1 = laps, a2 = far, a3 = lap index */
#define PROLOGUE                                                     \
    "\taddi sp,sp,-32\n\tsd s0,0(sp)\n\tsd s1,8(sp)\n\tsd s2,16(sp)\n" \
    "\tmv s0,a2\n\tmv s1,a3\n\tmv s2,a0\n"                           \
    "\tli t5,16384\n\tadd a2,a0,t5\n\tadd a3,a2,t5\n"                \
    "\tadd a4,a3,t5\n\tadd a5,a4,t5\n\tli a7,0\n"
#define EPILOGUE                                                     \
    "\tmv a0,a7\n\tld s0,0(sp)\n\tld s1,8(sp)\n\tld s2,16(sp)\n"     \
    "\taddi sp,sp,32\n\tret\n"

#define CHAIN                                                        \
    ".globl k_P\nk_P:\n\tld t1,0(a0)\n"                              \
    ".globl k_C\nk_C:\n\tld t2,0(t1)\n"                              \
    ".globl k_E\nk_E:\n\tld t3,0(t2)\n"                              \
    ".globl k_F\nk_F:\n\tld t4,0(t3)\n"                              \
    "\tadd a7,a7,t4\n"

/* flip the pointer P reads every 32 laps: a6 holds the pointer now, t6 is
 * the xor of the two copies; the (unconditional) store retires long before
 * the next lap's chain */
#define FLIP                                                         \
    "\tandi t0,a1,31\n\tseqz t0,t0\n\tneg t0,t0\n\tand t0,t0,t6\n"  \
    "\txor a6,a6,t0\n\tsd a6,0(a0)\n"

/* the forwarding kernel: s0 = far, s1 = lap index k, s2 = chain base (the
 * slots are at s2 - nothing: they are reached through the slots array
 * passed in a0 of the C wrapper, see FWD_SLOTS).  M is far + (k * 40503 mod
 * 16384) * 64 + 32; the slot of lap k is slot[k mod 32]; it is refilled
 * after use with the pointer for lap k + 32: far + 1 MiB + ((k + 32) * 12347
 * mod 16384) * 64 + 32 */
#define FWD_SEG(BASE)                                                \
    "\tli t5,40503\n\tmul t5,s1,t5\n\tli t6,16383\n\tand t5,t5,t6\n" \
    "\tslli t5,t5,6\n\tadd a6,s0,t5\n\taddi a6,a6,32\n"              \
    "\tandi t6,s1,31\n\tslli t6,t6,6\n\tadd t6,t6," BASE "\n"        \
    "\taddi t6,t6,528\n"                                             \
    "\taddi t5,s1,32\n\tli t4,12347\n\tmul t5,t5,t4\n"               \
    "\tli t4,16383\n\tand t5,t5,t4\n\tslli t5,t5,6\n\tadd t5,t5,s0\n" \
    "\tli t4,1048576\n\tadd t5,t5,t4\n\taddi t5,t5,32\n"             \
    ".globl f_M\nf_M:\n\tld t0,0(a6)\n"                              \
    ".globl f_P\nf_P:\n\tld t1,0(t6)\n"                              \
    ".globl f_C\nf_C:\n\tld t2,0(t1)\n"                              \
    "\tadd a7,a7,t2\n\tadd a7,a7,t0\n\tadd a7,a7,t1\n"                  \
    "\tsd t5,0(t6)\n\taddi s1,s1,1\n"

#if WORK == 1
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "1:\n" POLL(0) POLL(1) POLL(2) POLL(3) FENCE CHAIN
        "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#elif WORK == 2
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "1:\n" POLL(0) POLLV(1) POLLV(2) POLLV(3) FENCE CHAIN
        "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#elif WORK == 3
/* lines: A = 0 (P's pointer), B0 = 1, B1 = 4 (same next pointer), C = 2,
 * D = 3 */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "\taddi a6,a0,64\n\taddi t0,a0,256\n\txor t6,a6,t0\n"
        "\tld a6,0(a0)\n"
        "1:\n" POLL(0) POLL(1) POLL(4) POLL(2) POLL(3) FENCE CHAIN
        FLIP "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#elif WORK == 4
/* A = 0, B0 = 4096, C = 8192, D = 12288, B1 = 81920 (the same V$ index as
 * every chain line, and not a line the conflict stores write) */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "\tlui t0,1\n\tadd a6,a0,t0\n\tlui t0,20\n\tadd t0,a0,t0\n"
        "\txor t6,a6,t0\n\tld a6,0(a0)\n"
        "1:\n" POLL(0) POLLV(1) POLLV(2) POLLV(3) FENCE CHAIN
        FLIP "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#elif WORK == 5
/* P lines 8..15 (each holds a pointer to the B line 16 + r), B lines hold a
 * pointer to the D line 24 + r (value); r from bits 40-42 of a 64-bit LCG */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "\tli a6,1\n\tli t6,6364136223846793005\n"
        "1:\n" POLL(8) POLL(9) POLL(10) POLL(11) POLL(12) POLL(13) POLL(14)
        POLL(15) POLL(16) POLL(17) POLL(18) POLL(19) POLL(20) POLL(21)
        POLL(22) POLL(23) POLL(24) POLL(25) POLL(26) POLL(27) POLL(28)
        POLL(29) POLL(30) POLL(31) FENCE
        "\tmul a6,a6,t6\n\taddi a6,a6,1\n\tsrli t5,a6,40\n\tandi t5,t5,7\n"
        "\tslli t5,t5,6\n\tadd t5,t5,a0\n\taddi t5,t5,512\n"
        ".globl k_P\nk_P:\n\tld t1,0(t5)\n"
        ".globl k_C\nk_C:\n\tld t2,0(t1)\n"
        ".globl k_E\nk_E:\n\tld t3,0(t2)\n"
        "\tadd a7,a7,t3\n"
        "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#elif WORK == 6
/* kern(slots, laps, far, k0): the slots are the base (a0 -> s2) */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "1:\n" FWD_SEG("s2")
        "\taddi a1,a1,-1\n\tbnez a1,1b\n"
        "\tmv a0,a7\n\tmv a2,s1\n\tld s0,0(sp)\n\tld s1,8(sp)\n"
        "\tld s2,16(sp)\n\taddi sp,sp,32\n\tret\n");
#elif WORK == 9 || WORK == 10
/* a0 = chain base: line 0 = P's pointer cell, 1 = B0, 4 = B1 (same next
 * pointer), 2 = C's cell, 3 = D.  kern(base, laps, far, k0) */
#if WORK == 10
#define FWDB_FLIP                                                    \
    "\tandi t0,s1,31\n\tbnez t0,2f\n"                                \
    "\txor a4,a4,a3\n\tsd a4,0(a0)\n\tfence rw,rw\n2:\n"
#else
#define FWDB_FLIP ""
#endif
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "\taddi a3,a0,64\n\taddi t0,a0,256\n\txor a3,a3,t0\n\tld a4,0(a0)\n"
        "1:\n"
        "\tli t5,40503\n\tmul t5,s1,t5\n\tli t6,16383\n\tand t5,t5,t6\n"
        "\tslli t5,t5,6\n\tadd a6,s0,t5\n\taddi a6,a6,32\n"
        ".globl f_M\nf_M:\n\tld t0,0(a6)\n"
        ".globl f_P\nf_P:\n\tld t1,0(a0)\n"
        ".globl f_C\nf_C:\n\tld t2,0(t1)\n"
        ".globl f_E\nf_E:\n\tld t3,0(t2)\n"
        "\tadd a7,a7,t3\n\tadd a7,a7,t0\n\tadd a7,a7,t1\n"
        "\taddi s1,s1,1\n" FWDB_FLIP
        "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#elif WORK == 8
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "1:\n" POLL(0) POLL(1) POLL(2) POLL(3) FENCE
        "\tli t5,40503\n\tmul t5,s1,t5\n\tli t6,16383\n\tand t5,t5,t6\n"
        "\tslli t5,t5,6\n\tadd t5,t5,s0\n\taddi t5,t5,32\n\taddi s1,s1,1\n"
        ".globl k_S\nk_S:\n\tsd zero,0(t5)\n" CHAIN
        "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#else
/* the vcmiss chain, then the forwarding kernel: kern(big, laps, far, k0);
 * the slots are at big + 65536 + 4096 (past the last conflict line), the
 * chain's hot lines as in WORK 2 */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "\tli t5,69632\n\tadd s2,s2,t5\n"
        "1:\n" POLL(0) POLLV(1) POLLV(2) POLLV(3) FENCE CHAIN
        FWD_SEG("s2")
        "\taddi a1,a1,-1\n\tbnez a1,1b\n" EPILOGUE);
#endif

extern long kern(void *base, long laps, void *far, long k0);

static void
put(int line, u64 v)
{
    *(volatile u64 *)(big + 64 * line) = v;
}

#define LINE(j) ((u64)(big + 64 * (j)))

/* warm the slots (V$ and L1) and fill them with the pointers for the first
 * 32 laps */
static void
init_slots(unsigned char *s)
{
    for (int i = 0; i < 32; i++) {
        u64 idx = ((u64)i * 12347) & 16383;

        *(volatile u64 *)(s + 528 + 64 * i) =
            (u64)(farbuf + (1 << 20) + idx * 64 + 32);
    }
    for (int i = 0; i < 32; i++)
        (void)*(volatile u64 *)(s + 528 + 64 * i);
}

void
_start(void)
{
    long t = 0;
    void *base = big;

#if WORK == 1
    put(0, LINE(1)); put(1, LINE(2)); put(2, LINE(3)); put(3, 0x1234567UL);
#elif WORK == 2
    put(0, LINE(64)); put(64, LINE(128)); put(128, LINE(192));
    put(192, 0x13579bdfUL);
#elif WORK == 3
    put(0, LINE(1)); put(1, LINE(2)); put(4, LINE(2)); put(2, LINE(3));
    put(3, 0x2468ace0UL);
#elif WORK == 4
    put(0, LINE(64)); put(64, LINE(128)); put(1280, LINE(128));
    put(128, LINE(192)); put(192, 0x13579bdfUL);
#elif WORK == 5
    for (int r = 0; r < 8; r++) {
        put(8 + r, LINE(16 + r));
        put(16 + r, LINE(24 + r));
        put(24 + r, 0x1111UL * (r + 1));
    }
#elif WORK == 9 || WORK == 10
    put(0, LINE(1)); put(1, LINE(2)); put(4, LINE(2)); put(2, LINE(3));
    put(3, 0x1234567UL);
#elif WORK == 8
    put(0, LINE(1)); put(1, LINE(2)); put(2, LINE(3)); put(3, 0x1234567UL);
#elif WORK == 6
    init_slots(slots);
    base = slots;
#else
    put(0, LINE(64)); put(64, LINE(128)); put(128, LINE(192));
    put(192, 0x13579bdfUL);
    init_slots(big + 65536 + 4096);
#endif

    long k = 0;

#if WORK >= 6
    if (WARM > 0) {
        t += kern(base, WARM, farbuf, k);
        k += WARM;
    }
    M5_RESET();
    t += kern(base, ROI, farbuf, k);
    M5_DUMP();
#else
    if (WARM > 0)
        t += kern(base, WARM, farbuf, 0);
    M5_RESET();
    t += kern(base, ROI, farbuf, 0);
    M5_DUMP();
#endif
    (void)k;

    print_checksum(t);
    sys3(SYS_exit_group, 0, 0, 0);
    for (;;)
        ;
}
