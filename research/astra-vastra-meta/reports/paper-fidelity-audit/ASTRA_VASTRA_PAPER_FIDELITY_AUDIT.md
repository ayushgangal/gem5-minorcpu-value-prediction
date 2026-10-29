# ASTRA / V-ASTRA paper-fidelity audit (Stage 2b.2)

Written for: the researcher deciding what to do before META and dependent speculation.
Read-only audit of `~/gem5` (branch `vp-lvp-dev`, HEAD `ce1a9fdf5b`, all work uncommitted) on 2026-10-23.

## 0. Method, sources, and how to read this

* **Paper** (primary specification): Ravenel, Perais, Dupont de Dinechin, Pétrot, *Architecting Value Prediction around In-Order Execution*, HPCA 2025, pp. 72–84. Local copy: `~/Downloads/Architecting_Value_Prediction_HPCA_2025.pdf` (sha256 `8ad54b79…a7e`, 14 PDF pages; the copy used here is stored in `paper/`, with per-page text in `paper/pNN.txt`). A second, 6-page document in Downloads (`VALUE PREDICTION ARCHITECTURE IN INORDER PROCESSORS.pdf`) is not the paper and was not used.
* **Page numbers.** PDF page 1 is the HAL cover sheet; PDF page 2 starts printed page 72. So **printed page = PDF page + 70** (13 content pages = pp. 72–84, matching the HAL citation). Citations below are written `PDF p.N (printed N+70)`. Section/figure/table names come from the extracted text. Text extraction (`pdftotext -layout`) of two-column pages is not perfectly ordered; every quoted sentence was read in `paper/pNN.txt`.
* **Source** facts come from the files listed in the matrix (snapshots in `snapshot-source/`). Line numbers are those of the checkout on 2026-10-23 and are exact for `execute.cc`, `lsq.cc`, `astra.*`, `vcache.*`.
* **Test evidence** comes from retained logs in `~/gem5-validation-2026-10-23/vastra-stage2b-implementation/hardening/` (`regression/*.log`, `bypass-final.log`), not from re-running. No simulation was run in this audit.
* **Legend.** *Fact* = read from source/paper/log. *Evidence* = a retained test result. *Judgment* = my engineering opinion. Classes: `aligned`, `likely aligned`, `intentional adaptation`, `deviation`, `underspecified`, `untested`.

### Retained evidence used (pass counts of PASS lines; all FAIL = 0 unless noted)

| Suite (log) | PASS | Note |
|---|---|---|
| `regression/astra.log` | 78 | ASTRA shadow, golden model |
| `regression/astra_targeted.log` | 340 | cold, alias, conf, squash, fault, invalid-config, lvp-coexist |
| `regression/vcache.log` | 157 | V$ ops script (52 steps), squash, fault, noninterference |
| `regression/vastra.log` | 276 | classify, store, discard, fault, noninterference, verify-detect |
| `regression/lvp_*.log` | 473 + 71 + 79 + 37 + 57 + 55 | existing LVP suite |
| `regression/bypass.log` | 271, **1 FAIL** | the 1 FAIL is the old whole-run `numCycles` assertion, later replaced (see §5); superseded by: |
| `bypass-final.log` | 274, 0 FAIL | final bypass suite on the current source |

The source files did not change after the `regression/` run (only tests/README), so these logs describe the current source. `regression/summary.txt` records `bypass rc=1`; that is the superseded latency assertion, not a bypass failure.

---

## 1. Executive verdict

1. **ASTRA** (`astra.hh/.cc`): structurally faithful to §IV-A (PC-indexed untagged LAT, last address + stride index, untagged SS of 16-bit strides, prediction = LAT address + SS[stride], update at retirement, no confidence). Everything the paper leaves open (PC hash, SS index, stride sign wording, cold start, overflow, what the LAT holds in the enhanced variant) was resolved by inference. The tests check the code against a golden model of **the same inferences**, so they establish internal consistency, not agreement with the paper (the README says so).
2. **V$** (`vcache.*`): geometry matches (256 × 16 B = 4 KiB, direct-mapped, index in the page offset, virtual address, loads allocate at retirement, stores update matching entries only). Two deliberate differences matter for coverage, not correctness: per-byte valid bits and **no fill of the neighbouring doubleword on allocation** (the paper says a 16-byte line "naturally prefetches nearby data"). One paper-silent hazard is real: **virtual synonyms** (§3, concern 1).
3. **V-ASTRA bypass** (Stage 2b): the paper's safety property ("no dependent will ever execute with an incorrectly predicted source operand", PDF p.5, printed 75) **holds** here, because a V-ASTRA value reaches the load only through a response created after validation, and no younger instruction can read it before the load commits. What differs is *when* the validation and the benefit happen: the paper validates the base register in the **issue stage** and lets a validated load and its dependents issue together (0-cycle load-use); this implementation validates at `executeMemRefInst` and again at the LSQ send point and benefits only through **earlier commit** of the load. It is a faithful *safety* model and a weak *performance* model of the paper.
4. **Not implemented** (all outside the current scope, none a bug): META, LACT/compressor, minicache, CBF + in-flight invalidation FIFO, scoreboard replay, multiprocessor coherence, full-system CVA6 / SPEC CPU2017 evaluation.
5. **Genuine correctness concerns** (ranked, §6): (1) virtual-synonym staleness in the V$, (2) no guard against multi-core / shared-memory use, (3) bypass has no in-simulation independent oracle (differential testing only) and two safety branches were never exercised by any test, (4) FP loads are bypass-eligible but never tested, (5) older *atomic* conflicts untested.
6. **Biggest fidelity gap in practice** (not a bug): compressed (RVC) loads can never be V-ASTRA candidates, and ASTRA's lookup-to-training lag in MinorCPU is larger than the paper's, which lowers coverage. Absolute coverage/speed numbers from this model must not be compared with the paper's.

