"""Flask application factory for the context visualizer."""

import atexit

from flask import Flask, render_template

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

    @app.route("/provenance")
    def provenance():
        return render_template("provenance.html")

    @app.route("/recovery")
    def recovery():
        return render_template("recovery.html")

    @app.route("/call-graph")
    def call_graph():
        return render_template("call_graph.html")

    @app.route("/overhead")
    def overhead():
        return render_template("overhead.html")

    # Clean shutdown
    atexit.register(chimaera_client.finalize)

    return app
