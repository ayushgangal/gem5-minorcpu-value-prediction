# Issue-time V-ASTRA in gem5 MinorCPU: design and feasibility study (Stage 2c)

Written for: the researcher who will decide whether and how to implement an issue-time V-ASTRA path on MinorCPU before META.
Strictly read-only study of `~/gem5` (branch `vp-lvp-dev`, HEAD `ce1a9fdf5b`, all Stage 2b work uncommitted). Nothing was built, run, edited, staged or committed. Source snapshots are in `snapshot-source/`; one retained trace excerpt is in `evidence/`.

Conventions: **Fact** = read from source or a retained trace (file:line of the current checkout). **Judgment** = my engineering opinion. Paper citations are `PDF p.N (printed N+70)` as in the fidelity audit.

---

## 0. Summary

1. **The central finding is that MinorCPU does not hold operand values where the paper's issue stage does.** Instructions *execute at commit*: ALU results are computed and written to the register file only in `commitInst` (`execute.cc:1072`, `staticInst->execute` at ~1141, via `setRegOperand` → `thread.setReg`, `exec_context.hh:~168`). The scoreboard is a pure *timing* structure (`returnCycle`, `numResults`, `numUnpredictableResults`, `writingInst`; `scoreboard.cc:78–225`). Before a producer commits, no register holds its value. Therefore "validate the base register against the predicted base at issue" (paper §IV-B, PDF 6) is possible in Minor only when the base's producer has already committed.
2. **Because of (1), a validated V-ASTRA value can never be "read early" by a dependent ALU instruction in value terms.** What a dependent ALU can gain is **timing**: earlier *issue* into its functional unit (scoreboard readiness). Its value is still read at its own in-order commit, which is after the load commits, so no wrong value can reach it.
3. **The current Stage 2b bypass already completes a load in the same simulated tick as its decision** (retained trace, `evidence/same-tick-bypass-lifecycle.txt`: push, translation, bypass, `Complete`, response handled, request deleted, all at tick 7011000). What it does not do: (a) tell the scoreboard, (b) hand the value to a dependent load's address generation before the producer commits, (c) decide earlier than "FU front with all producers committed", (d) change the baseline's load-to-use assumption.
4. **With the current research baseline's default Minor FU timing the scoreboard cannot show a gain at all**: `MinorDefaultMemFU` has `extraAssumedLat=2` (`BaseMinorCPU.py:236–245`), so a load's destination is marked ready 3 cycles after issue regardless of the real latency, and dependents already issue early and wait at the end of their FU (`FUPipeline::advance`, `buffers.hh:351–370`). The paper's baseline is stall-on-use. To reproduce the paper's mechanism the experiment needs a **stall-on-use memory FU timing variant** (`extraAssumedLat=0`), as a *new* research configuration; the canonical baseline stays untouched.
5. **Recommendation** (smallest design that materially improves fidelity): **Design A**, validated scoreboard release, plus a stall-on-use configuration variant; then **Design B** (validated-value forwarding to dependent loads, reusing the LVP address-speculation mechanism with no recovery path) as slice 2. A third design (execute-ahead with result buffers) is rejected. A speculative release is safe in Minor because the scoreboard is timing-only: a wrong release costs cycles, never correctness.
6. **Go**, for Design A slice 1, under the conditions in §9.

---

## 1. Current execution path (facts)

### 1.1 Cycle order inside `Execute::evaluate` (`execute.cc:2544`)
`lsq.step()` (2563 area) → interrupt check → `commit()` (called at ~2594 and the drain variants) → `issue()` (~2618) → pipeline advance (`fu->advance()` ~2655). So in one cycle the commit stage sees FU-end instructions first and `issue()` runs afterwards: a scoreboard change made during commit is visible to `issue()` **in the same cycle** (the code comment at 2580 says so: "commit can set stalled flags observable to issue").

