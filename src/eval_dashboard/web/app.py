"""Read-only Flask app: JSON API + a static comparison UI.

No write endpoints -- this process only ever reads from its configured
sources and serves computed aggregates + the raw records behind them.
"""
from __future__ import annotations

import os
import pathlib

from flask import Flask, jsonify, request, send_from_directory

STATIC_DIR = pathlib.Path(__file__).parent / "static"


def create_app(operational, controlled, source_mode: str) -> Flask:
    app = Flask(__name__, static_folder=None)
    panels = {"operational": operational, "controlled": controlled}

    @app.route("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.route("/<path:filename>")
    def static_files(filename):
        return send_from_directory(STATIC_DIR, filename)

    @app.route("/api/stats")
    def api_stats():
        return jsonify(
            {
                "source_mode": source_mode,
                "live_dashboard_url": os.environ.get("LIVE_DASHBOARD_URL", "http://10.0.0.49:30801"),
                "operational": operational.snapshot(),
                "controlled": controlled.snapshot(),
            }
        )

    @app.route("/api/episodes")
    def api_episodes():
        panel = panels.get(request.args.get("panel", "controlled"))
        if panel is None:
            return jsonify({"error": "panel must be 'operational' or 'controlled'"}), 400
        model_version = request.args.get("model_version")
        limit = min(int(request.args.get("limit", 200)), 1000)
        episodes = panel.episodes(model_version)
        episodes.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        return jsonify(episodes[:limit])

    return app
