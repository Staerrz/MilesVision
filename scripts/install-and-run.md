# Install and run

Windows is the desktop this agent drives. The Python package installs on other
systems so the dry-run loop and tests can run, but `ImageGrab`, `user32`, and
`os.startfile` execute only on Windows.

## Install

From the repository root, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ocr,dev]"
```

Tesseract is the default OCR engine. Install the binary and make sure
`tesseract` is on `PATH`, or set `TESSERACT_CMD` to `tesseract.exe`.

```powershell
winget install UB-Mannheim.TesseractOCR
```

Long-term memory is MilesMemory (`memory_kb` on `main`). This tree does not
vendor it. Session events work without it. Recall and search need the package:

```powershell
git clone https://github.com/Staerrz/MilesMemory.git
python -m pip install -e .\MilesMemory
```

The database file defaults to `memory_kb.db` in the working directory. Override
it with `MEMORY_KB_DB`. The first archived summary calls `build_index` when the
index is missing, which is what MilesMemory requires before `memory_recall` and
`search_memories` will run.

Optional OCR swaps:

* `DESKTOP_AGENT_OCR=ollama` uses the `read_text` prompt against
  `OLLAMA_VISION_OLLAMA_URL` (default `http://localhost:11434`) and
  `OLLAMA_VISION_DEFAULT_MODEL` (default `llava-phi3`). Pull the model with
  `ollama pull llava-phi3`.
* `DESKTOP_AGENT_OCR=vlm` uses the vision-primitives OCR prompt against
  `VISION_API_BASE`, `VISION_API_KEY`, and `VISION_MODEL`.

Mouse, keyboard, focus, launch, URL, and the mutating PC-Control tools
(`pc_click`, `pc_type`, `pc_drag`, `pc_key`, `pc_scroll`, `pc_show`,
`pc_open_app`) do nothing unless `VISION_ALLOW_SCREEN_CONTROL=1`. Leave it
unset while you are reading the screen. Pass `dry_run=True` on a risky call
to log the plan without moving the cursor.

PC-Control window tools (no focus steal) need the Windows extra:

```powershell
python -m pip install -e ".[pc]"
```

`pc_windows`, `pc_look`, and `pc_read` do not use that switch. They still
follow `PC_CONTROL_MODE` and `~/.pc-control/PAUSE`.

Miles Memory stays a second process. Start it the way that repo documents
(`python -m memory_kb`, port `8765`, path `/mcp`). Do not point that port at
this package.

The PC control listener is a third process, not a route on Miles Memory.
From `desktop_agent\control`:

```powershell
python -m pc_control.server
```

It stays up at `http://127.0.0.1:8770/mcp` and answers JSON. The session is not dropped after initialize. `Host:
aetherbridge.a.pinggy.link` is accepted. An unauthenticated `POST /mcp` is
401, and `POST /token` before a code is 401. `GET /authorize` with
`response_type=code`, PKCE S256, and
`redirect_uri=https://sesameai.app/api/oauth/external-mcp/callback` returns
200, the confirm page, even when that `client_id` was not registered with
this process. Approve the page, then exchange the code at `/token`. Send
`Authorization: Bearer` with `Content-Type: application/json` and `Accept:
application/json`. `initialize` includes `capabilities.tools` and sets
`mcp-session-id`. Send that id on `tools/call`. `tools/list`
is JSON, not an empty SSE stream. Each tool has `name`, `title`, `description`,
and `inputSchema`. The names are `windows`, `look`, `click`, `type`, `drag`,
`key`, `scroll`, `read`, `show`, and `open_app`, and the same tools again as
`pc_windows`, `pc_look`, `pc_click`, `pc_type`, `pc_drag`, `pc_key`,
`pc_scroll`, `pc_read`, `pc_show`, and `pc_open_app`.

## Run the example

```powershell
$env:DESKTOP_AGENT_OCR = "tesseract"
python -m desktop_agent.agents.example_loop "Read the title of the front window"
```

Or:

```powershell
.\scripts\run-example.ps1 "Read the title of the front window"
```

The loop captures the full screen, runs OCR, stores the observation, archives
a summary when MilesMemory is installed, prints a stub reply, and issues one
`mouse_click` with `dry_run=True`. It does not ask a remote model what to do.

## Tests

```powershell
python -m pytest
```

The tests use fake grabbers and a fake input backend. They do not move the cursor.
