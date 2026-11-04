# M7 sandbox fixture

Run `PYTHONPATH=m0 /path/to/pilot/python research/experiments/2026-11-05-m7-pilot-sandbox/run.py` on a Linux host with the configured bubblewrap/seccomp dependencies. This runs synthetic public CSV data and a loopback response server, not a real model or official benchmark. The observed one-iteration full-profile run and exact source revision are in `summary.json`. The temporary fixture ledger is created separately and never touches the user campaign.
