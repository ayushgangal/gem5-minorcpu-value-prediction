# ASTRA shadow predictor tests

Stage A of an implementation of V-ASTRA (Ravenel, Perais, Dupont de Dinechin,
Petrot, "Architecting Value Prediction around In-Order Execution", HPCA 2025)
in gem5 MinorCPU: the ASTRA address predictor alone, in **shadow mode**. Its
predictions are recorded and compared with the load's real base address and
never used, so it changes no architectural result and no timing, and no
performance gain is claimed. This is not Enhanced V-ASTRA (no address
compression), has no value cache, CBF, in-flight FIFO or minicache, and is not
META. LVP is a separate feature and is off in every run here.

Code: `src/cpu/minor/astra.hh/.cc`, hooks in `execute.cc`, parameters
`enableAstra` (default `False`) and `astraTableEntries` (default 1024).

## State (paper section IV-A1, Table II)

| Structure | Entries | Entry | Source |
|---|---|---|---|
| LAT, selected by the load PC, untagged | 2^n | last base address (64 bit) and a stride index (n bits) | paper |
| SS (Stride to Stride), untagged | 2^n | signed 16 bit stride | paper |

Prediction: `LAT.base + SS[LAT.idx]`. Table II's "Stride 16+n" bits per entry
is read as the 16 bit SS stride plus the n bit stride index kept in the LAT
(both tables have 2^n entries): 20 + 26 + 5 bits per entry for 1024 entries
gives about 11.2 kB with the V$ (the paper says 11.1 kB), which supports this reading.
No tags, no confidence counters, no valid bits.

## Choices the paper does not specify (inferences, documented in astra.hh)

- PC to LAT index: `(pc >> 1) & (entries - 1)`.
- Stride to SS index: the low n bits of the 16 bit two's complement stride.
- Update (order-1 D-FCM), at retirement, with LAT state `(base0, idx0)` and
  committed base `b`: `stride = int16(b - base0)` (wraps if it does not fit);
  `SS[idx0] = stride`; `LAT = (b, index(stride))`.
- Cold start: LAT `(0, 0)`, SS all 0, so the first prediction is 0 and a
  prediction is always made.
- The predicted value is the 64 bit sum; no carry-out handling.
- ASTRA predicts the **base register's value** (paper section IV-B and
  Figure 3: the immediate is not speculated), not the effective address.

## Timing, and how the base address is obtained

- Lookup: at issue (`Execute::issue`), before the base is read.
- Base capture: in `executeMemRefInst`, just before `initiateAcc` computes
  `EA = rvZext(Rs1 + offset)`; the base is `Rs1`, read from the register file
  exactly as `initiateAcc` reads it (`ThreadContext::getReg` of source 0). It is
  valid there because Minor only computes an effective address when the
  instruction's operands are architecturally ready. The sign extended
  12 bit offset is not needed to obtain the base; the test checks it anyway:
  for every retired load, base = effective address - immediate, both read from
  the committed trace (`astra.c` has loads with immediates +24 and -16).
- Update: when the load leaves the in-flight queue committed and without a
  fault, in retirement order. Squashed or faulted loads never train. A load
  that ran on an LVP predicted source has no valid base and is counted, not
  trained (not used here: LVP is off).
- Deviation from the paper: Minor's window is larger than CVA6's, so more
  instances of a load are looked up before an earlier one retires, which lowers
  accuracy. The checker replays the actual interleaving exactly.

## Running

    tests/astra/run_astra.sh check-asm     # build, check the disassembly
    tests/astra/run_astra.sh run           # check-asm, then D, S, SL, checker

`OUT` (default `/tmp/astra-test`). gem5 must already be built. Runs: D (ASTRA
off), S (shadow), SL (shadow with the ASTRA log).

## What the checker proves (`check_astra.py`)

