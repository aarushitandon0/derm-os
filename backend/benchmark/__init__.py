"""derm//os evidence benchmark: scripted cases with hand-written expected outputs.

Written by the derm//os team, so it is not an independent evaluation. It checks
that the engine does what the design promises; it says nothing about how
accurate YouCam's skin scores are.

    python -m benchmark            (from backend/)  -> prints pass counts, writes results/benchmark.md
    python -m pytest tests/test_evidence_benchmark.py
"""
import os

# Never read backend/.env here: the benchmark makes no YouCam calls and needs no key.
os.environ.setdefault("DERMOS_NO_DOTENV", "1")
