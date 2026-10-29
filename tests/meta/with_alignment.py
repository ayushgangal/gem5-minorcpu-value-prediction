# gem5 config wrapper for run_meta.sh align: tests/astra/with_params.py (and
# so configs/research/vp_baseline.py) with the RISC-V ISA's check_alignment
# on, so that a misaligned load raises an address fault in initiateAcc.
# Takes the arguments of with_params.py.

import os
import runpy
import sys

import m5

HERE = os.path.dirname(os.path.abspath(__file__))
WITH_PARAMS = os.path.join(HERE, "..", "astra", "with_params.py")
original = m5.instantiate


def instantiate(*a, **k):
    from m5.objects import Root

    for isa in Root.getInstance().system.cpu.isa:
        isa.check_alignment = True
    return original(*a, **k)


m5.instantiate = instantiate
sys.argv = [WITH_PARAMS] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
