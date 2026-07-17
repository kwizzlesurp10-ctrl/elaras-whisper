#!/usr/bin/env python3
"""
Elara's Whisper — Glass Eye UI server
=====================================

Local web loom: drag-and-drop tracks, turn the intensity dial, unbind the glass eye.
Optional open-source BPM adjust (librosa phase vocoder) + short preview playback.

  python3 elaras_whisper_ui.py
  python3 elaras_whisper_ui.py --port 8787 --open
  elaras-whisper-ui

Nothing is uploaded off-machine; processing runs in-process via elaras_whisper.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tempfile
import webbrowser
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow running as script from repo root or installed package sibling
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elaras_whisper import (  # noqa: E402
    DEFAULT_INTENSITY,
    DEFAULT_PREVIEW_SECONDS,
    HAZE_HZ,
    MAX_TEMPO_RATE,
    MIN_TEMPO_RATE,
    PRESETS,
    SUPPORTED_EXTS,
    detect_bpm,
    load_audio,
    process_audio,
    save_audio,
)

try:
    from flask import Flask, jsonify, request, send_file, send_from_directory
    from werkzeug.exceptions import RequestEntityTooLarge
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "The Glass Eye UI needs Flask.\n"
        "  pip install flask\n"
        "  # or:  pip install -e '.[ui]'\n"
        f"({e})"
    ) from e


UI_DIR = _ROOT / "ui"
STATIC_DIR = UI_DIR / "static"
MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB total

_SAFE_STEM = re.compile(r"[^\w.\-]+", re.UNICODE)


def _safe_stem(name: str) -> str:
    stem = Path(name).stem or "track"
    cleaned = _SAFE_STEM.sub("_", stem).strip("._") or "track"
    return cleaned[:120]


def _unique_out_name(stem: str, used: Dict[str, int]) -> str:
    """Ensure zip/entry names are unique when multiple files share a stem."""
    base = f"{stem}__elaras_whisper.wav"
    if base not in used:
        used[base] = 1
        return base
    used[base] += 1
    n = used[base]
    while True:
        candidate = f"{stem}__elaras_whisper_{n}.wav"
        if candidate not in used:
            used[candidate] = 1
            return candidate
        n += 1


def _parse_common_form() -> Tuple[Optional[Dict[str, Any]], Optional[Tuple]]:
    """
    Parse intensity / haze / seed / tempo fields from multipart form.
    Returns (params, None) or (None, (jsonify_response, status)).
    """
    try:
        intensity = float(request.form.get("intensity", DEFAULT_INTENSITY))
    except (TypeError, ValueError):
        return None, (jsonify({"error": "Invalid intensity."}), 400)

    try:
        haze_hz = float(request.form.get("haze_hz", HAZE_HZ))
    except (TypeError, ValueError):
        return None, (jsonify({"error": "Invalid haze_hz."}), 400)

    seed_raw = request.form.get("seed", "").strip()
    seed: Optional[int]
    if seed_raw == "":
        seed = None
    else:
        try:
            seed = int(seed_raw)
        except ValueError:
            return None, (jsonify({"error": "Seed must be an integer."}), 400)

    target_bpm: Optional[float] = None
    source_bpm: Optional[float] = None
    tempo_rate: Optional[float] = None
    preview_seconds: Optional[float] = None

    bpm_raw = request.form.get("target_bpm", "").strip()
    if bpm_raw:
        try:
            target_bpm = float(bpm_raw)
            if target_bpm <= 0:
                return None, (jsonify({"error": "Target BPM must be positive."}), 400)
        except ValueError:
            return None, (jsonify({"error": "Invalid target BPM."}), 400)

    src_raw = request.form.get("source_bpm", "").strip()
    if src_raw:
        try:
            source_bpm = float(src_raw)
            if source_bpm <= 0:
                return None, (jsonify({"error": "Source BPM must be positive."}), 400)
        except ValueError:
            return None, (jsonify({"error": "Invalid source BPM."}), 400)

    rate_raw = request.form.get("tempo_rate", "").strip()
    if rate_raw:
        try:
            tempo_rate = float(rate_raw)
            if tempo_rate < MIN_TEMPO_RATE or tempo_rate > MAX_TEMPO_RATE:
                return None, (
                    jsonify(
                        {
                            "error": (
                                f"Tempo rate must be between "
                                f"{MIN_TEMPO_RATE} and {MAX_TEMPO_RATE}."
                            )
                        }
                    ),
                    400,
                )
        except ValueError:
            return None, (jsonify({"error": "Invalid tempo rate."}), 400)

    # Explicit rate overrides target BPM
    if tempo_rate is not None:
        target_bpm = None

    prev_raw = request.form.get("preview_seconds", "").strip()
    if prev_raw:
        try:
            preview_seconds = float(prev_raw)
            if preview_seconds <= 0:
                return None, (jsonify({"error": "Preview seconds must be positive."}), 400)
            preview_seconds = min(preview_seconds, 60.0)
        except ValueError:
            return None, (jsonify({"error": "Invalid preview seconds."}), 400)

    return {
        "intensity": intensity,
        "haze_hz": haze_hz,
        "seed": seed,
        "target_bpm": target_bpm,
        "source_bpm": source_bpm,
        "tempo_rate": tempo_rate,
        "preview_seconds": preview_seconds,
    }, None


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    @app.errorhandler(413)
    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_err):
        return (
            jsonify(
                {
                    "error": (
                        f"Upload too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)."
                    )
                }
            ),
            413,
        )

    @app.get("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.get("/api/health")
    def health():
        tempo_ok = True
        try:
            import librosa  # noqa: F401
        except ImportError:
            tempo_ok = False
        return jsonify(
            {
                "ok": True,
                "name": "elaras-whisper",
                "ui": "glass-eye",
                "tempo": tempo_ok,
            }
        )

    @app.get("/api/presets")
    def presets():
        return jsonify(
            {
                "default": DEFAULT_INTENSITY,
                "haze_hz": HAZE_HZ,
                "presets": PRESETS,
                "extensions": sorted(SUPPORTED_EXTS),
                "preview_seconds_default": DEFAULT_PREVIEW_SECONDS,
                "tempo_rate_min": MIN_TEMPO_RATE,
                "tempo_rate_max": MAX_TEMPO_RATE,
            }
        )

    @app.post("/api/detect-bpm")
    def api_detect_bpm():
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "No file received."}), 400
        storage = files[0]
        name = Path(storage.filename or "track.wav").name
        with tempfile.TemporaryDirectory(prefix="elaras_bpm_") as tmp:
            src = Path(tmp) / name
            try:
                storage.save(str(src))
                audio, sr = load_audio(src)
                bpm = detect_bpm(audio, sr)
            except ImportError as e:
                return jsonify({"error": str(e)}), 500
            except Exception as exc:  # noqa: BLE001
                return jsonify({"error": f"Could not detect BPM: {exc}"}), 400
        if bpm <= 0:
            return jsonify({"error": "Could not estimate BPM for this clip.", "bpm": None}), 400
        return jsonify(
            {
                "bpm": round(bpm, 2),
                "filename": name,
                "duration_sec": round(audio.shape[0] / sr, 2),
                "sr": sr,
            }
        )

    @app.post("/api/preview")
    def api_preview():
        """Process first file, first N seconds — return playable WAV + tempo meta."""
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "No files received. Lay a track upon the glass."}), 400

        params, err = _parse_common_form()
        if err:
            return err
        assert params is not None

        # Default preview window when not specified
        if params["preview_seconds"] is None:
            params["preview_seconds"] = DEFAULT_PREVIEW_SECONDS

        storage = files[0]
        name = Path(storage.filename or "track.wav").name
        suffix = Path(name).suffix.lower()
        if suffix and suffix not in SUPPORTED_EXTS:
            return jsonify({"error": f"Unsupported extension: {suffix}"}), 400

        with tempfile.TemporaryDirectory(prefix="elaras_preview_") as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / f"in_{name}"
            out = tmp_path / "preview.wav"
            try:
                storage.save(str(src))
                audio, sr = load_audio(src)
                soft, meta = process_audio(
                    audio,
                    sr,
                    intensity=params["intensity"],
                    seed=params["seed"],
                    haze_hz=params["haze_hz"],
                    target_bpm=params["target_bpm"],
                    source_bpm=params["source_bpm"],
                    tempo_rate=params["tempo_rate"],
                    preview_seconds=params["preview_seconds"],
                )
                save_audio(out, soft, sr)
                data = out.read_bytes()
            except ImportError as e:
                return jsonify({"error": str(e)}), 500
            except Exception as exc:  # noqa: BLE001
                return jsonify({"error": f"Preview failed: {exc}"}), 400

        buf = io.BytesIO(data)
        buf.seek(0)
        # Expose tempo meta in headers for the UI readout
        resp = send_file(
            buf,
            mimetype="audio/wav",
            as_attachment=False,
            download_name=f"{_safe_stem(name)}__preview.wav",
        )
        if meta.get("source_bpm"):
            resp.headers["X-Source-Bpm"] = f"{float(meta['source_bpm']):.2f}"
        if meta.get("target_bpm"):
            resp.headers["X-Target-Bpm"] = f"{float(meta['target_bpm']):.2f}"
        if meta.get("rate"):
            resp.headers["X-Tempo-Rate"] = f"{float(meta['rate']):.4f}"
        resp.headers["X-Preview-Seconds"] = f"{float(params['preview_seconds']):.1f}"
        resp.headers["X-Tempo-Applied"] = "1" if meta.get("applied") else "0"
        resp.headers["Access-Control-Expose-Headers"] = (
            "X-Source-Bpm, X-Target-Bpm, X-Tempo-Rate, X-Preview-Seconds, X-Tempo-Applied"
        )
        return resp

    @app.post("/api/process")
    def process():
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "No files received. Lay a track upon the glass."}), 400

        params, err = _parse_common_form()
        if err:
            return err
        assert params is not None

        results: List[Tuple[str, bytes]] = []
        errors: List[str] = []
        used_names: Dict[str, int] = {}

        with tempfile.TemporaryDirectory(prefix="elaras_ui_") as tmp:
            tmp_path = Path(tmp)
            for idx, storage in enumerate(files):
                name = Path(storage.filename or "track.wav").name
                if not name or name in {".", ".."}:
                    errors.append("skipped unnamed file")
                    continue
                suffix = Path(name).suffix.lower()
                if suffix and suffix not in SUPPORTED_EXTS:
                    errors.append(f"{name}: unsupported extension")
                    continue

                src = tmp_path / f"in_{idx}_{name}"
                stem = _safe_stem(name)
                out_name = _unique_out_name(stem, used_names)
                out = tmp_path / out_name
                try:
                    storage.save(str(src))
                    audio, sr = load_audio(src)
                    # Full export: no preview slice unless client asked for one
                    soft, _meta = process_audio(
                        audio,
                        sr,
                        intensity=params["intensity"],
                        seed=params["seed"],
                        haze_hz=params["haze_hz"],
                        target_bpm=params["target_bpm"],
                        source_bpm=params["source_bpm"],
                        tempo_rate=params["tempo_rate"],
                        preview_seconds=params["preview_seconds"],
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
