---
cursor:
  subagentId: "bc-bafcd86b-c6e7-5dfa-9fd9-791f8464b39a"
---

# Unified Windows desktop agent

One Python package, `desktop_agent`, is the local desktop agent. A model calls `desktop_agent.bridge` and nothing else. The package was written after reading the repositories below. PC-Control was added later, onto the same bridge. It is not a dump of those trees.

Shallow clones, default branch, commits that were read:

| Repository | Commit |
| --- | --- |
| https://github.com/988hj7tczd-oss/dsh-computer-use | `3cf9bd8ae60271512f263bfa75485cb242ca0892` |
| https://github.com/GongRzhe/opencv-mcp-server | `0ac73bcfe5aede0df0bbc64573d7ff5f5e7b7724` |
| https://github.com/zouyuanqing/vision-primitives-mcp | `083009c4d8804e514d7c429d2588db0465449aee` |
| https://github.com/xkiranj/ollama-vision-mcp | `5737bc80f3456aefcc2594f4a857a5093ef7bbd1` |
| https://github.com/Staerrz/MilesMemory (`main`, package `src/memory_kb`) | `7497e4f17c7ec846a5d6b07d3c2956666efde84c` |
| https://github.com/VortexJer/PC-Control (`claude-pc-control` 0.6.1) | `31113310f071af2eb09ee2c00faf807c8a5b1de4` |

## Memory

None of the four desktop repositories is a memory core.

* `dsh-computer-use` `lib/snapshot.js` keeps one observation snapshot and a TTL. That is not a store.
* `vision-primitives-mcp` `VisionScratchpad` / `tool_scratch_think` keeps layers of one image while a vision model edits it. That is not SQLite recall.
* `opencv-mcp-server` and `ollama-vision-mcp` have no memory.

Long-term memory is MilesMemory. This package does not copy `memory_kb` and does not add a third ranker. `MemoryManager.search` returns the two existing results side by side:

* `KnowledgeBase.recall` — cell-mem `memory_recall`
* `KnowledgeBase.search_memories` — agent-memory-os `search_memories`

Session and tool events are a separate SQLite table, `session_events`, in this process. `archive_summary` writes one summary twice: `KnowledgeBase.save(..., "semantic")` and `KnowledgeBase.create_memory(..., memory_type="semantic")`. If `index_ready` is false, archive calls `build_index` once, because MilesMemory refuses recall and search until that index exists. Rank order is still the framework's order.

If `memory_kb` is not installed, session events still record. Search and archive return `memory_kb_unavailable`.

## How a call moves

```text
model
  → bridge function          logs timestamp, params, outcome
      → vision or control or MemoryManager
          → Win32 / Tesseract / MilesMemory
```

| Package | Role |
| --- | --- |
| `desktop_agent/core` | Env and JSON settings, log format |
| `desktop_agent/memory` | Session events plus MilesMemory |
| `desktop_agent/vision` | Full screen, region, active window, OCR, model downsample |
| `desktop_agent/control` | Win32 `move_mouse`, `click`, `type_text`, `press`, `focus_window`, `launch_app`, `open_url`, plus PC-Control under `control/pc_control` |
| `desktop_agent/bridge` | The only functions a model calls. PC-Control is `pc_*` on this same object |
| `desktop_agent/agents` | One example loop |
| `scripts` | Install and run notes |

Bridge functions, each an event:

`memory_add_event`, `memory_search`, `memory_get_recent`, `screen_capture_full`, `screen_capture_region`, `screen_ocr_full`, `screen_ocr_region`, `mouse_move`, `mouse_click`, `mouse_drag`, `keyboard_type`, `keyboard_hotkey`, `window_focus`, `pc_windows`, `pc_look`, `pc_click`, `pc_type`, `pc_drag`, `pc_key`, `pc_scroll`, `pc_read`, `pc_show`, `pc_open_app`.

`launch_app` and `open_url` stay on `desktop_agent.control`. Active-window capture stays on `desktop_agent.vision.capture.capture_active_window`. They are not bridge tools.

