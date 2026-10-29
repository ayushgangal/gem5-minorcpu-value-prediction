# Stage 2b feasibility review (read-only), 2026-10-23

Recommendation: prototype Option A (synthetic LSQ response, memory access suppressed) first, in
`LSQ::tryToSendToTransfers`, next to the existing store-buffer forwarding, with an in-simulation
functional check. B is not feasible without restructuring the LSQ; C needs A (or the LVP recovery path).

Key source facts
- A load: early issue -> executeMemRefInst (decision point; initiateAcc builds the request) ->
  LSQ::pushRequest -> translation (same tick in SE) -> LSQ::step/tryToSendToTransfers -> sendTimingReq ->
  recvTimingResp/retireResponse (state Complete) -> at the head, findResponse -> handleMemResponse
  (completeAcc writes the register, LVP validation, V$ update) -> popResponse (delete request) -> pop.
- Loads already complete without memory: store-buffer forwarding (lsq.cc ~1096): forwardStoreData memcpy
  into the packet, makeResponse, do_access=false, setState(Complete), moveFromRequestsToTransfers.
- popResponse deletes the request: a request cannot retire while its packet is in the memory system.
- Syscalls run at commit (fault invoke) and write memory outside the LSQ: the V$ must be flushed then.
