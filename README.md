# Desktop agent

A local Windows desktop agent. A model calls one bridge. The bridge captures
the screen, reads it with OCR, remembers what happened, and can move the mouse
or type. Risky calls can be planned with `dry_run` and not executed.

The code is a rewrite of four public computer-use repositories plus the
existing MilesMemory server. It is not a copy of those trees.

| Piece | Where it came from |
| --- | --- |
| Mouse, keyboard, region grab, model downsample | [vision-primitives-mcp](https://github.com/zouyuanqing/vision-primitives-mcp) Win32 and Pillow tools |
| Allowlist, dangerous-label gate, launch and focus | [dsh-computer-use](https://github.com/988hj7tczd-oss/dsh-computer-use) |
| Settings lookup and the Ollama `read_text` OCR swap | [ollama-vision-mcp](https://github.com/xkiranj/ollama-vision-mcp) |
| Image and video tools | [opencv-mcp-server](https://github.com/GongRzhe/opencv-mcp-server) — read, not ported; screen pixels stay in Pillow |
| Window tools that do not steal focus | [PC-Control](https://github.com/VortexJer/PC-Control) `windows`, `look`, `click`, `type`, `drag`, `key`, `scroll`, `read`, `show`, `open_app` |
| Long-term recall | [MilesMemory](https://github.com/Staerrz/MilesMemory) `memory_kb` |

None of the four desktop repositories is a memory core. Observation snapshots
and the vision scratchpad are not SQLite recall. Long-term memory is
MilesMemory: cell-mem `memory_recall` and agent-memory-os `search_memories`.
Session and tool events are a separate table in this process. A summary can be
archived into both long-term stores. The two rankers are not fused.

## Layout

```text
desktop_agent/
  core/       config, logging, settings
  memory/     MemoryManager
  vision/     full screen, region, active window, OCR, downsample
  control/    move_mouse, click, type_text, press, focus_window, launch_app, open_url
              pc_control/   PC-Control's own modules (not a second server)
  bridge/     the functions a model calls, including pc_look, pc_click, ...
  agents/     one example loop
scripts/      install and run notes
```

## Install

Windows, Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ocr,dev]"
```

Install the Tesseract binary and put it on `PATH`, or set `TESSERACT_CMD`.
For long-term memory, install MilesMemory (`pip install -e` on that clone) and
leave `MEMORY_KB_DB` pointing at the database you want. Details and the OCR
swaps are in [scripts/install-and-run.md](scripts/install-and-run.md).

Screen control stays off until `VISION_ALLOW_SCREEN_CONTROL=1`.

## Run the example

```powershell
python -m desktop_agent.agents.example_loop "Read the title of the front window"
```

The loop captures the screen, runs OCR, stores the observation, archives a
summary when MilesMemory imports, prints a stub reply, and clicks once with
`dry_run=True`. The stub does not call a model.

## How another agent calls the bridge

Import the functions. They are the only model API. Each call returns `ok`,
`tool`, `timestamp`, `params`, `outcome`, and `event_id`, and writes that
event to the session log.

```python
from desktop_agent.bridge import (
    memory_add_event,
    memory_search,
    memory_get_recent,
    screen_capture_full,
    screen_capture_region,
    screen_ocr_full,
    screen_ocr_region,
    mouse_move,
    mouse_click,
    mouse_drag,
    keyboard_type,
    keyboard_hotkey,
    window_focus,
)

shot = screen_capture_full()
text = screen_ocr_full()
memory_add_event("saw", {"path": shot["outcome"]["path"]}, {"ocr": text["outcome"]["items"]})
mouse_click(120, 40, dry_run=True)
```

`memory_search` returns `cell_mem` and `agent_memory_os` as separate payloads.
`memory_get_recent` reads the session table. `memory_add_event(..., archive=True)`
writes the text into MilesMemory with `save` (semantic) and `create_memory`
(semantic).

`mouse_move`, `mouse_click`, `mouse_drag`, `keyboard_type`, `keyboard_hotkey`,
and `window_focus` accept `dry_run=True`. A label that matches the
dsh-computer-use dangerous-word list does not run unless `approved=True`.
Typing into `AXSecureTextField` or `AXPasswordField` is refused. Pass
`field_role` when the caller knows it. There is no accessibility tree in this
tree, because the Win32 path does not expose one.

`launch_app` and `open_url` live on `desktop_agent.control`. They are not
bridge tools. `open_url` accepts only `http://` and `https://`. Active-window
capture is `desktop_agent.vision.capture.capture_active_window`.

Swap OCR with `DESKTOP_AGENT_OCR=tesseract` (default), `ollama`, or `vlm`.

PC-Control's ten tools are on this same bridge: `pc_windows`, `pc_look`,
`pc_click`, `pc_type`, `pc_drag`, `pc_key`, `pc_scroll`, `pc_read`, `pc_show`,
`pc_open_app`. They call the PC-Control implementations (UI Automation, no
`SetForegroundWindow`). They do not replace `mouse_click` or `keyboard_type`.
Mutating ones honor `dry_run` and `VISION_ALLOW_SCREEN_CONTROL`. A protected
window returns `needs_permission` and does not run; there is no confirm flag
for the model. On Windows, `pip install -e ".[pc]"`.

Miles sees those tools over streamable HTTP. From `desktop_agent\control`:

```powershell
python -m pc_control.server
```

That stays up at `http://127.0.0.1:8770/mcp` as stateless JSON. Pinggy's host
`aetherbridge.a.pinggy.link` is accepted. OAuth stays on: an unauthenticated
`POST /mcp` is 401. `GET /authorize` for a public PKCE client is a 200 confirm
page, including a client id that was registered on another process.
`redirect_uri` `https://sesameai.app/api/oauth/external-mcp/callback` and a
long `state` are accepted. Approving that page, then `POST /token` with the
matching PKCE verifier, returns an access token. `POST /token` before a code
stays 401. With the bearer token, `initialize` returns `capabilities.tools` as `{}`. `tools/list` is JSON, with `name`, `description`, and `inputSchema` for `pc_windows`, `pc_look`,
`pc_click`, `pc_type`, `pc_drag`, `pc_key`, `pc_scroll`, `pc_read`,
`pc_show`, and `pc_open_app`. Calls still go through `desktop_agent.bridge`.

## Two processes, two bridges

Miles Memory and this agent are not one server.

| | Vision agent | Miles Memory |
| --- | --- | --- |
| Process | `python -m pc_control.server` from `desktop_agent\control` | `python -m memory_kb` |
| Port | `127.0.0.1:8770` | `127.0.0.1:8765` (unchanged) |
| Surface | `http://127.0.0.1:8770/mcp` | `http://127.0.0.1:8765/mcp` or stdio |
| Tools | the ten `pc_*` tools | `memory_recall`, `search_memories`, and the other `memory_kb` tools |
| Registry | this process only | the memory process only |

Nothing here vendors `memory_kb`, binds port 8765, or registers memory tools
next to `pc_look`. `memory_search` on the in-process vision bridge calls Miles
Memory's library when it is installed. It does not mount Miles Memory's `/mcp`
route, and this listener does not mount on the memory server.

## Tests

```powershell
python -m pytest
```
