# Gateway deploy with automatic rollback

Two commands. Windows 11, PowerShell 5.1, run from a normal shell (not from inside the hub).

## 1. Build the bundle (cloud/Linux, repo root)

```bash
tools/deploy/make_bundle.sh <from_ref> <to_ref> /mnt/user-data/outputs/bundle-<unique>.zip
```

Zips the files changed under `gateway/` between the two refs (tests and `__pycache__` excluded) with a
`MANIFEST.json` (`from`, `to`, `files[{path, sha256}]`, `deleted[]`). The last line printed is the zip SHA256.
Send the zip to `C:\AI\deploy\` (use a new staged filename every time; the bridge caches by name).

## 2. Deploy (PC)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\deploy\deploy.ps1 -Zip C:\AI\deploy\bundle-<unique>.zip -Sha256 <hex>
```

Add `-DryRun` first to see the plan (hash check, per-file SAME/CHANGE/NEW, busy state) with nothing changed and
no restart. Add `-ApplyDeletes` to also remove files the manifest lists as deleted (off by default).

What it does, in order:

1. Verifies the zip SHA256 and every file against the manifest.
2. Busy guard: aborts (exit 2) if `state\video\jobs.json` has a job `queued/waiting/starting/running` or anything
   listens on 127.0.0.1:8188.
3. Backs up each live file to `C:\AI\gateway\backups\<yyyyMMdd-HHmmss>-<to>\` (mirrored, including the ComfyUI
   `elz_nodes` copies) and writes `restore.ps1` there.
4. Installs `gateway/<x>` to `C:\AI\gateway\<x>`; `gateway/comfy_nodes/elz_nodes/*` also to
   `...\ComfyUI\custom_nodes\elz_nodes`.
5. Restarts the `Local MCP hub (mcpo)` task in a detached process (stop task, taskkill /T owners of 8100 and 8093,
   start task) and polls up to 120 s for both ports plus `GET /approvals/studio` == 200.
6. If that fails (or the install fails), runs the backup's `restore.ps1`, restarts again, exits 1.
7. Appends one JSON line to `C:\AI\gateway\deploy.log` (time, to, zip_sha256, files, ok, seconds, backup, rolled_back).

Exit codes: 0 ok, 1 failed and rolled back, 2 aborted (busy), 3 bad input/bundle.

## Rollback by hand

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\gateway\backups\<folder>\restore.ps1 -Restart
```

Files that were new in that deploy are removed; changed files are put back. `-Restart` bounces the hub and
reports the health result. Without `-Restart` only files are restored.

## Never touched

`gateway.json`, anything under `gateway\state\`, `secrets`, `.env*` files, `backups\`, `deploy.log`. Manifest
entries matching those are refused before anything is written. Tests are never bundled.