### 1.2 Issue (`Execute::issue`, `execute.cc:719–968`)
In-order: instructions are taken from the input buffer in program order and the loop stops at the first one that cannot issue (`issued=false` ends the do/while, 960–966). To issue, an instruction needs a capable FU that is not stalled and can accept it (`fu->stalled`, `canInsert`), and `Scoreboard::canInstIssue` (`scoreboard.cc:~200–262`): for each source, `returnCycle[reg] > now + srcRegRelativeLatency` or `numUnpredictableResults[reg] != 0` blocks issue. On issue:
* the instruction is pushed into the FU pipeline (`fu->push`), into `inFlightInsts`, and, for memory references, into `inFUMemInsts` with `instToWaitFor = scoreboard.execSeqNumToWaitFor(inst)` (the youngest writer among its sources, `scoreboard.cc:~145–171`) and `canEarlyIssue=true` (`execute.cc:~872–905`);
* `markupInstDests(inst, now + opLat + extraCommitLat + extraAssumedLat, …, mark_unpredictable = issued_mem_ref && extraAssumedLat == 0)` (`execute.cc:~925–932`) sets `returnCycle[dest]`, `numResults++`, and, only for a memory reference with `extraAssumedLat==0`, `numUnpredictableResults++`;
* then `lvpOnIssue`, `astraOnIssue`, `vastraOnIssue` (`execute.cc:~936–948`).
FU parameters of the research baseline (`configs/research/vp_baseline.py:191–234`): issue limit 4, commit limit 4, memory issue limit 1, memory commit limit 1, early memory issue allowed, `SingleThreaded` policy (so commit() keeps running while the oldest instruction is a load waiting in the LSQ), 16 outstanding demand loads. FU pool = Minor default: Int FU `opLat=3`, `srcRegsRelativeLats=[2]`; Mem FU `opLat=1`, `srcRegsRelativeLats=[1]`, `extraAssumedLat=2` (`BaseMinorCPU.py:153–158, 236–245`).

### 1.3 Commit (`Execute::commit`, `execute.cc:1252–1700`)
Each iteration looks at the head of `inFlightInsts`:
* if the head is in the LSQ and its response is the front of the transfers queue → `handleMemResponse` (425): `completeAcc` writes the load's destination register, LVP/V$/ASTRA hooks run, `popResponse`; this is how a load commits;
* otherwise, an instruction at the **end of its FU** whose execSeqNum equals the head is *executed* by `commitInst` (`staticInst->execute`, register writes happen here);
* a memory reference that is the front of `inFUMemInsts` and sits at the end of the Mem FU may be taken **early** (before it is the head) if `head_exec_seq_num > instToWaitFor` (all producers of its sources have committed) and `canEarlyIssue` and the stream matches (`execute.cc:1391–1430`); `executeMemRefInst` (602) then calls `initiateAcc`, which reads the *base register from the register file* (so it needs the committed value) and builds the LSQ request.
Retirement pops `inFlightInsts` and calls `scoreboard.clearInstDests(inst, inst->isMemRef())` (`execute.cc:1659`): `numResults--`, and `numUnpredictableResults--` for memory references.

### 1.4 LSQ and the bypass
`pushRequest` (`lsq.cc:1592`) → translation; in SE mode translation completes synchronously, `SingleDataRequest::finish` (`lsq.cc:271–296`) calls `tryToSendToTransfers` at once (line 294), where `vastraTryBypass` runs (`lsq.cc:1122`, `execute.cc:2257`). Requests/transfers are **FIFO queues in program order**; `findResponse` only matches the front of `transfers` (`lsq.cc:1495`). A request therefore cannot overtake an older one; this constrains any design (§4.3).

### 1.5 What the retained trace shows
`evidence/same-tick-bypass-lifecycle.txt`: for exec 2480 at tick 7011000 the request is pushed, translated, the bypass hook creates the response, `Complete`, `Found matching memory response`, `Memory response inst`, and `Deleting load request`, all at the same tick, because the load was at the head. **When the candidate is the head of the in-flight queue its commit happens in the same cycle as its decision.**

