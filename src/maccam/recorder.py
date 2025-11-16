import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Optional

from .config import RecorderConfig


class RecorderService:
    def __init__(self, config: RecorderConfig) -> None:
        self.config = config
        self.stop_event = Event()
        self.config.ensure_directories()

    def run(self) -> None:
        pid_file = self.config.pid_file
        self._write_pid_file(pid_file)
        try:
            self._record_loop()
        finally:
            if pid_file.exists():
                pid_file.unlink()

    def _write_pid_file(self, pid_file: Path) -> None:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

    def _record_loop(self) -> None:
        import cv2

        cap = cv2.VideoCapture(self.config.device_index)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open camera device {self.config.device_index}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        cap.set(cv2.CAP_PROP_FPS, self.config.fps)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_path = self._next_video_path()
        writer = cv2.VideoWriter(str(video_path), fourcc, float(self.config.fps), (self.config.width, self.config.height))
        writer.set(cv2.VIDEOWRITER_PROP_BITRATE, float(self.config.bitrate))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError(f"Could not create video writer at {video_path}")

        last_cleanup = time.monotonic()
        previous_gray: Optional[object] = None
        motion_active = False

        def _handle_signal(signum, frame):
            self.stop_event.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        while not self.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            should_write = True
            if self.config.motion_detection:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                if previous_gray is None:
                    previous_gray = gray
                    continue
                frame_delta = cv2.absdiff(previous_gray, gray)
                _, thresh = cv2.threshold(frame_delta, self.config.motion_threshold, 255, cv2.THRESH_BINARY)
                motion_ratio = cv2.countNonZero(thresh) / (self.config.width * self.config.height)
                motion_detected = motion_ratio >= self.config.motion_pixel_ratio
                previous_gray = gray
                should_write = motion_detected
                if motion_detected and not motion_active:
                    motion_active = True
                    self._notify_motion(motion_ratio)
                elif not motion_detected and motion_active:
                    motion_active = False

            if should_write:
                writer.write(frame)

            now = time.monotonic()
            if now - last_cleanup > 300:
                self._cleanup_old_files()
                last_cleanup = now

        cap.release()
        writer.release()

    def _next_video_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"recording-{timestamp}.mp4"
        return self.config.output_dir / filename

    def _cleanup_old_files(self) -> None:
        cutoff = datetime.now() - timedelta(days=self.config.retention_days)
        for file in self.config.output_dir.glob("recording-*.mp4"):
            try:
                mtime = datetime.fromtimestamp(file.stat().st_mtime)
                if mtime < cutoff:
                    file.unlink()
            except OSError:
                continue

    def _notify_motion(self, motion_ratio: float) -> None:
        if not self.config.notify_url:
            return
        payload = {
            "event": "motion",
            "ratio": motion_ratio,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "output_directory": str(self.config.output_dir),
        }
        import requests

        try:
            requests.post(
                self.config.notify_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
        except requests.RequestException:
            # Notifications are best-effort; errors are ignored intentionally.
            pass


def start_background(config: RecorderConfig, extra_args: list[str]) -> None:
    if config.pid_file.exists():
        existing_pid = int(config.pid_file.read_text())
        if _pid_running(existing_pid):
            raise SystemExit(f"Recorder already running with PID {existing_pid}")

    args = [
        sys.executable,
        "-m",
        "maccam",
        "run",
        "--pid-file",
        str(config.pid_file),
    ]
    args.extend(extra_args)
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Started background recording with PID file {config.pid_file}")


def stop_background(config: RecorderConfig) -> None:
    if not config.pid_file.exists():
        raise SystemExit("No PID file found; is the recorder running?")
    pid = int(config.pid_file.read_text())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    config.pid_file.unlink()
    print("Stopped recorder")


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
