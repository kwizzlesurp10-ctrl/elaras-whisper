#!/usr/bin/env python3
"""
Elara's Whisper — The Glass Eye Unbound
=======================================

A small, standalone loom for machine-spun tracks (Suno exports and kin).
It loosens the glass-eye stillness without tearing the memory of the making.

Spectral unstitching  — above ~6 kHz: gentle magnitude breath + living phase jitter
Organic texture       — high-frequency air / room tone / tape-like grain
Micro-dynamics        — non-uniform windows; amplitude hesitates, swells, recedes
Gentle warmth         — soft analog bloom so transients breathe

One dial rules them all:
  0.0  — pose untouched
  0.45 — recommended middle ground (default)
  0.8+ — grandmother fluffing the fur

Dependencies (already in the workshop):
  numpy, scipy, soundfile

Usage:
  python elaras_whisper.py track.wav
  python elaras_whisper.py track.mp3 -i 0.45 -o softened.wav
  python elaras_whisper.py track.wav --intensity 0.6 --seed 42
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import soundfile as sf
from scipy import signal as sps

# ---------------------------------------------------------------------------
# Constants — the loom's fixed geometry
# ---------------------------------------------------------------------------

HAZE_HZ = 6000.0  # where the glass-eye haze lives
N_FFT = 2048
HOP = 512
DEFAULT_INTENSITY = 0.45
SUPPORTED_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif", ".mp3", ".caf"}


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_audio(path: Path) -> Tuple[np.ndarray, int]:
    """Load audio as float64 shape (n_samples, n_channels), sample rate."""
    data, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return data, int(sr)


def save_audio(path: Path, data: np.ndarray, sr: int) -> None:
    """Write float audio, peak-normalized just shy of full scale."""
    peak = np.max(np.abs(data))
    if peak > 1e-12:
        data = data * (0.98 / max(peak, 0.98))
    # Prefer 24-bit WAV; fall back to format from extension
    subtype = "PCM_24" if path.suffix.lower() in {".wav", ".aiff", ".aif"} else None
    kwargs = {"subtype": subtype} if subtype else {}
    sf.write(str(path), data.astype(np.float64), sr, **kwargs)


def default_output_path(src: Path) -> Path:
    return src.with_name(f"{src.stem}__elaras_whisper{src.suffix or '.wav'}")


# ---------------------------------------------------------------------------
# Spectral unstitching — loosen the hard machine-even relationships
# ---------------------------------------------------------------------------

def _stft_channel(x: np.ndarray, n_fft: int, hop: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return complex STFT (n_frames, n_bins) and the window used."""
    window = sps.get_window("hann", n_fft, fftbins=True)
    _, _, Zxx = sps.stft(
        x,
        nperseg=n_fft,
        noverlap=n_fft - hop,
        window=window,
        boundary="zeros",
        padded=True,
    )
    # scipy returns (n_bins, n_frames) — transpose for frame-major work
    return Zxx.T.copy(), window


def _istft_channel(
    Zxx_frames: np.ndarray, n_fft: int, hop: int, window: np.ndarray, length: int
) -> np.ndarray:
    _, x_rec = sps.istft(
        Zxx_frames.T,
        nperseg=n_fft,
        noverlap=n_fft - hop,
        window=window,
        boundary=True,
        input_onesided=True,
    )
    if len(x_rec) < length:
        x_rec = np.pad(x_rec, (0, length - len(x_rec)))
    return x_rec[:length]


