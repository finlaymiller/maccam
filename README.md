# MacCam

A small command-line recorder for macOS laptops that uses the built-in webcam to capture low-resolution video. It supports background execution with PID tracking, motion-triggered recording, webhook notifications, and automatic cleanup of recordings older than a week.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Usage

Run the recorder in the foreground:

```bash
maccam run --motion --notify-url https://ntfy.sh/your-topic
```

Start and stop a background session with PID tracking:

```bash
maccam start --output-dir ~/maccam_recordings --retention-days 7 --motion
maccam stop
```

Common options:

- `--device`: Camera index (default: 0)
- `--width`/`--height`: Resolution (default: 640x480)
- `--fps`: Frames per second (default: 15)
- `--bitrate`: Target bitrate in bits/s (default: 500000)
- `--output-dir`: Directory where recordings are saved
- `--retention-days`: How many days of recordings to keep (default: 7)
- `--motion`: Enable motion-triggered recording via frame differencing
- `--motion-threshold`: Pixel intensity delta that counts as motion (default: 25)
- `--motion-ratio`: Fraction of changed pixels needed to trigger motion (default: 0.01)
- `--notify-url`: Webhook endpoint (Pushcut/ntfy/etc.) invoked on motion events

Recordings are written to timestamped files in the output directory. When motion detection is enabled, frames are only written while motion is detected. A housekeeping pass runs every five minutes to delete recordings older than the configured retention period (default one week).

## Running continuously on power

### systemd (Linux)
Create a user service at `~/.config/systemd/user/maccam.service`:

```ini
[Unit]
Description=MacCam recorder
After=network-online.target

[Service]
ExecStart=%h/.venv/bin/python -m maccam run --motion --output-dir %h/maccam_recordings
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now maccam.service
```

### launchd (macOS)
Create `~/Library/LaunchAgents/com.example.maccam.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.example.maccam</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>maccam</string>
        <string>run</string>
        <string>--motion</string>
        <string>--output-dir</string>
        <string>~/maccam_recordings</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>~/Library/Logs/maccam.log</string>
    <key>StandardErrorPath</key><string>~/Library/Logs/maccam.log</string>
</dict>
</plist>
```

Load the agent:

```bash
launchctl load ~/Library/LaunchAgents/com.example.maccam.plist
launchctl start com.example.maccam
```

### Simple loop script
For minimal setups, you can use a restart loop:

```bash
#!/usr/bin/env bash
while true; do
  maccam run --motion --output-dir ~/maccam_recordings
  echo "Recorder exited; restarting in 5 seconds" >&2
  sleep 5
done
```

Run the script with `nohup` or inside a tmux session to keep it active while powered.
