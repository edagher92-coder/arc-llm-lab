# ComfyUI v2 (Elz front-end extension)

"ComfyUI v2" is the stock ComfyUI with one extra front-end file. There is no fork: the
extension lives in `web/elz_studio.js` and is loaded through `WEB_DIRECTORY = "./web"`
in `elz_nodes/__init__.py`.

## What it adds

- **Studio button**: opens `https://<this host>:8447/approvals/studio` in a new tab.
  It appears in the top menu when the frontend exposes that menu, otherwise as
  "Elz: Open Studio" in the command palette.
- **Status badge** (bottom right): queue remaining from the `status` event, and the
  elapsed time of the running prompt. It stops when the prompt finishes or errors.
- **Release GPU**: a hint only. It tells you to stop the session from Studio. It makes no
  backend calls and stops nothing.
- **Node colours**: `LTX*` nodes and `Elz*` nodes get a fixed colour preset on graph load
  and when created.

Every feature is feature-detected and wrapped in try/catch. If a frontend update changes
an API, the feature goes quiet and the rest of ComfyUI still works. The extension makes no
external network requests and uses no `eval`.

## Full ComfyUI on the tailnet

The full ComfyUI UI is reachable at **https://<your-machine>.<your-tailnet>.ts.net:8448** only while
a Studio "ComfyUI session" is running. Stop the session in Studio to take it down.

ComfyUI has no login. Access control is the tailnet. Keep the port tailnet-only.

**Never expose it with Tailscale Funnel.** Funnel makes a port public on the internet, and
ComfyUI has no authentication. Do not add port 8448 to Funnel, and do not add any other
Funnel config for this host.

## Files

- `web/elz_studio.js`: the extension
- `__init__.py`: `WEB_DIRECTORY` line only; node classes are unchanged
- `tests/test_elz_web.py` (in `gateway/`): checks the path, the file, `registerExtension`, and no `http://` or `eval(`
