---
name: browser-verify
description: >
  Verify web UI changes by actually rendering them — drive Chromium via
  Playwright, screenshot, assert on real DOM/console/network state. Use
  whenever a change has a rendered surface (page, dashboard, email preview,
  ad creative) and "tests pass" isn't the same as "it looks right". Not for
  API-only changes.
---

# browser-verify — see it render before claiming it works

Distilled from `microsoft/playwright` (Apache-2.0 — importable).

## Extracted logic

1. **A rendered surface is only verified rendered.** Type checks and unit
   tests cannot see overlap, contrast failures, hydration errors, or a
   broken layout. If the change touches anything a human sees, drive it.
2. **Use the pre-installed browser.** Cloud sessions ship Chromium at
   `/opt/pw-browsers` (`PLAYWRIGHT_BROWSERS_PATH` is set) — never run
   `playwright install`. If the project pins its own Playwright version,
   launch with `executablePath: '/opt/pw-browsers/chromium'`.
3. **The observation loop:** start the app → `page.goto` → wait for a
   *content* signal (`locator.wait_for`), never a fixed sleep → capture
   evidence. Evidence = screenshot + console errors + failed network
   responses, all three every time:
   ```python
   errors = []
   page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
   page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
   page.goto(url); page.locator("main").wait_for()
   page.screenshot(path="evidence.png", full_page=True)
   ```
4. **Assert on state, not pixels.** Screenshots are for the human report;
   pass/fail comes from DOM assertions (`expect(locator).to_have_text`),
   console-error count == 0, and no 4xx/5xx on first load.
5. **Check the two viewports that matter:** 390×844 (phone) and 1440×900
   (desktop). Wide content must scroll inside its container, not the body.
6. **Auth walls:** use a storage-state file or test account from env — never
   hardcode credentials, never verify against production with real user data.

## Procedure

1. Launch the project per its run skill/README; confirm the port answers.
2. Drive the changed flow with the loop above; save `evidence.png`.
3. Report: what was asserted, console/network error count, the screenshot.
   A claim of "renders correctly" without these three is unverified.

## Verification

- Screenshot exists and shows the changed surface; zero console errors;
  zero failed requests on the exercised flow (or each one explained).
