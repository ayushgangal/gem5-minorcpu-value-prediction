#!/bin/bash
# kills gem5 if the disk runs low (a run's own trace would otherwise fill it)
while true; do
  a=$(df --output=avail -m /home | tail -1)
  if [ "$a" -lt 300 ]; then pkill -x gem5.opt; echo "$(date +%T) disk low ${a}MB: gem5 killed" >> ~/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage3-meta/logs/diskwatch.log; fi
  sleep 3
done