Risky bridge calls (`mouse_move`, `mouse_click`, `mouse_drag`, `keyboard_type`, `keyboard_hotkey`, `window_focus`) take `dry_run`. `VISION_ALLOW_SCREEN_CONTROL` defaults off, from vision-primitives. A dry-run returns the plan and does not call Win32.

OCR defaults to Tesseract (`DESKTOP_AGENT_OCR=tesseract`). `ollama` swaps in the ollama-vision `read_text` prompt. `vlm` swaps in the vision-primitives `tool_ocr_image` prompt. OCR reads the full-resolution capture. `fit_model` writes a second PNG for a vision model. `tool_ocr_image` does not downsample, and this tree does not either.

## dsh-computer-use

JavaScript plugin. Actions go through `cua-driver`. That client is not ported. The Win32 calls below come from vision-primitives. dsh contributes the safety rules, launch/focus shape, and modifier names.

| Source | Functions | New path | What happened |
| --- | --- | --- | --- |
| `lib/guard.js` | `isDangerousLabel`, `DANGEROUS_PATTERNS`, `PASSWORD_ROLES`, allowlist inside `guard` | `desktop_agent/control/guard.py` | Rewritten. Dangerous labels still block unless `approved=True`. Password roles `AXSecureTextField` and `AXPasswordField` still refuse `type_text`, including dry-run. `allowed_apps` still skips launch, matching `OPERATION_TOOLS` (launch is not in that set). There is no `ctx.approval` service; dry-run is the non-executing path. |
| `lib/actions.js` | `launchApp`, `bring_to_front` | `desktop_agent/control/window.py` `launch_app`, `focus_window` | Rewritten. Launch is `cmd /c start`. Focus is `FindWindowW` or a pid scan, then `ShowWindow` + `SetForegroundWindow`. The returned pid is the `start` helper, not a cua-driver pid. |
| `lib/actions.js` | `dispatchKey` modifier names `cmd`, `command`, `control`, `option` | `desktop_agent/control/keys.py` `parse_combo` | Merged into the vision-primitives virtual-key table. `cmd` / `command` become `win` (`0x5B`). |
| `index.js` | config `ttlMs` (default 30000), `allowedApps` | `desktop_agent/core/settings.py` | `allowed_apps` is enforced on mouse, keyboard, and focus. `ttl_ms` is stored and not enforced. The AX snapshot it belonged to was not ported. |
| `README.md` | observe → act → observe loop | `desktop_agent/agents/example_loop.py` | Rewritten as one pass: instruction, capture, OCR, memory, stub reply, one dry-run click. No second observe, no model. |

Dropped from dsh. Not copied into the new tree:

| Source | Why it was dropped |
| --- | --- |
| `index.js` Cordis `defineTool` registration of the 12 tools | The bridge function list is the one in the request, not `screen_observe` / `computer_*` / `app_list`. |
| `lib/cua.js` | `cua-driver` spawn, session, MCP normalize. |
| `lib/human.js` | Virtual-cursor glide (`glideCursor`, `humanClick`). Clicks are `SetCursorPos` + `mouse_event`. |
| `lib/observe.js`, `lib/snapshot.js` | AX/UIA observe, element tokens, snapshot TTL. No accessibility tree on this Win32 path. |
| `lib/vision.js` | DeepSeek / GLM vision describe. OCR swaps are Tesseract, Ollama `read_text`, and the vision-primitives OCR prompt. |
| `lib/actions.js` `click`, `doubleClick`, `rightClick`, `typeText`, `key`, `scroll`, `drag`, `wait`, `listApps` | Click, type, key, and drag are the vision-primitives Win32 tools instead. `scroll`, `wait`, and `listApps` are not in the requested control surface. |
| `install.sh`, `uninstall.sh`, `cordis.patch.yml`, `tests/`, `verify-runtime.mjs` | DeepSeek Harness install. Windows notes are `scripts/`. |

`screen_observe` is not reimplemented. Capture is a screenshot, not an element list.

## opencv-mcp-server

