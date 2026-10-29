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

#include "cpu/minor/meta.hh"

#include "base/logging.hh"

namespace gem5
{

namespace minor
{

MetaSelector::MetaSelector(statistics::Group *parent) :
    statistics::Group(parent, "meta"),
    stats(this, *this)
{
}

MetaSelector::MetaStats::MetaStats(statistics::Group *parent,
    const MetaSelector &owner) :
    statistics::Group(parent),
    ADD_STAT(consumersEvaluated, statistics::units::Count::get(),
             "Dependent loads evaluated for an early request (once each)"),
    ADD_STAT(selVAstra, statistics::units::Count::get(),
             "Evaluated consumers served by a validated V-ASTRA value"),
    ADD_STAT(selLVP, statistics::units::Count::get(),
             "Evaluated consumers served by an LVP prediction"),
    ADD_STAT(selNone, statistics::units::Count::get(),
             "Evaluated consumers that used neither source"),
    ADD_STAT(consumersInFlight, statistics::units::Count::get(),
             "Evaluated consumers without an outcome yet"),
    ADD_STAT(consumersCarryIn, statistics::units::Count::get(),
             "consumersInFlight at the most recent statistics reset"),
    ADD_STAT(vastraCommitted, statistics::units::Count::get(),
             "V-ASTRA consumers that committed"),
    ADD_STAT(vastraSquashed, statistics::units::Count::get(),
             "V-ASTRA consumers that were squashed"),
    ADD_STAT(vastraFaulted, statistics::units::Count::get(),
             "V-ASTRA consumers that faulted"),
    ADD_STAT(lvpCommitted, statistics::units::Count::get(),
             "LVP consumers that committed"),
    ADD_STAT(lvpSquashed, statistics::units::Count::get(),
             "LVP consumers that were squashed"),
    ADD_STAT(lvpFaulted, statistics::units::Count::get(),
             "LVP consumers that faulted"),
    ADD_STAT(vastraValidated, statistics::units::Count::get(),
             "Consumers whose producer had a validated V-ASTRA value"),
    ADD_STAT(vastraPending, statistics::units::Count::get(),
             "Consumers that found the V-ASTRA record pending (waited)"),
    ADD_STAT(vastraFailed, statistics::units::Count::get(),
             "Consumers that found the V-ASTRA record failed"),
    ADD_STAT(vastraNoRecord, statistics::units::Count::get(),
             "Consumers whose producer was no V-ASTRA candidate"),
    ADD_STAT(lvpAdmissible, statistics::units::Count::get(),
             "Consumers the LVP rules admitted"),
    ADD_STAT(lvpRefused, statistics::units::Count::get(),
             "Consumers the LVP rules did not admit when consulted"),
    ADD_STAT(lvpHeldForVAstra, statistics::units::Count::get(),
             "Consumers LVP could serve but that waited for a pending "
             "V-ASTRA outcome"),
    ADD_STAT(vastraOverLvp, statistics::units::Count::get(),
             "V-ASTRA consumers whose source also had an LVP prediction"),
    ADD_STAT(bothAdmissible, statistics::units::Count::get(),
             "Consumers both sources could serve at the same time"),
    ADD_STAT(provisionalBases, statistics::units::Count::get(),
             "ASTRA bases taken from an LVP operand (metaAstraLvpLoads)"),
    ADD_STAT(provisionalValidated, statistics::units::Count::get(),
             "Provisional bases validated when the load's response was "
             "handled"),
    ADD_STAT(provisionalDropped, statistics::units::Count::get(),
             "Provisional bases of loads squashed or faulted before "
             "validation"),
    ADD_STAT(provisionalInFlight, statistics::units::Count::get(),
             "Provisional bases not yet validated or dropped"),
    ADD_STAT(provisionalCarryIn, statistics::units::Count::get(),
             "provisionalInFlight at the most recent statistics reset")
{
    provisionalInFlight.functor(
        [&owner]() { return owner.liveProvisional(); });
    provisionalCarryIn.functor(
        [&owner]() { return owner.provCarryInAtReset(); });
    consumersInFlight.functor([&owner]() { return owner.liveConsumers(); });
    consumersCarryIn.functor(
        [&owner]() { return owner.carryInAtReset(); });
}

void
MetaSelector::resolved(MetaSource source, int kind)
{
    panic_if(liveCons == 0, "META: outcome for a consumer that was not "
        "evaluated");
    --liveCons;

    switch (source) {
      case MetaSource::VAstra:
        ++stats.selVAstra;
        ++(kind == 0 ? stats.vastraCommitted : kind == 1 ?
            stats.vastraSquashed : stats.vastraFaulted);
        break;
      case MetaSource::LVP:
        ++stats.selLVP;
        ++(kind == 0 ? stats.lvpCommitted : kind == 1 ?
            stats.lvpSquashed : stats.lvpFaulted);
        break;
      default:
        ++stats.selNone;
        break;
    }
}

void
MetaSelector::resetStats()
{
    /* The live count survives the reset; the identity
     *   consumersEvaluated + consumersCarryIn == selVAstra + selLVP +
     *       selNone + consumersInFlight
     * holds in every statistics window */
    carryCons = liveCons;
    carryProv = liveProv;
    statistics::Group::resetStats();
}

} // namespace minor
} // namespace gem5
