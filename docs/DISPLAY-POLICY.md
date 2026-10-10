# Display policy: does a lower resolution give the model its VRAM back?

**Short answer: not on our PC. The script works, and it ships switched off.**

## Why we tried it

On the test PC the Windows compositor, `dwm.exe`, held about 2.6 GB of the Arc Pro B60's 24 GB while the card ran a 27B model. The PC has two 3440x1440 monitors. The idea: when nobody is at the screen, drop to fewer pixels so `dwm.exe` needs less, and give the model more headroom for context.

## What we built

[`governor/display-policy.ps1`](../governor/display-policy.ps1), run in your own desktop session (a service cannot change the display):

| State | When | Mode |
|---|---|---|
| PRESENT | keyboard or mouse used in the last 5 minutes | your normal mode, restored from Windows' own saved setting |
| AWAY-REMOTE | idle, and an RDP session or a watched file (the gateway audit log) changed in the last 10 minutes | 2560x1440 |
| AWAY-IDLE | idle, nobody connected | 1920x1080 |

- 60 Hz cap, a 60 s settle time before switching states, and a restore within about 2 s of any input.
- Changes are temporary (nothing is written to the registry), each mode is validated before it is applied, and a failure returns to the normal mode. A kill file or `"enabled": false` in `display-policy.json` stops it and restores the normal mode.
- `-Status` lists each monitor's modes. On our monitors no 2560x1080 mode exists, so "2K" means 2560x1440.
- `-Install` registers a logon task for the current user. Nothing happens until `display-policy.json` has `"enabled": true`.

## What we measured (2026-10-11)

| Moment | dwm.exe dedicated VRAM |
|---|---|
| Native 3440x1440 x2 | 2,571 MB |
| Seconds after switching both to 1920x1080 | 3,250 MB |
| About a minute later | 2,782 MB |
| After returning to native | 3,269 MB |

The switch itself worked (both monitors reached 1920x1080@60 in the same step, and native came back). The compositor's footprint did not follow the pixel count. INFERRED: it is dominated by per-window surfaces and cached buffers rather than by the screen size, so a mode change does not release them. We have not tested restarting `dwm.exe` or closing GPU-composited apps, so the real driver of the 2.6 GB is not established.

## What it still does

Fewer pixels means less for a remote-desktop tool to encode and send, and a cooler idle card. We did not measure either. Windows can rearrange windows when the mode changes, which is the cost. If you want to try it on your own PC, run `-Status`, then `-Set Idle -Hold 20` while you watch, then enable it.

## Next to test (not done)

- Close or minimise GPU-heavy windows (Chrome, Electron apps) and see whether `dwm.exe` drops. That would point at window surfaces.
- Hardware-accelerated scheduling off (needs a reboot, a Windows graphics setting you apply yourself).
- Drive only one monitor while the model is working.
