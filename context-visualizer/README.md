# context-visualizer

Flask-based dashboard for the Chimaera runtime with a React "workspace"
view for multi-agent conversation inspection.

## Layout

    context-visualizer/
    ├── context_visualizer/        # Python package (Flask app + API)
    │   ├── app.py                 # Flask factory; registers blueprints + page routes
    │   ├── chimaera_client.py     # C++ runtime bridge
    │   ├── adapters/              # Shape adapters (e.g. conversation_adapter)
    │   ├── analysis/              # Call-graph and context-graph analysis
    │   ├── api/                   # Flask blueprints (one file per topic)
    │   ├── checkpointing/         # Checkpoint manager and rollback plans
    │   ├── semantic/              # LLM-based error attribution
    │   ├── static/                # Static assets served by Flask
    │   │   ├── css/               # Shared stylesheet for template pages
    │   │   ├── js/                # Vanilla JS for the template pages
    │   │   └── workspace/         # ← SPA bundle (built from frontend/, git-ignored)
    │   └── templates/             # Jinja2 template pages (topology/pools/etc.)
    ├── frontend/                  # React + TypeScript + Vite source
    │   ├── package.json
    │   └── src/
    ├── docs/                      # Design notes (workspace.md, etc.)
    └── tests/                     # Python tests

The **template pages** (topology, pools, config, node, recovery) are
server-rendered Jinja. The **workspace page** at `/workspace` is a
separate React SPA that talks to the backend over the same HTTP API as
the template pages — it is built independently and served from
`context_visualizer/static/workspace/`.

## Running the backend

```bash
python -m context_visualizer --host 127.0.0.1 --port 5000
```

The Chimaera runtime must be reachable; if it's not running the dashboard
still boots but individual panels will surface connection errors.

## Building the workspace SPA

The workspace UI is shipped pre-built in release wheels, but when
iterating locally you need Node 18+ and npm.

```bash
# One-time build (runs npm install + vite build)
make workspace
```

After this, `/workspace` returns the bundled `index.html`. Before this,
`/workspace` returns a 503 with a hint pointing to this command.

### Iterating on the UI

For a fast feedback loop, run Flask and Vite in two terminals:

```bash
# terminal 1 — Flask on :5000
python -m context_visualizer --host 127.0.0.1 --port 5000

# terminal 2 — Vite dev server on :5173 (proxies /api and /_interceptor to :5000)
make workspace-dev
```

Then open <http://127.0.0.1:5173/>. HMR + full API proxying, no CORS
plumbing required.

### Cleaning

```bash
make workspace-clean    # wipe the built SPA bundle
```

## Tests

```bash
python -m unittest discover -s tests
```

## Further reading

- `docs/workspace.md` — rationale for the workspace view and the
  parent/child session-id convention it relies on.