Read: `opencv_mcp_server/image_basics.py`, `image_processing.py`, `computer_vision.py`, `video_processing.py`, `utils.py`, `main.py`.

No function was kept. The server reads image and video files. It does not grab the screen, run OCR, or move the mouse. Region capture is Pillow `ImageGrab` (vision-primitives `tool_screen_capture`). Downsample is `fit_model`, not `resize_image_tool`.

Dropped as a group:

* `save_image_tool`, `convert_color_space_tool`, `resize_image_tool`, `crop_image_tool`, `get_image_stats_tool`
* `apply_filter_tool`, `detect_edges_tool`, `apply_threshold_tool`, `detect_contours_tool`, `find_shapes_tool`, `match_template_tool`
* `detect_features_tool`, `match_features_tool`, `detect_faces_tool`, `detect_objects_tool`
* `extract_video_frames_tool`, `detect_motion_tool`, `track_object_tool`, `combine_frames_to_video_tool`, `create_mp4_from_video_tool`, `detect_video_objects_tool`, `detect_camera_objects_tool`
* `register_tools`, `main`, Haar/YOLO model files

## vision-primitives-mcp

The Windows screen tools and the model-size helper are the capture and input core. The file is `vision_primitives_mcp.py`. `vision_bridge_mcp.py` only re-exports it and was not copied.

| Source function | New path | What happened |
| --- | --- | --- |
| `tool_screen_capture` | `desktop_agent/vision/capture.py` `capture_full`, `capture_region` | Rewritten. Same `ImageGrab.grab` and `[x1,y1,x2,y2]` check. Also writes the `fit_model` PNG. |
| `tool_screen_info` DPI block (`SetProcessDpiAwareness`) | `WindowsGrabber._dpi` in `capture.py` | Merged into capture so the window rectangle matches pixels. The metrics/DPI return value is not a bridge tool. |
| `tool_screen_capture` region + `user32` | `capture_active_window` | Rewritten. The rectangle is `GetForegroundWindow` + `GetWindowRect` + `GetWindowTextW`, then the same region grab. `GetForegroundWindow` is not a function in the source; `tool_screen_info` uses `GetDesktopWindow`. |
| `_fit_model`, `_scale_geo` | `desktop_agent/vision/downsample.py` `fit_model`, `scale_geo` | Rewritten in Python types. `VISION_MAX_MODEL_SIDE` default 2600 and `VISION_NORM_SIZE` are unchanged. |
| `_unique_path` | `capture.py` | Rewritten. A counter was added so two captures in the same second do not overwrite. |
| `tool_ocr_image` prompt and `{"text","box"}` items | `desktop_agent/vision/ocr.py` `VlmBoxOcr` | Rewritten as a swap, not the default. Posts to `VISION_API_BASE/chat/completions`. Cache, `load_image`, and the MCP frame are not included. |
| `_require_screen_control`, `VISION_ALLOW_SCREEN_CONTROL` | `desktop_agent/control/guard.py` | Rewritten. Default remains off. `dry_run=True` records the plan instead of raising. |
| `_VK`, `_press_vk`, `_key_combo`, `tool_screen_key` | `desktop_agent/control/keys.py`, `desktop_agent/control/backend.py` `press` | Rewritten. Combo parsing also accepts dsh modifier aliases. |
| `_vk_for_char`, `tool_screen_type` | `keys.py` `key_for_char`, `type_method`; `backend.py` `type_text` | Rewritten. The source accepts only `0-9` and `A-Z`, so lowercase and space never typed. Space uses the existing `space` code `0x20`. Letters use the `A-Z` virtual key; uppercase holds shift, because `keybd_event` types lowercase when shift is up. Non-ASCII still uses the PowerShell `Set-Clipboard` plus `ctrl+v` path. Unsupported ASCII punctuation still raises, and the check runs before any key is sent. |
| `tool_screen_move` | `desktop_agent/control/mouse.py` `move_mouse` | Rewritten. Adds the gate and a log line. |
| `tool_screen_click` | `mouse.py` `click` | Rewritten. Same buttons and double-click flags. |
| `tool_screen_drag` | `mouse.py` `drag`, `keys.py` `drag_points` | Rewritten. Step count is still `max(1, int(duration * 50))`. |
| `tool_screen_scroll` | — | Dropped. Not in the requested control surface. |

