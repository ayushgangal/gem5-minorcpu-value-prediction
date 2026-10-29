/*
 * Latency-bound dependent-load kernels for the LVP versus ASTRA/V-ASTRA
 * comparison (Stage 2d).  Freestanding RV64G, SE mode.  WORK selects the
 * kernel; every kernel walks a chain of four dependent loads per lap
 *
 *     P: ld t1,0(Pbase)   C: ld t2,0(t1)   E: ld t3,0(t2)   F: ld t4,0(t3)
 *
 * (F loads the final value, added to a checksum), after storing to four
 * conflicting lines of the L1 set of every hot line (addresses 16 KiB apart:
 * same L1D set, same V$ index, another tag).  Stores do not allocate or
 * change a V$ entry with another tag, but four of them evict the hot line from
 * the 4-way L1D, so every chain load misses the L1 and hits the L2 (the loads
 * are latency bound; the V$ keeps the hot words).
 *
 *  WORK 1  stable    the same four addresses and values every lap: LVP
 *                    saturates, ASTRA predicts (stride 0), V$ hits
 *  WORK 2  randbase  P's base is one of 8 lines chosen by bits 40-42 of a
 *                    64-bit LCG (aperiodic over the run), all holding
 *                    the same pointer: LVP predicts P's value, ASTRA cannot
 *                    predict P's base (C, E, F are stable)
 *  WORK 4  vcmiss    as WORK 1 but the four chain lines are 4096 bytes apart:
 *                    they share one V$ index and replace each other, so
 *                    V-ASTRA never finds its bytes (V$ tag miss) while LVP
 *                    still sees stable values
 *  WORK 3  altvalue  P reads a pointer that alternates between two copies of
 *                    the next node every lap (a store flips it at the end of
 *                    the lap): P's value changes every lap (LVP never gets
 *                    confident at P), P's base is constant and C's base
 *                    alternates with a stride pattern ASTRA learns
 *
 * The region of interest is delimited by the gem5 pseudo-instructions
 * m5_reset_stats (before ROI laps) and m5_dump_stats (after); WARM laps run
 * before it.  Output: the checksum.
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

static unsigned char big[5 * 16384] __attribute__((aligned(16384)));

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

/* the fence drains the store buffer, so the conflicting lines are in the L1
 * (and the hot lines evicted) when the chain starts */
#define FENCE "\tfence rw,rw\n"

#define PROLOGUE                                                     \
    "\tli t5,16384\n\tadd a2,a0,t5\n\tadd a3,a2,t5\n"                \
    "\tadd a4,a3,t5\n\tadd a5,a4,t5\n\tli a7,0\n"

#if WORK == 1
/* hot lines: 0 = A, 1 = B, 2 = C, 3 = D (the value) */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "1:\n" POLL(0) POLL(1) POLL(2) POLL(3) FENCE
        ".globl k_P\nk_P:\n\tld t1,0(a0)\n"
        ".globl k_C\nk_C:\n\tld t2,0(t1)\n"
        ".globl k_E\nk_E:\n\tld t3,0(t2)\n"
        ".globl k_F\nk_F:\n\tld t4,0(t3)\n"
        "\tadd a7,a7,t4\n"
        "\taddi a1,a1,-1\n\tbnez a1,1b\n"
        "\tmv a0,a7\n\tret\n");
#elif WORK == 2
/* P lines 8..15 (all hold the pointer to B); B = 1, C = 2, D = 3 */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "\tli a6,1\n\tli t6,6364136223846793005\n"
        "1:\n" POLL(8) POLL(9) POLL(10) POLL(11) POLL(12) POLL(13) POLL(14)
        POLL(15) POLL(1) POLL(2) POLL(3) FENCE
        "\tmul a6,a6,t6\n\taddi a6,a6,1\n\tsrli t5,a6,40\n\tandi t5,t5,7\n"
        "\tslli t5,t5,6\n"
        "\tadd t5,t5,a0\n\taddi t5,t5,512\n"
        ".globl k_P\nk_P:\n\tld t1,0(t5)\n"
        ".globl k_C\nk_C:\n\tld t2,0(t1)\n"
        ".globl k_E\nk_E:\n\tld t3,0(t2)\n"
        ".globl k_F\nk_F:\n\tld t4,0(t3)\n"
        "\tadd a7,a7,t4\n"
        "\taddi a1,a1,-1\n\tbnez a1,1b\n"
        "\tmv a0,a7\n\tret\n");
