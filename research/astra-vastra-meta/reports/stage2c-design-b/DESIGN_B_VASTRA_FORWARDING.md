# Design B: forwarding a validated V-ASTRA value to dependent loads (design and feasibility study)

Written for: the researcher deciding whether to implement Design B on MinorCPU before META.
Strictly read-only study of `~/gem5` (branch `vp-lvp-dev`, HEAD `ce1a9fdf5b`, all earlier stages uncommitted, Design A built and tested). Nothing was built, run, edited, staged or committed. Source snapshots are in `snapshot-source/`.

Conventions: **Fact** = read from the current checkout (file:function:line, lines are current as of this study and approximate to a few lines where marked `~`). **Judgment** = my engineering opinion. Paper citations: `PDF p.N (printed N+70)`.

---

## 0. Summary

1. **A dependent load can consume a validated V-ASTRA value early; the machinery to do it already exists for LVP, but it cannot be reused unchanged.** The LVP operand override binds a *predicted* value to a consumer **at the consumer's issue**, from the producer's issue, and admits the consumer only when the producer is the **head** of the in-flight queue (so that a wrong prediction is caught by the producer's response before the consumer can commit). A V-ASTRA value does not exist at the producer's issue: it exists only at the producer's **final bypass success**, which happens at `executeMemRefInst`/`tryToSendToTransfers`, after the producer has left the issue stage, and it is final (never wrong afterwards), so the producer need not be the head and no recovery path is needed. The binding therefore has to be made **late** (at admission) from a per-producer record, not at issue.
2. **The exact event that makes the value available is the success branch of `vastraTryBypass`** (`execute.cc:2267`, the same place where Design A releases the scoreboard). It is not the synthetic response as such and not the producer's decision (`vastraDecide`, 2401), which is a snapshot that can still be abandoned at the LSQ send point.
3. **The "dependent reaches the issue path before validation" case is common** (the producer's request can wait in the LSQ behind an older request or a store in the transfers queue) **and must stall**: the consumer is not admitted while the producer's record is *pending*; it is admitted when the record becomes *validated*, and falls back to the normal rule (wait for the producer's commit) if the record becomes *failed*. No deadlock: the producer's outcome does not depend on the consumer.
4. **Recommendation: Option A, a V-ASTRA twin of the LVP override** (new `vaFwd*` fields, a per-thread map keyed by producer execSeqNum, a new admission function next to `lvpSpecAdmissible`, a scope guard like `LVPSpecOperandScope`), **with the first slice made mutually exclusive with `lvpSpecAddr`**. Option B (one shared validated-prediction mechanism for LVP and V-ASTRA) is the right shape for META but means refactoring tested LVP code; do it with META, not before.
5. **What it achieves**: dependent loads form their effective address and **send their memory request before the producer commits**, overlapping their latency with whatever holds the head. This is the first change in Stages 2b–2c that can plausibly move end-to-end time, because it moves *memory requests*, not scoreboard readiness. **What it does not achieve**: dependent ALU instructions still execute at commit (execute-at-commit is unchanged), which needs a separate result-buffer design.
6. **Go** for Option A slice 1, under the conditions in §10.

---

## 1. Current dataflow (facts)

### 1.1 The current V-ASTRA path (Stages 2b to 2c.2)
1. The load is issued (`Execute::issue`, `execute.cc:723`): `astraOnIssue` looks up the predicted base; `vastraOnIssue` records stores. The load enters the Mem FU and `inFUMemInsts`; `instToWaitFor = scoreboard.execSeqNumToWaitFor(inst)` = the youngest writer of its single source register (`execute.cc:~900`), `canEarlyIssue = true`.
2. In `commit()` (`execute.cc:1259`), the early-issue block (`~1398–1445`) picks the front of `inFUMemInsts`/Mem FU end (`fu_inst`) when it is not yet in the LSQ, is in the right stream, and `deps_satisfied = head_exec_seq_num > fu_inst->instToWaitFor` (all producers committed) or the LVP-spec admission holds.
3. `commitInst` → `executeMemRefInst` (`606`): `astraCaptureBase` (2018) reads the architectural base register (skipped when `lvpSpecActive`), `vastraDecide` (2401) builds a candidate (base right, immediate decoded, older-store scan, V$ snapshot), then `initiateAcc` builds the LSQ request; the request is popped from `inFUMemInsts` (`~1609`).
4. `initiateAcc` → `LSQ::pushRequest` → synchronous translation → `SingleDataRequest::finish` → `tryToSendToTransfers` (`lsq.cc:~294`, hook at `~1122`) → **`vastraTryBypass`** (2267): support predicate, address equality, store rescan, byte-valid snapshot, fresh V$ lookup; on success `makeResponse`, `vaBypassed = true`, then (Design A) the scoreboard release. `tryToSendToTransfers` returns **before** the hook whenever the request is not at the front of `requests`, a store is in the transfers queue (`numStoresInTransfers != 0`, `lsq.cc:~1036`), the request is still in translation, the memory system needs a retry, or the transfers queue is full. In those cases the validation is **deferred**: the producer has left `inFUMemInsts` but has neither bypassed nor fallen back.
5. The response is at the front of `transfers` and is committed when the load reaches the head of `inFlightInsts` (`handleMemResponse`, 429).
So the validated value exists exactly from the success branch of 4 until the producer's commit; nothing else in the pipeline can see it today.

### 1.2 The LVP precedent (all references current)
| Behaviour | Where |
|---|---|
| Prediction made at the **producer's issue**; recorded per thread in `lvpSpecMap[tid][flattened dest reg] = {producerSeq, producerPC, value}` | `lvpOnIssue` (1761), step 3; `execute.hh:163–173` (`LVPSpecEntry`, `lvpSpecMap`) |
| A later writer of that register erases the entry (so the map always names the youngest older writer) | `lvpInvalidateDests` (1748), `lvpOnIssue` step 2 |
| **Consumer binding at the consumer's issue**: an eligible consumer (`lvpEligibleConsumer`: ordinary int load, exactly one int source) takes the entry for its source register only if `entry.producerSeq == inst->instToWaitFor` and both PCs are in the speculation window; it copies `lvpSpecProducer`, `lvpSpecSrcIdx = 0`, `lvpSpecSrcVal`, `lvpSpecSrcReg` into the dynamic instruction | `lvpOnIssue` step 1 (`~1775–1795`); fields `dyn_inst.hh:277–301` |
| **Admission**: the consumer is the front of `inFUMemInsts` (`fu_inst == head_mem_ref_inst`), has a bound producer that equals `instToWaitFor`, and the producer is the **head** of the in-flight queue, was predicted, is outstanding in the LSQ without a response, all in the current stream | `lvpSpecAdmissible` (1821); call in the early-issue block (`~1415`) |
| **Application**: `LVPSpecOperandScope` (1232) sets `lvpSpecActive` only around `commitInst`; `ExecContext::getRegOperand` returns `lvpSpecSrcVal` iff `lvpSpecActive && idx == lvpSpecSrcIdx && si == inst->staticInst && reg == lvpSpecSrcReg` (`exec_context.hh:147–163`); nothing is written to the register file | |
| The consumer's **effective address** is therefore computed by the ISA's own `initiateAcc` (`EA = rvZext(Rs1 + offset)`, `Rs1` = the override); `astraCaptureBase` returns early under the override so ASTRA neither trains nor decides on a speculative base | `execute.cc:2018–2026` |
| After `initiateAcc`, if the request is in the LSQ the consumer becomes `lvpConsState = Accepted` | `executeMemRefInst` (`~668`) |
| **Actual vs predicted**: the register file always holds actual values; the predicted value exists only in the override and the dynamic instruction's `lvpSpecSrcVal` | |
| **Validation**: at the producer's response (`lvpValidateProducer`, 1858, in `handleMemResponse` before the register effects) it compares the actual loaded register with `lvpPredValue`, trains LVP, and `recover = !correct && lvpUsedBySpec` | |
| **Recovery**: `updateBranchData(UnpredictedBranch, ...)` to the load's next PC (`handleMemResponse ~559`), squash and refetch; `lvpRedirect` marks it for Fetch2; `lvpSpecMap[tid].clear()` on every stream change (`updateBranchData`, `~410`) | |
| **Consumer safety net**: before `completeAcc`, if `lvpConsState == Accepted` the register file's source must equal `lvpSpecSrcVal` (panic otherwise) | `handleMemResponse` (`~459`) |
| **Outcomes**: every producer and consumer ends in exactly one terminal state (retired, squashed, faulted) | `lvpClassify` (1887), statistics identities in `lvp.hh` |
| Faults: a translation fault on a wrongly predicted address is suppressed at `initiateAcc` and taken at the response like any load's | `executeMemRefInst` (`~632–645`), `handleMemResponse` |

### 1.3 Does the LVP mechanism fit a V-ASTRA value? (assumptions that differ)
| LVP assumption | V-ASTRA |
|---|---|
| Value known at the producer's **issue** | Known only at the producer's final bypass success, later and possibly much later (deferred validation, §1.1 item 4) |
| Binding at the **consumer's issue** from a map filled at the producer's issue | Consumer may issue before the value exists; the binding has to be made at admission by `producerSeq` |
| Producer must be the **head**, outstanding, predicted: the value may be wrong and is checked at the producer's response, which precedes any consumer commit | Value is **final**; the producer may be anywhere in the in-flight queue; requiring head would remove the benefit |
| Recovery by squash and refetch | None needed; a mismatch is a bug and must panic |
| The base is *not* trusted: `astraCaptureBase` skips, the consumer cannot train/decide | The base is final, so the consumer **should** be a full ASTRA/V-ASTRA participant (this is what makes chains possible) |
| Translation faults on a speculative address are suppressed | An address built from a validated value is real: a fault is an architectural fault, taken in order |
So: the *infrastructure* (per-instruction override, scope guard, `getRegOperand` check, early-issue block, consumer outcome accounting) is reusable; the *binding time*, *admission rule*, *ASTRA capture rule*, *fault rule* and *recovery* differ.

---

## 2. The validation-to-forwarding ordering (proposed)

Let `P` be the producer load, `C` its dependent load (one integer source, `C.instToWaitFor == P`), `M` an older instruction holding the head.

1. **P decided** (`vastraDecide`, 2401, at `executeMemRefInst`): creates the per-thread record `fwdMap[P.execSeq] = {state = Pending, destReg (flattened), stream}` (candidates only).
2. **P's request built; validation possibly deferred.** The record stays `Pending`.
3. **P's final success** (success branch of `vastraTryBypass`, 2267): response made, `vaBypassed = true`; the register value is computed from the V$ bytes by the load's opcode (`lb lbu lh lhu lw lwu ld`; FP excluded) into `vaRegValue`; **then** `fwdMap[P].state = Validated`, `value = vaRegValue`. Design A's scoreboard release happens at the same place and is independent of this.
4. **Failure paths** (`fallback(...)`, abandoned, unsupported, address mismatch, store re-scan, no candidate): `fwdMap[P].state = Failed`. A load that is never a candidate has no record.
5. **C admission** (new, in the early-issue block next to the LVP admission): C is the front of `inFUMemInsts`, at the end of the Mem FU, not in the LSQ, right stream, and `fwdMap[C.instToWaitFor]` exists with `stream == C's`, `destReg == flatten(C.src0)`, and:
   * `Validated` → admit with `value`;
   * `Pending` → **not admitted this cycle** (stall); re-evaluated every cycle;
   * `Failed`/absent → not admitted (the ordinary `deps_satisfied` rule applies, i.e. after P's commit).
6. **Application**: a scope guard sets `C.vaFwdActive` (value, reg, idx 0) only around `commitInst`; `getRegOperand` returns the value for exactly that operand of exactly that instruction; `initiateAcc` computes `EA = rvZext(value + sext(imm12))` through the ISA code; `astraCaptureBase` captures the **forwarded** value as `astraActualBase` (valid, because final) so C can itself be decided and bypassed, and trained at its retirement.
7. **Hand-over**: after `initiateAcc`, if C is in the LSQ, `C.vaFwdState = Accepted`, `C.vaFwdProducer = P.execSeq`, `C.vaFwdSrcVal = value`. If C itself reaches final success its own record becomes `Validated` (chain).
8. **Retirement** (in order, unchanged): P commits first (older, response at the front of `transfers`), then C (its own response behind it). Before `completeAcc` of C: `panic_if(thread.getReg(src) != C.vaFwdSrcVal)` (the producer has committed by then). `fwdMap[P]` is erased when P pops (`vastraPop`, 2468, for commit, discard and fault alike); C's consumer outcome is classified at its pop.

**Earliest timing**: P's success and C's admission are at least one cycle apart (C must reach the Mem FU end after P's slot is freed; FU pipelines advance one stage per cycle), and `executeMemoryIssueLimit = 1` allows one early memory issue per cycle, so a chain advances at most one link per cycle.

### The harder case: C is ready before P's validation
Facts: P leaves `inFUMemInsts` at `executeMemRefInst`, i.e. before a deferred validation; C is then the front and may reach the FU end. Handling (judgment, sound): **stall**. Reasons: forwarding the *decision snapshot* before the final checks would hand C a value that can still be abandoned or rejected (V$ entry replaced, store re-scan), which needs LVP-style recovery; and a stalled C costs nothing relative to today (it waits for P's commit anyway). A *wake-up* design (C is admitted when the record flips to `Validated`) is what the per-cycle re-evaluation already gives. Under stall-on-use timing (`vp_stall_on_use.py`) C cannot even issue before P's release (Design A), which happens at the same event, so Design B in that configuration **requires Design A** (otherwise C never reaches the FU end); in the default timing C is already waiting in the FU and Design B works alone.

---

## 3. Options

### Option A: V-ASTRA twin of the LVP override (recommended)
**Data structures** (new, nothing in LVP changes except one exclusion):
* `execute.hh`: `struct VAFwdEntry {enum {Pending, Validated, Failed} state; RegId destReg; RegVal value; uint64_t stream;}` and `std::vector<std::map<InstSeqNum, VAFwdEntry>> vaFwdMap` (per thread, keyed by **producer execSeqNum**).
* `dyn_inst.hh`: producer: `vaRegValue`, `vaRegValid`; consumer: `vaFwdProducer`, `vaFwdSrcVal`, `vaFwdSrcReg`, `vaFwdActive` (scoped), `vaFwdState {None, Accepted, Done}`.
* `BaseMinorCPU.py`: `enableVAstraForward` (default False; needs `enableVAstraBypass`; fatal together with `lvpSpecAddr` in slice 1).
* `vastra.hh/.cc`: counters `fwdAdmitted`, `fwdCommitted`, `fwdSquashed`, `fwdFaulted`, `fwdBlockedPending`, `fwdBlockedFailed`, plus `valuesPublished`.
**Functions to change**: `vastraDecide` (create record), `vastraTryBypass` (publish `Validated` at success; mark `Failed` at every fallback/abandon; compute `vaRegValue`), `commit()` early-issue block (admission, scope guard), a new `vastraFwdAdmissible`, `ExecContext::getRegOperand` (second override condition), `astraCaptureBase` (capture under a *V-ASTRA* override, skip only under the LVP override), `executeMemRefInst` (consumer `Accepted`), `handleMemResponse` (consumer check), `vastraPop` (erase record, classify consumer), `isDrained` (map empty, no consumer live), `updateBranchData` (nothing to clear: records are keyed by seq and checked against the stream).
**Producer/consumer link**: by execSeqNum: `C.instToWaitFor` (set at C's issue from the scoreboard's `writingInst`, the youngest older writer of its only source) names P; the record carries P's flattened destination register and stream; both are compared at admission. No pointer to P is stored (no use-after-free).
**Many in-flight loads and chains**: one record per candidate producer; a consumer looks up exactly one key; a chain P→C→E works because C publishes its own record when its own bypass succeeds; unrelated loads have different keys.
**No leaks to an unrelated or later instance**: the key is a unique per-thread sequence number, the override is bound to `(si, idx, reg)` of one dynamic instruction and active only inside the scope guard, records are erased at the producer's pop.
**Effective address**: the ISA's own `initiateAcc` with the override (no V-ASTRA-specific address code); the consumer's immediate is the non-speculative one.
**Blocking**: store conflicts, V$ misses, base mismatches and stale candidates all end in `Failed`/no record (no `Validated` is published): a stale or abandoned candidate cannot forward. Only the final success publishes.
**Producer fallback / squash / fault / stream change / drain / reset**: fallback → `Failed` (C waits for P's commit); squash → the stream check blocks admission, records vanish at pop, C (younger) is discarded with P, and an accepted C is classified `Squashed`; translation fault of C → taken in order at its response (not suppressed: the address is real); P cannot be a faulting load (the hook is after a successful translation); drain → `isDrained` asserts empty map and no live consumer; statistics reset → counters only, live counts survive like the other lifecycle counters.
**In-order retirement and state**: unchanged: C's response is behind P's in `transfers`; no register is written before commit; the commit-time check is a safety net, not a recovery path.
**Risks**: stale operand (the `instToWaitFor` + register + stream check; consumer check at commit); duplicate completion (C's request is created once; admission requires `!fu_inst->inLSQ`); deadlock (a stalled C waits on P's *validation*, which does not depend on C; if P fails or commits the ordinary rule applies); interaction with LVP (excluded in slice 1); interaction with Design A (independent, composable); consumer's request stuck behind P's in the requests FIFO (then it is not earlier, harmless).
**Expected performance mechanism**: C's memory request starts when P is validated instead of when P commits; benefit is the overlap of C's latency with whatever holds the head (e.g. an older DRAM miss) and, along a chain, one link per cycle instead of one link per commit.

### Option B: a shared validated-prediction forwarding mechanism
One `ForwardedOperand {producerSeq, source = {LVP, VASTRA}, validated, value, destReg, stream}` per producer, one admission function with two rules (LVP: producer is the head and unvalidated, recovery needed; V-ASTRA: validated), one consumer state machine (`Accepted → Done`), one set of counters and identities, one `getRegOperand` condition, one `isDrained` check. Advantages: no duplicate machinery; META chooses per producer which source publishes (validated V-ASTRA beats a predicted LVP value, paper IV-E, PDF 7 (77)); the per-producer identity "exactly one source" is natural. Costs: refactors `lvpOnIssue`, `lvpSpecAdmissible`, `lvpClassify`, `handleMemResponse` and the LVP counters used by about 1,300 passing checks; any behavioural drift in LVP is a regression risk; it also forces the late-binding design on LVP, which does not need it.
**Judgment**: B is the right *end state* but not the smallest safe step. Build A with an interface that META can absorb: `{producerSeq, source, validated, value, destReg, stream}` in the record, so that B is a refactor, not a redesign.

### Comparison
| | Option A (twin) | Option B (shared) |
|---|---|---|
| LVP code touched | one exclusion check | substantial refactor |
| Source size | medium | large |
| Regression risk to existing suites | low | medium |
| Fit for META | needs a later merge | direct |
| Safe without broader pipeline change | yes | yes, with the refactor |
**Recommendation**: Option A, slice 1, mutually exclusive with `lvpSpecAddr`; revisit B with META.

---

## 4. Minimal vertical slice (Option A) and its tests

Configuration: run each workload with the feature off (P) and on (R), in the **default** timing configuration (where C is already waiting in the FU) and, for the stall-on-use case, with Design A on as well. ASTRA, V$, bypass on in both. Traces: `MinorExecute`, `MinorMem`, `VBypass`, `VAstra`, `ExecEnable`, plus new `VBypass fwd` lines (publish, admit with value and tick, blocked-pending, blocked-failed, accepted/outcome). Counters are supporting evidence only.

Workload shape (new `forward.c`, sections like `release.c`): an older DRAM-missing load `M` holds the head; then `P: ld t1,0(a0)` (a pointer, V$-warm, stride 64, candidate), `C: ld t2,0(t1)` (dependent, base = P's result), `E: ld t3,0(t2)` (second link), independent `I1 I2`, a use `D: add t4,t3,t5`.

| # | Case | Required trace events | Invariants the checker enforces |
|---|---|---|---|
| 1 | Delayed older load, producer validated | `VBypass exec` (success) for P, `fwd publish exec P value V` at the same tick | publish tick == success tick; value == the register value P commits later; exactly one publish per bypassed producer |
| 2 | Dependent load issues its request before the producer's normal completion | R: `Trying to send request` (or `Pushing request`) for C at tick T_C, with T_C < P's commit tick and >= publish tick + 1; P: the same request at P's commit tick or later | T_C(R) < T_C(P) and T_C(R) < P.commit; C's `Memory response inst` tick earlier than in P-run; C's response is not processed before P's commit (in order) |
| 3 | Chain P→C→E | publish P, admit C, publish C (C is a candidate), admit E | publish(P) < admit(C) <= publish(C) < admit(E), one link per cycle at most; E's request before P's commit |
| 4 | Producer with a wrong base prediction (`bw` section) | `VAstra decide ... basewrong` for P; no publish | no admit for its consumer; C's request tick == P's commit tick (same as the feature-off run) |
| 5 | V$ tag miss; older-store conflict | `tagmiss` outcome / `storeconflict` decision; record `Failed`; `blocked-failed` | no admit; C waits for the producer's commit; real request for P |
| 6 | C ready before the producer's validation | P's request deferred (older store in transfers, as in `abandon`/`order`); C at the FU end: `blocked-pending` lines until P resolves; then either `publish`+`admit` (late) or `Failed` | no admit while pending (every `admit` tick > its `publish` tick); no consumer request before its producer's record is `Validated`; abandon case ends `Failed` and C waits for P's commit |
| 7 | Architectural equivalence | all runs | output, committed instruction stream and instruction counts identical P vs R |
| 8 | The memory request really moves earlier | `Trying to send request` ticks | for admitted consumers: T_C(R) + (P commit − publish) ~ T_C(P) ; reported as a measurement; no assertion on `numCycles` |
| 9 | Exactly-once completion, drain, squash | `Deleting load request` once, one `Memory response` per load; `fwd accepted`/`outcome` once per accepted consumer; wrong-path consumer (discard program): `Squashed`; drain and reset variants | consumer `Accepted` count == committed + squashed + faulted + live; `isDrained` finds an empty map and no live consumer; a squashed consumer's request is deleted once; the commit-time check never fires |
Additional: the **negative controls** of the existing style: (a) a damaged-trace self-test of the new accounting; (b) a test-only switch that publishes **before** final success (the decision snapshot) would let an abandoned candidate forward and must be caught by the consumer check at commit (only if a fault-injection parameter is considered acceptable; otherwise rely on (a) and on the structural argument, as the audit did for fallbacks).
The measurable section (a non-candidate `C` on a cold line behind a candidate `P`, an older DRAM miss `M` at the head) is where an end-to-end effect is expected: `C`'s DRAM latency is overlapped with `M`'s instead of added to it.

---

## 5. State and lifecycle requirements

Per dynamic instruction (all reset at construction, like the existing `va*`/`lvp*` fields):
* producer: `vaRegValue`, `vaRegValid` (set only at final success).
* consumer: `vaFwdProducer`, `vaFwdSrcVal`, `vaFwdSrcReg`, `vaFwdActive` (only inside the scope guard), `vaFwdState {None, Accepted, Done}`.
Per thread: `vaFwdMap` (producer seq → `{state, destReg, value, stream}`), entry created at decision, updated at final success or any failure, erased at the producer's pop.
Invariants: (I1) a `Validated` record exists only after `vaBypassed` is set; (I2) the override value equals the producer's final architectural register value; (I3) a consumer is `Accepted` at most once and reaches exactly one outcome; (I4) the map is empty and no consumer is live when drained; (I5) no record outlives its producer's pop; (I6) `vaFwdActive` is false outside the scope; (I7) no forward happens in a configuration with `lvpSpecAddr` (slice 1).

---

## 6. Relationship to the paper

* **Achieved** (if built): a validated value reaches a dependent *load* before the producer completes, so the dependent can issue its memory request earlier, as in the paper's issue-time forwarding (IV-B, PDF 5–6 (75–76): "the waiting time of the dependent load will be zero"). Validation remains at execute/LSQ, not at issue (Stage 2c finding: Minor has no operand values at issue).
* **Not achieved**: dependent ALU instructions. In MinorCPU an ALU instruction reads its operands and writes its result only in `commitInst` (`execute.cc:1072`), which is at in-order commit; forwarding a value to it cannot make it execute earlier. Doing so needs a **separate execution-result-buffer design**: execute the dependent early with the forwarded operand through a result-capturing `ExecContext`, restrict it to side-effect-free instruction classes, and write the buffered result (or re-execute with an assertion) at commit; plus the scoreboard/FU timing to represent the early completion. That is a distinct stage with its own safety argument; this study does not recommend starting it now.
* **Not in scope**: META (it will need the shared record of Option B), LACT, the minicache, RVC, multi-CPU.

---

## 7. Failure handling summary

| Event | Behaviour |
|---|---|
| P falls back / abandoned / unsupported | record `Failed`; consumers wait for P's commit; nothing forwarded |
| P base mismatch, V$ miss, store conflict | no record (decision rejected) or `Failed`; same |
| P pending (validation deferred) | record `Pending`; consumer stalls; re-evaluated each cycle |
| P squashed / stream change | stream check blocks admission; record erased at pop; accepted consumers (younger) are discarded and counted `Squashed` |
| C translation fault | architectural; taken at C's response in order (the address was real) |
| C wrong stream when admitted | not admitted (stream check) |
| Drain | `isDrained` asserts empty map, no live consumer |
| Statistics reset | counters only; live counts carry over |
| Bug: forwarded != committed value | `panic` at C's response (never a recovery) |

---

## 8. Risks and limitations
* The consumer's ASTRA capture under a V-ASTRA override is a deliberate difference from LVP (it trains on a validated value); it must not be enabled under the LVP override.
* A deferred producer (pending) can stall a ready consumer for a long time; this is the same as today but now visible in counters (`fwdBlockedPending`).
* Design B only affects loads whose single source is a load result; pointer chains, array-of-pointers and indirect loads are the target; other dependents see no change.
* One early memory issue per cycle (baseline limit); the paper issues two loads per cycle.
* Under stall-on-use timing Design B needs Design A; under default timing it works alone, but the earlier-issue effect then also exists without any V-ASTRA.
* Gains are conditional on something holding the head; when P is the head, P and C already commit/issue in the same cycle.
* The register value of a sub-doubleword load is derived from the opcode, outside `completeAcc`; a mistake would be caught by the commit-time check, not at publication: test all of `lb lbu lh lhu lw lwu ld`.
* FP producers are excluded (their value cannot be an integer base).
* RVC, multi-CPU, synonyms: unchanged (unsupported or unverified).

---

## 9. Unresolved questions
1. Slice 1 exclusive with `lvpSpecAddr`: acceptable? (Recommended: yes.)
2. Should a consumer that is *not* a V-ASTRA candidate still be admitted? (Recommended: yes: this is the memory-level-parallelism case.)
3. Should the record be created at issue instead of at decision, to count loads that never reach a decision (`fwdNoRecord`)? (Recommended: no; keep it candidate-only.)
4. Whether to add a fault-injection switch for the negative control (publish early). Judgment: optional; the structural argument plus the commit-time check is the primary defence.

---

## 10. Go / no-go
**Go** for Option A, slice 1, with these conditions:
* a new default-off parameter requiring bypass, fatal with `lvpSpecAddr`;
* the traces and checker of §4 written first, failing with the feature off for the right reason;
* the commit-time consumer check as a panic, never a recovery;
* all existing suites rerun unchanged;
* the measurable (memory-latency) section reported as a measurement; no whole-run `numCycles` assertion; no claim about dependent ALU instructions.
**No-go** for forwarding the decision snapshot (before final success), for admitting a consumer while the producer is pending, and for starting META or the result-buffer design before this slice is stable.

---

## 11. Integrity
See the section appended below.

### Integrity result
* HEAD `ce1a9fdf5be02f2c70d0f655607e9c1c385d6bab` before and after; `git status --short` identical (`run1/status-before.txt` = `run1/status-after.txt`); index empty; stash empty.
* `run1/state-before.txt` and `run1/state-after.txt` (SHA-256 of every file under `tests/`, `src/cpu/minor/`, `configs/research/`, the `tests/astra/__pycache__` listing and hashes, the backup check count) are byte-identical.
* Canonical baseline `vp_baseline.py` (`c29e3f0c…603adc`) and `vp_stall_on_use.py` (`4bea34f0…f3dc2d`) unchanged; ASTRA backup 12 checksums OK.
* Nothing was built, run, edited, staged or committed; this study wrote only into `stage2c-design-b/` (this file, `snapshot-source/`, `run1/`).
