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

from rich.console import Console

from .config import RecorderConfig


class RecorderService:
    _VIDEO_WRITER_OPTIONS = (
        (".mp4", "mp4v"),
        (".mp4", "avc1"),
        (".mov", "avc1"),
        (".avi", "MJPG"),
    )

    def __init__(self, config: RecorderConfig, console: Console | None = None) -> None:
        self.config = config
        self.console = console
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
        self._log(
            f"Camera ready on device {self.config.device_index} at "
            f"{self.config.width}x{self.config.height}@{self.config.fps}fps"
        )

        writer = None
        video_path: Optional[Path] = None
        previous_gray: Optional[object] = None
        motion_active = False
        recording_active = False
        last_motion_seen: Optional[float] = None
        notifications_blocked = False

        def _handle_signal(signum, frame):
            self._log(f"Signal {signum} received; stopping recorder")
            self.stop_event.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        while not self.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

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
                if motion_detected:
                    last_motion_seen = time.monotonic()
                    if not recording_active:
                        writer, video_path = self._create_video_writer(cv2)
                        recording_active = True
                        self._log(
                            f"Motion detected (ratio={motion_ratio:.4f}); recording started with post-roll of {self.config.motion_post_seconds}s"
                        )
                        if not notifications_blocked:
                            self._notify_motion(motion_ratio)
                            notifications_blocked = True
                    motion_active = True
                else:
                    motion_active = False
            else:
                motion_detected = True
                if not recording_active:
                    writer, video_path = self._create_video_writer(cv2)
                    recording_active = True

            if recording_active and writer is not None:
                writer.write(frame)

            if (
                recording_active
                and self.config.motion_detection
                and not motion_active
                and last_motion_seen is not None
                and (time.monotonic() - last_motion_seen) >= self.config.motion_post_seconds
            ):
                writer.release()
                if video_path is not None:
                    success, error = self._upload_to_google_drive(video_path)
                    self._notify_upload(success, video_path, error)
                writer = None
                video_path = None
                recording_active = False
                notifications_blocked = False

        cap.release()
        if writer is not None:
            writer.release()
        self._log("Recorder stopped")

    def _create_video_writer(self, cv2):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        attempted: list[str] = []
        frame_size = (self.config.width, self.config.height)
        for extension, codec in self._VIDEO_WRITER_OPTIONS:
            video_path = self._next_video_path(timestamp=timestamp, extension=extension)
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(
                str(video_path),
                fourcc,
                float(self.config.fps),
                frame_size,
            )
            if writer.isOpened():
                bitrate_prop = getattr(cv2, "VIDEOWRITER_PROP_BITRATE", None)
                if bitrate_prop is not None:
                    writer.set(bitrate_prop, float(self.config.bitrate))
                self._log(f"Recording to {video_path} using codec {codec}")
                return writer, video_path
            writer.release()
            attempted.append(f"{codec}{extension}")
        raise RuntimeError(
            "Could not create video writer in "
            f"{self.config.output_dir}; tried codecs: "
            + ", ".join(attempted)
        )

    def _next_video_path(self, *, timestamp: Optional[str] = None, extension: str = ".mp4") -> Path:
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"recording-{timestamp}{extension}"
        return self.config.output_dir / filename

    def _cleanup_old_files(self) -> None:
        cutoff = datetime.now() - timedelta(days=self.config.retention_days)
        extensions = {option[0] for option in self._VIDEO_WRITER_OPTIONS}
        for extension in extensions:
            for file in self.config.output_dir.glob(f"recording-*{extension}"):
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

        self._log(
            f"Sending motion notification to {self.config.notify_url} (ratio={motion_ratio:.4f})"
        )
        try:
            requests.post(
                self.config.notify_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            self._log("Motion notification delivered")
        except requests.RequestException as exc:
            self._log(f"Motion notification failed: {exc}")
            # Notifications are best-effort; errors are ignored intentionally.
            pass

    def _upload_to_google_drive(self, video_path: Path) -> tuple[bool, Optional[str]]:
        token = self.config.google_drive_access_token
        if not token:
            self._log("Google Drive upload skipped: no access token configured")
            return False, "No Google Drive access token configured"

        import requests

        metadata = {"name": video_path.name}
        if self.config.google_drive_folder_id:
            metadata["parents"] = [self.config.google_drive_folder_id]

        with video_path.open("rb") as fh:
            files = {
                "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
                "file": (video_path.name, fh, "video/mp4"),
            }
            headers = {"Authorization": f"Bearer {token}"}
            self._log(f"Uploading {video_path} to Google Drive")
            try:
                response = requests.post(
                    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                    headers=headers,
                    files=files,
                    timeout=60,
                )
                if response.status_code in (200, 201):
                    self._log(f"Upload succeeded: {video_path}")
                    return True, None
                self._log(f"Upload failed with status {response.status_code}: {response.text}")
                return False, f"HTTP {response.status_code}: {response.text}"
            except requests.RequestException as exc:
                self._log(f"Upload failed: {exc}")
                return False, str(exc)

    def _notify_upload(self, success: bool, video_path: Path, error: Optional[str]) -> None:
        if not self.config.notify_url:
            return

        payload = {
            "event": "upload_success" if success else "upload_failure",
            "file": video_path.name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "output_directory": str(self.config.output_dir),
        }
        if error:
            payload["error"] = error

        import requests

        status = "succeeded" if success else "failed"
        self._log(
            f"Sending upload {status} notification to {self.config.notify_url} for {video_path.name}"
        )
        try:
            requests.post(
                self.config.notify_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            self._log("Upload notification delivered")
        except requests.RequestException as exc:
            self._log(f"Upload notification failed: {exc}")
            pass

    def _log(self, message: str) -> None:
        if self.console is not None:
            self.console.log(message)
        else:
            print(message)


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