- ASTRA changes nothing: checksum (computed from the program's structure),
  committed trace and every non-ASTRA statistic are identical in D, S, SL; D has
  no `astra.*` statistics and logs no ASTRA event.
- The committed loads are exactly the ones `astra.c` is written to execute,
  at the effective addresses of an independent model of the program.
- Every lookup and update in the log agrees with `AstraModel` (a Python
  re-implementation of the algorithm above), replayed in log order, including
  the table state each lookup read; updates are in retirement order, are for
  exactly the committed loads, and each load has one outcome.
- Statistics agree with the log, and `lookups + carryIn == trainings + squashed
  + faulted + unavailable + inFlight`.
- Section properties from the model run with no pipeline lag (constant,
  positive and negative strides converge; a changing stride costs mispredictions
  at each change; the second PC of `pair` benefits from the first one's SS
  update (constructive aliasing); `conf`, with strides 64 and 1088 that share
  SS index 64 in a 1024 entry table, thrashes (destructive aliasing)). These
  are properties of this model, not guarantees of the paper.

The cold start and every expectation that depends on an inference above are
model-derived, not paper-specified.

## Targeted tests (`run_astra_targeted.sh`)

These add coverage the first suite lacked. They run on the research baseline
`configs/research/vp_baseline.py` (SingleThreaded, queue limits 16), through its
own `--astra` and `--astra-entries` options, with LVP off unless stated. They
do not change the predictor. Commands (gem5 must be built; `OUT` defaults to
`/tmp/astra-targeted`, use a directory of your own):

    OUT=<dir> tests/astra/run_astra_targeted.sh MODE      # MODE below
    OUT=<dir> tests/astra/run_astra_targeted.sh all       # every MODE, about 40 s
    OUT=<dir> tests/astra/run_astra_targeted.sh check-asm MODE   # cold alias conf squash fault

The program is `astra_targeted.c` (every load is one `ld` in assembly, so the
loads and their PCs are known; the runner checks the disassembly: exactly the
expected loads and no other). The checker is `check_astra_targeted.py`; it
imports the model and trace reader of `check_astra.py`, so every lookup and
update of every run is also replayed against that model. `with_params.py` runs
the baseline unchanged with extra `-P system.cpu[0].NAME=VALUE` options (used
only for `invalid-config`, to reach the C++ checks).

Each mode runs D (ASTRA off) and S (ASTRA on, with the log) and requires the
same checksum, committed instruction count, committed trace and non-ASTRA
statistics, and the lifecycle identity `lookups + carryIn == trainings +
squashed + faulted + unavailable + inFlight`.

| MODE | What it requires |
|---|---|
| `cold` | The first load of the program reads LAT base 0, stride index 0 and SS 0 and predicts 0. Its update takes the stride from base 0 (the 16 bit truncation of the address). A second load (other PC, other LAT entry) reads its own cold LAT entry (base 0, index 0) but SS[0], written by the first update. Then each load reads what its first update wrote. |
| `alias` | `ld_a` and `ld_b` are 2048 bytes apart; the index `(pc >> 1) & 1023`, computed from the assembled PCs, is equal. `ld_a` is trained with stride 64; `ld_b`'s first lookup reads `ld_a`'s last base and stride index (and the trained SS entry) and predicts base + 64; its update computes the stride against `ld_a`'s base; `ld_a`'s next lookup reads `ld_b`'s base. The same program with `--astra-entries 2048` (indexes differ) reads cold state instead: the sharing is the table index. |
| `conf` | Destructive SS aliasing with the pipeline lag removed by delays (the checker verifies every load is looked up after the previous load retired, and that each prediction equals the lag-free model's). Strides 64 and 1088 share SS index 64 in a 1024 entry table: 0 of 48 predictions are correct for either load; the control (64 and 128, different SS entries) predicts 45 of 48. |
| `squash` | Four cold, always-taken branches whose fall-through is a load: it is looked up on the wrong path and discarded. Requires `squashedLoads` non-zero and equal to the squashed outcome lines, every squashed load looked up and with no update, the `sq_wrong` loads squashed and absent from the committed trace, and exactly the four real loads trained. (Each wrong path also fetches the following real load, so 8 loads are squashed.) |
| `fault` | Two mmap'd pages are never touched; the first load from each takes a translation fault that the SE page fault handler resolves (the page is in a mapping) and the load is executed again. Requires `faultedLoads` = 2, each faulted outcome followed in the trace by the faulting `ld` (address, no result), no update for a faulted load, and three trainings (two re-executions and one load without a fault). gem5 exits 0. |
| `invalid-config` | ASTRA table sizes 0, 1, 3 and 65537 are rejected, and 2, 1024, 65536 and the default are accepted, in two layers: through the baseline's command line (argparse: exit 2, "not a power of two" or "must be in [2, 65536]") and through the C++ check in the `AstraPredictor` constructor (exit 1, `fatal: astraTableEntries must be a power of two in [2, 65536] (got N)`). With ASTRA disabled: `--astra-entries` without `--astra` is rejected by the command line; setting `astraTableEntries=3` directly with ASTRA off is accepted and ignored (no predictor, no `astra.*` statistics), the same policy as LVP's `lvpTableEntries` (checked only when enabled). |
| `lvp-coexist` | The LVP phase workload (built by `tests/lvp/run_lvp_stageb.sh check-asm phase`) with LVP address speculation, with LVP and ASTRA, and with the ASTRA log. Requires identical checksum, committed trace, instruction count, cycles, every non-ASTRA statistic and every LVP counter (the LVP path is exercised: speculative loads committed and recovery redirects), `astra.*` statistics only with ASTRA, and that `baseUnavailableLoads` equal the speculative loads that committed, all at the LVP consumer PC: its base register held an LVP predicted value when its address was computed, and `astraCaptureBase` skips such loads. |

### What these tests do and do not show

- A pass shows that the implementation does what `astra.hh` documents. The model
  is a re-implementation of the same inferences, so it is **not independent
  evidence that the inferences are the paper's**.
- Decisions the paper leaves open, recorded and not changed here: the stride is
  `current base - previous base` (the paper's prose says "subtracting the load
  address from the last address", which would have the other sign, but the
  stride is then added to the last address); the SS index is the low n bits of
  the 16 bit stride; a stride that does not fit in 16 bits is truncated (the
  `fault` test shows it: the first update from a cold entry with base
  `0x20000000` gives stride 0); the cold start is LAT {0, 0} and SS all 0. A
  cold LAT entry therefore reads SS[0], the entry of the stride-0 context.
- The `fault` test covers a fault the SE handler resolves. A fault it cannot
  resolve ends gem5 with a panic and no statistics; that is not tested.
- `conf` needs delays to expose destructive aliasing; in `astra.c` the pipeline
  lag hides it (see the first suite). Constructive aliasing (`pair`) is still
  only compared with the lag-free model.
- Not covered: stride overflow as its own test, ASTRA with LVP prediction only
  (not speculation), SMT, statistics resets with live loads, other table sizes
  in the workloads, and the paper's address compression, value cache and META
  (not implemented).

## Shadow value cache (V$), Stage 1 of V-ASTRA

`src/cpu/minor/vcache.hh/.cc`, parameter `enableVCache` (default `False`, needs
one thread), debug flag `VCache`, statistics `cpu.vcache.*`. It is a model of
the paper's V$ (Section IV-A2) that observes real memory operations and never
affects execution: it is not given an ASTRA prediction, supplies no value to
anything, has no speculative state and is not a V-ASTRA prediction. The
hook is `Execute::vcacheRetire`, called from `handleMemResponse` for a memory
operation that completed without a fault and was not discarded (the same
non-speculative point at which a load trains LVP and ASTRA).

Organisation: 256 direct-mapped entries of 16 bytes (4 KiB), index
`(vaddr >> 4) & 255`, tag `vaddr >> 12` (virtual, no LACT or compression).
Choices the paper does not specify, made for correctness and documented in
`vcache.hh`: one valid bit per byte (a load records only the bytes it read; a
lookup hits only if the tag matches and every requested byte is valid; the
paper's 16-byte fill is not modelled), and an "occupied" flag.

Maintenance, all at retirement, from the request and its packet (raw bytes,
not the extended register result):

| Operation | Effect |
|---|---|
| cacheable load in one line | diagnostic lookup with the real address before the update (tag miss, byte miss, correct, wrong); then allocate, replace (the old valid bits are cleared) or add its bytes |
| cacheable store in one line | writes its bytes (and marks them valid) in a matching entry; never allocates; otherwise only counted |
| atomic, load-reserved, store-conditional, masked, prefetch, cache maintenance, micro-op, sizeless | `special`: clears the valid bits of the bytes covered (even for a load-reserved, which only costs bytes) |
| uncacheable or strictly ordered | not looked up, not allocated; a store, and a load too (conservatively), clears the covered bytes |
| crosses a 16-byte boundary | load: rejected (no lookup, no allocation); store: rejected and the covered bytes of both lines are cleared |

Statistics: `retiredOps`, `lookups`, `tagHits`, `tagMisses`, `byteValidHits`,
`byteInvalidMisses`, `valueCorrect`, `valueWrong`, `loadAllocations`,
`loadReplacements`, `loadUpdates`, `storeUpdates`, `storeMisses`,
`uncacheableLoads/Stores`, `crossLineLoads/Stores`, `specialOps`,
`invalidationOps`, `bytesInvalidated` (see `vcache.cc` for each), with
identities the checker verifies. They are ordinary statistics and are reset
with the others; the V$ contents are not.

### Tests (`run_vcache.sh`)

    OUT=<dir> tests/astra/run_vcache.sh MODE        # ops squash fault noninterference
    OUT=<dir> tests/astra/run_vcache.sh all
    OUT=<dir> tests/astra/run_vcache.sh check-asm MODE   # ops squash fault

Programs are in `vcache.c`; `check_vcache.py` checks the runs (the baseline is
run through `with_params.py` for the `-P` option). Every mode compares a run
with the V$ off (D) and on (S): checksum, committed instruction count, committed
trace and every statistic except `vcache.*`, cycles included, must be equal.

| MODE | What it requires |
|---|---|
| `ops` | A script of 52 loads, stores and atomics (the table `SCRIPT` in the checker has the expected outcome of each step): repeated byte, halfword, word and doubleword loads, signed and unsigned (the raw bytes extended by the opcode equal the traced result); partial stores that leave neighbouring bytes intact; stores that miss and do not allocate; tag conflicts 4 KiB apart, including that a replacement clears the old valid bytes; byte-invalid misses; a load and a store that cross a 16-byte boundary (single `ld`/`sd`, rejected; the store clears the bytes it covers in both lines); `amoadd.d`, `lr.d` and `sc.d` (special, invalidate); a store that makes the bytes it writes valid. Every VCache line is a committed memory operation of the trace, in order (the trace has no line for atomics, so those are matched with the disassembly). |
| `squash` | A load on a wrong path (a cold, always-taken branch): ASTRA (on in both runs) logs it as looked up and squashed; it never retires, has no VCache line, and the first retired load from the line it addressed is a tag miss that allocates. |
| `fault` | Two never-touched mmap'd pages: the two faulting loads (ASTRA outcome `faulted`, traced without a result) have no VCache line, and the three loads that complete are allocate, hit, and a conflicting page that replaces. |
| `noninterference` | The ASTRA program (`astra.c`) and the LVP phase workload (LVP address speculation and ASTRA on), with the V$ off and on: also every ASTRA and LVP statistic equal, speculative loads and recovery present in the LVP run, and, over all their loads and stores, no diagnostic hit with wrong data. |

Every mode also replays the whole log on `VModel`, a model written from the
specification in `vcache.hh`, and requires each classification, each
invalidation count and each `vcache.*` statistic to agree. As for ASTRA, the
model is by the same author as the code: a pass shows that the code does what
`vcache.hh` says, not that these choices are the paper's.

Not covered: uncacheable and strictly ordered accesses (a user-mode SE program
cannot create one; those counters stay 0 in every test), byte-masked accesses,
SMT (rejected with a fatal error), stores to lines held by another core, and
everything V-ASTRA adds beyond Stage 1 (using a predicted base or the V$ value,
in-flight store handling, LACT and the minicache).

## Diagnostic V-ASTRA probe, Stage 1b

`src/cpu/minor/vastra.hh/.cc`, parameter `enableVAstraDiag` (default `False`;
needs `enableAstra` and `enableVCache`), debug flag `VAstra`, statistics
`cpu.vastra.*`. For each load that has an ASTRA prediction it asks what the
shadow V$ would have supplied if the **predicted base** had been used (the
paper's enhanced variant: predicted base + the instruction's own immediate),
and compares that only with what the load really read. Nothing is used: the
load's operands, response, issue and timing are untouched, and the retirement
updates of the V$ are unchanged. It is not a V-ASTRA prediction or result.

**Lifecycle of a load with an ASTRA prediction** (a load ASTRA did not look up
gets no outcome):

1. *Decision* (`Execute::vastraDecide`, in `executeMemRefInst` just after
   `astraCaptureBase`: the first point at which the real base register is
   available, because registers are written at commit). `metadataMissing`: the
   base was not captured (the load ran on an LVP-predicted source) or it is not
   an uncompressed RISC-V `Load`. `baseWrong`: the predicted base is not the
   register. Otherwise `baseCorrect`; the predicted address is `base + sext12
   (machInst.imm12)`, the decoded immediate field of `RiscvISA::Load` (not
   parsed from text; the RV32 zero extension is applied). Then the older stores
   still in flight are checked: `rejStoreConflict` if a store with a known
   address overlaps the load's bytes (the size is not known yet, so 8 bytes are
   assumed, a superset), else `rejStoreUnknown` if one has no address yet, else
   a *candidate*: a copy of the V$ entry for the predicted address is taken (tag
   hit, valid bits, 16 bytes), so the value is the one at decision time.
2. *Terminal outcome of a candidate*, exactly one: discarded or faulted before
   it retired (`Execute::vastraPop`, at the one place an instruction leaves the
   in-flight queue); or at retirement (`vcacheRetire`, with the real request and
   raw bytes) `rejUnsupported` (special, uncacheable or crossing a 16-byte
   boundary), `eaMismatch` (predicted address is not the real one: should not
   happen when the base is right), or a lookup of the copy: tag miss, byte
   miss, or a byte-valid hit whose bytes equal (`candidateCorrect`) or differ
   from (`candidateWrong`) the load's raw bytes. A tag match alone is neither.

Identities (checked): `predAvailable = metadataMissing + baseWrong +
baseCorrect`; `baseCorrect = rejStoreConflict + rejStoreUnknown + candidates`;
`candidates + carryIn = discarded + faulted + rejUnsupported + eaMismatch +
lookups + inFlight`; `lookups = tagMisses + tagHits`; `tagHits =
byteInvalidMisses + byteValidHits`; `byteValidHits = candidateCorrect +
candidateWrong`. `inFlight` and `carryIn` follow the ASTRA convention, and
`isDrained` asserts no candidate is live.

The scan of older stores is a **MinorCPU implementation choice**, not the
paper's counting Bloom filter and prediction-invalidation FIFO. It uses a
per-thread list of issued, not yet popped stores and atomics (`vastraStores`),
and the address and size that `LSQ::pushRequest` now records on every memory
instruction (`memAddrKnown`, `memVaddr`, `memSize`, plain fields that nothing
else reads). Because the V$ copy is taken at the decision and committed
stores have already updated the V$ (at retirement), an older store that is
still in flight is the only way the copy can be stale.

### Tests (`run_vastra.sh`)

    OUT=<dir> tests/astra/run_vastra.sh MODE        # classify store discard fault noninterference
    OUT=<dir> tests/astra/run_vastra.sh all
    OUT=<dir> tests/astra/run_vastra.sh check-asm MODE   # classify store discard fault

Programs are in `vastra.c` and each probed load is one `ld` at its own PC;
`check_vastra.py` checks the runs. ASTRA and the V$ are on in every run; D has
the probe off and S on, and they must have the same checksum, committed
instruction count and trace and every statistic except `vastra.*`, cycles
included. Every mode replays the whole log: ASTRA's own log gives the predicted
and real base, the V$ log the V$ at each decision, the disassembly the
immediate; each decision, address, in-flight store, V$ copy and outcome (against
the raw bytes the load read) and every `vastra.*` statistic must agree, and
the identities must hold.

| MODE | What it shows |
|---|---|
| `classify` | Constant stride 64 (24 loads): **hit** (all 16 bytes of each line loaded first): correct base, byte-valid hit, candidate bytes equal the load's (22 of 24; the rest are ASTRA learning); **tagmiss** (nothing loaded first); **bytemiss** (only bytes 0..7 loaded, the load reads 8..15: tag matches, bytes invalid); **cross** (8 bytes at +12 crossing a 16-byte boundary: rejected as unsupported at retirement); **basewrong** (stride changes each time: wrong base although the V$ holds valid bytes: for 11 loads the V$ held valid bytes at the *wrongly predicted* address and they were not the load's bytes, so a tag hit alone would have given a wrong value; for 14 it held the right bytes at the real address and the probe still rejected them) |
| `store` | A load that misses keeps everything younger from retiring, then a store, then the probed load. Store writes the bytes the load reads: 14 of 16 rejected as `storeconflict`; control, the store writes the next line: 15 of 16 are still candidates with an older store in flight, so the scan rejects only overlapping stores. The checker recomputes the in-flight stores from the V$ log (stores whose retirement is logged after the decision) and requires the same result. |
| `discard` | A load decided on a mispredicted branch's wrong path with a correct prediction is a candidate and is discarded (ASTRA logs it as squashed; the V$ has no line for it). |
| `fault` | Never-touched mmap'd pages, stride 4096: loads that take a translation fault after a correct prediction are candidates with the terminal outcome `faulted` (ASTRA logs them as faulted; no V$ line); the re-executions are looked up. |
| `noninterference` | The ASTRA program and the LVP phase workload (LVP speculation on): identical with the probe off and on, and over all their loads no candidate was a byte-valid hit with wrong bytes; in the LVP run the loads with `metadataMissing` are exactly the LVP consumer. |

### Limits

- `rejStoreUnknown` cannot be produced: `Execute::commit` sends a memory
  operation to the LSQ only when it is at the front of `inFUMemInsts`, so
  memory operations reach `executeMemRefInst` (where a store's address is
  computed and recorded) in program order, and every older store has an address
  by the time a younger load is decided. The counter is asserted to be 0 and
  the rule is kept as a conservative guard; the case is not tested.
- The load's size is not known at the decision, so the scan assumes 8 bytes,
  and unsupported sizes, special and cross-line accesses are classified at
  retirement.
- The immediate comes from RISC-V's decoded `machInst`, so it is RISC-V
  specific (other ISAs, and compressed loads, are `metadataMissing`).
- Like the other checkers, the model is by the same author as the code; the
  paper's counting Bloom filter, invalidation FIFO, address compression and
  the use of a candidate by the CPU are not implemented.

### Strict verification, Stage 2a

Parameter `enableVAstraVerify` (default `False`; needs `enableVAstraDiag`, else
a fatal error). A candidate that passed every check (base correct, no
conflicting older store, supported access, V$ tag hit with every requested byte
valid) is compared at its normal retirement with the raw bytes the real load
returned (`Execute::vastraValidate`). Equal: `vastra.verifiedHits` is counted.
Different: the run stops with a `panic` that reports the load's execution
number, pc, predicted base, actual base, effective address, size, candidate
bytes and actual bytes. A candidate rejected for any other reason (base wrong,
store, unsupported, tag miss, invalid bytes), discarded or faulted is not
checked: those are other outcomes, not valid candidate values. Every existing
counter keeps its meaning (`verifiedHits` is the only addition), and the
candidate is never used (not as a response, operand or forwarding value, and
no real memory access is suppressed); the check reads the instruction's own
snapshot, taken at its decision, and calls nothing in LVP or ASTRA.

Safety assumptions, from source: the snapshot is stored in the `MinorDynInst`
of the load at its decision and read from the same instruction in
`handleMemResponse`, so it cannot be confused with a later V$ lookup (the V$
is not read again); the address is `base + sext<12>(machInst.imm12)` (RV32 zero
extension applied) and a candidate whose address is not the real one is
`eaMismatch`, not compared; byte validity, cross-line and special accesses are
checked from the snapshot and the real request before any comparison; every
older store still in flight is rejected at the decision, so only stores already
retired (which have updated the V$) can precede a compared candidate; a
discarded or faulted load leaves through `vastraPop` and can only be counted as
such. The unknown-store-address case cannot occur in the scheduling path tested
here (memory operations reach the LSQ in program order, see Limits above). The
scan is a MinorCPU choice, not the paper's counting Bloom filter and
invalidation FIFO.

`run_vastra.sh` now also runs each workload with strict verification (run V,
S plus the option) and requires V to equal S in checksum, trace and every
statistic (cycles included) except `verifiedHits`, and every byte-valid hit to
have been verified. Mode `verify-detect` shows that the check can fail: the
store program with the test-only parameter `vastraTestSkipStoreScan` (candidates
are no longer rejected because of older stores) admits 6 stale candidates (X1,
each with an older overlapping store in flight); with strict verification (X2)
the run stops with a panic whose report is the first of them.