Dropped from the same file, and from the rest of that repo (`paper_reader.py`, `benchmarks/`, `models/`, `test/`):

`tool_describe_image`, `tool_analyze_image`, `tool_locate_object`, `tool_cv_locate`, `tool_som_locate`, `tool_cursor_locate`, `tool_text_detect`, `tool_text_zoom`, `tool_ui_parse`, `tool_ui_locate`, `tool_ui_refine`, `tool_annotate_image`, `tool_crop_image`, `tool_zoom_region`, `tool_annotate_infer`, `tool_compare_images`, `tool_compare_infer`, `tool_reason_graph`, `tool_scan_anomalies`, `tool_scratch_think`, `VisionScratchpad`, `tool_vision_health`, the JSON-RPC `handle_message` server, YOLO `icon_detect.pt`, CRAFT `craft_text.onnx`.

`tool_crop_image` overlaps region capture and was not copied. Screen region is `ImageGrab`, not a file crop.

## ollama-vision-mcp

| Source | Functions | New path | What happened |
| --- | --- | --- | --- |
| `src/config.py` | `Config._get_config`, `_find_config_file`, `_load_config` | `desktop_agent/core/config.py`, `desktop_agent/core/settings.py` | Rewritten. Lookup order is still environment, then JSON, then default. Env names kept: `OLLAMA_VISION_OLLAMA_URL`, `OLLAMA_VISION_DEFAULT_MODEL`, `OLLAMA_VISION_TIMEOUT`, `OLLAMA_VISION_LOG_LEVEL`, `OLLAMA_VISION_CONFIG`. |
| `src/server.py` | `logging.basicConfig` format | `desktop_agent/core/logging.py` | Rewritten. Same format string. |
| `src/server.py` | `read_text` prompt | `desktop_agent/vision/ocr.py` `OllamaReadText`, `READ_TEXT_PROMPT` | Merged as the `ollama` OCR swap. The prompt text is unchanged. |
| `src/ollama_client.py` | `analyze_image` body | `OllamaReadText.read` | Rewritten with `urllib` instead of aiohttp. `POST /api/generate` still sends `model`, `prompt`, `images`, `stream: false`. |
| `src/image_handler.py` | thumbnail at 2048 in `_process_image_bytes` | — | Not used. Model input downsample is `_fit_model` (2600). The 2048 cap stays in the source only. |

Dropped: MCP `analyze_image`, `describe_image`, `identify_objects` tool schemas; `list_models` / `ensure_model` / `api/pull`; URL and base64 image loading; `examples/`; `setup.bat`.

## MilesMemory

Not copied into this tree. `desktop_agent/memory/manager.py` imports `memory_kb.engine.KnowledgeBase` when the package is installed.

| Called | Used for |
| --- | --- |
| `recall` | `memory_search` → `cell_mem` |
| `search_memories` | `memory_search` → `agent_memory_os` |
| `save` (semantic, confidence 0.9) | `archive_summary` / `memory_add_event(..., archive=True)` |
| `create_memory` (semantic, `agent_id` default `desktop-agent`) | same archive |
| `build_index` | only when archive finds `index_ready` false |
| `close` | `MemoryManager.close` |

Not called: OAuth, the HTTP app, `memory_forget`, `memory_associate`, stats, timeline, update, delete. Those stay in MilesMemory.

The session table (`add_event`, `get_recent`) is new. It is the tool log. It is not a third ranker.

## Two servers, no shared registry

Miles Memory stays its own process. This integration does not vendor `src/memory_kb`, does not change its port, routes, OAuth, or tool names, and does not mount its `/mcp` bridge on the vision bridge.

