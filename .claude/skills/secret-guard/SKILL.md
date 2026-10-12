---
name: secret-guard
description: >
  Keep credentials out of git — pre-commit secret scanning, incident response
  for a committed secret, and safe-config conventions. Use before any commit
  touching config/env/scripts, when setting up a new repo, or the moment a
  key is suspected leaked. Enforces the father rule "never commit secrets".
---

# secret-guard — secrets never reach the remote

Distilled from `gitleaks/gitleaks` (MIT) and `pre-commit/pre-commit` (MIT) —
patterns re-expressed; use the installed binaries where present.

## Extracted logic

1. **Scan the diff, not the repo, on every commit.** The cheap, always-on
   check is staged-diff scanning: `gitleaks protect --staged` if installed,
   else the stdlib fallback — grep the staged diff for the high-signal
   classes before committing:
   - `sk-[A-Za-z0-9]{20,}`, `ghp_[A-Za-z0-9]{36}`, `xox[bap]-`, `AKIA[0-9A-Z]{16}`
   - `-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----`
   - `(api[_-]?key|secret|token|password)\s*[:=]\s*['"][^'"]{16,}`
   Match found → stop, unstage, move the value to env.
2. **Convention beats vigilance:** real values live in `.env` (gitignored),
   committed files carry `.env.example` with names only. Config code reads
   `os.environ[...]` and fails loud when unset — never a hardcoded fallback
   secret "for dev".
3. **History is the trap.** A secret deleted in the next commit is still
   leaked — the scan matters *before* the first push, because after it the
   only fix is rotation.
4. **Incident response (already pushed):** (a) **rotate the credential
   first** — history rewriting without rotation is theatre; (b) then purge
   history (`git filter-repo`) and force-push only with the owner's
   sign-off; (c) check provider logs for use of the leaked key; (d) note
   the incident where the team will see it.
5. **New-repo setup:** `.gitignore` gets `.env*`, `*.pem`, `*.key`,
   `credentials*.json` on day one; add a pre-commit hook running the §1 scan
   if the repo has contributors beyond Claude sessions.

## Procedure (pre-commit gate)

1. `git diff --staged` → run the §1 patterns.
2. Hit → unstage the file, externalise to env, add to `.env.example`, rescan.
3. Clean → commit. Mention in the commit flow only when something was caught.

## Verification

- Staged diff scans clean; no new file matches the ignore-class patterns;
  any caught value confirmed rotated if it ever left the machine.
