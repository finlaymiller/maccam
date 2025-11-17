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
maccam run --motion --notify-url https://ntfy.sh/finlays_room
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
- `--retention-days`: How many days of recordings to keep (default: 7). Currently recordings are never deleted to preserve a complete archive.
- `--motion`: Enable motion-triggered recording via frame differencing
- `--motion-threshold`: Pixel intensity delta that counts as motion (default: 25)
- `--motion-ratio`: Fraction of changed pixels needed to trigger motion (default: 0.01)
- `--motion-post-seconds`: Seconds to keep recording after motion subsides (default: 3)
- `--notify-url`: Webhook endpoint (Pushcut/ntfy/etc.) invoked on motion events
- `--google-drive-token`: OAuth access token used for Drive uploads (can also be set via `GOOGLE_DRIVE_ACCESS_TOKEN` environment variable)
- `--google-drive-folder`: Optional Drive folder ID where videos should be uploaded

Recordings are written to timestamped files in the output directory. When motion detection is enabled, recording starts on motion and continues for a short post-roll (default three seconds) after motion stops. Each completed clip is uploaded to Google Drive when credentials are provided, and a new file is started after each upload attempt. Files are never removed from disk, and notifications are buffered so that motion alerts are followed by an upload result notification before another motion alert is sent.

### Getting a Google Drive access token

MacCam expects a short-lived OAuth access token with the `https://www.googleapis.com/auth/drive.file` scope:

1. Visit the [OAuth 2.0 Playground](https://developers.google.com/oauthplayground) and expand **Step 1**.
2. Under "Input your own scopes" enter `https://www.googleapis.com/auth/drive.file` and click **Authorize APIs**. Sign in and approve when prompted.
3. In **Step 2**, click **Exchange authorization code for tokens**. Copy the **Access token** value (ignore the refresh token; MacCam currently only accepts the access token).
4. Start MacCam with `--google-drive-token <copied token>` or set `GOOGLE_DRIVE_ACCESS_TOKEN=<copied token>` in the environment.

Access tokens typically expire within an hour; when uploads start failing with `401 Unauthorized`, repeat the steps above to fetch a new token.

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
