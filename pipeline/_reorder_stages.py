"""Move the connectivity and drainage stages to run after the population stage.

The screening reads population_grid_1km.parquet from the current run, so it
cannot execute before that stage has written it. Previously it picked up the
in-progress run directory and failed on a file that did not exist yet.
"""

from pathlib import Path

P = Path("pipeline/bkkflow/city_runner.py")
src = P.read_text(encoding="utf-8")

START = "    # ---- observed-hazard connectivity screening --------------------------"
END = "    # ---- population ------------------------------------------------------"

start = src.index(START)
end = src.index(END)
block = src[start:end]
src = src[:start] + src[end:]

# Re-insert immediately before the validation section, after population exists.
ANCHOR = "    # ---- validation ------------------------------------------------------"
assert src.count(ANCHOR) == 1, src.count(ANCHOR)
src = src.replace(ANCHOR, block + ANCHOR, 1)

P.write_text(src, encoding="utf-8")
print("stages moved after the population stage")
