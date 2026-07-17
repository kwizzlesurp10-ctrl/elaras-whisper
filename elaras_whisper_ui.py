#!/usr/bin/env python3
"""
Elara's Whisper — Glass Eye UI server
=====================================

Local web loom: drag-and-drop tracks, turn the intensity dial, unbind the glass eye.

  python3 elaras_whisper_ui.py
  python3 elaras_whisper_ui.py --port 8787 --open
  elaras-whisper-ui

Nothing is uploaded off-machine; processing runs in-process via elaras_whisper.
"""

from __future__ import annotations

import argparse
import io
import sys
import tempfile
import webbrowser
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

# Allow running as script from repo root or installed package sibling
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elaras_whisper import (  # noqa: E402
    DEFAULT_INTENSITY,
    HAZE_HZ,
    PRESETS,
    SUPPORTED_EXTS,
    load_audio,
    save_audio,
    whisper,
)

try:
    from flask import Flask, jsonify, request, send_file, send_from_directory
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "The Glass Eye UI needs Flask.\n"
        "  pip install flask\n"
        "  # or:  pip install -e '.[ui]'\n"
        f"({e})"
    ) from e


UI_DIR = _ROOT / "ui"
STATIC_DIR = UI_DIR / "static"


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512 MB total

    @app.get("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "name": "elaras-whisper", "ui": "glass-eye"})

    @app.get("/api/presets")
    def presets():
        return jsonify(
            {
                "default": DEFAULT_INTENSITY,
                "haze_hz": HAZE_HZ,
                "presets": PRESETS,
                "extensions": sorted(SUPPORTED_EXTS),
            }
        )

    @app.post("/api/process")
    def process():
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "No files received. Lay a track upon the glass."}), 400

        try:
            intensity = float(request.form.get("intensity", DEFAULT_INTENSITY))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid intensity."}), 400

        try:
            haze_hz = float(request.form.get("haze_hz", HAZE_HZ))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid haze_hz."}), 400

        seed_raw = request.form.get("seed", "").strip()
        seed: Optional[int]
        if seed_raw == "":
            seed = None
        else:
            try:
                seed = int(seed_raw)
            except ValueError:
                return jsonify({"error": "Seed must be an integer."}), 400

        # Work in a temp dir so soundfile can use real paths (some formats prefer that)
        results: List[Tuple[str, bytes]] = []
        errors: List[str] = []

        with tempfile.TemporaryDirectory(prefix="elaras_ui_") as tmp:
            tmp_path = Path(tmp)
            for storage in files:
                name = Path(storage.filename or "track.wav").name
                if not name or name in {".", ".."}:
                    errors.append("skipped unnamed file")
                    continue
                suffix = Path(name).suffix.lower()
                if suffix and suffix not in SUPPORTED_EXTS:
                    errors.append(f"{name}: unsupported extension")
                    continue

                src = tmp_path / f"in_{len(results)}_{name}"
                out_name = f"{Path(name).stem}__elaras_whisper.wav"
                out = tmp_path / out_name
                try:
                    storage.save(str(src))
                    audio, sr = load_audio(src)
                    soft = whisper(
                        audio,
                        sr,
                        intensity=intensity,
                        seed=seed,
                        haze_hz=haze_hz,
                    )
                    save_audio(out, soft, sr)
                    results.append((out_name, out.read_bytes()))
                except Exception as exc:  # noqa: BLE001 — surface to UI
                    errors.append(f"{name}: {exc}")

            if not results:
                msg = "; ".join(errors) if errors else "Nothing could be processed."
                return jsonify({"error": msg}), 400

            if len(results) == 1:
                fname, data = results[0]
                buf = io.BytesIO(data)
                buf.seek(0)
                return send_file(
                    buf,
                    mimetype="audio/wav",
                    as_attachment=True,
                    download_name=fname,
                )

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for fname, data in results:
                    zf.writestr(fname, data)
                if errors:
                    zf.writestr("_errors.txt", "\n".join(errors) + "\n")
            zip_buf.seek(0)
            return send_file(
                zip_buf,
                mimetype="application/zip",
                as_attachment=True,
                download_name="elaras_whisper_batch.zip",
            )

    return app


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="elaras-whisper-ui",
        description="Elara's Whisper — open the Glass Eye local UI",
    )
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8787, help="Port (default: 8787)")
    p.add_argument(
        "--open",
        action="store_true",
        help="Open the UI in your default browser",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Flask debug mode (reload on code change)",
    )
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)

    if not UI_DIR.is_dir() or not (UI_DIR / "index.html").is_file():
        print(f"error: UI assets missing under {UI_DIR}", file=sys.stderr)
        return 1

    app = create_app()
    url = f"http://{args.host}:{args.port}/"
    print("Elara's Whisper — The Glass Eye Unbound")
    print(f"  UI:     {url}")
    print("  local only · nothing leaves this machine")
    print("  Ctrl+C to close the loom")

    if args.open:
        # Delay slightly so the server is up
        import threading

        def _open() -> None:
            import time

            time.sleep(0.6)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
