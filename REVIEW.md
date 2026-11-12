# Review: Aster Resource Check v0.1

Reviewed 2026-11-12. Scope: Linux compatibility, CPU/load interpretation, memory and disk math, error handling, CLI behaviour, security, tests. Constraints kept: standard library only, read-only, no daemon, network access or deployment. Nothing was deployed.

## Fixed

Each fix has a regression test that fails on the original v0.1 code (10 failures and 1 error when the new suite runs against v0.1).

| # | Area | Issue | Evidence | Fix |
|---|------|-------|----------|-----|
| 1 | Disk | `used_percent = used / total` counts root-reserved blocks as usable, so the figure reads lower than `df`. On a stock ext4 root (5% reserved), the tool shows ~95% when `df` shows 100% and non-root services such as PostgreSQL or PHP can no longer write. A `--disk-warn` above 95 could therefore never fire. | Review host: `/` 4.7% vs `df` 29%; `/opt/claude-code` 90.7% vs `df` 93%. | `used / (used + free)`, the same formula `df` uses. Added `disk.used_bytes` so the percentage can be reproduced from the JSON. |
| 2 | Errors / exit codes | A failure writing stdout (for example, output redirected to a log on a full disk) raised a traceback and exited `1`, the code reserved for "threshold exceeded". A cron wrapper would read a broken run as a warning. | `resource_check.py > /dev/full` → traceback, exit 1. | Catch `OSError` on output → message on stderr, exit `2`. Uses the stdlib-documented `dup2(devnull)` pattern so the exit-time flush cannot raise again. |
| 3 | CLI | `nan` and `inf` passed the `x < 0` check. A `nan` threshold disables its check silently (exit 0, `OK`). Percentages above 100 also disabled checks silently. | `--memory-warn nan --disk-warn nan --load-warn nan` → `OK`, exit 0. | Thresholds must be finite and ≥ 0; memory and disk thresholds must be in the 0–100 range. Invalid values get an argparse usage error (exit 2). Added help text to `--memory-warn` and `--disk-warn`. |
| 4 | Memory | If `MemTotal` is missing, memory is `null` and the status is `OK` (a silent false OK). | Fixture without `MemTotal` → `warnings=[]`. | Raise `ValueError` → exit 2. |
| 5 | Memory | Without `MemAvailable` (kernels before 3.14, e.g. old OpenVZ), the code fell back to `MemFree` alone. That counts page cache as used and contradicts the README. | 2 GiB fixture with 1.5 GiB cache → false 87.5% warning. | Fallback is now `MemFree + Buffers + Cached` (classic `free` behaviour): 62.5% for the same fixture. |
| 6 | Memory | An `available` value above `total` (virtualised `/proc`) produced a negative used %. | Fixture → negative percentage. | Clamp `available` to `total`. |
| 7 | CLI output | Text output printed `Swap: None% used` on swapless hosts (the Ubuntu cloud-image default) and `Disk: None% used` on pseudo-filesystems. | Live run on the review host. | `Swap: none configured` and `Disk: n/a`. The JSON output is unchanged (`null`). |
| 8 | Security / packaging | The zip shipped `__pycache__/*.pyc` for CPython 3.13. Their headers matched the sources, so Python 3.13 would execute the bytecode instead of the reviewed `.py`. The shipped files were benign (bytecode identical to the source) but cannot be audited by reading them, and they recorded a build path (`/mnt/data/...`). | Header and bytecode comparison against the source. | Removed. Added `.gitignore`. The README now says to distribute source only. |
| 9 | Tests | 5 tests. Nothing exercised `snapshot()`, the success path of `main()`, text output, exit codes 0/1, or the disk formula. | n/a | 27 tests, hermetic (mocked `/proc`, `statvfs` and loadavg). The 5 original tests are kept unchanged. Three live-Linux smoke tests skip automatically elsewhere. Tests also run from any directory. |
| 10 | Docs | Calculations, exit-code meanings and the container caveat were undocumented. | n/a | README documents formulas, threshold rules, exit-code meanings, the container caveat and tested Python versions. `sample-output.json` was regenerated for the new schema. |

## Reviewed, no change needed

- **Linux compatibility:** the tool uses only `/proc/meminfo`, `statvfs`, `getloadavg()` and `uname()`. Without `/proc/meminfo` (non-Linux) it exits 2 cleanly. All tests pass on Python 3.8–3.13; 3.10 and 3.12 match Ubuntu 22.04 and 24.04.
- **Load denominator:** on Linux, `os.cpu_count()` returns the *online* CPUs (strace shows it reading `/sys/devices/system/cpu/online`). That is the correct divisor for the system-wide load average, and it matched `nproc`. One caveat: on Python ≥ 3.13, the `PYTHON_CPU_COUNT` environment variable or `-X cpu_count` overrides it. That is an operator setting and was left alone.
- **Load meaning:** the README already says load is not CPU % and includes I/O wait. A note was added that the 1-minute value is spiky on 1 vCPU.
- **Rounding:** threshold comparisons use the displayed (rounded) values, so a warning's text always agrees with the printed numbers. The effect is at most 0.05 percentage points.
- **Memory definition:** `total − MemAvailable` matched the `available` column of `free -b` exactly.
- **Pipes:** `| head -c1` exits 0 with no `BrokenPipeError`.
- **Read-only and no network (strace):** no write-mode opens, no sockets, no file-modifying syscalls and no subprocesses. The tool works as `nobody`; root is not required.
- **Footprint:** about 13 MiB peak RSS and 31–37 ms per run (Python 3.12/3.13).

## Not changed: suggestions for a later version (outside "minimal fixes")

- For cron-driven checks on 1 vCPU, consider warning on the 5-minute load, or PSI (`/proc/pressure/{cpu,memory,io}`, available on Ubuntu kernels), which measures stall time directly.
- An inode usage check (`statvfs` `f_files`/`f_favail`). Running out of inodes is a common VPS failure (PHP sessions, mail queues) and costs nothing to read.
- An optional swap-usage threshold.
- A `--version` flag.

## Test results

See `test-results.txt` (delivered alongside). Summary: 27/27 passed on CPython 3.8.20, 3.9.25, 3.10.20, 3.11.18, 3.12.3 and 3.13.18; pyflakes clean. The new suite fails on v0.1 (10 failures, 1 error), confirming that each regression test detects its bug.

Note: `sample-output.json` was produced on the review sandbox (2 vCPU, 8 GiB, quota-limited disk), not on a 1-vCPU/2-GiB VPS. On that disk `used + free` is far below `total` because of a quota, the same effect as reserved blocks, only larger.
