#!/bin/bash
# pauses (never kills) the indexer if free space falls below 3.5 GB
while true; do
  a=$(df --output=avail -m /home | tail -1)
  if [ "$a" -lt 3500 ]; then kill -STOP 4292 2>/dev/null && echo "$(date +%T) free ${a}MB: indexer paused" >> $HOME/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage3-meta/logs/indexwatch.log; fi
  sleep 5
done