#elif WORK == 4
/* A = 0, B = 4096, C = 8192, D = 12288: the four chain lines have the same V$
 * index, so each chain load replaces the V$ entry of the previous one (V$ tag
 * miss every time); their L1D sets differ, and the conflict lines of each
 * (hot + 16384 k) evict it as in the other kernels */
#define POLLV(off)                                                   \
    "\tlui t0," #off "\n\tadd t1,a2,t0\n\tadd t2,a3,t0\n"           \
    "\tadd t3,a4,t0\n\tadd t4,a5,t0\n"                              \
    "\tsd zero,0(t1)\n\tsd zero,0(t2)\n\tsd zero,0(t3)\n\tsd zero,0(t4)\n"
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "1:\n" POLL(0) POLLV(1) POLLV(2) POLLV(3) FENCE
        ".globl k_P\nk_P:\n\tld t1,0(a0)\n"
        ".globl k_C\nk_C:\n\tld t2,0(t1)\n"
        ".globl k_E\nk_E:\n\tld t3,0(t2)\n"
        ".globl k_F\nk_F:\n\tld t4,0(t3)\n"
        "\tadd a7,a7,t4\n"
        "\taddi a1,a1,-1\n\tbnez a1,1b\n"
        "\tmv a0,a7\n\tret\n");
#else
/* A = 0 (alternating pointer), B0 = 1, B1 = 4 (same next pointer), C = 2,
 * D = 3; a6 = the pointer A holds now, t6 = B0 xor B1 */
__asm__(".text\n.balign 64\n.globl kern\nkern:\n" PROLOGUE
        "\taddi a6,a0,64\n\taddi t0,a0,256\n\txor t6,a6,t0\n"
        "\tld a6,0(a0)\n"
        "1:\n" POLL(0) POLL(1) POLL(4) POLL(2) POLL(3) FENCE
        ".globl k_P\nk_P:\n\tld t1,0(a0)\n"
        ".globl k_C\nk_C:\n\tld t2,0(t1)\n"
        ".globl k_E\nk_E:\n\tld t3,0(t2)\n"
        ".globl k_F\nk_F:\n\tld t4,0(t3)\n"
        "\tadd a7,a7,t4\n"
        "\txor a6,a6,t6\n\tsd a6,0(a0)\n"
        "\taddi a1,a1,-1\n\tbnez a1,1b\n"
        "\tmv a0,a7\n\tret\n");
#endif

extern long kern(void *base, long laps);

static void
put(int line, u64 v)
{
    *(volatile u64 *)(big + 64 * line) = v;
}

#define LINE(j) ((u64)(big + 64 * (j)))

void
_start(void)
{
    long t = 0;

#if WORK == 1
    put(0, LINE(1)); put(1, LINE(2)); put(2, LINE(3)); put(3, 0x1234567UL);
#elif WORK == 4
    put(0, LINE(64)); put(64, LINE(128)); put(128, LINE(192));
    put(192, 0x13579bdfUL);
#elif WORK == 2
    for (int j = 8; j < 16; j++)
        put(j, LINE(1));
    put(1, LINE(2)); put(2, LINE(3)); put(3, 0x7654321UL);
#else
    put(0, LINE(1)); put(1, LINE(2)); put(4, LINE(2)); put(2, LINE(3));
    put(3, 0x2468ace0UL);
#endif
    if (WARM > 0)
        t += kern(big, WARM);
    M5_RESET();
    t += kern(big, ROI);
    M5_DUMP();

    print_checksum(t);
    sys3(SYS_exit_group, 0, 0, 0);
    for (;;)
        ;
}
