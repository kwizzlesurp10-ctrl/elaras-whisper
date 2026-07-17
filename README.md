# Elara’s Whisper — The Glass Eye Unbound

A small, standalone **Python audio loom** for machine-spun tracks (Suno exports and kin). It loosens the glass-eye stillness without tearing the memory of the making.

One dial rules them all:

| Intensity | Feel |
|-----------|------|
| `0.0` | Pose untouched (processing is a no-op) |
| `0.45` | Recommended middle ground (**default**) |
| `0.8+` | Grandmother fluffing the fur |

## What it does

Four gentle stages, all scaled by intensity:

1. **Spectral unstitching** — above ~6 kHz: magnitude breath + living phase jitter  
2. **Organic texture** — high-frequency air / room tone / tape-like grain  
3. **Micro-dynamics** — non-uniform gain windows (hesitate, swell, recede)  
4. **Gentle warmth** — soft analog bloom so transients breathe  

Channels are processed independently with related RNG streams. Output RMS is matched to the input; WAV/AIFF writes as 24-bit PCM by default.

## Install

**Dependencies:** `numpy`, `scipy`, `soundfile` (and a libsndfile build that can read your formats — system **ffmpeg** helps for some MP3 paths).

```bash
# from this repo
pip install -e .

# with Glass Eye UI
pip install -e ".[ui]"
```

Console scripts: `elaras-whisper`, `elaras_whisper`, `elaras-whisper-ui`.

## Glass Eye UI

A local web loom — living iris intensity dial, drop zone, preset beads, stage breath animation. **Processing stays on your machine.**

```bash
python3 elaras_whisper_ui.py --open
# or
python3 elaras_whisper.py --gui
# or after install
elaras-whisper-ui --open
```

Opens at [http://127.0.0.1:8787/](http://127.0.0.1:8787/) by default (`--host` / `--port` available).

| Control | Role |
|---------|------|
| Drop lens | Multi-file drag-and-drop (batch → zip) |
| Glass Eye dial | Intensity 0–1.2 (drag, wheel, arrows) |
| Preset beads | pose · breath · recommended · fluff · grandmother |
| Memory seed | Reproducible RNG |
| Haze from | Spectral unstitch / air floor (Hz) |
| **Unbind the glass eye** | Run the four-stage loom |
| **Tempo loom** | Detect BPM, set target BPM or rate (librosa phase vocoder) |
| **Preview** | Process first N seconds + play in-page before full export |

Requires optional dep: `flask` (`pip install flask` or `.[ui]`).  
BPM adjust: `librosa` (`pip install librosa` or `.[tempo]` / `.[all]`).

### BPM / preview (CLI)

```bash
# estimate tempo
python3 elaras_whisper.py track.wav --detect-bpm

# stretch to target BPM (auto-detect source), then whisper
python3 elaras_whisper.py track.wav --bpm 128 -o out.wav

# explicit rate (1.05 = 5% faster), pitch preserved
python3 elaras_whisper.py track.wav --tempo-rate 1.05 -o out.wav

# quick A/B: first 10 seconds only
python3 elaras_whisper.py track.wav --bpm 120 --preview-seconds 10 -o preview.wav
```

## Usage (CLI)

```bash
# single track (writes track__elaras_whisper.wav beside the source)
python3 elaras_whisper.py track.wav

# intensity + explicit output + reproducible seed
python3 elaras_whisper.py track.mp3 -i 0.45 -o out.wav --seed 42

# named preset (A/B stops)
python3 elaras_whisper.py track.wav --preset fluff
python3 elaras_whisper.py track.wav --preset breath -o light.wav

# batch: several files → output directory
python3 elaras_whisper.py a.wav b.wav -o ./softened/

# batch folder (optional recursive walk)
python3 elaras_whisper.py --batch ./suno_exports -i 0.45
python3 elaras_whisper.py --batch ./album -r -o ./album_whispered/

# list presets
python3 elaras_whisper.py --list-presets
```

### Presets

| Name | Intensity |
|------|-----------|
| `pose` | 0.0 |
| `breath` | 0.25 |
| `recommended` | 0.45 |
| `fluff` | 0.80 |
| `grandmother` | 1.0 |

`--preset` sets intensity; if both `--preset` and `-i` are given, the **preset wins**.

### Useful flags

| Flag | Meaning |
|------|---------|
| `-i` / `--intensity` | Dial 0.0–1.0+ |
| `--preset NAME` | Named intensity stop |
| `-o` / `--output` | File (single) or directory (batch) |
| `--batch DIR` | All supported audio in `DIR` (repeatable) |
| `-r` / `--recursive` | Walk subfolders with batch/folder inputs |
| `--seed N` | Reproducible breath / grain |
| `--haze-hz HZ` | Where unstitching / air begins (default `6000`) |
| `-q` / `--quiet` | Less console chatter |

**Supported extensions:** `.wav` `.flac` `.ogg` `.aiff` `.aif` `.mp3` `.caf`

## Library API

```python
from pathlib import Path
import elaras_whisper as ew

audio, sr = ew.load_audio(Path("track.wav"))
soft = ew.whisper(audio, sr, intensity=0.45, seed=42)
ew.save_audio(Path("soft.wav"), soft, sr)
```

Core entry point: `whisper(audio, sr, intensity=0.45, seed=None, haze_hz=6000.0)`.

Stages are also importable: `spectral_unstitch`, `organic_texture`, `micro_dynamics`, `gentle_warmth`.

## Notes

- **Intensity 0.0** leaves the sample buffer unchanged in the processing chain (identity through `whisper`). Peak-safe write still applies on save when peaks exceed ~0.98.  
- Prefer **WAV/FLAC** exports from Suno when possible for clean decode paths.  
- Default haze band starts at **6 kHz** — tune with `--haze-hz` if a track’s air lives higher or lower.

## Status

Verified: intensity `0.0` is bit-identical through `whisper`; smoke-tested on synthetic stereo and MusicGen-style material; Glass Eye UI process API smoke-tested.

**Not (yet):** OS drop-folder watcher, full packaging release polish, end-to-end album / Suno catalogue runs.

## License

MIT — see repository.