### 1.6 How values reach dependents
* **Dependent ALU instruction:** reads its sources inside `staticInst->execute` at commit (through `ExecContext::getRegOperand`, `exec_context.hh:~147–163`, which returns `thread.getReg(reg)`). The producer must have committed (in-order commit), so the value is the producer's final value. No forwarding network exists.
* **Dependent load:** its base is read in `initiateAcc` at early issue (needs `head_exec_seq_num > instToWaitFor`) or at commit. The only place an *uncommitted* value is ever supplied is the LVP address-speculation override: `ExecContext::getRegOperand` returns `inst->lvpSpecSrcVal` when `inst->lvpSpecActive && idx == lvpSpecSrcIdx && si == inst->staticInst && reg == lvpSpecSrcReg` (`exec_context.hh:147–163`), admitted by `Execute::lvpSpecAdmissible` (`execute.cc:1811–1852`) and checked/recovered by `lvpValidateProducer` (1854+) with squash-and-refetch. Nothing is written to the register file. This is the existing, tested precedent for per-instruction forwarding.

### 1.7 Squash, fault, stream change, drain
* A stream change (`updateBranchData`/`tryToBranch`, `execute.cc:314`) bumps `streamSeqNum`; younger instructions are discarded at issue, at commit (`discard_inst`) and as responses (`popResponse` without `completeAcc`); `clearInstDests` runs at their pop, so scoreboard counts of discarded instructions are released.
* Translation faults are carried on the instruction and handled in `handleMemResponse`; the bypass hook runs only after a successful translation and only for the current stream.
* `isDrained` (`execute.cc:2989`) requires empty in-flight queues, then checks the LVP/V-ASTRA live counters. Statistic resets only reset scalars; the live counters survive (`carryIn`).

---

## 2. The precise gap versus the paper

| Paper (PDF p.) | Behaviour in the paper | This implementation |
|---|---|---|
| IV-B (PDF 5–6, printed 75–76) | A prediction is validated **in the issue stage** by comparing the base *register value* to the predicted base; a validated load completes immediately and its dependents "may only issue after the load issues", in the same cycle. | Validation at `executeMemRefInst` (`execute.cc:602`, call 626) when the load is at the end of the Mem FU and all producers have committed, and again at the LSQ send point (`execute.cc:2257`). Same tick as the commit, but **after** FU traversal and producer commit. |
| IV-B | Predicted loads stall at issue if the base operand is not available. | Equivalent in effect: the decision waits for committed producers. |
| IV-B | Base operand values are available at issue (register file or bypass). | **Not available in Minor** unless the producer has committed (execution happens at commit, §1). Fundamental difference. |
| IV-B, IV-G (PDF 9) | Dependents of a validated load issue with it (0-cycle load-to-use); the baseline is stall-on-use. | Dependents of any load already issue 3 cycles after the load (extraAssumedLat) and then wait at the FU end; with `extraAssumedLat=0` they would wait for the load's *commit*; V-ASTRA currently does nothing to the scoreboard in either case. |
| IV-B | No dependent ever executes with a wrong predicted source. | True here, trivially: a V-ASTRA value is delivered only through the response, no instruction reads it early. |
| IV-D | V$ read in the front-end, protected by CBF/FIFO. | V$ snapshot at the decision, fresh lookup at the send point, exact older-store scan (adaptations accepted in the audit). |

**Why the current synthetic response does not reproduce the paper's issue-time behaviour** (judgment, source-grounded): (a) it is not visible to the scoreboard, so no younger instruction issues earlier because of it; (b) it never reaches dependent loads before the producer commits; (c) it fires only when the load is at the FU end with committed producers; (d) under default FU timing there is no stall-on-use to break. Its only effect is that the load can commit as soon as it is the head.

---

## 3. What can and cannot move earlier in Minor (feasibility analysis)

