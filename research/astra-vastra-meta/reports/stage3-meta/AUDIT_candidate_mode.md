# Audit: metaAstraLvpLoads=candidate, speculative-dependency correctness (read-only; no file in the repository changed)
Lines are `src/cpu/minor/execute.cc` unless named.  [F] = proved by code, [T] = observed in retained traces, [I] = inferred.

## Terminology (the question's premise needs one correction)
In candidate mode the younger load C is an **LVP-served consumer** (source operand = the LVP value of P; `META accept ... source: lvp`).
The V-ASTRA part is C's **own result** (C is a V-ASTRA candidate, bypassed).  "V-ASTRA-served consumers do not set `lvpUsedBySpec`"
applies only to a load whose *operand* comes from a V-ASTRA forwarding record (source: vastra).  C is not that: it sets `lvpUsedBySpec`.

## Event trace (scenario: P predicted wrong, C uses it as base, C bypasses before P is validated)
1. P issues: `lvpOnIssue` (2164) makes a confident prediction; C issues and picks up the LVP snapshot (lvpSpec* fields).
2. P is the oldest instruction, outstanding, no response: `metaSelect` (2020) -> `lvpSpecAdmissible` (2224; requires `!head_has_response`, line 2252) -> choice LVP.
3. Commit loop, early issue of C: `LVPSpecOperandScope` active; `commitInst` -> `executeMemRefInst` (660): `astraCaptureBase` (2421) stores the
   LVP operand as the **provisional** base (`astraBaseProvisional`, base valid only in candidate mode); `vastraDecide` (2852) compares ASTRA's predicted
   base with it; `initiateAcc` pushes the request; the LSQ send calls `vastraTryBypass` (2690) synchronously (trace: `VBypass exec` printed before
   `Speculative load accepted` at the same tick): synthetic response built (2796), scoreboard marks released (2807, timing only).  Back in
   `executeMemRefInst`: `lvpConsState = Accepted` (724).  Back in the commit loop: `lvp_spec_producer->lvpUsedBySpec = true` (1703).  [F]
   No other code runs between 3's bypass and 1703 (single-threaded sequential call chain). [F]
4. C's synthetic response waits in the LSQ.  C is younger than P, so C can reach the head of `inFlightInsts` only after P left it, and P leaves only
   after its response was handled (handleMemResponse 459).  [F]
5. P's response: `handleMemResponse` -> `completeAcc` -> `lvpValidateProducer` (571, 2261): `recover = !correct && lvpUsedBySpec` (2283) -> true;
   `tryToBranch`; then (613) `updateBranchData(UnpredictedBranch)` -> `streamSeqNum++` (436).  `fetch2.cc:142` handles the history without
   touching the branch predictor.  The commit loop stops on a stream change (1421).  [F]
6. C (old stream) reaches the head: the mem-response branch sets `discard_inst` (1483) and `lsq.popResponse` without `handleMemResponse`: no `completeAcc`,
   no register write.  `vastraPop` counts the candidate as discarded; the scoreboard clear does not double-decrement (`vaScoreReleased`).  `astraRetire`
   counts it squashed (no training); `metaClassify` drops the provisional base (`provisionalDropped`).  [F]

## Answers
1. **Registered as dependent: yes**, independently of the bypass.  `lvpUsedBySpec` is set at 1703 from `lvpConsState == Accepted` only; the
   bypass does not touch it.  [F]  [T] 12 cases (3 recoveries each in ldld-phase, ldld-fanout, drain-ldld-phase, reset-ldld-phase, candidate runs): the LVP consumer
   had a `VBypass exec` line (bypassed), at or before the tick of the producer's `Validated ... (incorrect)`, which equals the tick of the `Recovery redirect`, and the
   consumer's response was `Discarding mem inst` one cycle later; it never appears as `Memory response inst` handled or `Committing inst`.
2. **Guarantee** (all [F]): (a) acceptance sets `lvpUsedBySpec` at once (724/1703); (b) a younger instruction cannot be handled before the older load's
   response is (in-order head rule, 4 above); (c) at P's response a wrong used prediction always redirects (2283, 613) unless a stream change is already present, which
   discards the younger instructions anyway (613 comment, 1421); (d) discard happens before `completeAcc`/`execute` (1483, 1627).  (e) Backstop: if a consumer
   with an LVP operand ever reached its response, line 503 panics when the register differs from the operand, before `completeAcc` (no silent commit).
   If P itself faults or is squashed first, the fault redirect / older stream change discards C the same way.
