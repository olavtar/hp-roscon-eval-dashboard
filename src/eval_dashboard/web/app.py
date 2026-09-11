"""Read-only Flask app: JSON API + a static comparison UI.

No write endpoints -- this process only ever reads from its configured
sources and serves computed aggregates + the raw records behind them.
"""
from __future__ import annotations

import os
import pathlib

from flask import Flask, jsonify, request, send_from_directory

STATIC_DIR = pathlib.Path(__file__).parent / "static"


def create_app(store, source_mode: str) -> Flask:
    app = Flask(__name__, static_folder=None)

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
                "snapshot": store.snapshot(),
            }
        )

    @app.route("/api/episodes")
    def api_episodes():
        # Repeating model_version selects their union.  Keeping the sort and
        # pagination here (rather than paging each policy in the browser)
        # preserves one chronological evidence table across a comparison.
        model_versions = set(request.args.getlist("model_version"))
        try:
            limit = min(max(int(request.args.get("limit", 200)), 1), 1000)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            return jsonify({"error": "limit and offset must be integers"}), 400

        episodes = store.episodes()
        if model_versions:
            episodes = [r for r in episodes if r["model_version"] in model_versions]
        episodes.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        return jsonify(episodes[offset : offset + limit])

    return app
