# ClawBeam

> OpenClaw → WLED Real-Time Reactive Lamp Controller

A Python daemon that watches [OpenClaw](https://github.com/openclaw) live session
logs and drives a [WLED](https://kno.wled.ge/) RGB strip over WiFi so your desk lamp
reacts in real-time to what the AI agent is doing.

| Agent activity | Lamp effect |
|---|---|
| Idle | Soft blue breathing |
| User sends message | Quick white flash |
| Assistant thinking | Slow purple pulse |
| Tool call in flight | Cyan sweep animation |
| Tool succeeds | Green flash |
| Tool error | Red rapid blink |
| WLED unreachable | Magenta pulsating flash |
| High token usage | Amber warm pulse |

---

## Repository layout

```
clawbeam/
├── __init__.py
├── config.py            # YAML config loader + defaults
├── parser.py            # JSONL line → Event
├── state_machine.py     # Event → LampState with timers
├── session_watcher.py   # Finds + tails the active .jsonl
├── wled_client.py       # Async WLED JSON-API client
├── main.py              # Orchestrator + CLI entry point
├── simulator.py         # Fake event generator for testing
├── config.yaml          # Sample configuration
├── config_local.yaml    # Local test config (no OpenClaw needed)
├── clawbeam@.service     # systemd unit file
└── tests/
    ├── test_parser.py
    ├── test_session_watcher.py
    ├── test_state_machine.py
    └── test_wled_client.py
```

## Quick start

### 1. Install

```bash
# create and activate a virtualenv (recommended)
python -m venv .venv
source .venv/bin/activate   # on PowerShell: \.venv\Scripts\Activate.ps1

# from project root
pip install -e ".[dev]"
```

This installs the package in editable mode with test dependencies.

### 2. Configure

Copy and edit the sample config:

```bash
cp clawbeam/config.yaml ~/.config/clawbeam.yaml
# edit wled.host to your WLED lamp's IP
```

Or set the environment variable:

```bash
export CLAWBEAM_CONFIG=~/.config/clawbeam.yaml
```

### 3. Run

```bash
# Daemon mode (tails the live session forever)
clawbeam

# Or with explicit config
clawbeam -c /path/to/config.yaml

# One-shot (process existing lines then exit)
clawbeam --one-shot

# Verbose output
clawbeam --log-level DEBUG

# Run the simulator (no OpenClaw needed)
clawbeam-sim -c clawbeam/config_local.yaml --speed 1.5
```

### 4. Run as a systemd service (Linux)

```bash
sudo cp clawbeam/clawbeam@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now clawbeam@$USER
```

## Running tests

```bash
pytest clawbeam/tests/ -v
```

## How it works

```
┌─────────────────────┐
│  ~/.openclaw/        │
│  sessions/*.jsonl    │  ← OpenClaw appends lines here
└────────┬────────────┘
         │  tail -f style
         ▼
┌─────────────────────┐
│  session_watcher.py  │  watches dir, picks latest file, yields lines
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  parser.py           │  JSON line → Event(type, severity, tokens…)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  state_machine.py    │  Event → LampState (with debounce, min-duration,
│                      │  idle timeout)
└────────┬────────────┘
         │  on_transition callback
         ▼
┌─────────────────────┐
│  wled_client.py      │  POST /json/state  → WLED lamp
│                      │  (rate-limited, retries, health check)
└─────────────────────┘
```

## WLED API payloads

Each state maps to a JSON payload posted to `POST http://<WLED_IP>/json/state`.
Example for the **IDLE** state (soft blue breathing):

```json
{
  "on": true,
  "bri": 80,
  "seg": [{
    "col": [[0, 60, 180]],
    "fx": 2,
    "sx": 80,
    "ix": 128
  }]
}
```

To use a saved WLED preset instead of raw segment data, set `ps`:

```yaml
state_effects:
  USER_INPUT:
    ps: 5
```

See the [WLED JSON API docs](https://kno.wled.ge/interfaces/json-api/)
for the full list of fields and effect IDs.

## Configuration reference

| Key | Default | Description |
|---|---|---|
| `wled.host` | `192.168.1.100` | WLED device IP / hostname |
| `wled.port` | `80` | HTTP port |
| `wled.max_requests_per_sec` | `5.0` | Rate limit |
| `wled.health_check_interval` | `30` | Seconds between pings |
| `watcher.sessions_dir` | `~/.openclaw/agents/main/sessions` | Where OpenClaw writes logs |
| `watcher.poll_interval` | `0.25` | Tail poll (seconds) |
| `state_machine.min_state_duration` | `0.5` | Anti-flicker guard (seconds) |
| `state_machine.idle_timeout` | `30.0` | Revert to IDLE after silence |
| `state_machine.debounce_window` | `0.5` | Suppress duplicate transitions |
| `log_level` | `INFO` | Python log level |
| `daemon` | `true` | `false` = one-shot mode |

## License

MIT