---

## 2. Requirement matrix

Columns: **#** · **Paper (PDF p., printed)** · **Expected behaviour (paraphrase)** · **Implementation (file:function:lines)** · **Test and evidence** · **Class** · **Confidence / rationale** · **Action before META**.

### 2.1 ASTRA (`astra.hh`, `astra.cc`, hooks in `execute.cc`)

| # | Paper | Expected | Implementation | Test / evidence | Class | Confidence / rationale | Action |
|---|---|---|---|---|---|---|---|
| A1 | §IV-A1, PDF 5 (75) | "ASTRA is accessed using a load PC" to read the LAT; no tags ("does not use tags or confidence counters"). | `AstraPredictor::lookup` astra.cc:79–90; index `(pc >> 1) & mask` astra.hh:152; no tag field (`LatEntry` astra.hh:140–144). | `astra_targeted alias`: two loads 2048 B apart share an entry at 1024 entries, differ at 2048 (README); `check_astra.py` replay. | aligned (untagged, PC-indexed); hash function **underspecified** | High that the structure is right. The `>>1` is our choice (RVC alignment). | None; keep documented. |
| A2 | §IV-A1 (75) vs §IV-B end, PDF 6 (76); Table II, PDF 12 (82) | IV-A1: LAT holds "the last committed **virtual address**". IV-B: the enhanced V-ASTRA predicts the **base** address, compared with the base register ("we compare the value of the base register with the predicted base address"); Table II: Addr = L = 20 low bits (+ LACT). | LAT stores the full 64-bit **base register value** captured at `executeMemRefInst` (`astraCaptureBase` execute.cc:2008–2027); `AstraPredictor::retire` stores it astra.cc:108–110. | `check_astra.py` "recovered base" check: trained base = effective address − sign-extended immediate, both from the committed trace. | intentional adaptation (follows the enhanced variant); paper wording **underspecified** (plain ASTRA = address, enhanced = base) | The paper never states the LAT content of the enhanced variant explicitly; "predicted base address" implies it. | Design decision D1 (§7). |
| A3 | §IV-A1 (75), Fig. 1 (75), Table II (82) | LAT entry = last address + signed stride used as index into SS (stride sized accordingly); SS = 16-bit strides; "stride from SS is then added to the last address". Table II: stride "16 + n" bits per predictor entry. | `lat` (base, idx) + `ss` (int16) astra.hh:140–147; prediction `base + int64(int16 ss[idx])` astra.cc:88–89. | `cold`, `alias` (targeted); replay against model. | aligned | High; the "16+n" reading (16-bit SS + n-bit LAT index) is the natural one for 2^n entries. | None. |
| A4 | §IV-A1 (75) | History is "not a hash of past strides, but the un-hashed last observed stride". | SS index = low n bits of the 16-bit stride, no hash (`ssIndex` astra.hh:153–156). | `conf`: strides 64 and 1088 collide at n = 10 (0/48 correct), 64/128 do not (45/48). | likely aligned; "sized accordingly" **underspecified** | Truncation to n bits vs. another n-bit reduction of a 16-bit stride is not stated. Shows aliasing exists; does not show the paper's mapping. | D2 (§7). |
| A5 | §IV-A3, PDF 5 (75) | "the stride [is computed] by subtracting the load address from the last address", then LAT gets the committed address and new stride and "the SS is updated with the new stride". | stride = `int16((base − LAT.base) & 0xffff)` i.e. **current − previous** astra.cc:103–104; `ss[LAT.idx] = stride` astra.cc:108 (the entry the load's *previous* stride index selects); LAT updated astra.cc:109–110. | README "What these tests do and do not show" records the sign choice; the model mirrors it. | **underspecified** (sign), likely aligned (SS write target) | Read literally, "last − load address" has the opposite sign; but the stride is then **added** to the last address, so only current − last predicts linear strides. Our sign is the only self-consistent reading; the wording is the ambiguity. Tests cannot decide it. | Record; no change. |
| A6 | §IV-A1 (75); §IV-C1, PDF 6–7 (76–77); Table II (82) | 16-bit strides "are sufficient"; the paper's enhanced design adds strides to the **20 low bits** (upper 44 via LACT); overflow of the *immediate* addition rejects the prediction (PDF 7, 77). Nothing is said for strides that do not fit. | 64-bit sum, no carry handling (astra.cc:88–89); stride truncated to 16 bits (astra.cc:103–104). No LACT, so no overflow rule. | `fault` targeted test: first update from a cold entry with base `0x20000000` yields stride 0 (truncation). README: stride overflow "not covered" as its own test. | intentional adaptation / **untested** (edge cases) | 64-bit arithmetic is exact where the paper's 20-bit arithmetic wraps; differs only across 1 MiB boundaries. Wrap to 16 bits is our inference. | Add a dedicated overflow/wrap test (§8). |
| A7 | not specified | – | Cold LAT {0,0}, SS all 0; first lookup predicts 0 (astra.cc ctor; astra.hh:60). A cold LAT reads SS[0]. | `cold` test; README. | **underspecified** | Valid bits are the alternative. | D3 (§7). |
| A8 | §IV-A3 (75) | Update when a load **retires**. | `astraRetire` execute.cc:2031–2075 called when the instruction leaves `inFlightInsts` (execute.cc:1641); discarded → `squashed()`, faulted → `faulted()`, neither trains; committed with captured base → `retire()`; committed without base (LVP speculative source) → `baseUnavailable()`, no training. | `squash` (8 squashed loads, none trained), `fault` (2 faulted, none trained, 3 trainings), `lvp-coexist` (baseUnavailable = speculative loads). Identity `lookups + carryIn = trainings + squashed + faulted + unavailable + inFlight`, replayed per window (drain test). | aligned (time of update); the LVP-source skip is an **intentional adaptation** | High. The skip exists because an LVP-speculative base is not the real register value; the paper has no such interaction (its LVP side replays). | None. |
| A9 | §IV-A1, PDF 5 (75): "the predictions for all the different loads will be incorrect until the first memory reference updates the SS table... a shallow in-order pipeline" keeps the time between prediction and issue short; Fig. 6, PDF 9 (79): META inserted two cycles before issue. | Lookup shortly before issue, update at retire, small lag. | Lookup when the instruction is issued into an FU (`astraOnIssue` execute.cc:1989, call execute.cc:945); update at in-order commit. In MinorCPU the issue-to-retire span is larger and memory ops wait for producers to commit. | `astra.c` "pipeline lag hides" destructive aliasing; `conf` needs delays; latency workload: `vastra.baseWrong` 116 of 294 decisions without delays vs 39 with delays (retained `scratch` runs reported in Stage 2b.1). | **intentional adaptation / deviation in effect** | The lag is a property of MinorCPU, not an algorithm change, but it lowers ASTRA accuracy for tight dependent loops compared with the paper. | D4 (§7); keep in mind when interpreting coverage. |
| A10 | §IV-A1, Fig. 2, PDF 5 (75) | Constructive aliasing: loads that share a stride after a function call predict each other (x264 `satd`). | Shared SS entries (A4). | `pair` section of `astra.c` and `alias`: compared with a lag-free model only. The x264 pattern is **not** reproduced. | **untested** against the paper's claim | The mechanism exists; its benefit is not shown. | Optional (§8). |
| A11 | §IV-A3 (75): "predictions are only made on loads" | Which loads? | `astraEligible` execute.cc:1970–1986: any non-atomic, non-LR/SC, non-micro-op, non-prefetch load whose first source is an integer register. **Includes FP loads and compressed loads.** | No FP load in any test (grep of `tests/astra/*.c`). Tests use `-march=rv64g` (no RVC). | **underspecified / untested** | See concern 4 and §6.B. | Decide scope (D6). |

### 2.2 V$ (`vcache.hh`, `vcache.cc`, `vcacheRetire` execute.cc:2092)

| # | Paper | Expected | Implementation | Test / evidence | Class | Confidence / rationale | Action |
|---|---|---|---|---|---|---|---|
| V1 | §IV-A2, PDF 5 (75); Table II (82) | 16 bytes per entry, 256 entries, 4 KiB. | `lineBytes=16`, `numEntries=256` vcache.hh:92–94, static_asserts vcache.cc ctor. | `vcache.log`: 157 PASS incl. "every vcache.* statistic equals the model's count". | aligned | High. | None. |
| V2 | §IV-C2, PDF 7 (77): tag = 5-bit ID + 8 upper bits of the 20 ASTRA bits; "remaining 12 bits are used as index (8-bit) and offset (4-bit)". Direct-mapped is implied (256 entries, 8-bit index). | Index/offset in the page offset; tags from compressed upper bits. | index `(vaddr>>4)&255`, offset `vaddr&15`, tag `vaddr>>12` (full, uncompressed) vcache.hh `indexOf/tagOf`. | `ops` script step 23–28 (tag conflicts 4 KiB apart). | aligned (geometry); compression **not implemented** (out of scope) | Tag compression (ID recycling invalidations) is not modelled; no effect on correctness here. | None before META. |
| V3 | §IV-A2 (75) | Virtual addresses; "to handle virtual synonyms, the V$ size is limited to a single page"; PID "may be cached along the tag to avoid flushing the entire V$ on context switches". | Virtual index/tag, one process, no PID; flush only at syscalls (B9). A store updates **only an entry with the matching tag** (`storeRetired` vcache.cc:184–205; `invalidate` vcache.cc:213–231 also matches by tag). | No test with two virtual mappings of one physical page. | **underspecified / untested — concern 1** | With a virtual tag, a store through VA1 does not update a resident entry tagged VA2 (same set, same physical memory): that entry keeps stale bytes. The paper's single-page rule makes synonyms *conflict* in one set but does not say how the store reaches the other tag. | D5 (§7); add test (§8). |
| V4 | §IV-A2 (75): "Having two double words per line naturally prefetches nearby data" | A 16-byte entry holds both doublewords after allocation. | A load writes only the bytes it read (`loadRetired` vcache.cc:122–182); valid bits are per byte; no neighbour fill. | `vcache` byte-invalid misses (`ops` steps 29–31), `classify` bytemiss section. | **intentional adaptation (coverage-reducing)** | The load retiring knows only its own bytes. The paper's wording implies a fill from the L1D line, which the shadow model does not read. Expect lower V$ hit rate than the paper. | D7 (§7); do not compare hit rates with the paper. |
| V5 | §IV-A3 (75) | "Allocation takes place when a load retires if its address is cacheable. Stores do not allocate but update data in matching entries." V$ updated "by both loads and stores at commit". | Load → allocate/replace/update (`loadRetired`); store → update matching only, miss otherwise (`storeRetired`); both from `vcacheRetire` at response handling (= retirement). | `ops` script, noninterference (V$ off/on identical architecture), "every VCache line agrees with the model" (0 disagreements). | aligned | High. | None. |
| V6 | not specified | Partial loads/stores, sizes. | Per-byte valid bits (`valid` mask), partial store updates only written bytes, subword loads need all their bytes valid. | `ops` steps 4–13, 15–20. | intentional adaptation | The paper's V$ has no stated byte validity (its M$ has, Fig. 5, PDF 9). Needed for correctness with partial stores. | None. |
| V7 | not specified | Atomics, LR/SC, prefetch, cache maintenance, micro-ops, uncacheable, cross-line. | `vcacheRetire` execute.cc:2092–2175: those operations invalidate the bytes they touch (`otherRetired` vcache.cc:257–287); cross-line loads are not recorded; uncacheable never allocate. | `ops` H (atomics, LR/SC), G (cross-line); `special` bypass test. **Uncacheable: untested** (SE mode has none here). | intentional adaptation; uncacheable **untested** | The paper only says "if its address is cacheable". | Document only. |
| V8 | §IV-D, PDF 7 (77); §IV-H2, PDF 9–10 (79–80) | V$ must stay coherent with memory: in-flight stores (CBF + in-flight invalidation FIFO); remote writes invalidate the entry; non-predicted loads whose L1 line is invalidated before commit must not allocate (second CBF). | Single core only; exact older-store scan (C5); no remote writes exist. `enableVCache` requires one thread (execute.cc:154) but **nothing refuses a system with several CPUs** or shared memory. | None (no multiprocessor test). | **untested — concern 2**; MP coherence out of scope | Safe for the single-core SE experiments; unsafe if misused. | Add a guard or documented restriction (§8). |
| V9 | not applicable (hardware has no functional memory path) | Memory changed outside the LSQ. | SE syscalls write user memory through the functional proxy inside `fault->invoke` (execute.cc:~1175, just before the flush call at 1181); `vcacheSyscallFlush` (execute.cc:2241, called at execute.cc:1181) runs right after, before `tryToBranch`; flush covers every `IsSyscall` instruction. | `syscall` (22 loads bypass, new values seen after `read`), `syscall-negative`: with the flush suppressed 21 stale values are consumed (= the program's error count 21) and strict verification stops with candidate = OLD(i), actual = NEW(i). One flush per committed `ecall` (8 = 8). | intentional adaptation (required by SE emulation); necessity **shown for this program** | Strong evidence for this program and path. Not covered: m5 pseudo-ops that write memory, other cores/devices. | None. |
| V10 | – | Drain and statistics reset. | Plain `Scalar`s plus `live/carry` integers; flush stats are ordinary scalars. | `drain` mode (nothing in flight at any window end) and `reset` mode (no drain; `carryIn = 1` window observed, identity holds, `carryIn(k) = inFlight(k−1)`, no negative values). | n/a (engineering) | Contract is per window with carry-in; stated in `tests/astra/README.md`. | None. |

### 2.3 V-ASTRA candidate validation and bypass (`execute.cc`, `lsq.cc`, `vastra.*`)

| # | Paper | Expected | Implementation | Test / evidence | Class | Confidence / rationale | Action |
|---|---|---|---|---|---|---|---|
| C1 | §IV-B, PDF 6 (76) | Full predicted address = predicted base + the **non-speculative immediate from decode**; if the base is right so is the address; the immediate is not speculated (like CAP, unlike CAP: no immediate speculation). | `vastraEffectiveAddress` execute.cc:2185–2200: `base + sext<12>(machInst.imm12)`, truncated to 32 bits for RV32; **uncompressed RISC-V `Load` only** (compressed → `metadataMissing`). Real base = `thread->getReg(srcRegIdx(0))` read when the EA is computed (execute.cc:2022). | `eaMismatch` = 0 in every retained run (classify/store/discard/fault/special/syscall/latency/lvp). | aligned (arithmetic); compressed loads **excluded (deviation in coverage)** | High for the arithmetic. | D6 (§7). |
| C2 | §IV-B (76): validate "early in the issue cycle"; "stalls predicted loads at issue if their source operands are not available"; dependents "may only issue after the load issues". | Validation at **issue**, base register vs predicted base. | Decision at `executeMemRefInst` (`vastraDecide` execute.cc:2356, call execute.cc:626) when the source registers hold committed values (MinorCPU writes registers at commit); second validation at the LSQ send point (`vastraTryBypass` execute.cc:2257 from lsq.cc:1122): EA equality, store re-scan with real size, byte-validity, fresh V$ lookup. Validation therefore happens at **two** points, neither is the issue stage. | `classify` (hit/basewrong/tagmiss/bytemiss/cross), `bypass` pair tests (identical committed traces). | **intentional adaptation** | Safety property preserved (C3); timing differs. | D4 (§7). |
| C3 | §IV-B (75–76), §IV-H2 | No dependent ever executes with an unvalidated predicted source; no re-fetch/re-execute needed. | The candidate bytes are copied into the packet only after all checks; the register is written by `completeAcc` at commit; MinorCPU executes dependents at commit, so none can read an unvalidated value. (LVP address speculation, a separate mechanism, does consume unvalidated values and recovers by squash; it is not V-ASTRA.) | Committed trace equality P vs B in all 9 workloads; `syscall-negative` shows what a stale value would do and that the normal run avoids it. | **aligned (safety)** | High; follows from in-order commit + response-based delivery. | None. |
| C4 | §IV-D (77): predictions are read in the front-end and protected by CBF at prediction and an invalidation FIFO for stores issuing later. | V$ content valid when used. | Snapshot at the decision, then a **fresh lookup** at the LSQ send point; the bypass is abandoned if the requested bytes differ from the snapshot (execute.cc:2330–2340). | `bypassAbandoned_` is **0 in every test**: the branch is never exercised. | intentional adaptation; the abandon path **untested** | Fresh data at the use point makes the FIFO unnecessary. Untested branch is a gap. | Add a test that provokes it (§8). |
| C5 | §IV-D (77) | "if the value of the predicted address set is different from 0, the prediction is rejected" (any in-flight store to the V$ set, regardless of address); stores issuing after the prediction invalidate in-flight predictions. | Exact scan: any older store/atomic in `vastraStores` (pushed at issue, popped at retirement) whose known address overlaps `[ea, ea+size)` rejects (`vastraScanStores` execute.cc:2213–2238, size 8 at decision, real size at the LSQ). LSQ gating before the bypass: no store in the transfers queue (lsq.cc:1036), store-buffer full overlap → real forwarding, partial → wait (lsq.cc:1100–1121). Unknown older address: structurally unreachable (comment at execute.cc:2216). | `store` test: `rejStoreConflict` > 0 and the loads behind a conflicting store are never bypassed; `verify-detect`: with the scan off, 6 stale byte-valid candidates (`candidateWrong 6`), each with an older overlapping store in flight, and strict verification stops the run (rc 134). | **intentional adaptation** | Safer than the paper only where exact addresses are known; rejects less than the CBF (set granularity) — fine because addresses are exact. Only plain stores are tested as conflicts (concern 5). | Test an atomic conflict (§8). |
| C6 | §IV-D, §IV-G (79) | Predicted loads must be ordinary loads; faults/squashes must not leave state. | Support predicate (`vastraTryBypass` execute.cc:2276–2296): single request, load, not atomic/prefetch/micro-op/LR/SC/swap/maintenance/masked/uncacheable/strict/local, fits one 16-byte line, packet size equals request size. Wrong-stream requests abort before it (lsq.cc:999) and translation faults are moved to the transfers queue before it (lsq.cc:1015–1024). | `special` (LR/AMO never bypassed), `classify` (cross-line fallback 22), `fault` (faulted candidates identical P/B), `discard` (1 bypassed load discarded: deleted once, no memory response). | intentional adaptation | Safe. FP loads and RVC untested/excluded (A11). | See concerns 4, D6. |
| C7 | §IV-B (76): a correct prediction lets "the load completely skip the L1D access" | Request suppressed. | `makeResponse()` on the request packet; `do_access=false`; same queue move as store-buffer forwarding (lsq.cc:1122–1131); `issuedToMemory` untouched. **Address generation and the DTLB translation still happen** (they precede the hook). | MinorMem trace check on every bypassed load: no "Trying to send", no "Received response packet", ≤ 1 completion, deleted once (e.g. 243 loads in `latency`); `ReadReq.accesses` falls by exactly the suppressed count in every pair. | aligned for the L1D; **adaptation** for the execute stage / TLB | The paper says the execute stage is bypassed; here TLB state is still touched by every load. | None; note for timing claims. |
| C8 | §IV-A3 (75) | V$ updated by retiring loads/stores; paper silent on whether a V-ASTRA-hit load updates it. | `vcacheRetire` returns early for `vaBypassed` (execute.cc:2100–2112): no V$ update, no lookup counters; `candidatesBypassedRetired` is its terminal outcome. ASTRA still trains on the load's base (address-based, independent of the value); LVP still validates/trains on the architectural register value. | Pair test: P − B `vcache.lookups` and `retiredOps` equal the bypassed retired loads (all workloads); per-window identity (drain/reset tests). | likely aligned / **underspecified** (paper silent) | Not updating avoids recording synthetic bytes as observed memory. | D8 (§7). |
| C9 | – | Flush before younger instructions can use stale values. | `commit()` runs after `lsq.step()` within a cycle (execute.cc:2519 vs commit); the flush at execute.cc:1181 precedes `tryToBranch`, which forces a branch (`IsSerializeAfter`, `force_branch` execute.cc:322) so younger instructions are discarded; wrong-stream requests abort before the bypass. | `syscall-negative` (stale consumed without the flush, not with). | aligned with the safety goal | A younger load can bypass with old bytes in the cycle of the syscall commit but is in the discarded stream. | None. |
| C10 | – | What depends on SE/MinorCPU. | See §5 below. | – | – | – | – |

### 2.4 Strict verification (`enableVAstraVerify`)

| # | Paper | Expected | Implementation | Test / evidence | Class | Rationale | Action |
|---|---|---|---|---|---|---|---|
| S1 | §IV-B (75): "explicitly checking the predicted value against the load data when it returns" is the alternative to address-only validation. | A value check against real data. | `vastraValidate` execute.cc:2455–2518: a byte-valid candidate must equal the bytes the real load read, else `panic`. Mutually exclusive with bypass: `fatal_if(enableVAstraBypass && enableVAstraVerify)` execute.cc:169; requirements execute.cc:165; `vastraTestSkipSyscallFlush` constrained execute.cc:174–177; `vastraTestSkipStoreScan` forbidden with bypass execute.cc:179. | `config` mode: 5 invalid combinations rejected, valid accepted; config.ini shows both test-only flags false in a normal run; verify-detect X2 rc 134; syscall-negative X rc 134. Stage 2a: 5,642 candidates verified (stage2a report). | aligned (independent oracle when bypass is off) | Strict verification compares V$ bytes with bytes a **real** memory request returned; with bypass on no such request exists, so the self-comparison cannot happen — it is a fatal configuration error. | Concern 3 (§6). |

---

## 3. V$ and coherence summary (separating paper, adaptation, untested)

| Topic | Stated in the paper | Our choice | Untested |
|---|---|---|---|
| Geometry | 256 × 16 B, 8-bit index, 4-bit offset, direct-mapped | same | – |
| Tags | compressed (5-bit ID + 8 bits) | full virtual tag | ID recycling |
| Synonyms | "limit V$ to a single page" | virtual tag, page-offset index | **two mappings of one page** |
| Context switch | PID in tag or flush | one process; flush at syscalls | context switches (none in SE) |
| Allocation / update | load allocates at retire if cacheable; stores update matching entries | same | – |
| Byte validity | not stated | per byte | – |
| Neighbour doubleword | "naturally prefetches" | not filled | – |
| Atomics/special | silent | invalidate touched bytes | atomic conflict with bypass |
| Uncacheable | "if cacheable" | not allocated; invalidate | **any uncacheable access** |
| In-flight stores | CBF + invalidation FIFO | exact scan + LSQ gating | unknown-address path (unreachable) |
| Remote writes | invalidate entry | none (single core) | **multi-core/shared memory** |
| Memory changed outside the LSQ | not applicable | flush at `ecall` | pseudo-ops, devices |

## 4. Test-quality classification

| Tests | What they establish |
|---|---|
| `run_astra.sh` (78), `astra_targeted` (340) | **Internal consistency** with `astra.hh`'s documented inferences (golden model re-implements them); architecture/trace noninterference (functional correctness of the shadow); lifecycle identities. They are **not** evidence that the inferences are the paper's. `invalid-config`: configuration checks. `squash`, `fault`: functional behaviour of the lifecycle. |
| `run_vcache.sh` (157) | Internal consistency with the V$ model (every line and statistic replays), architectural noninterference. Geometry is checked against the paper's numbers only by the constants. |
| `run_vastra.sh` (276) | Probe classification vs a model; **stale-candidate detection** (`verify-detect`): shows the scan prevents real stale candidates (6 stale byte-valid hits without it) and strict verification catches them. Strongest independent safety evidence for the decision rules. |
| `run_bypass.sh` (274) | **Safety of the real synthetic path**: output, committed trace and instruction counts equal bypass-off in 9 workloads plus drain/reset variants; per-load request suppression and single completion from the MinorMem trace; read-access count falls by exactly the suppressed count; syscall flush necessity (negative control); per-window accounting; LVP coexistence (510 wrong predictions still recovered, checksum equal). The latency test is a **measurement**, not a correctness test. |
| `syscall-negative` | A **known limitation / negative control**: it passes only when the hazard is reproduced (21 stale values = program error count; X stops with candidate = OLD(i), actual = NEW(i)). |
| LVP suite (existing) | LVP behaviour (outside this audit's scope); its counts are unchanged. |
| Anything establishing agreement with an explicit paper requirement | Only Table II constants (entries, sizes) and the A1/A3/V1/V5 structural rules; none of A4–A7, V3–V4 is paper-established. |

Quality limits found:
* No test makes ASTRA's predictions agree with an *independent* implementation of the paper (none exists).
* `bypassAbandoned_`, `fbOlderStore`, `rejStoreUnknown`, `fbUnsupported`, `fbEaMismatch` are 0 in every test — the corresponding branches are never exercised.
* Whole-run `numCycles` is not a stable measure for the latency workload (it varies up to ~3% with layout); the per-walk span measurement (2,279 cycles saved, 0.44% of walk time; walks after eviction −591/−779/−901 cycles; L1-hit walks unchanged) is the retained measurement (Stage 2b.1 report; reproduced by `bypass-final.log`: "each walk after the eviction is faster … saved [591, 779, 901] cycles").
* One retained log (`regression/bypass.log`) contains a FAIL line from a superseded assertion; the current evidence is `bypass-final.log`. The `regression/` run itself was not repeated after the checker change (source unchanged).

## 5. What depends on RISC-V SE mode or on this MinorCPU model

Source-derived facts:
* RISC-V: base register = first source; `EA = rvZext(Rs1 + offset)`; immediate field `machInst.imm12`; `ecall` is the only `IsSyscall` instruction and `IsSerializeAfter`.
* MinorCPU: registers are written at commit; dependents execute at commit (`scoreboard` is timing only, loads `extraAssumedLat=2`); memory operations reach the LSQ from the front of `inFUMemInsts`; a load needs `numStoresInTransfers == 0` and a store-buffer check before it can issue; `lsq.step()` precedes `commit()` each cycle.
* SE mode: syscalls modify memory through the functional proxy; no uncacheable memory in these runs; one process.
Judgments: the "unknown older store address" unreachability, the absence of an invalidation FIFO, and the choice of "validate at execute/LSQ" rest on those facts; they do not transfer to an out-of-order or full-system model.

## 6. Findings

### 6.A Genuine correctness concerns (ranked)

1. **Virtual-synonym staleness in the V$** (V3). A store through one virtual alias updates only a matching-tag entry; a resident entry for another alias of the same physical bytes stays stale and can be bypassed. The paper's single-page rule does not say how stores reach that entry. *Risk now:* low (SE benchmarks, one mapping), but unproven. *Judgment:* either invalidate the set on any retiring store to that set or add a physical tag; needs a decision (D5).
2. **No guard against several CPUs / shared memory** (V8). `enableVCache` checks one thread only. With two CPUs sharing memory the V$ would be stale after remote writes and the bypass would consume it. Unsupported by design, but nothing refuses it.
3. **No independent in-simulation oracle when bypass is on.** Correctness of the bypass is established by differential testing (committed trace equality) and by a negative control; strict verification is correctly forbidden with bypass. Two safety branches were never taken (`bypassAbandoned_`, LSQ re-scan fallback), so they are untested code. A functional-read oracle (proposed in Stage 2b design) was not built.
4. **FP loads are bypass-eligible and untested** (A11, C6). `flh/flw/fld` use `format Load`, so they are `RiscvISA::Load`; ASTRA trains on them and the bypass can complete them. `completeAcc` should handle NaN-boxing from the raw bytes, but no test runs an FP load.
5. **Older atomic conflicts untested.** Atomics are placed in `vastraStores`, but the conflict path is exercised only with plain stores.

### 6.B Coverage/accuracy gaps that are not correctness bugs
* Compressed (RVC) loads never become candidates (`vastraEffectiveAddress` rejects them); binaries built with `rv64gc` would lose most V-ASTRA coverage. Tests use `rv64g`.
* ASTRA's lookup-to-training lag is larger than in the paper (A9).
* No neighbour-doubleword fill (V4).
* Address generation and TLB access still happen (C7); the benefit is earlier commit, not 0-cycle load-use (C2/C3).

### 6.C Deliberate MinorCPU adaptations
Full-width base in LAT (A2/A6); 64-bit prediction arithmetic; lookup at issue; per-byte valid bits; full virtual tag; exact older-store scan replacing CBF + FIFO; decision at `executeMemRefInst` plus re-check at LSQ send; syscall flush; V$ not updated by bypassed loads; ASTRA training skipped under an LVP-speculative source; squash-and-refetch LVP recovery instead of scoreboard replay; strict verification forbidden with bypass.

### 6.D Ambiguities needing a design decision
* D1 LAT content in the enhanced variant: base (current) vs effective address.
* D2 SS index from a 16-bit stride ("sized accordingly"): low n bits (current).
* D3 Cold start: zero (current) vs valid bits.
* D4 Where to validate and where the benefit arises (issue-stage emulation vs commit-time).
* D5 Synonym handling (see concern 1).
* D6 Scope: FP loads and compressed loads (decode the RVC immediate or exclude explicitly).
* D7 Whether allocation should fill the neighbouring doubleword (needs a data source).
* D8 Whether a V-ASTRA-hit load should update the V$ (paper silent).
* Stride sign (A5): wording vs consistency — recorded, no action.

### 6.E Missing tests that matter
1. Two virtual mappings of one page (mmap twice) with a store through one and a bypass-eligible load through the other.
2. A bypass-eligible FP load (`fld`/`flw`) with checksum equality.
3. An older **atomic** overlapping the candidate load.
4. A workload that triggers `bypassAbandoned_` (an older load or store retiring between decision and send).
5. Stride overflow/wrap (> ±32 KiB, and a 1 MiB boundary) against the model.
6. A configuration test that refuses (or documents) multi-CPU use.
7. An RVC-built workload (documents the exclusion).
8. A second-path check of the stride sign (a literal paper-reading mode would need a switch; not recommended).

### 6.F Acceptance criteria before META
* Decisions D1–D8 recorded (at least D4, D5, D6).
* Concern 2 closed (guard) and concern 1 closed or explicitly scoped out in the README.
* Tests 1–4 of §6.E present and passing; branches counted by `bypassAbandoned_` and `fbOlderStore` exercised at least once, or documented as unreachable with an assertion.
* Optional but recommended: a functional-memory oracle for bypass runs.
* The latency measurement quoted only as per-walk span (not whole-run cycles), and no comparison of coverage/speedup with the paper's numbers.

## 7. Scope of the paper vs the implementation

| Element | Paper (PDF p.) | Status here | Significance |
|---|---|---|---|
| META (V-ASTRA + LVP, selected at issue) | §IV-E, 7 (77) | not implemented | Out of scope now; LVP exists separately (squash recovery). Selection rule (V-ASTRA if base right and V$ hit, else saturated LVP) is not wired. |
| LACT / compressor / tag compression | §IV-C, 6–7 (76–77) | not implemented | Storage optimisation; no correctness role (recycling invalidation and the "overflow ⇒ reject" rule vanish). |
| L0 minicache (M$) | §IV-F, 8 (78) | not implemented | Gives store-forwarding for rejected loads and speeds locality; absent, so conflict-rejected loads go to memory. |
| Issue-time validation and dependent speculation | §IV-B, §IV-E1, 5–8 | validation at execute/LSQ; dependents not speculated | The dominant source of the paper's speedup is absent. |
| CBF and in-flight invalidation FIFO | §IV-D, 7 (77), Fig. 4 | exact scan | Adaptation; safe under MinorCPU ordering invariants (§5). |
| Scoreboard replay | §IV-E1, 7–8 | not applicable (LVP squash) | Not needed for V-ASTRA (no repair). |
| CVA6, SPEC CPU2017 simpoints, full-system gem5 | §V, 10–11 | MinorCPU, SE mode, micro-workloads | No claim of equivalence with the paper's results is justified. |
| Multiprocessor coherence | §IV-H, 9–10 | not supported | Unsupported and unguarded (concern 2). |
| Security (flush on privilege change) | §IV-I, 10 | n/a in SE | – |

## 8. Recommended next action
Do not start META. First, in this order: (1) decide D4–D6; (2) add the multi-CPU guard (or document and assert single-CPU); (3) add the missing tests 1–4 of §6.E, which exercise code that currently has no coverage; (4) decide the synonym policy (D5) and, if fixed, regression-test it; (5) then proceed to META selection on top of the bypass, using the existing differential and negative-control infrastructure. Nothing in this pass was changed.

## 9. Integrity
See the final section appended by the verification step (initial/final Git status, index, stash, `__pycache__`, backup checksums).

---

## 10. Integrity verification (performed at the end of the audit)

* Git HEAD `ce1a9fdf5b…` before and after; `git status --short` identical before and after (same modified and untracked entries); index empty (0 lines of `git diff --cached --stat`); stash list empty before and after.
* A SHA-256 of every file under `tests/`, `src/cpu/minor/` and `configs/research/`, plus the listing and hashes of `tests/astra/__pycache__/*`, was taken before and after: `run1/state-before.txt` and `run1/state-after.txt` are **byte-identical**. No tracked or untracked repository file changed; the `__pycache__` bytecode files were preserved.
* ASTRA backup `~/gem5-astra-backup-2026-10-18/`: 12 checksums OK, none failed, before and after.
* No simulator was run and nothing was built during this audit.
* Everything written is outside the repository: this report, `paper/` (copy of the PDF and per-page text), `snapshot-source/` (copies of the audited sources and checkers), `run1/` (state files), in `~/gem5-validation-2026-10-23/vastra-stage2b-implementation/paper-fidelity-audit/`.
