# Phase 9 — Workflow node editor (spec)

## Goal
A **Workflow** page where the user wires nodes into a graph (prompt → image → video and so on) and runs it. Nodes run in dependency order on a worker thread. Graphs save and load as JSON. Done when a 3-node chain (prompt → image → video) runs in tests and in the app with the offline demo providers.

## Pieces
| Module | What it does |
|---|---|
| `src/workflow/registry.py` | Port types (`text`, `image`, `video`, `any`), `Port`, `NodeType`, `NodeContext`, `Registry`, the app-wide `default_registry()` and `register()`. Qt-free. |
| `src/workflow/graph.py` | `Graph` with `Node` / `Edge`: add/remove nodes, typed `connect` (rejects type mismatches, self-links and loops; an input takes one wire and a new one replaces the old), `topo_order`, `missing_inputs`, `to_dict`/`from_dict`, `save`/`load`. Qt-free. |
| `src/workflow/runner.py` | `GraphRunner(graph, out_dir, on_event, max_attempts=2)`. Runs on a worker thread (`start/stop/wait`) or inline (`run`). Qt-free. |
| `src/workflow/provider_node.py` | `provider_node(...)` turns any `src.gen` `Provider` into a node type. |
| `src/workflow/nodes/*.py` | Node modules. Each is imported by `default_registry()` and registers its own types. |
| `src/ui/workflow/scene.py` | `WorkflowScene` (QGraphicsScene) with `NodeItem`, `PortItem`, `EdgeItem`; drag to connect. |
| `src/ui/workflow/page.py` | `WorkflowPage`: toolbar, `GraphView`, `Inspector`, `RunnerBridge`, autosave, `starter_graph`. |

## Values on ports
- `text` is a `str`.
- `image` and `video` are a `list[Path]` of saved files. `provider_node.as_paths` flattens anything path-like.
- `any` connects to every type.

## Node types shipped
| type_id | Category | Inputs | Output | Settings |
|---|---|---|---|---|
| `prompt` | Basic | none | text | prompt text (multiline) |
| `text_join` | Basic | a (text), b (text, optional) | text | separator (`\n` = new line) |
| `image_file` | Basic | none | image | file path (browse) |
| `gemini.image` | Gemini | prompt, refs (image, optional) | image | `GeminiImageProvider` fields + count |
| `gemini.video` | Gemini | prompt, start (image, optional) | video | `GeminiVideoProvider` fields + count |
| `demo.image` | Demo | prompt, refs (optional) | image | Phase 2 `FakeProvider` fields + count |
| `demo.video` | Demo | prompt, start (optional) | video | aspect + count. Writes an animated GIF from the start frame. Offline. |

A wired `start` input feeds the provider's `job.refs`. With Gemini Omni's `auto` task, one image is the start frame and two are start and end.

## Runner rules
- Order is `Graph.topo_order()`, with ties in insertion order so runs repeat the same way.
- The runner takes a snapshot of the graph (deep-copied nodes) when it is built, so edits made during a run don't affect it.
- A node whose upstream didn't finish is **skipped**. A required input with no wire fails the node with "Input not connected: …".
- `ProviderError(retryable=True)` is retried until `max_attempts` (2). `ctx.attempt` is passed through to `job.attempts`. Other `ProviderError`s fail the node. Any other exception fails only that node and is logged with its traceback.
- Stop sets a flag: the running provider sees `should_stop()` and raises `StopRequested` (node → stopped), and every later node is marked stopped.
- Files go to `<out_dir>/<run stamp>/<node id>/` and are named by `save_outputs`. The page's `out_dir` is `default_save_dir("workflow")` (`%APPDATA%\LabsStudio\outputs\workflow`).
- Events: `RunEvent("node", node_id, state)` on every status or progress change, then `RunEvent("finished")`. `RunnerBridge` re-emits them as Qt signals, which the GUI thread receives through queued connections.

## JSON file
```json
{"format": "labs-studio-workflow", "version": 1,
 "nodes": [{"id": "a1b2c3d4", "type": "prompt", "title": "", "pos": [-380, -40],
            "params": {"text": "a red fox"}}],
 "edges": [{"src": "a1b2c3d4", "src_port": "text", "dst": "…", "dst_port": "prompt"}]}
```
Loading checks `format`, refuses a newer `version`, refuses unknown node types, and re-validates every edge through `connect`. Saves write a temp file and then replace the target. No secrets are stored, because keys stay in the key store.

## Page behaviour
- Toolbar: **Add node** (menu by category, built from the registry), **Run**, **Stop**, **New**, **Open…**, **Save as…**, **Open output folder**, and a status line.
- Canvas: drag from an output port (right side) to an input port (left side), or the other way round. Dragging off a wired input picks up its wire. Port colours: text amber, image blue, video purple. A hollow port is optional. Scroll zooms (0.25×–3×), a middle-drag pans, and dragging on empty space draws a selection box. Delete/Backspace removes the selected nodes and wires.
- Nodes show their status colour, a progress bar while running, the error when failed, and a thumbnail of the first image output (GIF first frame for the demo video).
- Inspector: the selected node's title and settings (choice, int, float, bool, text, multiline, file, folder editors), its error, and its output files. Double-clicking a file opens it.
- The graph autosaves to `%APPDATA%\LabsStudio\workflows\autosave.json` 600 ms after each edit and on shutdown, and reopens from there. On first open the graph is the starter chain: prompt → demo image → demo video, also wired prompt → video.

## Out of scope
- Batch runs (one prompt list through the graph), per-node run/rerun, caching results between runs, undo/redo, copy/paste, groups, minimap.