| | Vision agent | Miles Memory |
| --- | --- | --- |
| Process | `desktop_agent` in this repo | `python -m memory_kb` |
| Port | `127.0.0.1:8770` for the PC listener. The in-process bridge has no port | `127.0.0.1:8765`, unchanged |
| Surface | `http://127.0.0.1:8770/mcp` (original PC-Control names, plus `pc_*` aliases) and `desktop_agent.bridge` | HTTP `/mcp` or stdio |
| Tools | screen, Win32 mouse and keyboard, and `pc_*` | `memory_recall`, `memory_save`, `memory_status`, `memory_associate`, `memory_forget`, `search_memories`, `create_memory`, `update_memory`, `delete_memory`, `get_memory_stats`, `get_timeline`, `get_episodic_memories`, `build_knowledge_index` |
| Registry | this process only | the memory process only |

`memory_search` on the vision bridge imports `memory_kb.engine.KnowledgeBase` when that package is installed beside this one. That is a library call. It is not Miles Memory's `/mcp` route, and the `pc_*` names are not registered in the memory server.

`python -m pc_control.server` stays up as streamable HTTP at `http://127.0.0.1:8770/mcp`. The implementation is `desktop_agent/control/pc_control/server.py`. From `desktop_agent/control` that command loads the file directly. From `desktop_agent` the same command loads `desktop_agent/pc_control/server.py`, which calls `desktop_agent.control.pc_control.server.main` and does not move the implementation. One `StreamableHTTPSessionManager` is created with the process and entered from the Starlette lifespan. The listener answers JSON and keeps one session for the process, so initialize does not end it. DNS-rebinding protection is off, so `Host: aetherbridge.a.pinggy.link` is not a 421. OAuth stays on. Unauthenticated `POST /mcp` is 401 and `WWW-Authenticate` carries `resource_metadata="https://aetherbridge.a.pinggy.link/.well-known/oauth-protected-resource"` (`PC_CONTROL_PUBLIC_ORIGIN` overrides that origin). The same process serves `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, and `/token`. `GET /authorize` is a 200 confirm page for a public PKCE request. A `client_id` registered with another process, `redirect_uri=https://sesameai.app/api/oauth/external-mcp/callback`, `resource=https://aetherbridge.a.pinggy.link/mcp`, and a long `v1.gAAAA...` state are not a 400. Approving the page issues the code. `POST /token` before that code stays 401. `POST /token` with `grant_type=authorization_code` and the matching PKCE verifier returns an access token. After that bearer token, `POST /mcp` `initialize` returns JSON whose `capabilities` object is `{"tools": {}}`, and the response sets `mcp-session-id` (`Mcp-Session-Id`). That id stays valid after initialize and `tools/list`. MilesVision has no separate client communication layer. Sesame (`https://sesameai.app/api/oauth/external-mcp/callback`) talks to this listener. A later `POST /mcp` `tools/call` that sends the same bearer and that `mcp-session-id` is handled and runs through `desktop_agent.bridge`. A protocol version that would otherwise be stateless is served on this session, so the response still carries the id. `POST /mcp` `tools/list` returns JSON, not an SSE stream. Each object has `name`, `title`, `description`, and `inputSchema`. The names a toolkit matches are the original PC-Control names: `windows`, `look`, `click`, `type`, `drag`, `key`, `scroll`, `read`, `show`, `open_app`. The same functions are also listed as `pc_windows`, `pc_look`, `pc_click`, `pc_type`, `pc_drag`, `pc_key`, `pc_scroll`, `pc_read`, `pc_show`, and `pc_open_app`, so a lookup for either spelling resolves. `click` and `pc_click` both run the bridge `pc_click` implementation. `mouse_click` and `keyboard_type` stay off this listener. Each description starts with the exact argument names. Each `inputSchema` lists only the arguments of the registered function (`click` is `window`, `target`, `right`, `double`, and `dry_run`; `confirm` is not one of them). The schema is not closed with `additionalProperties: false`, so a call that uses those names still validates when an extra original PC-Control field is present. Those calls go through `desktop_agent.bridge`, so `dry_run` and `VISION_ALLOW_SCREEN_CONTROL` are unchanged. This process does not bind `127.0.0.1:8765` and does not register Miles Memory tools.

