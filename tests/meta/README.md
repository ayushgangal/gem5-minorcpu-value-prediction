# META selection tests (`enableMeta`)

META chooses, for each dependent load that could only issue early on a
predicted source, exactly one of three outcomes (`Execute::metaSelect`):

1. **V-ASTRA** if the producer's V-ASTRA forwarding record is `Validated`
   (published only at the final bypass success): the existing Design B
   forwarding path serves the load.
2. otherwise **nothing yet** while that record is still `Pending` (a value is
   never taken from an undecided V-ASTRA candidate);
3. otherwise **LVP** if the existing LVP admission rule
   (`lvpSpecAdmissible`: producer is the oldest instruction, predicted and
   outstanding) allows it, with the existing validation and recovery;
4. otherwise the ordinary path.

`enableMeta` requires `enableLVP`, `lvpSpecAddr` and `enableVAstraForwarding`
(and so bypass and scoreboard release) and excludes the test-only fault
injection parameters.  Forwarding and `lvpSpecAddr` stay mutually exclusive
without it.

Counters: `system.cpu.meta.*` (evaluated, selVAstra, selLVP, selNone, outcomes
per source, and why a source was not used).  Debug flag `META` traces
`decide`, `accept` and `outcome` for every consumer.

* `run_meta.sh config`     accepted and rejected parameter combinations
* `run_meta.sh directed`   `meta.c` kernels 1-10 (`KERNELS` overrides the
                           list) and `tests/sou/forward.c` under np / lvp /
                           va / meta (traces)
* `run_meta.sh lifecycle`  LVP, V-ASTRA and bypass programs under np / meta,
                           drain and statistics reset
* `run_meta.sh astra-lvp`  the `metaAstraLvpLoads` experiment (below)
* `run_meta.sh align`      the provisional-base retry test (below)
* `check_meta.py`          the trace checker (one accepted source per
                           consumer, the precedence rule on every decision,
                           the recovery ordering of every wrong used LVP
                           prediction, identity of every statistics window);
                           `check_meta.py selftest TRACE` checks that the
                           recovery-ordering check fails on deliberately
                           broken copies of a trace (temporary files only)
* `meta.c`                 the kernels (see its header)
* `with_alignment.py`      `tests/astra/with_params.py` with the RISC-V ISA's
                           `check_alignment` on (used by `align`)

`OUT` (default `/tmp/meta-test`) is where everything is written; gem5 must
already be built.  `tests/lvp/ldld.c` is built from a copy whose `NUM_SLOTS`
is 1024 instead of 16384, which keeps its traces small.

Large traces: uncompressed per-instruction traces reach hundreds of MB per
program (more for `ldld-fault`, which therefore runs with a light trace whose
checks skip the response and discard lines); run the suites one at a time,
traces are compressed after each checker.

## Experiment: `metaAstraLvpLoads` (default `off`)

With META a load whose source operand came from an LVP prediction is not an
ASTRA/V-ASTRA load (it cannot capture its base: the operand is only a
prediction).  `metaAstraLvpLoads=train` keeps the operand as a *provisional*
ASTRA base and makes it the actual base only when the load's response is
handled, after the check that the register equals the LVP operand (a wrong
prediction squashes the load before that), so ASTRA trains once on a validated
base.  `candidate` also lets the V-ASTRA decision use the provisional base
(ASTRA's predicted base must equal the LVP operand); such a load may be
bypassed but never publishes a forwarding record.  Counters
`meta.provisional*`; `run_meta.sh astra-lvp` runs np / off / train / cand.

`run_meta.sh astra-lvp` runs `meta.c` kernels 3 4 5 7 10 11 12 (`KERNELS`
overrides the list, `KERNELS_ONLY=1` skips the other programs), the LVP
programs, `forward.c` and drain / reset, each under np / off / train / cand.
Kernel 12 forces mispredictions whose consumers are bypassed in candidate
mode before the producer is validated; the checks require each of them to be
discarded after the recovery redirect and never committed.

## Provisional-base retry test (`run_meta.sh align`)

An early-issued load served by an LVP operand records a provisional ASTRA
base (`train`, `candidate`).  If its `initiateAcc` then faults before a
request exists, it is executed again at the head; the provisional base of the
failed attempt must be dropped there (`Execute::astraCaptureBase`), otherwise
the committed load would still carry it.

Kernel 13 builds that case: a load 2048 bytes before the producer (the same
entry of the untagged LVP table) makes the predictor confident in a
misaligned value, so the producer's consumer is sent early with a misaligned
address.  It needs `check_alignment=True` on the RISC-V ISA (the default is
`False`, where a misaligned address does not fault in `initiateAcc`), which
`with_alignment.py` sets.  The test runs four configurations: np (no
prediction), off (META), train and cand (`metaAstraLvpLoads`).  It checks, for
each: exit status 0 and output and committed instruction stream identical to
np; no architectural fault; the early faults are all the consumer's (none in
np), and every such instance committed at the head, published no forwarding
record and was not bypassed; ASTRA never trained the consumer on a misaligned
base; in train and cand every provisional base of a faulting attempt was
dropped (created = dropped + validated, from the trace), none in off; the
statistics-window identities and the META invariants.
