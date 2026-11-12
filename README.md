# Aster Resource Check

A tiny, read-only Linux VPS resource checker. Python 3.9+ (tested on 3.9–3.13), standard library only, released under the GNU General Public License v3.0 (GPL-3.0-only).

## Usage

```bash
python3 resource_check.py
python3 resource_check.py --json
python3 resource_check.py --path /srv --memory-warn 80 --disk-warn 90 --load-warn 1.5
python3 -m unittest discover -s tests -v
```

Run the tests from the project directory. The live-system smoke tests are skipped automatically on non-Linux hosts.

Exit codes: `0` healthy; `1` threshold exceeded; `2` error (invalid arguments, unreadable `/proc/meminfo`, bad `--path`, or output that cannot be written). JSON contains UTC timestamp, hostname, CPU count and **1/5/15-minute load averages**, memory availability, swap use and filesystem usage. `load_1_per_core` is *not* CPU utilization percentage. Disk paths on the same filesystem may report identical values.

How values are calculated:

- **Memory** `used_percent` = (`MemTotal` − `MemAvailable`) / `MemTotal`, so reclaimable page cache is not counted as used. On kernels older than 3.14 (no `MemAvailable`), available memory is estimated as `MemFree + Buffers + Cached`, as older versions of `free` did.
- **Disk** `used_percent` = `used_bytes` / (`used_bytes` + `free_bytes`), the same formula `df` uses for Use%. `free_bytes` is the space available to non-root users. Root-reserved blocks (usually 5% on ext4) are excluded, so 100% means non-root services can no longer write.
- **Swap**: hosts without swap (the Ubuntu cloud-image default) show `Swap: none configured` (`used_percent: null` in JSON).
- **Load**: the warning uses the 1-minute average divided by online CPUs. On a 1-vCPU host, that average spikes briefly during apt runs, backups or cron jobs. Read it alongside the 5- and 15-minute values before acting.
- **Thresholds** are inclusive (`>=`). They must be finite and non-negative, and `--memory-warn` / `--disk-warn` are percentages between 0 and 100.

## Security and limitations

- Local operator execution only. This tool does not connect to SSH, enumerate users/processes, read credentials, contact networks, or modify server configuration.
- No scheduler, logging retention, background agent or external alerts by default. Avoid sharing hostname or diagnostic JSON publicly if it is sensitive.
- Works on Linux with `/proc/meminfo`. CPU load averages are not instantaneous CPU utilization; a high load can also reflect I/O wait.
- Inside a container (Docker, or LXC without lxcfs), `/proc/meminfo` and the load average describe the host, not the container's cgroup limits. On a full VM (KVM) VPS they describe the VPS itself.
- Runs as an ordinary user; root is not needed. Distribute the source only. Do not ship `__pycache__/*.pyc`, because Python may execute a bundled `.pyc` instead of the reviewed `.py`.
- For remote servers, run after separately authorized SSH login. Do **not** add shell execution to a read-only MCP connector.
- Test on a disposable machine before production use. Do not install automatically, touch systemd, or deploy into a live VPS without approval.

## Project and contact

**Publisher / maintainer:** [TheCustomizeWindows.com](https://thecustomizewindows.com)  
**Website:** https://thecustomizewindows.com  
**Contact / security reports:** [admin@thecustomizewindows.com](mailto:admin@thecustomizewindows.com)  

Report reproducible problems via GitHub Issues once the repository is live, or contact the maintainer by email. Please do not publish sensitive server diagnostic output, private hostnames or credentials in public issues.

## License

Copyright (C) 2026 TheCustomizeWindows.com.

Aster Resource Check is free software under the **GNU General Public License, version 3 only** (`GPL-3.0-only`). You may use, study, modify and redistribute it subject to that license's terms. The full license text is included in [`LICENSE`](LICENSE). This software comes with **no warranty**.

