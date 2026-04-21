"""Flask application factory for the context visualizer."""

import atexit
from pathlib import Path

from flask import Flask, render_template, send_from_directory

from . import chimaera_client


def create_app():
    app = Flask(__name__)

    # Register API blueprints
    from .api.workers import bp as workers_bp
    from .api.pools import bp as pools_bp
    from .api.config import bp as config_bp
    from .api.system import bp as system_bp
    from .api.topology import bp as topology_bp
    from .api.node import bp as node_bp
    from .api.provenance import bp as provenance_bp
    from .api.recovery import bp as recovery_bp
    from .api.checkpoints import bp as checkpoints_bp
    from .api.llm_dispatch import bp as llm_dispatch_bp
    from .api.semantic import bp as semantic_bp
    from .api.overhead import bp as overhead_bp
    from .api.conversations import bp as conversations_bp

    app.register_blueprint(workers_bp, url_prefix="/api")
    app.register_blueprint(pools_bp, url_prefix="/api")
    app.register_blueprint(config_bp, url_prefix="/api")
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(topology_bp, url_prefix="/api")
    app.register_blueprint(node_bp, url_prefix="/api")
    app.register_blueprint(provenance_bp, url_prefix="/api")
    app.register_blueprint(recovery_bp, url_prefix="/api")
    app.register_blueprint(checkpoints_bp, url_prefix="/api")
    app.register_blueprint(semantic_bp, url_prefix="/api")
    app.register_blueprint(overhead_bp, url_prefix="/api")
    # Conversation/workspace routes carry full paths on their handlers
    # (both /api/... and /_interceptor/...), so register without a prefix.
    app.register_blueprint(conversations_bp)
    # LLM dispatch bridge — handles /_session/<id>/... and catch-all
    # Must be registered LAST (catch-all routes)
    app.register_blueprint(llm_dispatch_bp)

    # Template routes
    @app.route("/")
    def topology():
        return render_template("topology.html")

    @app.route("/pools")
    def pools():
        return render_template("pools.html")

    @app.route("/config")
    def config():
        return render_template("config.html")

    @app.route("/node/<int:node_id>")
    def node(node_id):
        return render_template("node.html", node_id=node_id)

    @app.route("/recovery")
    def recovery():
        return render_template("recovery.html")

    # Workspace SPA shell. Vite writes its build output into
    # ``static/workspace/``; the ``/static/workspace/...`` asset URLs are
    # served by Flask's default static handler, so only the HTML entry
    # point needs a dedicated route. If the SPA has not been built yet,
    # fall back to a 503 with a clear hint rather than serving a 404 that
    # looks like a deploy bug.
    workspace_dir = Path(app.static_folder) / "workspace"

    @app.route("/workspace")
    def workspace():
        index_html = workspace_dir / "index.html"
        if not index_html.is_file():
            body = (
                "<!doctype html><meta charset='utf-8'>"
                "<title>Workspace not built</title>"
                "<style>body{font-family:sans-serif;padding:40px;max-width:640px}"
                "code{background:#eee;padding:2px 6px;border-radius:4px}</style>"
                "<h1>Workspace UI not built yet</h1>"
                "<p>The multi-agent workspace bundle is missing from "
                "<code>static/workspace/</code>. Run "
                "<code>make workspace</code> (or "
                "<code>cd context-visualizer/frontend &amp;&amp; "
                "npm install &amp;&amp; npm run build</code>) and reload.</p>"
            )
            return body, 503, {"Content-Type": "text/html; charset=utf-8"}
        return send_from_directory(workspace_dir, "index.html")

    # Clean shutdown
    atexit.register(chimaera_client.finalize)

    return app