Facts used above, restated as constraints:
* **C1** execution (value computation) is at commit, in program order → no out-of-order value production for ALU instructions.
* **C2** the scoreboard is timing-only → a release can be wrong without corrupting anything; values are read from the register file at commit.
* **C3** memory references can begin early (EA + request) only from the front of `inFUMemInsts`, one per cycle (`executeMemoryIssueLimit=1`), and responses commit one per cycle (`executeMemoryCommitLimit=1`).
* **C4** the LSQ is FIFO in program order.
* **C5** operand *values* exist in the register file only for committed producers, except the LVP-style per-instruction override.

Consequences:
* *Dependent ALU, "uses the value early"* can only mean: it **issues** earlier (scoreboard). It still commits after the load.
* *Dependent load, "consumes the earlier validated result"* is real value forwarding and needs the override mechanism (C5).
* The only places where earlier release changes outcomes: (i) stall-on-use mode, where dependents otherwise wait for the load's commit; (ii) a validated load that is **not** yet the head (an older instruction still pending): its dependents can issue and (for loads) start their own memory access while older instructions are still outstanding. When the validated load is the head it commits the same cycle, so a release at decision gains nothing over the normal clear at commit.

---

## 4. Candidate designs

### 4.0 Common building block: "validated" state
Per dynamic instruction (all in `MinorDynInst`, `dyn_inst.hh`, next to the existing `va*` fields):
* `vaValidated` (bool): the bypass hook reached its final success (response created). After this point the load's architectural result is fixed: the bytes are in the response packet and `completeAcc` is deterministic.
* `vaRegValue` (RegVal) and `vaRegValid`: the *register* value the load will write (extension of the bytes), needed by Design B. Compute from the opcode (`lb lbu lh lhu lw lwu ld`, `flw/fld` excluded in slice 1) when the response is created; **do not** write it anywhere.
* `vaScoreReleased` (bool): the scoreboard release was done for this instruction, so `clearInstDests` must not decrement `numUnpredictableResults` again.
Final validation is already the success branch of `vastraTryBypass` (`execute.cc:~2338–2352`): base equals prediction (decision), predicted EA equals the real EA, older-store scan, byte-valid snapshot, unchanged fresh lookup, support predicate. No new validation logic is required for slice 1.

### Design A: validated scoreboard release (recommended first slice)
**Idea.** Make V-ASTRA visible to the scoreboard: when a load becomes validated, release its destination registers so that younger dependents can **issue** (timing), the Minor analogue of "dependents issue with the load". In stall-on-use mode this is exactly the paper's mechanism; no value is forwarded.

**Configuration prerequisite** (explicit scope decision D-SOU, §8): a new research config (for example `configs/research/vp_baseline_sou.py`, a copy of the baseline with the Mem FU timing `extraAssumedLat=0`, plus a note). The canonical `vp_baseline.py` is not modified. With `extraAssumedLat==0` the load's dests get `numUnpredictableResults++` (`execute.cc:~931`), so `canInstIssue` blocks dependents until `clearInstDests` at the load's pop (`execute.cc:1659`, `clear_unpredictable = inst->isMemRef()`). That is stall-on-use. (Facts: `scoreboard.cc:~254–262` blocks on `numUnpredictableResults != 0`.) All comparisons for this feature (feature off vs on) must be made inside the stall-on-use configuration; results in the default-timing configuration are expected to show no issue-timing change, only the Stage 2b commit effect.