```bash
curl -sS -D - -o /dev/null -X POST http://127.0.0.1:8770/mcp -H "Host: aetherbridge.a.pinggy.link" -H "Content-Type: application/json" -H "Accept: application/json" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"miles\",\"version\":\"0\"}}}"
```

## PC-Control

Read at `31113310f071af2eb09ee2c00faf807c8a5b1de4` (`claude-pc-control` 0.6.1). The ten tools see and operate a Windows window through UI Automation. They do not call `SetForegroundWindow`, `SendInput`, `keybd_event`, or `SetCursorPos`. That path stays the vision-primitives Win32 tools (`mouse_click`, `keyboard_type`, `mouse_drag`, `keyboard_hotkey`). Bridge names are prefixed `pc_` so the two sets sit on one `Bridge` and do not replace each other.

`desktop_agent/bridge/pc.py` `run` is the only caller of `server.TOOLS`. Mutating tools (`click`, `type`, `drag`, `key`, `scroll`, `show`, `open_app`) honor `dry_run` and `VISION_ALLOW_SCREEN_CONTROL`. `windows`, `look`, and `read` do not. `NeedsPermission` returns `needs_permission` and does not run. The model cannot pass `confirm`. The Windows stack (`uiautomation`, `pywin32`, `opencv`) is imported only when a non-dry-run call actually runs, so a dry-run does not load Win32. Optional extra is `pip install -e ".[pc]"`, not the default install.

