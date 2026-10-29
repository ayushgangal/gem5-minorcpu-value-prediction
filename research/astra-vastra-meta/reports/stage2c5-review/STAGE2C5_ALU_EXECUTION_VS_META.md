# Stage 2c.5: early dependent-ALU execution versus META (design review)

Written for: the researcher choosing the order of the next two architectural steps of the V-ASTRA/MinorCPU project.
Strictly read-only review of `~/gem5` (branch `vp-lvp-dev`, HEAD `ce1a9fdf5b`, all stages through Design B built, uncommitted). Nothing was built, run, edited, staged or committed. Source snapshots are in `snapshot-source/`.

Conventions: **Fact** = read from the current checkout (function and approximate line in `src/cpu/minor/`) or from a retained trace/log; **Judgment** = my engineering opinion. Paper citations: `PDF p.N (printed N+70)`.

---

## 0. Summary and recommendation

1. **In MinorCPU, executing an integer ALU instruction early does not make anything complete earlier.** An ALU instruction already spends its latency in its functional unit (Int FU `opLat = 3`), waits at the end of the FU, and is *executed at the instant it is committed* (`commitInst`, `staticInst->execute`, ~1198), which costs no extra cycles and up to four instructions commit per cycle (`executeCommitLimit = 4`). After Design A the dependent of a released load commits **1 cycle after its producer commits** (retained log: `D commit - L commit: off [3], on [1] cycles`, `stage2c-release/regression/release.log`). The only things that early-computed ALU results can change are **consumers that need the value before commit**: loads/stores forming an address from an ALU result (`ld; add/slli; ld`), and branches. For everything else the remaining gap is at most one cycle plus commit-width effects.
2. **Therefore the useful form of "early ALU execution" is a forwarding source, not a result buffer applied at commit.** The smallest safe form is *shadow evaluation* of pure integer ALU instructions with a side-effect-free `ExecContext`, producing a forwarding record for a dependent load (exactly like Design B's record), while the instruction is still executed normally at commit and the shadow value is asserted equal. This avoids applying buffered results, avoids duplicate side effects and avoids touching the commit path. It is a **later, optional** slice that depends on the record interface META needs anyway.
3. **META is the architectural necessity.** The paper's predictor *is* V-ASTRA + LVP selected per load (§IV-E, PDF 7 (77)); both predictors exist, tested, and both are limited to the same consumer path (a dependent load's address), so META can be built now on top of that path, and the ALU extension would later reuse its interface.
4. **Recommendation: Option A: implement META now, keeping the execute-at-commit limitation, after stabilizing three interfaces** (a per-producer forwarding record with a `source` field, a single consumer-admission function returning the source, per-source accounting), keeping `lvpSpecAddr` and V-ASTRA forwarding exclusive until META provides the explicit precedence rule. Do **not** start a result buffer for ALU instructions; if the early-ALU question is revisited, start with the shadow-evaluation slice of §3, after a workload measurement shows load→ALU→load address chains matter.

---

## 1. What the code does today (facts)

### 1.1 Issue, readiness, execution, commit
* **Issue** (`Execute::issue`, 759): strictly in order; an instruction enters an FU when `Scoreboard::canInstIssue` allows it (a source is blocked only by `returnCycle > now + srcLatency` or by an *unpredictable* mark) and the FU can accept it. Destination readiness is timing only: `markupInstDests` records `returnCycle` and counts; no value exists in the scoreboard.
* **Execution**: an instruction travels through its FU (Int `opLat 3`, Mul `3`, Div `9`, Mem `1`) and stalls at the end (`FUPipeline::advance`, `buffers.hh`). In `commit()` (1320) an FU-end instruction is **executed by `commitInst`** (`staticInst->execute(&context, traceData)`, ~1198) only when it is the head of `inFlightInsts` (or, for a memory reference, taken early for its address, §1.3). `ExecContext::getRegOperand`/`setRegOperand` read/write `thread.getReg/setReg` directly (`exec_context.hh:147–200`), so execution *is* the architectural register write. Branch redirects are computed in the same call (`tryToBranch`, 330) and take effect when the branch commits.
* **Commit rate**: up to `executeCommitLimit = 4` instructions per cycle, one memory response per cycle (`executeMemoryCommitLimit = 1`), in program order (`configs/research/vp_baseline.py:191–207`).
* **Consequence (fact from traces)**: with Design A on, the dependent `D` of a bypassed load `L` issues 1 cycle after the release, 107–462 cycles before `L` commits, but commits 1 cycle after `L` (`release.log`: `D commit - L commit` 1 vs 3 off). With Design B, a forwarded memory-missing dependent sends its request 92–468 cycles before its producer commits and commits about 1 cycle after it instead of ~94 cycles later (`stage2c-forward/directed-*.log`).