**Source changes.**
* `scoreboard.hh/.cc`: new `releaseUnpredictable(inst, now)`: for each flattened dest register of `inst`: if `inst->flatDestRegIdx` is tracked and `numUnpredictableResults[idx] != 0`, decrement it, and set `returnCycle[idx] = now`; set nothing else (`numResults`, `writingInst` unchanged so ordering and `instToWaitFor` are intact). Assertion: only called for memory references that were marked unpredictable at issue (flag in the inst).
* `execute.cc`:
  * in `vastraTryBypass`, on the success path after `makeResponse()`: `scoreboard[tid].releaseUnpredictable(inst, cpu.curCycle())`, `inst->vaScoreReleased = true`. (Same cycle, before `issue()` runs in this `evaluate`.)
  * at retirement: `clearInstDests(inst, inst->isMemRef() && !inst->vaScoreReleased)` (`execute.cc:1659`) to avoid a double decrement (the underflow hazard noted in the Stage 1 LVP audit: `clearInstDests` guards `!= 0` but would steal another writer's count).
  * new counters in `VAstraDiag` (`vastra.hh/.cc`): `scoreboardReleases`, `releaseIssuedDependents` (optional), under a new debug flag line `VBypass release exec: N`.
* `BaseMinorCPU.py`: parameter `enableVAstraRelease` (default False; requires `enableVAstraBypass`; fatal otherwise; mutually exclusive with nothing else).
* No change to `lsq.cc`.

**Validation and V$.** Unchanged (final success branch of `vastraTryBypass`). The load's real base operand is the committed register read by `initiateAcc`; the immediate is the decoded non-speculative `imm12` (`vastraEffectiveAddress`, `execute.cc:2185`). V$ protection: decision scan + LSQ gating + fresh lookup (audit §C4/C5).

**Dependent ALU / dependent loads.** ALU: issue earlier (timing), value read at commit. Dependent load: *issues* earlier into the Mem FU but cannot begin its own memory access until its producer commits (`instToWaitFor` rule), exactly as today. Same-cycle ordering: commit stage first (creates the response and releases), then `issue()` in the same `evaluate`, so a dependent can issue in the cycle of the decision. Dependent chains: a dependent that is itself a validated candidate is decided only when its base register is committed (unchanged), so chains advance at most one link per cycle (`executeMemoryIssueLimit=1`).

**Failure handling.** Release happens only on final success, so the release is never wrong in slice 1: if any check fails the load goes to memory and the scoreboard keeps its unpredictable mark until commit (baseline behaviour). *Optional later slice (A+):* an earlier, *speculative* release at issue when the base is architecturally current and the best-effort checks pass; a wrong early release is harmless to correctness (timing only, C2) and costs a counted `wastedReleases`; it is closer to "validation at issue" but is **not** in slice 1, because it needs a V$ lookup, store scan and base read at issue and a re-count policy.

**Retire exactly once; state correctness.** Unchanged: the load still completes through `handleMemResponse` at the head; no register is written early; `clearInstDests` runs once at pop with the flag.

**Closer to the paper?** Yes in kind: a validated load unblocks its dependents without waiting for the load to commit (in stall-on-use). It remains an adaptation in *when* validation happens (§2). It is not merely a timing workaround because it changes which instructions may issue under the paper's own baseline assumption (stall-on-use) and it is verified by trace evidence.

**Risks.** Double decrement of `numUnpredictableResults` (flag + assertion); release of a register that another in-flight writer also marked (counts are per register; a release only decrements one count, other writers keep blocking, conservative); discard after release (the pop path still runs `clearInstDests`, flagged correctly); drain (assert that the scoreboard has no unpredictable counts when drained); FU pile-up: more dependents issued early can fill FU ends (stalled) and block younger independent work, same structure as baseline's assumed latency (performance, not safety); deadlock: none, because commit never waits on a dependent issuing.

### Design B: validated-value forwarding to dependent loads (second slice)
**Idea.** Let a dependent load build its address from a validated producer's value *before the producer commits*, using the existing LVP override mechanism, with no mispredict path.

**Source changes.**
* `dyn_inst.hh`: reuse `lvpSpecSrcIdx/SrcVal/SrcReg/Active` or add `vaFwd*` twins to keep META orthogonal; add `vaFwdProducer` (execSeqNum), `vaFwdActive`.
* `execute.cc` `issue()` path: at issue, for an eligible dependent load (`lvpOrdinaryIntLoad`-style predicate, one integer source), record the producer it waits for (already `instToWaitFor`). No value yet.
* New `Execute::vastraFwdAdmissible(ex_info, head_candidate, fu_inst, head_mem_ref_inst)` modelled on `lvpSpecAdmissible` (`execute.cc:1811`): the dependent is the front of `inFUMemInsts`, not yet in the LSQ, `instToWaitFor` equals a producer whose `vaValidated` is true, the producer is in flight in the right stream (it need **not** be the head: that is the point), and the dependent's single source is that producer's destination register.
* In the early-issue block (`execute.cc:1391–1430`): `deps_satisfied || lvp_spec_admit || va_fwd_admit`; set the operand override (value `producer->vaRegValue`) inside a scope guard like `LVPSpecOperandScope`; `ExecContext::getRegOperand` (`exec_context.hh:147`) already checks the override flag; add the V-ASTRA twin.
* At the dependent's commit: reuse the LVP consumer check (`panic_if` the register value read at commit differs from the forwarded value), and classify the consumer for statistics.
* Counters: `fwdAdmitted`, `fwdCommitted`, `fwdDiscarded`.

**Why no recovery is needed.** The forwarded value is exactly the value that the producer's already-created response will write at its commit; the producer cannot change after final validation (no fault after translation, deterministic `completeAcc`). If the producer is squashed, the consumer (younger) is squashed with it. The check at the consumer's commit is a safety net (a mismatch is a bug and panics), not a recovery path. A forward must **not** be offered before final validation: forwarding from the decision snapshot (before the fresh lookup) could use a value that is later abandoned, which would need LVP-style recovery (rejected).

**Constraints and risks.** C3: at most one early memory issue per cycle. C4: the consumer's request is pushed after the producer's, so the FIFO order is preserved, and the producer's response sits at the front of the transfers queue ahead of it. LVP interplay: a producer that is both LVP-predicted and V-ASTRA-validated must be forwarded the validated value only (validated beats predicted; META later formalises it); `lvpSpecAdmissible` must therefore refuse a producer with `vaValidated`. Stale operand: loads have exactly one register source, and `instToWaitFor` is the youngest writer of it, so no intervening redefinition; use-after-free: store the producer's execSeqNum and the value copied into the consumer, never a pointer. Duplicate completion: none new (the consumer's request is created once, `inLSQ` set, existing guards).
**Benefit.** Real for a chain behind an older pending instruction (pointer chasing behind a missing load); none when the producer is the head (it commits in the same cycle). Also the part of the paper that lets "the waiting time of the dependent load be zero" (PDF 5, printed 75).
**Closer to the paper?** Yes: it is the only mechanism by which a *value* is consumed before the producer retires, as the paper's issue-time forwarding does. For dependent ALU instructions nothing equivalent exists in Minor (C1).

### Design C: execute-ahead with per-instruction result buffers (rejected)
Run dependent ALU instructions early with the forwarded operand into a per-instruction result buffer and write it at commit. Needs: a result-capturing `ExecContext` (all `setRegOperand/setMiscReg/pcState` paths), exclusion of anything with side effects (memory, CSR, branches), a decision whether commit re-executes or writes the buffer, and out-of-order FU result timing that Minor's FU model does not represent; it does not change commit order, so it only helps if commit is decoupled, which is a different microarchitecture. High risk, little gain in this model.

### Design 0 (status quo)
Stage 2b: valid and verified, but leaves the scoreboard and dependent loads untouched.

### Comparison

| | A: scoreboard release | B: value forwarding to loads | C: execute-ahead |
|---|---|---|---|
| Changes timing of dependent ALU issue | yes (stall-on-use) | no | yes |
| Dependent value consumed before producer commit | no | **dependent loads only** | yes |
| Needs recovery path | no | no (forward only after final validation) | yes |
| Source size | small (scoreboard + hook + flag) | medium (admission + override twin) | large |
| Safe by construction | yes (timing only) | yes (value is final) | needs proof per instruction class |
| Paper fidelity gain | medium | medium–high for chains | n/a (rejected) |

**Recommendation.** A, then B. Judgment: A is the smallest change that moves V-ASTRA from "the load finishes sooner" to "the pipeline reacts to a validated load", and it is testable by traces; B adds true value consumption for loads.

---

## 5. Minimal first vertical slice (Design A) and its tests

All tests run inside the stall-on-use variant configuration (and, for item 6, also in the canonical baseline to show equivalence); feature off vs on; matched output directories (same path length) for timing runs, ticks-on traces. New debug line `VBypass release exec: N pc: … tick`. Pass criteria are on traces; counters are supporting only.

Workload shape (new `release.c`, reusing `bypass.c` helpers): an older, independent, DRAM-missing load `M` (far, never reused) at the head; then a candidate load `L` (ring node or strided line, V$ holds its bytes, base register from a committed register, ASTRA trained with delays as in the existing tests); then a dependent ALU chain `D1: add t,a0,1; D2: add u,t,2` consuming `L`'s result; then a dependent load `E: ld x,0(a0)` (for slice 2) and independent work `I1..I4` after the dependents. Because `M` is older and missing, `L` is decided while not at the head, so the gap between "decision" and "commit of `L`" is visible.

| # | Requirement | Evidence required |
|---|---|---|
| 1 | A cache-missing load gets a valid ASTRA/V$ candidate | `L` misses L1 in the feature-off run (`MinorMem`/stats), `VBypass exec` for `L`'s PC; `eligibleBypass`, `syntheticResponses` > 0. |
| 2 | Dependent ALU uses the validated value before ordinary load completion | In the on run: `MinorExecute` line "Issuing inst: D1 … into FU" has tick T_issue(D1) **earlier** than the tick of `L`'s commit (`Memory response inst`/Exec trace) and earlier than T_issue(D1) in the off run, which equals `L`'s commit tick (stall-on-use). The committed value of `D1` (`D=`) equals the off run's. State precisely: the value is read at D1's commit; the release changes issue timing. |
| 3 | (slice 2) A dependent load consumes the earlier validated result | `MinorMem` "Pushing request" for `E` at a tick earlier than `L`'s commit; operand override debug line; `E`'s result equals the off run's; consumer check never fires. |
| 4 | An incorrect base prediction does not release | A section where ASTRA mispredicts the base (as in `classify` basewrong): no `VBypass release` line for that load; `D1` issues at `L`'s commit tick, equal to the off run; `scoreboardReleases` does not count it. |
| 5 | V$ miss and older-store conflict fall back safely | Tag-miss, byte-miss, atomic and store-conflict sections (reuse `classify`, `store`, `atomic` structure): no release line, real request sent (`Trying to send` present), dependents unchanged vs off. |
| 6 | Equivalence disabled vs enabled | Identical program output, committed trace (`ExecEnable` lines), instruction counts, and `candidates + carryIn = outcomes + inFlight` per window (existing `check_bypass.py` pair checks). |
| 7 | Timing traces show the dependent advancing earlier | Per-walk/segment tick comparison from ticks-on traces (the method of the existing `latency` test); report cycles saved as a measurement; never assert whole-run `numCycles`. |
| 8 | No unintended request, duplicate completion, stale state | Existing `evidence()` check (no send/recv for a bypassed load, one deletion, one completion); new invariant: every released load later pops with `numUnpredictableResults` unchanged by `clearInstDests` (assert in debug build) and the scoreboard is clean at drain; drain/reset runs. |

**Counter invariants** (new): `scoreboardReleases ≤ syntheticResponses`; `releases = released loads that retired + released loads discarded`; none of these counters change the meaning of existing `vcache.*`, `vastra.*`, `astra.*`, `lvp.*` counters (new names only). Existing suites (ASTRA, V$, V-ASTRA incl. `verify-detect`, LVP, bypass incl. syscall negative control and drain/reset) must still pass unchanged with the feature off.

---

## 6. Explicit scope decisions

* RVC loads stay out of scope (compressed loads never become candidates, `vastraEffectiveAddress`). To include them: decode the compressed immediate in a second extractor and add RVC loads to the test builds; the audit's coverage caveat then lapses.
* SE mode, one CPU, one hardware thread stay enforced (`MinorCPU::init`, `Execute` ctor). Expanding to multi-CPU would need invalidations on remote writes (paper IV-H) and a second CBF for non-predicted loads; none exists.
* Virtual synonyms remain unsupported and unverified: not creatable in SE; the V$ store policy is unchanged; do not claim coherence for them.
* The older-store scan stays as the safety mechanism. If the decision moves earlier (A+), the scan at issue cannot see stores that have not yet computed their address (not built the LSQ request), so an issue-time pre-check must treat "unknown" as "no release" or accept counted wasted releases; the final scan at the decision remains authoritative.
* **New: D-SOU** a stall-on-use memory timing variant is a *separate configuration*, not the canonical baseline. Judgment: required; without it Design A's effect cannot be demonstrated.

---

## 7. What META will need from this path (not designed here)

* A per-load **validated** flag and a per-load **validated value** (`vaValidated`, `vaRegValue`) available at the decision/final-validation point, so META can choose "validated V-ASTRA value, else saturated LVP, else none" (paper IV-E, PDF 7, printed 77).
* A single place that decides what is released/forwarded (so LVP-spec and V-ASTRA forwarding do not both fire), and a rule that validated beats predicted.
* Counters that separate "validated and used", "validated, not used", "LVP used", "none" per load, with an identity that holds per statistics window.
* LVP recovery stays squash-and-refetch (paper: scoreboard replay is not modelled).
Do not build META around the current counters (`vastra.syntheticResponses` and the `fb*` classification); those describe the Stage 2b mechanism and will be reorganised.

---

## 8. Unresolved questions and assumptions

1. **Is a stall-on-use research baseline acceptable** (new config, new timing model), or should the experiment keep default Minor timing and accept that dependent issue timing cannot change? (Recommended: stall-on-use variant.) Without it, only commit-side effects remain.
2. Early (issue-time) pre-validation (A+): worth the extra state, or is "release at final validation, same cycle as the load's decision" sufficient fidelity? Judgment: start with the latter.
3. `vaRegValue` for sub-doubleword and FP producers: slice 2 should support `ld`, `lw`, `lwu`, `lh`, `lhu`, `lb`, `lbu` by mnemonic, exclude FP (an FP value cannot feed an integer base register).
4. One memory issue and one memory commit per cycle are baseline limits (`executeMemoryIssueLimit=1`, `executeMemoryCommitLimit=1`); the paper issues and predicts two loads per cycle. Keep, and document.
5. Whether the dependents' FU pile-up (stalled FU ends) will limit the gain; measure before tuning.
6. Assumption: execute-at-commit semantics of this gem5 version (23.0.0.1) hold for every instruction class used in the tests; verified from source for ALU, load and store paths only.

---

## 9. Go / no-go

**Go** for implementing Design A (slice 1), with these conditions:
* a new stall-on-use configuration variant is created and reviewed first (canonical baseline unchanged);
* the release is on by a new default-off parameter and requires bypass;
* the trace-based tests of §5 (items 1, 2, 4, 5, 6, 7, 8) are written before the source change and fail with the feature off for the right reason;
* all existing suites are rerun unchanged;
* Design B is a separate, later stage with its own review (it touches the early-issue admission logic shared with LVP).
**No-go** for Design C and for any attempt to write speculative values into architectural registers.

---

## 10. Integrity (verified at the end of this study)

See the appended section.

### Integrity result
* `git status --short`, HEAD (`ce1a9fdf5b…`), index (empty), stash (empty) identical before and after (`run1/state-before.txt` = `run1/state-after.txt`, byte-identical, which also contains SHA-256 of every file under `tests/`, `src/cpu/minor/`, `configs/research/` and of `tests/astra/__pycache__/*`).
* No source or test file was edited, nothing was built or run, nothing was staged or committed.
* ASTRA backup `~/gem5-astra-backup-2026-10-18/`: 12 checksums OK before and after.
* All Stage 2b / 2b.1 / 2b.2 / 2b.3 artifacts are untouched; this study wrote only into `~/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage2c-design/` (this file, `snapshot-source/`, `evidence/`, `run1/`).
* Line numbers marked `~` are approximate (the `issue()`/`commit()`/`evaluate()` ranges were read from the current checkout but quoted loosely); function names and files are exact.