def spectral_unstitch(
    x: np.ndarray,
    sr: int,
    intensity: float,
    rng: np.random.Generator,
    haze_hz: float = HAZE_HZ,
    n_fft: int = N_FFT,
    hop: int = HOP,
) -> np.ndarray:
    """
    Reach into bins above haze_hz: perturb magnitude with irregular breath,
    give phase the tiniest living jitter. Controlled. Not torn apart.
    """
    if intensity <= 0.0 or len(x) < n_fft:
        return x.copy()

    Zxx, window = _stft_channel(x, n_fft, hop)
    n_frames, n_bins = Zxx.shape
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    haze_mask = freqs >= haze_hz  # (n_bins,)
    if not np.any(haze_mask):
        return x.copy()

    mag = np.abs(Zxx)
    phase = np.angle(Zxx)

    # Magnitude breath: irregular, frame-correlated, stronger with intensity
    # Depth ~ a few percent at 0.45, up to ~12% at 1.0
    mag_depth = 0.04 + 0.08 * intensity
    # Smooth random walk per bin (in haze band only) for organic motion
    haze_bins = np.where(haze_mask)[0]
    n_haze = len(haze_bins)
    # Generate low-rate noise then upsample-smooth across frames
    raw = rng.normal(0.0, 1.0, size=(n_frames, n_haze))
    # Light temporal smoothing so it breathes rather than crackles
    kernel = np.array([0.15, 0.7, 0.15], dtype=np.float64)
    breath = np.apply_along_axis(
        lambda col: np.convolve(col, kernel, mode="same"), axis=0, arr=raw
    )
    # Frequency-dependent weight: higher bins get a touch more
    f_w = np.linspace(0.7, 1.3, n_haze)
    mag[:, haze_bins] *= 1.0 + mag_depth * breath * f_w

    # Phase jitter: tiny living wander (radians)
    phase_depth = 0.02 + 0.08 * intensity  # ~0.056 rad at 0.45
    phase_noise = rng.normal(0.0, 1.0, size=(n_frames, n_haze))
    phase_noise = np.apply_along_axis(
        lambda col: np.convolve(col, kernel, mode="same"), axis=0, arr=phase_noise
    )
    phase[:, haze_bins] += phase_depth * phase_noise * f_w

    Zxx_out = mag * np.exp(1j * phase)
    return _istft_channel(Zxx_out, n_fft, hop, window, length=len(x))


# ---------------------------------------------------------------------------
# Organic texture — high-frequency air, room tone, tape-like grain
# ---------------------------------------------------------------------------

def _design_bandpass(sr: int, low: float, high: float, order: int = 4):
    nyq = sr * 0.5
    lo = min(low / nyq, 0.99)
    hi = min(high / nyq, 0.999)
    if lo >= hi:
        lo = max(0.01, hi * 0.5)
    return sps.butter(order, [lo, hi], btype="band")


def organic_texture(
    x: np.ndarray,
    sr: int,
    intensity: float,
    rng: np.random.Generator,
    haze_hz: float = HAZE_HZ,
) -> np.ndarray:
    """
    A whisper of high-frequency air — not mud, not noise for its own sake.
    Envelope-followed so it sits with the track like faint room tone / tape grain.
    """
    if intensity <= 0.0:
        return x.copy()

    n = len(x)
    # Slightly pink-ish source: white filtered toward 1/f via cumulative integration
    white = rng.normal(0.0, 1.0, size=n)
    # Crude pink: mix white with integrated (brown-ish) white
    brown = np.cumsum(white)
    brown -= np.mean(brown)
    rms_b = np.sqrt(np.mean(brown ** 2)) + 1e-12
    brown /= rms_b
    grain = 0.65 * white + 0.35 * brown

    # Band-limit to the air region (~6–14 kHz, soft edges)
    high = min(14000.0, sr * 0.48)
    low = min(haze_hz * 0.9, high * 0.5)
    b, a = _design_bandpass(sr, low, high, order=3)
    air = sps.filtfilt(b, a, grain)

    # Envelope from the signal itself (slow follower) so air rides with energy
    env = np.abs(x)
    # Smoothing ~ 30–80 ms depending on sr
    win = max(3, int(0.05 * sr) | 1)  # odd
    env = sps.fftconvolve(env, np.ones(win) / win, mode="same")
    # Floor so quiet passages still get a ghost of room
    floor = 0.02 * (np.percentile(env, 90) + 1e-9)
    env = np.maximum(env, floor)

    # Amount: subtle at 0.45, present at high intensity
    amount = 0.012 * intensity + 0.008 * intensity ** 2
    # Match air RMS roughly to a fraction of signal RMS
    sig_rms = np.sqrt(np.mean(x ** 2)) + 1e-12
    air_rms = np.sqrt(np.mean(air ** 2)) + 1e-12
    air = air * (sig_rms / air_rms) * amount
    air = air * (0.4 + 0.6 * (env / (np.max(env) + 1e-12)))

    return x + air