### 1.2 What can be consumed before commit today
* The register file holds only committed values. The only per-instruction operand overrides are (a) the LVP override (`lvpSpecSrcVal`, `exec_context.hh:~157`, admitted by `lvpSpecAdmissible`, ~2005, binding at consumer issue in `lvpOnIssue`, ~1945) and (b) the V-ASTRA override (`vaFwdSrcVal`, `exec_context.hh:~164`, admitted by `vastraFwdAdmissible`, ~1875, binding at admission through the producer record `vaFwdMap`). Both apply to **loads with one integer source**, through `initiateAcc` at early memory issue. No ALU instruction, branch or store ever sees an override.

### 1.3 Stores, branches, faults, squash, drain
* Stores and loads build their address at **early memory issue** from the front of `inFUMemInsts` when `head_exec_seq_num > instToWaitFor` (all producers committed) or through an override; data is written at commit/store buffer.
* A fault in an early-issued memory reference is not taken early (`canEarlyIssue = false`, re-executed at the head, `commitInst` ~1160).
* A stream change discards younger instructions at issue, at commit and as responses; `clearInstDests` runs for every popped instruction; `isDrained` requires empty queues and asserts the LVP/V-ASTRA live counts and (now) the forwarding map are empty.

---

## 2. What Design B left, and what is open

* The paper (IV-B, PDF 5–6 (75–76)) lets a validated value reach *any* dependent in the same cycle; dependents execute in order but at issue. In Minor, the dependents of a validated load already issue early (Design A under stall-on-use) and execute at commit at zero cost; load dependents additionally start their memory request early (Design B).
* Remaining differences: (i) ALU/branch dependents compute at commit, not at an execute stage; (ii) a dependent ALU result cannot feed a dependent load's address before commit (`ld; add; ld` is **not** forwarded by Design B: the consumer's single source must be the load itself); (iii) validation is at execute/LSQ, not issue (a Minor property); (iv) META is absent.

---

## 3. Dependent ALU execution: options

### 3.0 What "benefit" can mean here (the test every option must pass)
An option is worth building only if it changes at least one of: the **tick at which a memory request starts**, the **tick at which a branch resolves**, or the **commit tick** of an instruction. Executing an ALU instruction early changes none of these by itself (§1.1). So every option below is evaluated by which *consumer* it enables.

