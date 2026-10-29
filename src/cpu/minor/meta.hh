/*
 * Copyright (c) 2023 The Regents of the University of California
 * All rights reserved
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/**
 * @file
 *
 *  META selection between the two value-prediction sources of a dependent
 *  load: V-ASTRA (a validated, published value) and LVP (a confident,
 *  not yet validated prediction).  This holds the decision enumeration, the
 *  per-consumer accounting and the statistics.  The admission itself is in
 *  Execute::metaSelect().
 */

#ifndef __CPU_MINOR_META_HH__
#define __CPU_MINOR_META_HH__

#include <cstdint>

#include "base/statistics.hh"
#include "cpu/minor/dyn_inst.hh"

namespace gem5
{

namespace minor
{

class MetaSelector : public statistics::Group
{
  public:
    explicit MetaSelector(statistics::Group *parent);

    /** A consumer is evaluated for the first time (a load whose request
     *  could only be sent early using a predicted source) */
    void evaluated() { ++stats.consumersEvaluated; ++liveCons; }

    /** The consumer's final source, once, where it leaves the in-flight
     *  queue.  kind: 0 committed, 1 squashed, 2 faulted */
    void resolved(MetaSource source, int kind);

    /** Reasons, each once per consumer */
    void seen(uint16_t &flags, uint16_t bit, statistics::Scalar &stat)
    {
        if (!(flags & bit)) {
            flags |= bit;
            ++stat;
        }
    }

    /** ASTRA bases taken from an LVP operand (metaAstraLvpLoads): created
     *  at the load's issue, then validated (its response) or dropped (the
     *  load was squashed or faulted first) */
    void provisionalCreated() { ++stats.provisionalBases; ++liveProv; }
    void
    provisionalResolved(bool validated)
    {
        panic_if(liveProv == 0, "META: provisional base resolved twice");
        --liveProv;
        ++(validated ? stats.provisionalValidated : stats.provisionalDropped);
    }
    uint64_t liveProvisional() const { return liveProv; }
    uint64_t provCarryInAtReset() const { return carryProv; }

    uint64_t liveConsumers() const { return liveCons; }
    uint64_t carryInAtReset() const { return carryCons; }

    void resetStats() override;

  private:
    uint64_t liveCons = 0;
    uint64_t carryCons = 0;
    uint64_t liveProv = 0;
    uint64_t carryProv = 0;

  public:
    struct MetaStats : public statistics::Group
    {
        MetaStats(statistics::Group *parent, const MetaSelector &owner);

        /** Consumers evaluated once, and the source each ended with */
        statistics::Scalar consumersEvaluated;
        statistics::Scalar selVAstra;
        statistics::Scalar selLVP;
        statistics::Scalar selNone;
        statistics::Value consumersInFlight;
        statistics::Value consumersCarryIn;

        /** Outcome of the consumers of each source */
        statistics::Scalar vastraCommitted;
        statistics::Scalar vastraSquashed;
        statistics::Scalar vastraFaulted;
        statistics::Scalar lvpCommitted;
        statistics::Scalar lvpSquashed;
        statistics::Scalar lvpFaulted;

        /** Why a source was or was not used (each once per consumer) */
        statistics::Scalar vastraValidated;
        statistics::Scalar vastraPending;
        statistics::Scalar vastraFailed;
        statistics::Scalar vastraNoRecord;
        statistics::Scalar lvpAdmissible;
        statistics::Scalar lvpRefused;
        statistics::Scalar lvpHeldForVAstra;
        /** V-ASTRA served a consumer for which LVP could also be used or
         *  had a prediction for its source (V-ASTRA won) */
        statistics::Scalar vastraOverLvp;
        statistics::Scalar bothAdmissible;

        /** ASTRA bases of loads served by an LVP operand: created,
         *  validated, dropped; provisionalBases + provisionalCarryIn ==
         *  validated + dropped + provisionalInFlight */
        statistics::Scalar provisionalBases;
        statistics::Scalar provisionalValidated;
        statistics::Scalar provisionalDropped;
        statistics::Value provisionalInFlight;
        statistics::Value provisionalCarryIn;
    } stats;
};

} // namespace minor
} // namespace gem5

#endif /* __CPU_MINOR_META_HH__ */
