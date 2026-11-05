# Final-source regression

Every validation suite was run once against the final source revision.
Every suite passed with no failures.

| | |
|---|---|
| Source | `astra-vastra-dev` at `233c12dc0e` (later commits only add the report) |
| Binary | `build/RISCV/gem5.opt`, sha256 prefix `5f7d037c25c6c8cd` |
| Date | 2026-11-05, 16:16–17:02 IST (about 46 minutes) |
| Machine | lab machine `shakti1913`, Ubuntu 22.04, 32 cores, 62 GB RAM |
| Toolchain | RISC-V GCC 16.2.0 (C only, freestanding) and binutils 2.42, both built in the user's home directory |
| Runner | `~/final_regress.sh` on the lab machine, adapted from `drivers/run_all.sh` |

## Why GCC 16 was needed

Ubuntu 22.04 has GCC 11.4 and binutils 2.38, and neither works for these tests:

- every test links with `ld --no-relax-gp`, which binutils 2.38 does not accept (the option needs 2.41 or later);
- some checkers verify the generated code shape (for example, the number of loads in an ASTRA kernel), and those expectations were written against GCC 16.

All test compiles use `-nostdlib -ffreestanding`, so a C-only cross GCC 16 without a C library is enough. The reference laptop uses Fedora's GCC 16.2.1 snapshot. The lab machine used the official 16.2.0 release.

## Results

| Suite | Final source | Earlier run | Note |
|---|---:|---:|---|
| ASTRA | 78 | 78 | |
| ASTRA targeted | 340 | 340 | |
| Value cache | 157 | 157 | |
| V-ASTRA | 276 | 276 | |
| LVP main run | 473 | 473 | |
| LVP threshold / pcwindow / invalid-config / confidence / alias | 71 / 79 / 37 / 57 / 55 | same | 772 in total |
| Bypass (17 modes) | 297 | 297 | every mode matches |
| Stall-on-use | 17 | 17 | |
| Design A (config 2, directed 37, selftest 3, lifecycle 213) | 255 | 255 | |
| Design B (config 10, directed 64, lifecycle 201) | 275 | 275 | |
| Bypass drain / reset (8 programs × 14) | 112 | 112 | |
| META config | 25 | 25 | |
| META directed | 281 | 281 | |
| META lifecycle | 4,685 | 4,625 | +60, see below |
| META ASTRA–LVP | 8,996 | 8,780 | +216, see below |
| META alignment | 92 | 92 | |

FAIL = 0 and rc = 0 for every suite and driver.

## The two count differences

In both META lifecycle and ASTRA–LVP, every program matches the earlier run (`logs/hard-meta-lifecycle.log`, `logs/hard-astra-lvp.log.gz`) exactly, except `drain-ldld-phase` and `reset-ldld-phase`:

| Program | META lifecycle | ASTRA–LVP |
|---|---|---|
| drain-ldld-phase | 215 → 240 (+25) | 763 → 853 (+90) |
| reset-ldld-phase | 210 → 245 (+35) | 745 → 871 (+126) |

These drain and statistics-reset programs add a set of checks for each statistics window. The run produced more windows for these two programs, so more checks ran. All of them passed. The most likely cause is the slightly different compiler build, which changes the workload length. This changes coverage, not correctness.