3. **Before recovery the bypassed result cannot influence**: the register file (written only in `completeAcc` at the head, 4-6); stores (execute at in-order
   commit; early issue is only for loads, and a dependent of C needs C committed (`instToWaitFor`/`writingInst` unchanged by the Design A release), an LVP admission (C must be
   the head with no response) or a V-ASTRA record (never created for a provisional candidate: guard at 2908 `!astraBaseProvisional`, and the publish branch needs the
   record)); ASTRA training (`astraRetire`: discarded -> squashed, never trained; the provisional base becomes actual only after the 503 check, 510); the V$
   (`vcacheRetire` runs only for committed loads and returns early for bypassed ones, 2539); LVP training / another prediction record (`lvpValidateProducer` only at the
   response of a non-discarded load; the fwd record map has no entry).  The only effect is timing: scoreboard release (2807) and statistics (`syntheticResponses`,
   `candidatesDiscarded` count wrong-path bypasses).  [F]  [T] ldld-phase candidate: provisionalBases 8 = validated 5 + dropped 3 (= 3 recoveries), candidatesDiscarded 3.
4. **Ordering** (synthetic completion, publication, retirement, recovery): bypass < accept-return < `lvpUsedBySpec` < P's validation <= redirect < discard of C [F][T];
   publication does not exist for these loads [F]; retirement of C (vcacheRetire/astraRetire/vastraPop) occurs only through the discard path [F].
5. **ldld-chain 1 -> 0 recovery** (off vs candidate, `exp/astra-lvp/ldld-chain/{off,cand}`): producer = exec 16767 (pc 0x10198), LVP prediction 0x60000, actual 0x68000
   (incorrect in both runs: `Validated ... incorrect` at 35840000 off, 35836000 cand).  Consumer = exec 16768 (pc 0x1019c).  In `off`, 16767 was a memory request still outstanding
   when it became head, so 16768 was admitted at 35835000 (`source: 0x60000`), `lvpUsedBySpec` was set, and the validation raised the redirect (35840000);
   16768 was discarded.  In `cand`, 16767 had been bypassed at issue (35768000, V$ data 0x68000), so its response existed when it became head:
   `lvpSpecAdmissible` refuses (`head_has_response`, line 2252) and `metaSelect` kept choosing none for 16768 until 16767 committed (35836000); 16768 then ran on the
   architectural register (response 35902000, committed, source none).  **The wrong prediction was never used by any consumer** (`lvpUsedBySpec` false), so there was nothing to
   recover; it is still counted incorrect.  This is not a lost recovery: it is the existing admission rule applied to a different producer state, caused by the bypass of the producer.
   (16767 itself was an LVP consumer of 16766 with a correct operand 0x58000, which the 503 check confirmed.)  [T] plus [F] for the rule.
6. **Tests**: the existing runs do exercise the exact ordering (12 cases above) and the checker invariants (exactly one source, window identities, output/stream equality) hold,
   but the suite does not assert the ordering itself; I verified it with an ad hoc script on the retained traces.  Output equality alone is a weak proof.  A targeted
   test is recommended (below), not because the source leaves the guarantee open but because no check fails if 1703 or the discard path were broken.

## Established invariants
I1 a consumer with an LVP operand cannot handle its response before the producer's response; I2 a wrong used prediction always redirects; I3 a discarded load never writes
state, trains ASTRA, updates the V$ or publishes; I4 provisional bases never train unless validated at the response (510, after the 503 check); I5 provisional candidates never publish a forwarding record.

## Unresolved risks / limits
R1 `lvpUsedBySpec` (1703) is set outside `executeMemRefInst`; correctness depends on that call order and is not asserted.  The 503 panic turns a violation into a stop, not silent corruption, but only if the consumer reaches its response.
R2 Candidate mode deliberately weakens the V-ASTRA rule "bypass only on a validated base" to "bypass on a provisional base covered by LVP recovery"; statistics (syntheticResponses, candidatesDiscarded) include wrong-path bypasses.
R3 The synthetic data of a wrong-operand bypass is the V$ content of a previously accessed address; it is discarded, never used (I3).
R4 Not covered: a wrong-prediction scenario where a *second-level* LVP consumer of the bypassed load exists (it needs C to be the head without a response, so it cannot start before P is validated: argued [I], not tested); SMT/multi-CPU excluded by the V$ guards.
R5 Interpretation of results: the candidate-mode speed-up partly comes from bypassing loads whose operand is still unvalidated.

## Recommendation
The recovery guarantee **can be proved from the existing source** for this scenario; I do not recommend disabling or redesigning the path.  Before keeping it: (1) add trace-derived
checker invariants (for every `Recovery redirect`, every LVP consumer of that producer, bypassed or not, is discarded after the redirect and never handled/committed; bypass tick <= validation tick);
(2) add a `panic_if` in `metaClassify`/`lvpClassify` that a committed LVP consumer's producer had `lvpUsedBySpec` (turns R1 into a hard check); (3) a forced-misprediction kernel (phase flip of the producer's pointer
with a V$-resident wrong target, and a depth-2 chain) run in candidate mode.  These need source/test edits and were not made.