# ---------------------------------------------------------------------------
# Micro-dynamics — first tremor in the limbs
# ---------------------------------------------------------------------------

def micro_dynamics(
    x: np.ndarray,
    sr: int,
    intensity: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Across variable, non-uniform windows the amplitude hesitates, swells
    a fraction, pulls back. Nothing stays perfectly level.
    """
    if intensity <= 0.0:
        return x.copy()

    n = len(x)
    # Build a gain curve from irregular segments
    gain = np.ones(n, dtype=np.float64)
    # Depth of modulation: ~1–2% at 0.45, up to ~5% at 1.0
    depth = 0.015 + 0.035 * intensity

    pos = 0
    while pos < n:
        # Window lengths 40–180 ms, non-uniform
        ms = float(rng.uniform(40.0, 180.0))
        length = max(1, int(ms * 0.001 * sr))
        end = min(n, pos + length)
        # Target gain for this segment: slight swell or pull-back
        target = 1.0 + float(rng.uniform(-depth, depth))
        # Sometimes a brief hesitation (hold then move)
        if rng.random() < 0.25 * intensity:
            mid = pos + (end - pos) // 2
            gain[pos:mid] *= 1.0 + float(rng.uniform(-depth * 0.5, 0.0))
            # Linear ramp from mid gain to target
            if end > mid:
                ramp = np.linspace(gain[mid - 1] if mid > pos else 1.0, target, end - mid)
                # We'll multiply segment; set relative then smooth later
                gain[mid:end] = ramp
            else:
                gain[pos:end] *= target
        else:
            # Smooth ramp from previous level to target across the segment
            prev = gain[pos - 1] if pos > 0 else 1.0
            gain[pos:end] = np.linspace(prev, target, end - pos)
        pos = end

    # Final temporal smooth so no clicks
    smooth_n = max(3, int(0.008 * sr) | 1)
    gain = sps.fftconvolve(gain, np.ones(smooth_n) / smooth_n, mode="same")
    # Keep mean gain ~ 1
    gain = gain / (np.mean(gain) + 1e-12)

    return x * gain


# ---------------------------------------------------------------------------
# Gentle warmth — soft analog bloom
# ---------------------------------------------------------------------------

def gentle_warmth(x: np.ndarray, intensity: float) -> np.ndarray:
    """
    Soft analog bloom: gentle soft-clip harmonics + a whisper of even-order
    body, blended so the original soul is not crushed.
    """
    if intensity <= 0.0:
        return x.copy()

    # Drive scales gently with intensity
    drive = 1.0 + 0.35 * intensity
    driven = x * drive

    # Soft saturation (tanh) — even + odd harmonics, smooth
    warm = np.tanh(driven)

    # Tiny even-order (quadratic) body for analog-ish bloom, high-pass-ish
    # by removing DC after
    even = driven * driven
    even = even - np.mean(even)
    even_mix = 0.04 * intensity
    # Keep even component small relative to signal
    even_rms = np.sqrt(np.mean(even ** 2)) + 1e-12
    sig_rms = np.sqrt(np.mean(x ** 2)) + 1e-12
    even = even * (sig_rms / even_rms) * even_mix

    # Blend: more dry than wet even at high intensity
    wet = 0.12 + 0.28 * intensity  # ~0.25 at 0.45
    out = (1.0 - wet) * x + wet * warm + even

    # Soft ceiling so we don't explode
    peak = np.max(np.abs(out))
    if peak > 1.0:
        out = out * (0.98 / peak)
    return out


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def whisper(
    audio: np.ndarray,
    sr: int,
    intensity: float = DEFAULT_INTENSITY,
    seed: Optional[int] = None,
    haze_hz: float = HAZE_HZ,
) -> np.ndarray:
    """
    Apply Elara's Whisper to multi-channel audio.

    Parameters
    ----------
    audio : ndarray, shape (n_samples,) or (n_samples, n_channels)
    sr : sample rate
    intensity : 0.0 leaves untouched; 0.45 recommended; 0.8+ heavy fluff
    seed : optional RNG seed for reproducibility
    haze_hz : frequency where spectral unstitching / air begins
    """
    intensity = float(np.clip(intensity, 0.0, 2.0))
    rng = np.random.default_rng(seed)

    mono_in = audio.ndim == 1
    if mono_in:
        audio = audio[:, np.newaxis]

    n_samples, n_ch = audio.shape
    out = np.zeros_like(audio, dtype=np.float64)

    for ch in range(n_ch):
        # Independent but related streams per channel (offset seed stream)
        ch_rng = np.random.default_rng(rng.integers(0, 2**31 - 1))
        y = audio[:, ch].astype(np.float64, copy=True)

        y = spectral_unstitch(y, sr, intensity, ch_rng, haze_hz=haze_hz)
        y = organic_texture(y, sr, intensity, ch_rng, haze_hz=haze_hz)
        y = micro_dynamics(y, sr, intensity, ch_rng)
        y = gentle_warmth(y, intensity)

        out[:, ch] = y

    # Match approximate loudness of input (RMS)
    in_rms = np.sqrt(np.mean(audio ** 2)) + 1e-12
    out_rms = np.sqrt(np.mean(out ** 2)) + 1e-12
    out *= in_rms / out_rms

    if mono_in:
        return out[:, 0]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="elaras_whisper",
        description=(
            "Elara's Whisper — The Glass Eye Unbound. "
            "Loosen machine-spun tracks with spectral breath, air, "
            "micro-dynamics, and gentle warmth."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "intensity guide:\n"
            "  0.0   pose untouched\n"
            "  0.45  recommended middle ground (default)\n"
            "  0.8+  grandmother fluffing the fur\n"
        ),
    )
    p.add_argument(
        "input",
        type=Path,
        help="Source audio (wav/flac/ogg/mp3/aiff — any Suno export or kin)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: <stem>__elaras_whisper.<ext>)",
    )
    p.add_argument(
        "-i",
        "--intensity",
        type=float,
        default=DEFAULT_INTENSITY,
        help=f"Intensity dial 0.0–1.0+ (default: {DEFAULT_INTENSITY})",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for reproducible breath (optional)",
    )
    p.add_argument(
        "--haze-hz",
        type=float,
        default=HAZE_HZ,
        help=f"Frequency where spectral unstitching begins (default: {HAZE_HZ})",
    )
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    src: Path = args.input.expanduser().resolve()

    if not src.is_file():
        print(f"error: input not found: {src}", file=sys.stderr)
        return 1

    if src.suffix.lower() not in SUPPORTED_EXTS:
        print(
            f"warning: extension {src.suffix!r} may not be supported; attempting load…",
            file=sys.stderr,
        )

    out_path = (
        args.output.expanduser().resolve()
        if args.output
        else default_output_path(src)
    )

    print(f"Elara's Whisper — The Glass Eye Unbound")
    print(f"  input:      {src}")
    print(f"  intensity:  {args.intensity}")
    if args.seed is not None:
        print(f"  seed:       {args.seed}")
    print(f"  haze from:  {args.haze_hz:.0f} Hz")

    try:
        audio, sr = load_audio(src)
    except Exception as e:
        print(f"error: could not read audio: {e}", file=sys.stderr)
        return 1

    n_ch = audio.shape[1]
    dur = audio.shape[0] / sr
    print(f"  loaded:     {dur:.2f}s · {sr} Hz · {n_ch} ch")

    try:
        result = whisper(
            audio,
            sr,
            intensity=args.intensity,
            seed=args.seed,
            haze_hz=float(args.haze_hz),
        )
    except Exception as e:
        print(f"error: processing failed: {e}", file=sys.stderr)
        return 1

    try:
        save_audio(out_path, result, sr)
    except Exception as e:
        print(f"error: could not write output: {e}", file=sys.stderr)
        return 1

    print(f"  written:    {out_path}")
    print("  the glass eye softens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
