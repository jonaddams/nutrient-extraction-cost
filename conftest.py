"""Suite-wide fixture-free setup: run every test outside UTC.

costlab/compare.py's `_to_ymd` deliberately never builds a datetime, because a
datetime carries a timezone question this comparison has no business asking:
"2025-03-01" and "March 1, 2025" are the same calendar day, and any
implementation that turns them into instants gets that right in UTC and wrong
by one day in half the world. That docstring claims the date tests run under a
non-UTC TZ precisely to catch a port that forgets it — this file is what makes
the claim true. Without it, a UTC developer machine and a UTC CI runner would
both stay green against exactly the bug the design exists to prevent.

Asia/Kolkata rather than a whole-hour offset on purpose: it is UTC+05:30, so it
also catches an implementation that happens to be correct only for integral
offsets (a half-hour shift moves a local midnight across the date line for a
strictly wider set of instants than a whole-hour one does).

`setdefault`, never an unconditional assignment: a developer or CI job running
`TZ=UTC pytest` or `TZ=America/New_York pytest` to check a specific zone must
keep the zone they asked for. The default only applies when nothing was chosen.
"""

import os
import time

os.environ.setdefault("TZ", "Asia/Kolkata")
# Python caches the process timezone at first use; tzset() re-reads TZ so the
# setdefault above actually takes effect rather than being read too late.
if hasattr(time, "tzset"):
    time.tzset()