| Source | Functions | New path | What happened |
| --- | --- | --- | --- |
| `pc_control/server.py` | `windows`, `look`, `click`, `type`, `drag`, `key`, `scroll`, `read`, `show`, `open_app`, plus helpers `_target`, `_by_name`, `_proc`, `_allowed`, `_paused`, `_gate`, `_category`, `_recheck_window`, `_live_name`, `_guard_element`, `_guard_point`, `_mine`, `_closing_guard`, `_key_guard`, `_dialog_default_risk`, `T_`, `_is_hidden`, `_on`, `_cursor_wanted`, `_screen_point`, `_layout_ok`, `notice_text`, `_ensure_layout`, `verdict`, `_tr`, `_tr_report`, `_act`, `_init_main`, `_clean_old_log`, `_shutdown`, `_watch_parent` | `desktop_agent/control/pc_control/server.py` | Rewritten at the edges. FastMCP `"PC-Control"`, `mcp.tool()`, pydantic `_Permission`, async `_ask_user`, MCP `Image`/`Context`, and `_slim_schemas` are gone. A local `ToolError` and `TOOLS` dict replace them. `@tool` stores the sync inner function. `look` image mode returns a path string instead of an MCP `Image` block. `main()` now calls `http_server.serve()` and stays up. It does not call `_clean_old_log`, `_watch_parent`, or `_shutdown`. The ten tool bodies and the helpers are the source text. |
| `pc_control/server.py` ten tools | same names | `desktop_agent/bridge/api.py` `pc_windows`, `pc_look`, `pc_click`, `pc_type`, `pc_drag`, `pc_key`, `pc_scroll`, `pc_read`, `pc_show`, `pc_open_app` | Merged onto the existing `Bridge._call` logger (timestamp, params, outcome). Module functions of the same names are re-exported from `desktop_agent/bridge/__init__.py`. `confirm` is not a bridge argument. |
| `pc_control/__init__.py` | `__version__ = "0.6.1"` | `desktop_agent/control/pc_control/__init__.py` | Kept the version. The docstring now points at `python -m pc_control.server` on `127.0.0.1:8770/mcp`. |
| — | listener | `desktop_agent/control/pc_control/http_server.py` | New. Registers only the bridge `pc_*` functions and serves streamable HTTP. Not a copy of upstream `cli.py` or FastMCP `"PC-Control"`. |
| `pc_control/actions.py` | `scroll`, `read_text`, `shortcut`, `select_option`, `find`, `scroll_into_view`, `select_in_parent`, `press_out_of_view` | `desktop_agent/control/pc_control/actions.py` | Kept. Unchanged from the source file. |
| `pc_control/core.py` | `find_window`, `list_windows`, `grab`, `walk_uia`, `ocr_items`, `look`, `choose` | `desktop_agent/control/pc_control/core.py` | Kept. Unchanged. `SetProcessDpiAwareness` still runs at import, which is why the bridge imports this only when a call executes. |
| `pc_control/cursor.py` | `render_arrow`, `render_caret`, `render_note`, `render_mark`, `mark_clicked` | `desktop_agent/control/pc_control/cursor.py` | Kept. Unchanged. This is PC-Control's orange overlay, not the Win32 cursor. |
| `pc_control/envvars.py` | `get` (`PC_CONTROL_<NAME>`, `PCSIGHT_<NAME>`) | `desktop_agent/control/pc_control/envvars.py` | Kept. Unchanged. |
| `pc_control/hidden.py` | `on_hidden_thread` | `desktop_agent/control/pc_control/hidden.py` | Kept. Unchanged. Used by `open_app(..., hidden=True)`. |
| `pc_control/office.py` | `is_excel`, `summary`, `read`, `write`, `save`, `is_powerpoint`, `powerpoint_text` | `desktop_agent/control/pc_control/office.py` | Kept. Unchanged. |
| `pc_control/perm.py` | `sig`, `mark`, `take`, `approved`, `approve`, `set_cc_mode`, `cc_mode` | `desktop_agent/control/pc_control/perm.py` | Kept. Unchanged. The Claude Code hook no longer calls it; the file stays because `policy` and the tool guards import it. |
| `pc_control/policy.py` | `mode`, `check_window`, `check_launch`, `check_click`, `check_type`, `NeedsPermission` | `desktop_agent/control/pc_control/policy.py` | Kept. Unchanged. Modes are still `follow` / `auto` / `ask` / `strict` / `bypass` via `PC_CONTROL_MODE`. Pause is still `~/.pc-control/PAUSE` or `PC_CONTROL_PAUSE`. |
| `pc_control/ui_text.py` | `lang`, `T`, `category` | `desktop_agent/control/pc_control/ui_text.py` | Kept. Unchanged. |
| `pc_control/word.py` | `type_text`, `format_click`, `describe`, `anchor_pos` | `desktop_agent/control/pc_control/word.py` | Kept. Unchanged. |

Dropped. Not copied into this tree:

| Source | Why it was dropped |
| --- | --- |
| `pc_control/server.py` `FastMCP("PC-Control")`, `mcp.run`, script `pc-control-mcp` | A second MCP entry point. The vision bridge is the only model API. |
| `pc_control/server.py` `_ask_user`, `_Permission`, MCP elicitation, `confirm=True` retry | Needs the MCP `Context`. Protected actions return `needs_permission` and stop. |
| `pc_control/cli.py` (`install`, `uninstall`, `serve`, `update`, skill text, `SERVER_NAME = "PC-Control"`) | Registers `mcp__PC-Control__*` in Claude Code. That is a competing tool registry. |
| `pc_control/hook.py` (`decide`, `convert_rules`, PreToolUse / PermissionRequest) | Claude Code hook for that registry. |
| `install.ps1`, `update.ps1`, `uninstall.ps1` | Same Claude Code install. |
| `tests/`, `tools/`, `docs/`, `.github/workflows/publish.yml`, `.claude/` | Upstream package tests, images, and publish workflow. Not a second server and not part of `desktop_agent`. |
| `pyproject.toml` scripts `pc-control` and `pc-control-mcp`, dependency `mcp` | Not entry points of this package. Windows libraries are the optional extra `pc`. |

`desktop_agent/control/__init__.py` does not import `pc_control`. Importing `desktop_agent.bridge` does not load `user32` from this package.


## Glue that is not a source module

