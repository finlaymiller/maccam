import argparse
from pathlib import Path
from typing import Iterable

from rich.console import Console

from .config import RecorderConfig
from .recorder import RecorderService, start_background, stop_background


DEFAULT_CONFIG = RecorderConfig()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MacCam video recorder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--device", type=int, default=0, help="Camera device index (default: 0)")
        p.add_argument("--width", type=int, default=640, help="Frame width (default: 640)")
        p.add_argument("--height", type=int, default=480, help="Frame height (default: 480)")
        p.add_argument("--fps", type=int, default=15, help="Frames per second (default: 15)")
        p.add_argument("--bitrate", type=int, default=500_000, help="Target bitrate in bits/s (default: 500000)")
        p.add_argument("--output-dir", type=Path, default=DEFAULT_CONFIG.output_dir, help="Directory for recordings")
        p.add_argument("--retention-days", type=int, default=DEFAULT_CONFIG.retention_days, help="Days to retain recordings (default: 7)")
        p.add_argument("--motion", action="store_true", help="Enable motion-triggered recording")
        p.add_argument("--motion-threshold", type=int, default=25, help="Pixel intensity threshold for motion detection")
        p.add_argument("--motion-ratio", type=float, default=0.01, help="Fraction of pixels that must change to trigger motion")
        p.add_argument("--notify-url", type=str, help="Webhook URL for motion notifications")

    run_parser = subparsers.add_parser("run", help="Run recorder in the foreground")
    add_common_options(run_parser)
    run_parser.add_argument("--pid-file", type=Path, default=DEFAULT_CONFIG.pid_file, help="PID file location")

    start_parser = subparsers.add_parser("start", help="Start recorder in background")
    add_common_options(start_parser)
    start_parser.add_argument("--pid-file", type=Path, default=DEFAULT_CONFIG.pid_file, help="PID file location")

    stop_parser = subparsers.add_parser("stop", help="Stop background recorder")
    stop_parser.add_argument("--pid-file", type=Path, default=DEFAULT_CONFIG.pid_file, help="PID file location")

    return parser


def config_from_args(args: argparse.Namespace) -> RecorderConfig:
    return RecorderConfig(
        device_index=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        bitrate=args.bitrate,
        output_dir=args.output_dir if isinstance(args.output_dir, Path) else Path(args.output_dir),
        retention_days=args.retention_days,
        motion_detection=args.motion,
        motion_threshold=args.motion_threshold,
        motion_pixel_ratio=args.motion_ratio,
        notify_url=args.notify_url,
        pid_file=args.pid_file if isinstance(args.pid_file, Path) else Path(args.pid_file),
    )


def run_cli(argv: Iterable[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    if args.command == "run":
        console = Console()
        with console.status("Recording... press Ctrl+C to stop", spinner="dots"):
            RecorderService(config, console=console).run()
    elif args.command == "start":
        extra = _extra_args_from_namespace(args)
        start_background(config, extra)
    elif args.command == "stop":
        stop_background(config)
    else:
        parser.print_help()


def _extra_args_from_namespace(args: argparse.Namespace) -> list[str]:
    flags = []
    for flag in [
        ("--device", args.device),
        ("--width", args.width),
        ("--height", args.height),
        ("--fps", args.fps),
        ("--bitrate", args.bitrate),
        ("--output-dir", str(args.output_dir)),
        ("--retention-days", args.retention_days),
        ("--motion-threshold", args.motion_threshold),
        ("--motion-ratio", args.motion_ratio),
    ]:
        flags.extend([flag[0], str(flag[1])])
    if args.motion:
        flags.append("--motion")
    if args.notify_url:
        flags.extend(["--notify-url", args.notify_url])
    return flags
