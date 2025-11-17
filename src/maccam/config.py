import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RecorderConfig:
    device_index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 15
    bitrate: int = 500_000
    output_dir: Path = field(default_factory=lambda: Path.home() / "maccam_recordings")
    retention_days: int = 7
    motion_detection: bool = False
    motion_threshold: int = 25
    motion_pixel_ratio: float = 0.01
    notify_url: Optional[str] = None
    pid_file: Path = field(default_factory=lambda: Path.home() / ".maccam" / "maccam.pid")
    google_drive_access_token: Optional[str] = field(
        default_factory=lambda: os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    )
    google_drive_folder_id: Optional[str] = None
    motion_post_seconds: int = 3

    def ensure_directories(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
