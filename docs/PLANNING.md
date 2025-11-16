# Project Planning: "maccam" MacBook Webcam Recorder

## Goals
- Turn an Intel MacBook Pro into a low-resolution webcam recorder that can run unattended for up to a week.
- Support continuous or motion-triggered capture, with optional phone notifications on motion events.
- Provide a simple way to start/stop the system (CLI or launch agent), with configurable storage location and retention.

## Target Environment
- macOS (Intel) with built-in FaceTime camera.
- Python 3.10+ (installed via Homebrew or pyenv) for portability and quick iteration.
- Homebrew packages likely required: `ffmpeg` (for encoding and muxing), `opencv` (for motion detection), and optionally `portaudio` (if future audio alerts are added).
- macOS permissions: camera and microphone (if audio recorded) must be granted to terminal/launch agent.

## High-Level Architecture
- **CLI entrypoint (e.g., `maccam` package with `cli.py`)** to start/stop recording modes and manage configuration.
- **Capture pipeline** using OpenCV + FFmpeg backends:
  - Initialize webcam at a low resolution (e.g., 640x360 or 800x600) and modest fps (5–15) to reduce storage.
  - Encode to H.264 (MP4 container) via `ffmpeg` or OpenCV `VideoWriter`, with tunable bitrate.
- **Motion detection layer** (optional): frame differencing with adaptive background model to decide when to start/stop recording segments.
- **Notification layer** (optional): send HTTP POST to a user-configurable webhook (e.g., `ntfy`, Pushover, Pushcut) on motion events.
- **Storage/retention layer**: rolling directory structure with date-based folders; optional automatic cleanup based on size/days.
- **Monitoring/logging**: structured logs and optional stats (frame rate, dropped frames, disk usage).
- **Launch automation**: `launchd` plist or simple `nohup` invocation to keep the process alive for long runs.

## Modules and Responsibilities
- `maccam/config.py`
  - Load/save config from YAML/JSON; allow CLI overrides.
  - Key fields: `resolution` (width, height), `fps`, `bitrate_kbps`, `output_dir`, `segment_duration_sec`, `max_retention_days`, `mode` (continuous vs motion), `motion` thresholds (pixel delta %, area), `notification` settings (webhook URL, auth headers), and `camera_index`.
- `maccam/capture.py`
  - OpenCV-based camera acquisition (ensure correct backend on macOS, e.g., AVFoundation). Handle graceful init errors (permission, missing camera).
  - Provide frame generator and metadata (timestamps, frame count).
  - Implement health checks (e.g., time since last frame) and reconnection logic.
- `maccam/recorder.py`
  - Manage active recording using OpenCV `VideoWriter` or external `ffmpeg` subprocess for better encoding quality.
  - Segment files by duration (e.g., 5–15 minutes) to reduce corruption risk; filenames include timestamps.
  - Support pre-roll/post-roll buffers for motion mode (circular buffer of recent frames) so events include leading context.
- `maccam/motion.py`
  - Basic motion detection via frame differencing + contour area or MOG2 background subtractor.
  - Debounce motion start/stop with hysteresis (e.g., require N consecutive motion frames) to avoid chattering.
  - Expose callbacks/events to recorder to start/stop segments.
- `maccam/notification.py`
  - Thin client for sending webhook notifications; retries with backoff on failure.
  - Payload includes timestamp and event summary; optionally attach snapshot frame.
- `maccam/storage.py`
  - Disk space checks before writing; optional cap (e.g., stop recording or delete oldest segments when exceeding quota).
  - Retention sweeper to delete files older than `max_retention_days` or beyond size budget.
- `maccam/logging_utils.py`
  - Configure standard logging, rotating file handler, and console output. Include structured context for events.
- `maccam/cli.py`
  - Commands: `record` (continuous), `motion` (motion-triggered), `once` (quick test), `status` (check camera/disk), `notify-test`.
  - Arguments to override config (resolution, fps, output dir, webhook URL, verbosity, dry-run).
