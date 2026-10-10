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
  bridge/     the functions a model calls
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

## Tests

```powershell
python -m pytest
```
