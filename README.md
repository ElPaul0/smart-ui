# smart-ui

Lightweight web UI and notifier for **MegaRAID / LSI** controllers via [storcli](https://docs.broadcom.com/).

Polls `storcli`, shows controller / VD / PD health in the browser, stores alerts in SQLite, and can push notifications to [ntfy](https://ntfy.sh/) on a dedicated topic.

Sibling project to [nut-ui](https://github.com/ElPaul0/nut-ui) (same themes, i18n, and ntfy patterns).

## Features

- Live MegaRAID status (controller, virtual drives, physical drives)
- Temperature, media / predictive / other error counters
- Event history (SQLite)
- Optional **ntfy** alerts (failed PD, offline / degraded VD, SMART / predictive / media errors, recovery)
- **Dark / light** themes (same teal/gray palette as nut-ui)
- **English / French** UI (choice saved in the browser)
- Configurable refresh interval + background poll for alerts
- Config via **`.env`** / `/etc/smart-ui/smart-ui.env` so settings survive updates

## Prerequisites

1. **storcli** installed and working (`storcli64 /c0 show`).
2. Python **3.10+**.
3. Root (or equivalent) access to talk to the MegaRAID driver — typically run on the hypervisor host.

## Quick start — host

```bash
curl -fsSL https://raw.githubusercontent.com/ElPaul0/smart-ui/main/scripts/install-host.sh | sudo bash
sudo nano /etc/smart-ui/smart-ui.env    # set NTFY_URL, DEFAULT_LANG, …
sudo systemctl restart smart-ui
```

Open `http://<host>:7001/`.

**What stays persistent across updates**

| Path | Purpose |
|------|---------|
| `/etc/smart-ui/smart-ui.env` | Your configuration (not overwritten on update) |
| `/var/lib/smart-ui/events.db` | Event history |
| `/opt/smart-ui` | App code (updated with `git pull` via the install script) |

Update:

```bash
sudo bash /opt/smart-ui/scripts/install-host.sh
```

### Manual host install

```bash
git clone https://github.com/ElPaul0/smart-ui.git /opt/smart-ui
cd /opt/smart-ui
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo mkdir -p /etc/smart-ui /var/lib/smart-ui
sudo cp .env.example /etc/smart-ui/smart-ui.env
sudo nano /etc/smart-ui/smart-ui.env
sudo cp deploy/smart-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smart-ui
```

## Configuration

Copy `.env.example` → `.env` or `/etc/smart-ui/smart-ui.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `STORCLI_PATH` | `/opt/MegaRAID/storcli/storcli64` | Path to storcli binary |
| `STORCLI_CONTROLLER` | `0` | Controller index (`/c0`) |
| `LISTEN_HOST` | `0.0.0.0` | Bind address |
| `LISTEN_PORT` | `7001` | HTTP port |
| `SITE_TITLE` | `Disk Monitor` | Page title |
| `DEFAULT_LANG` | `en` | Initial UI language (`en` / `fr`) |
| `DEFAULT_THEME` | `dark` | Initial theme (`dark` / `light`) |
| `DEFAULT_REFRESH_SEC` | `30` | UI refresh (`10` / `30` / `60` / `120`) |
| `POLL_SEC` | `60` | Background alert poll interval |
| `NOTIFY_LANG` | same as `DEFAULT_LANG` | Language for ntfy / logged events |
| `SMART_UI_DB` | `./events.db` | SQLite path |
| `NTFY_URL` | _(empty)_ | Full topic URL (use a **dedicated** channel, not the UPS one) |
| `NTFY_USER` / `NTFY_PASS` | _(empty)_ | Optional ntfy auth |
| `NTFY_TITLE` | `Disks` | Notification title |

Theme, language, and refresh interval chosen in the UI are stored in **browser `localStorage`**.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `GET /api/status` | Controller + VD + PD JSON |
| `GET /api/events` | Last 100 events |
| `GET /api/test-notify` | Send a test ntfy message |
| `GET /api/health` | Liveness + storcli reachability |
| `GET /api/config` | Public UI defaults (no secrets) |

## License

MIT