- `maccam/app.py`
  - Wire together config, capture, motion detector, recorder, notifications, and retention sweeper.
  - Handle graceful shutdown signals (SIGINT/SIGTERM) to flush and close files.
- `maccam/launchd/` (optional)
  - Sample `com.example.maccam.plist` to auto-start the CLI with specific flags on login or boot.

## Key Flows
- **Continuous recording**
  1. CLI loads config, initializes capture at requested resolution/fps.
  2. Recorder writes frames to rolling segments; storage layer enforces retention.
  3. Logging reports file paths, disk space warnings, and dropped frames.

- **Motion-triggered recording**
  1. Capture runs in a loop feeding frames to motion detector.
  2. When motion crosses thresholds, recorder starts a new segment (with optional pre-roll frames).
  3. When motion quiets, recorder stops after post-roll window; notifications fire on motion start/end.
  4. Storage sweeper prunes old segments.

## Configuration Details
- Default config file: `~/.maccam/config.yaml` with overridable per-run flags.
- Suggested defaults for low storage impact:
  - Resolution: 640x360 @ 10 fps
  - Bitrate: ~700–900 kbps (H.264)
  - Segment duration: 10 minutes (continuous) or per-motion event
  - Retention: 7 days by default
- Motion thresholds: luminance diff threshold (e.g., 25–30), minimum contour area (e.g., 500–1500 pixels), and required consecutive frames (e.g., 3–5) to trigger.
- Notification: `webhook_url`, optional `auth_token`, `cooldown_sec` to avoid spamming.

## Dependencies
- Python packages: `opencv-python`, `ffmpeg-python` or `imageio-ffmpeg`, `pydantic`/`dataclasses` for config, `pyyaml`, `requests`, `click`/`typer` for CLI, `tenacity` for retry logic, `psutil` for disk checks.
- macOS system tools: `ffmpeg` via Homebrew, ensure `/usr/local/bin` is in PATH for launchd contexts.
- Testing tools: `pytest`, `tox`/`nox` optional for automation; `mypy` or `pyright` for type checking.

## File/Directory Layout
- `maccam/` package with modules listed above.
- `scripts/` for helper scripts (e.g., `record.sh` for quick start, `launchd` install script).
- `docs/` for guides (setup, troubleshooting, launchd instructions, notification setup).
- `tests/` with unit tests for config parsing, motion detection, and notification payloads; integration tests with mocked camera input.

## Motion Detection Design Notes
- Convert frames to grayscale, blur to reduce noise; maintain a running average or use `cv2.createBackgroundSubtractorMOG2`.
- Compute delta mask, threshold, dilate to fill gaps; find contours and measure area.
- Use exponential decay to update background to handle lighting changes; add cooldown to prevent rapid re-triggering.

## Recorder Design Notes
- Prefer `ffmpeg` subprocess for reliable H.264 encoding on macOS. Fallback: OpenCV `VideoWriter` with `avc1` codec.
- Write to MP4; ensure files finalize cleanly on shutdown (flush, close handles).
- Pre-roll buffer: deque of last N frames (~2–5 seconds). On motion start, write buffer then live frames.
- Post-roll: continue recording for N seconds after motion stops; merge segments by event if needed.

## Reliability and Operations
- Handle camera disconnects gracefully: attempt reopen with backoff, log errors, and optionally alert.
- Disk monitoring: before each new segment, check available space; pause recording and log critical when below threshold.
- Health metrics: counters for motion events, frames captured, dropped frames, encoder errors.
- Provide `--dry-run` to test camera and motion pipeline without writing files.

## Security and Privacy
- Ensure output directory permissions are user-restricted.
- Avoid storing notification auth tokens in logs; support environment variable overrides.
- Provide clear guidance on macOS privacy permissions; surface helpful error messages when access is denied.

## Next Steps
- Scaffold Python package (`pyproject.toml`, virtualenv instructions), add dependencies, and stub modules.
- Implement CLI with minimal continuous capture first, then layer motion detection and notifications.
- Add documentation for setup on Intel macOS and launchd scheduling.