### Option X: early-result buffer applied at commit (result buffering)
* **Mechanism**: execute a restricted set of pure integer ALU instructions ahead, writing their results into a per-instruction buffer instead of the register file; at commit write the buffered value (no second execution).
* **State**: per dynamic instruction `earlyDone`, `earlyValue`, destination register, stream; a per-thread shadow map `reg -> {producerSeq, value}` invalidated by every later writer and by stream change (like `lvpSpecMap`); a capturing `ExecContext`.
* **Operand sources**: committed registers; a published V-ASTRA record (forwarded value); the shadow map (earlier buffered ALU results). Each needs the producer to be older, in the same stream, and the youngest writer (`instToWaitFor` rule).
* **Instruction classes** (RISC-V integer): safe: `add addi sub lui auipc and/or/xor(+i) sll/srl/sra(+i) slt/sltu(+i) addw subw sllw ... mv li` (single destination, no side effect, no PC write except `auipc` reading the PC). Excluded: branches and jumps (PC redirect, return address), loads/stores/atomics, CSR and fences (`isSerializing`, misc registers), system calls, FP, vector, micro-ops, `div/rem` (latency and a possible fault on some ISAs), `mul*` if kept out of slice 1.
* **Commit application**: the commit path (`commitInst`'s final else-branch, ~1195–1232) would have to skip `execute()` and apply the buffer, yet reproduce its side effects: `traceData` result fields (ExecResult trace), predicate for tracing, `doInstCommitAccounting`, `tryToBranch(inst, NoFault, branch)` (no PC change for ALU), plus decide what an early fault would do (none for the safe set). This is the part with most risk: the commit path is shared with every instruction and every existing suite.
* **Squash/fault/drain**: buffers live in the dynamic instruction (discarded with it); the shadow map is cleared on stream change and checked at `isDrained`.
* **Risks**: stale operand if a younger writer is missed; double application (buffer applied and `execute()` also run); trace/statistics drift; value mismatch undetected unless a commit-time check re-executes.
* **Paper fidelity**: closer in spirit (results computed at an execute stage, applied in order), but Minor's FU-then-commit structure gives no *timing* difference for the ALU itself (§1.1), so the fidelity gain is not observable without a consumer.
* **Judgment**: highest risk (touches the commit path), no standalone benefit.

### Option Y: shadow evaluation as a forwarding source (recommended form if ALU work is ever done)
* **Mechanism**: for the same restricted ALU set, evaluate `execute()` **once ahead with a side-effect-free context** (reads from the forwarding sources above; writes captured into a local value, never into the register file, the PC or the trace record), and publish the result in the same per-producer record structure Design B uses (`state`, `value`, `destReg`, `stream`, plus `source = ALU`). The instruction is **still executed normally at commit**; at commit the executed value is compared with the shadow value (mismatch = panic, never recovery).
* **Why this is smaller**: no change to the commit path except one comparison; no duplicate *side effects* because the shadow run has none; no ordering problem because the architectural execution is untouched; failure (no record, pending, failed) simply leaves the consumer on the ordinary rule, as in Design B.
* **What it enables**: `ld P; add/slli/andi t,P,k; ld C,0(t)` (pointer arithmetic and indexed accesses), chains of such, forwarded to the dependent load's address; stores' addresses (not slice 1). It does **not** enable early branch resolution.
* **State**: the Design B record extended with `source`; a capturing `ExecContext` subclass (overrides `getRegOperand` to read forwarded sources and `setRegOperand` to capture; `pcState()` read for `auipc`; everything else asserts "unsupported"); per-dynamic-instruction `shadowState`, `shadowValue`.
* **Risks**: the capturing context must refuse any instruction that touches state other than one integer destination (a whitelist by mnemonic or by `StaticInst` flags: `isInteger`, not `isControl/isMemRef/isSerializing/isMicroop`, one dest); wrong-width semantics (`addw` sign extension) are handled by running the ISA's own `execute()`; the shadow value must be bound to the correct dynamic operand producers.
* **Paper fidelity**: partial: provides the value early, but the instruction's own architectural execution remains at commit.
* **Judgment**: feasible and contained; build only after a measurement shows address chains through ALU instructions exist and matter, and after META defines the record interface.

### Option Z: broader execute-ahead with chained buffered results (not recommended)
* Execute ALU instructions, their dependents and (eventually) branches and stores ahead with buffered results, applying them at commit; chains through the shadow map; branches resolved early with an early redirect.
* **Requirements**: a full result-capturing context for all instruction classes; early redirect and squash before commit (Minor resolves branches at commit); store address/data buffering and ordering with the LSQ; precise-exception handling for early faults; replay/recovery when an operand was wrong (V-ASTRA values are validated, LVP's are not).
* **Judgment**: this is the CVA6 pipeline reimplemented inside MinorCPU; it contradicts the project's constraint to keep MinorCPU's structure, has no staged safe subset beyond X/Y, and is not needed for the paper's predictor (IV-A..E). **No-go.**

### 3.1 Instruction classes (summary)
| Class | Shadow (Y) / buffer (X) | Reason |
|---|---|---|
| integer add/logic/shift/compare/lui/auipc/mv | yes, slice 1 | pure, one dest |
| mul | later | latency/FU, pure |
| div/rem | no | long latency, ISA-specific faults |
| branches, jumps | no | PC redirect and link register; resolved at commit |
| loads | already Design B | memory request |
| stores, atomics, LR/SC, fences | no | side effects, ordering |
| CSR, ecall, serializing, micro-ops | no | state outside the register file |
| FP, vector | no | different register classes, flags |

---

## 4. META: what it needs (facts and requirements)

### 4.1 What exists
* **LVP** (`lvp.*`, `execute.cc`): prediction at **producer issue** with a confidence counter (saturated = used); a per-register `lvpSpecMap` binds at **consumer issue**; admission only when the producer is the head, predicted, outstanding (`lvpSpecAdmissible`); validation at the producer's response; recovery by squash and refetch; consumer states `lvpConsState`.
* **V-ASTRA forwarding** (`vastra*`, `execute.cc`): record per producer created at the decision, `Validated` at the final bypass success only; binding at **admission** by `instToWaitFor`; no recovery; consumer state `vaFwdState`.
* They are mutually exclusive by configuration (`fatal_if(vastraForwarding && lvpSpecAddr)`, ~190 in `execute.cc`).

### 4.2 The paper's rule (IV-E, PDF 7 (77))
"If the base address predicted by ASTRA is correct and if the data was found in the V$, its prediction is used. Otherwise, if the confidence counter of the Last Value Predictor is saturated, its prediction is used. Otherwise, the instruction is not value predicted." Selection is made "at issue time when the base address is verified".

### 4.3 State and interfaces META needs
| Need | Today | Stabilize before META |
|---|---|---|
| Does the producer have a safe value, and which source | V-ASTRA: record `Validated` + value; LVP: `lvpProdState == Predicted` + `lvpPredValue` (usable only under its head rule) | one **per-producer forwarding record** with fields `{source ∈ {VASTRA, LVP}, state, value, destReg, stream}`; V-ASTRA fills it as today; LVP keeps its own structures (do not refactor), exposed through a read-only accessor with the same shape |
| When is it safe to consume | V-ASTRA: after final success (any producer position); LVP: producer is the head and outstanding | a single `admitForwarded(consumer)` that returns `{None, VASTRA, LVP}` and fills the consumer's override fields |
| Precedence | exclusive by config | validated V-ASTRA first; else the LVP admission as today; else none |
| Consumer binding | V-ASTRA: `instToWaitFor` + record; LVP: bound at issue | unchanged; both bind to the same `instToWaitFor` producer, so a consumer can hold both candidates |
| Consumer outcome accounting | `lvpConsState` and `vaFwdState` separate | one `source` on the consumer plus both existing states; **exactly one** may be `Accepted`; counters per source and the identity `admitted(source) + carryIn = committed + squashed + faulted + live` per source |
| ASTRA capture | skipped under the LVP override, used under the V-ASTRA override | keep (the rule already distinguishes the two) |
| Recovery | LVP only (`lvpUsedBySpec`, redirect) | unchanged: a consumer admitted by V-ASTRA never sets `lvpUsedBySpec`, so a wrong LVP prediction at the same producer causes no recovery |
| Statistics | LVP counters, `vastra.fwd*` | a `meta.*` group: per-load decision classes `{vastra, lvp, none}`, `lvpWouldHaveSufficed`, `bothAvailable`, with a window identity |

### 4.4 Coexistence design (judgment, source-grounded)
Replace the exclusivity by a **precedence rule at admission**, nothing else:
1. In the early-issue block of `commit()`, evaluate the V-ASTRA admission first (`vastraFwdAdmissible`). If it admits, set `va_fwd_admit`, leave `lvp_spec_admit` false (the LVP binding fields stay unused, `lvpSpecActive` stays false).
2. Else evaluate `lvpSpecAdmissible` as today.
3. A producer that is both LVP-predicted and V-ASTRA-validated: LVP still validates and trains at the producer's response (no consumer used it, so no recovery); the V-ASTRA value is final.
4. `astraCaptureBase`: unchanged (override-specific).
5. `lvpSpecMap` and `vaFwdMap` stay independent; the stream-change clear of `lvpSpecMap` and the stream check of records already prevent cross-use.
Nothing in LVP's algorithm, confidence or recovery changes. Both structures are consulted by `instToWaitFor`; the per-register map of LVP (`flatten(reg) -> producerSeq`) and the per-producer record of V-ASTRA agree on the producer by construction (both name the youngest older writer).
**Risk** (judgment): a consumer holds LVP binding fields and could be admitted twice; guard with a single `vaFwdState/lvpConsState` exclusivity check (`panic_if` both Accepted). A consumer never admitted via either stays on the ordinary rule.

---

## 5. Comparison of the two sequencing choices

| | Option A: META now (execute-at-commit kept) | Option B: bounded early-ALU first, then META |
|---|---|---|
| Paper fidelity | adds the selection rule of IV-E (an explicit paper element) | adds an execute-ahead capability the paper has, but Minor gives it no timing effect by itself |
| What it changes in measurements | which predictor serves each load; coverage of dependents across both predictors | nothing until a consumer (ALU→load chain) exists; then only those chains |
| Implementation risk | low to medium: precedence at one place, one new counter group; LVP untouched | X: high (commit path); Y: medium (new shadow context, whitelist, binding) |
| Test complexity | moderate: four prediction situations × chain/squash/drain; reuses the Design B workload | high: operand sources (committed, forwarded, buffered), instruction whitelist, shadow-vs-commit equality, every squash/fault case |
| Rework risk | low: the ALU extension later reuses the record and admission interface | high: an ALU record built before META would need META integration afterwards |
| Engineering cost | small to medium | medium (Y) to large (X/Z) |
| Expected performance mechanism | unchanged mechanism (earlier dependent-load requests) but more loads covered: LVP covers loads whose V$/ASTRA conditions fail | only workloads with `load → ALU → load` address chains; none of the current tests has one |
| Evidence available now | LVP and V-ASTRA both tested; Design B timeline proven | none that ALU early results shorten anything (§1.1) |

**Recommendation: Option A.** Reasons: (1) META is required by the paper and independent of ALU execution; (2) the dominant claim "early ALU execution matters" is not supported by the traces (dependents commit 1 cycle behind their producer already); (3) building META first fixes the producer-record interface the ALU shadow evaluation would otherwise have to guess; (4) the riskiest piece (commit-path buffering) is avoided entirely.
**Architectural necessity**: META. **Optional, evidence-gated**: shadow-ALU forwarding (Option Y). **Rejected**: result buffering at commit (X) and broad execute-ahead (Z).
No performance gain is promised for META either: it widens coverage on the same consumer path, and the only measured effect of that path so far is earlier dependent-load requests with a small end-to-end effect (0.3–0.4% in the `cm` section, absorbed by an issue-limited delay loop).

---

## 6. Next vertical slice (Option A: META)

**Scope**: new default-off parameter `enableMeta` (needs `enableVAstraForwarding`, `enableLVP`, `lvpSpecAddr`; the existing exclusivity check is replaced by this explicit combination; every other restriction unchanged). No ALU work.

**Changes** (to be reviewed before coding): the admission precedence of §4.4 in `commit()`; a per-consumer `metaSource` field and `meta.*` counters; the mutual-exclusion `panic_if`; trace lines `META admit exec: N source: vastra|lvp`, `META none exec: N why: ...`.

**Workload**: the `forward.c` sections plus an LVP-friendly producer (a pointer that repeats so LVP saturates):
| Case | Expectation (trace) |
|---|---|
| V-ASTRA validated, LVP also predicted | consumer admitted with source `vastra`; LVP validates/trains at the producer; no LVP recovery |
| V-ASTRA fails (V$ miss, base wrong, store conflict, abandoned), LVP saturated and producer is the head | admitted with source `lvp` under LVP's own rule; recovery path intact when the prediction is wrong (existing LVP tests) |
| both fail | `none`; ordinary rule; request after the producer's commit |
| V-ASTRA validated and LVP wrong | no recovery, no squash (the V-ASTRA value is final) |
| pending V-ASTRA record, LVP admissible | consumer waits for the V-ASTRA outcome only if LVP is not admissible; otherwise `lvp` (decision documented and tested) |
| squash, fault, drain, reset | one source per consumer, exactly one outcome, identities per window and per source |
| feature off | byte-identical to the current suites; `meta.*` all 0 |
**Checker invariants**: at most one `Accepted` state per consumer; `source` matches the override actually applied (address check against the published/predicted value); LVP counters keep their existing identities; `vastra.fwd*` identities unchanged; scoreboard accounting unchanged.

---

## 7. If early ALU execution is pursued later (Option Y slice, evidence-gated)
**Precondition**: a measurement (workload scan or trace study) shows `load → ALU → load` chains where the intermediate ALU result is the only blocker; META is stable.
**Milestone**: shadow evaluation of `add/addi/slli/andi/mv` between a validated producer and a dependent load.
| Test | Trace evidence | Invariant |
|---|---|---|
| validated producer, one ALU, dependent load | shadow record published after the producer's final success; the load's request tick < the producer's commit tick | published < request < commit; address = ALU(value, immediate) |
| chain of two ALUs, then the load | admit ticks ordered; one request | each shadow value equals the value committed later |
| wrong/unavailable producer record | no shadow record; the load follows the ordinary rule | no invalid value released |
| V$ miss, older-store conflict | no record | ordinary rule |
| unsupported instruction in the chain (branch, load, csr) | chain stops; no record | whitelist enforced |
| squash, fault, drain, reset | records erased at pop; no leftover | map empty at drain; one outcome |
| feature on/off | identical output and committed stream | commit-time equality check never panics |
| proof that completion advances | the dependent *load's* request and commit ticks advance; the ALU's own commit tick does **not** (stated in the checker) | execution of the ALU is not claimed earlier |

---

## 8. Acceptance criteria
**Before starting META implementation**
1. This review's interface list (§4.3) agreed: record shape with `source`, single admission function, per-source accounting.
2. The exclusivity rule replaced by an explicit combination parameter, with `lvpSpecAddr` alone and forwarding alone still working exactly as today.
3. No change to LVP's prediction, confidence, validation or recovery code.
**META slice accepted when**: all existing suites unchanged and passing with the feature off; the §6 cases pass with trace evidence; exactly one source per consumer; no LVP recovery caused by a V-ASTRA-served consumer; per-window identities; drain and reset clean; no whole-run `numCycles` assertion.
**Before any early-ALU work**: a recorded measurement of the chain frequency and potential, the shadow-only design (Option Y) chosen, and the commit path left unchanged.

---

## 9. Remaining limitations (unchanged)
Validation at execute/LSQ, not issue; dependent ALU and branch instructions execute at commit; RVC loads, multi-CPU and virtual synonyms unsupported; the older-store scan stands in for the paper's counting Bloom filter and invalidation FIFO.

## 10. Integrity
See the section appended below.

### Integrity result
* HEAD `ce1a9fdf5be02f2c70d0f655607e9c1c385d6bab` before and after; `git status --short` identical; index empty; stash empty.
* `run1/state-before.txt` and `run1/state-after.txt` (SHA-256 of every file under `tests/`, `src/cpu/minor/`, `configs/research/`, the `tests/astra/__pycache__` listing and hashes, the backup check count) are byte-identical; the canonical and stall-on-use baseline hashes are unchanged; the ASTRA backup shows 12 OK.
* Nothing was built, run, edited, staged or committed. The review wrote only into `stage2c5-review/` (this file, `snapshot-source/`, `run1/`).
