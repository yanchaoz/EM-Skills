#!/usr/bin/env python3
"""Render and verify the kidney local-field example video.

This script intentionally uses only the four exported local fields. It does
not include or reconstruct a whole-kidney view.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np


WIDTH, HEIGHT, FPS = 1920, 1080, 24
SOURCE_RESOLUTION_NM = 20.0
REGIONS = (
    ("Cortex", (0, 0, 960, 540)),
    ("Corticomedullary junction", (960, 0, 1920, 540)),
    ("Medulla", (0, 540, 960, 1080)),
    ("Renal papilla", (960, 540, 1920, 1080)),
)
ACCENT = (198, 216, 52)  # BGR teal


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def alpha_rect(frame, pt1, pt2, color=(7, 12, 18), alpha=0.78):
    overlay = frame.copy()
    cv2.rectangle(overlay, pt1, pt2, color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


def clean_contact_sheet(source):
    frame = source.copy()
    for title, (x0, y0, x1, _) in REGIONS:
        alpha_rect(frame, (x0, y0), (x1, y0 + 88), alpha=1.0)
        cv2.line(frame, (x0, y0 + 86), (x1, y0 + 86), ACCENT, 3, cv2.LINE_AA)
        cv2.putText(frame, title, (x0 + 34, y0 + 59), cv2.FONT_HERSHEY_SIMPLEX,
                    1.05, (244, 246, 248), 2, cv2.LINE_AA)
    alpha_rect(frame, (38, 934), (1280, 1044), alpha=0.84)
    cv2.putText(frame, "Kidney EM: four local fields", (70, 982),
                cv2.FONT_HERSHEY_SIMPLEX, 1.28, (248, 250, 252), 3, cv2.LINE_AA)
    cv2.putText(frame, "20 nm/px | local views only | no whole-organ overview", (72, 1022),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72, (205, 214, 222), 2, cv2.LINE_AA)
    return frame


def local_frame(crop, title: str, progress: float):
    eased = smoothstep(progress)
    zoom = 1.0 + 0.065 * eased
    scaled = cv2.resize(crop, (round(WIDTH * zoom), round(HEIGHT * zoom)), interpolation=cv2.INTER_CUBIC)
    pan_x = round((scaled.shape[1] - WIDTH) * (0.25 + 0.25 * eased))
    pan_y = round((scaled.shape[0] - HEIGHT) * (0.50 - 0.12 * eased))
    frame = scaled[pan_y:pan_y + HEIGHT, pan_x:pan_x + WIDTH].copy()

    alpha_rect(frame, (0, 0), (1060, 142), alpha=1.0)
    cv2.line(frame, (0, 140), (1060, 140), ACCENT, 4, cv2.LINE_AA)
    cv2.putText(frame, title, (54, 96), cv2.FONT_HERSHEY_SIMPLEX,
                1.34, (248, 250, 252), 3, cv2.LINE_AA)
    alpha_rect(frame, (38, 928), (785, 1044), alpha=0.78)
    cv2.putText(frame, "Kidney EM | representative local field", (70, 976),
                cv2.FONT_HERSHEY_SIMPLEX, 0.78, (224, 230, 235), 2, cv2.LINE_AA)
    cv2.putText(frame, "Source display sampling: 20 nm/px", (70, 1017),
                cv2.FONT_HERSHEY_SIMPLEX, 0.68, (180, 192, 202), 2, cv2.LINE_AA)

    bar_um = 2.0
    bar_px = round((bar_um * 1000.0 / SOURCE_RESOLUTION_NM) * (WIDTH / crop.shape[1]) * zoom)
    x1, y = WIDTH - 72, HEIGHT - 76
    x0 = x1 - bar_px
    cv2.line(frame, (x0, y), (x1, y), (250, 252, 253), 8, cv2.LINE_AA)
    cv2.putText(frame, "2 um", (x0, y - 22), cv2.FONT_HERSHEY_SIMPLEX,
                0.72, (250, 252, 253), 2, cv2.LINE_AA)
    return frame


def crossfade(first, second, progress):
    alpha = smoothstep(progress)
    return cv2.addWeighted(first, 1.0 - alpha, second, alpha, 0)


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(video: Path, expected_frames: int, output_dir: Path):
    cap = cv2.VideoCapture(str(video))
    opened = bool(cap.isOpened())
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_ids = np.linspace(0, max(0, count - 1), 12).astype(int)
    thumbs, decoded = [], []
    for index in sample_ids:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = cap.read()
        decoded.append(bool(ok))
        thumbs.append(cv2.resize(frame, (480, 270)) if ok else np.zeros((270, 480, 3), np.uint8))
    cap.release()
    sheet = np.zeros((810, 1920, 3), np.uint8)
    for index, frame in enumerate(thumbs):
        row, col = divmod(index, 4)
        sheet[row * 270:(row + 1) * 270, col * 480:(col + 1) * 480] = frame
    contact = output_dir / "kidney-local-fields-tour-contact-sheet.jpg"
    cv2.imwrite(str(contact), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
    checks = {
        "dimensions": (width, height) == (WIDTH, HEIGHT),
        "fps": abs(fps - FPS) < 0.05,
        "frame_count": count == expected_frames,
        "all_samples_decoded": all(decoded),
    }
    report = {
        "video": video.name, "opened": opened, "width": width, "height": height,
        "fps": fps, "frame_count": count, "duration_seconds": count / fps if fps else None,
        "decoded_samples": decoded, "sha256": sha256(video), "checks": checks,
        "ok": opened and all(checks.values()),
        "scope": "four local kidney fields only; no whole-kidney overview",
        "source_display_resolution_nm_per_px": SOURCE_RESOLUTION_NM,
    }
    (output_dir / "kidney-local-fields-tour.verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    if not report["ok"]:
        raise RuntimeError(f"video verification failed: {checks}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).with_name("four-local-fields-20nm.jpg"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("kidney-local-fields-tour.mp4"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite {args.output}; use --force")
    source = cv2.imread(str(args.source), cv2.IMREAD_COLOR)
    if source is None or source.shape[:2] != (HEIGHT, WIDTH):
        raise SystemExit("Expected a readable 1920 x 1080 four-field contact sheet")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    intro_frames, transition_frames, hold_frames, outro_hold = 48, 12, 66, 36
    contact = clean_contact_sheet(source)
    crops = [(title, source[y0:y1, x0:x1].copy()) for title, (x0, y0, x1, y1) in REGIONS]
    writer = imageio_ffmpeg.write_frames(
        str(args.output), (WIDTH, HEIGHT), fps=FPS, codec="libx264", quality=None, bitrate="12M",
        pix_fmt_in="rgb24", pix_fmt_out="yuv420p", macro_block_size=8,
        ffmpeg_log_level="warning", output_params=["-movflags", "+faststart"],
    )
    writer.send(None)
    frame_count = 0

    def emit(frame):
        nonlocal frame_count
        writer.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        frame_count += 1

    previous = contact
    for _ in range(intro_frames):
        emit(contact)
    for title, crop in crops:
        first = local_frame(crop, title, 0.0)
        for index in range(transition_frames):
            emit(crossfade(previous, first, (index + 1) / transition_frames))
        for index in range(hold_frames):
            previous = local_frame(crop, title, index / max(1, hold_frames - 1))
            emit(previous)
    for index in range(transition_frames):
        emit(crossfade(previous, contact, (index + 1) / transition_frames))
    for _ in range(outro_hold):
        emit(contact)
    writer.close()
    report = verify(args.output, frame_count, args.output.parent)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
