# Stall-on-use baseline variant (`configs/research/vp_stall_on_use.py`)

Prerequisite of Design A (validated scoreboard release) of
`ISSUE_TIME_VASTRA_DESIGN.md`: a configuration in which a load's dependents
cannot issue before the load's result is available through the existing MinorCPU
model, which is the paper's baseline behaviour.

## What it is
`configs/research/vp_stall_on_use.py` runs `configs/research/vp_baseline.py`
unchanged (`runpy`) and, just before `m5.instantiate()`, replaces
`system.cpu.executeFuncUnits` with a `MinorFUPool` that has the same functional
units in the same order as `MinorDefaultFUPool`, except that the memory FU's
`MinorFUTiming` has `extraAssumedLat=0` instead of `2`. Nothing else differs
(`config.ini` of the two runs differs in exactly that one line; see
`stage2c-stall-on-use/` artifacts). All options of the baseline work unchanged
(predictors are off unless asked for). Single CPU, single thread, SE mode.

| Setting | `vp_baseline.py` | `vp_stall_on_use.py` |
|---|---|---|
| Mem FU `extraAssumedLat` | 2 (Minor default) | **0** |
| everything else in `config.ini` | | identical |

## Why that parameter, and what it really does (source-grounded)
`Execute::issue` (execute.cc) marks a memory reference's destination registers:
`returnCycle = now + opLat + extraAssumedLat`, and
`numUnpredictableResults++` **only if `extraAssumedLat == 0`**.
`Scoreboard::canInstIssue` refuses to issue an instruction while a source register
has `numUnpredictableResults != 0`. The mark is cleared when the load leaves the
in-flight queue (`Execute::commit`: `scoreboard.clearInstDests(inst,
inst->isMemRef())`), i.e. at its in-order commit.
So with 0, dependents cannot issue before the load's commit, and, because
issue is strictly in order, **nothing younger than a stalled dependent issues
either**; instructions between the load and its first use keep issuing.

## What the traces show (`run_sou.sh`, `check_sou.py`)
The workload (`sou.c`) has long-latency loads (cold, non-strided lines) with a
dependent `D`, three independent instructions before it and one after it
(section A), and a variant with an older missing load `M` ahead of an L1-hit
load `L` (section B). Timing is read from `MinorExecute` and `MinorMem` traces
(iterations 1..11; iteration 0 runs cold code):

| | baseline | stall-on-use |
|---|---|---|
| A: `D` issue - `L` issue | 2 cycles | 109..455 cycles |
| A: `D` issue - `L` commit | -107..-465 (before the result) | **0** (same cycle as the load's commit) |
| A: instructions between `L` and `D` | issue at once | issue at once (before `L` commits) |
| A: `J` (independent, after `D`) | issues at once | held behind `D`: `J` issue >= `D` issue |
| B: `D` issue vs `L` data arrival (106..442 cycles earlier than `L`'s commit) | before the arrival | **at `L`'s commit, not at the arrival** |
| architectural output, committed instruction stream | identical | identical |

## Limitations (what this is not)
* The release is the load's **in-order commit**, not the arrival of its data
  (section B): an older miss that holds the head also holds the dependents of a
  younger load whose data is already there. That is stall-on-use in Minor's
  model, stricter than the paper's.
* Dependent loads cannot occupy the memory FU before their producer commits
  (they used to issue early and wait there), so load-load chains are slower
  than in the baseline; ALU dependents wait for the producer's commit and then
  take `opLat` (3 cycles in the Int FU).
* `numCycles` of the two configurations is reported as information only and
  must not be used as a criterion.
* Predictors are off in this characterization; Design A is not implemented.
* One FU pool is replaced; nothing in `src/` is changed.