| New file | Why it exists |
| --- | --- |
| `desktop_agent/control/backend.py` | Win32 body shared by mouse, keyboard, and window. The calls are the vision-primitives ones. |
| `desktop_agent/control/window.py` `open_url` | No source function opens a URL. The requested control surface includes it. Implementation is `os.startfile`, and only `http://` / `https://`. |
| `desktop_agent/vision/ocr.py` `TesseractOcr` | Default OCR, as requested. Not present in the four repos. `words_to_items` maps `image_to_data` onto the `tool_ocr_image` fields `text` and `box_pixel`. |
| `desktop_agent/bridge/api.py` | The model API and the per-call event. |
| `desktop_agent/agents/example_loop.py` | The one loop. `stub_reply` does not call a model. |
| `scripts/install.ps1`, `scripts/run-example.ps1`, `scripts/install-and-run.md` | Windows install and run notes. |

## New tree, checked on disk

These paths exist in the project:

* `desktop_agent/__init__.py`
* `desktop_agent/core/__init__.py`
* `desktop_agent/core/config.py`
* `desktop_agent/core/logging.py`
* `desktop_agent/core/settings.py`
* `desktop_agent/memory/__init__.py`
* `desktop_agent/memory/manager.py`
* `desktop_agent/vision/__init__.py`
* `desktop_agent/vision/capture.py`
* `desktop_agent/vision/downsample.py`
* `desktop_agent/vision/ocr.py`
* `desktop_agent/control/__init__.py`
* `desktop_agent/control/guard.py`
* `desktop_agent/control/keys.py`
* `desktop_agent/control/backend.py`
* `desktop_agent/control/mouse.py`
* `desktop_agent/control/keyboard.py`
* `desktop_agent/control/window.py`
* `desktop_agent/pc_control/__init__.py` (shim so `python -m pc_control.server` works from `desktop_agent`)
* `desktop_agent/pc_control/server.py` (calls `desktop_agent.control.pc_control.server.main`)
* `desktop_agent/control/pc_control/__init__.py`
* `desktop_agent/control/pc_control/server.py`
* `desktop_agent/control/pc_control/http_server.py`
* `desktop_agent/control/pc_control/oauth.py`
* `desktop_agent/control/pc_control/actions.py`
* `desktop_agent/control/pc_control/core.py`
* `desktop_agent/control/pc_control/cursor.py`
* `desktop_agent/control/pc_control/envvars.py`
* `desktop_agent/control/pc_control/hidden.py`
* `desktop_agent/control/pc_control/office.py`
* `desktop_agent/control/pc_control/perm.py`
* `desktop_agent/control/pc_control/policy.py`
* `desktop_agent/control/pc_control/ui_text.py`
* `desktop_agent/control/pc_control/word.py`
* `desktop_agent/bridge/pc.py`
* `tests/test_pc_bridge.py`
* `desktop_agent/bridge/__init__.py`
* `desktop_agent/bridge/api.py`
* `desktop_agent/agents/__init__.py`
* `desktop_agent/agents/example_loop.py`
* `scripts/install-and-run.md`
* `scripts/install.ps1`
* `scripts/run-example.ps1`
* `README.md`
* `pyproject.toml`
* `tests/test_vision.py`
* `tests/test_control.py`
* `tests/test_bridge.py`
* `tests/test_memory.py`
* `tests/test_example.py`

Source files cited above were present in the clones at read time, including `dsh-computer-use/lib/guard.js`, `dsh-computer-use/lib/actions.js`, `opencv-mcp-server/opencv_mcp_server/image_basics.py`, `vision-primitives-mcp/vision_primitives_mcp.py`, `ollama-vision-mcp/src/server.py`, `ollama-vision-mcp/src/config.py`, `ollama-vision-mcp/src/ollama_client.py`, and `MilesMemory/src/memory_kb/engine.py`. PC-Control files cited above were present at `31113310f071af2eb09ee2c00faf807c8a5b1de4`, including `pc_control/server.py`, `pc_control/policy.py`, `pc_control/core.py`, `pc_control/cli.py`, and `pc_control/hook.py`.
