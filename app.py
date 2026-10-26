"""smart-ui — web UI and ntfy alerts for MegaRAID / storcli disk health."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, send_from_directory

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env", override=False)

app = Flask(__name__, template_folder="templates", static_folder="static")

# --- Config ---
DB = Path(os.environ.get("SMART_UI_DB", str(BASE_DIR / "events.db")))
STORCLI = os.environ.get(
    "STORCLI_PATH",
    "/opt/MegaRAID/storcli/storcli64",
).strip()
CONTROLLER = os.environ.get("STORCLI_CONTROLLER", "0").strip() or "0"
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "7001"))
SITE_TITLE = os.environ.get("SITE_TITLE", "Disk Monitor")
DEFAULT_LANG = os.environ.get("DEFAULT_LANG", "en").lower()
if DEFAULT_LANG not in ("en", "fr"):
    DEFAULT_LANG = "en"
NOTIFY_LANG = os.environ.get("NOTIFY_LANG", DEFAULT_LANG).lower()
if NOTIFY_LANG not in ("en", "fr"):
    NOTIFY_LANG = DEFAULT_LANG
DEFAULT_THEME = os.environ.get("DEFAULT_THEME", "dark").lower()
if DEFAULT_THEME not in ("dark", "light"):
    DEFAULT_THEME = "dark"
try:
    DEFAULT_REFRESH_SEC = int(os.environ.get("DEFAULT_REFRESH_SEC", "30"))
except ValueError:
    DEFAULT_REFRESH_SEC = 30
if DEFAULT_REFRESH_SEC not in (10, 30, 60, 120):
    DEFAULT_REFRESH_SEC = 30
try:
    POLL_SEC = int(os.environ.get("POLL_SEC", "60"))
except ValueError:
    POLL_SEC = 60
POLL_SEC = max(15, POLL_SEC)

NTFY_URL = os.environ.get("NTFY_URL", "").strip()
NTFY_USER = os.environ.get("NTFY_USER", "")
NTFY_PASS = os.environ.get("NTFY_PASS", "")
NTFY_TITLE = os.environ.get("NTFY_TITLE", "Disks")

# Bad VD / PD states (storcli abbreviations)
VD_BAD = {"Dgrd", "Pdgd", "OfLn", "Offln", "Offline", "Failed"}
PD_BAD = {"Failed", "Offln", "Offline", "UBad", "Missing", "Msng"}

MSG = {
    "en": {
        "started": "smart-ui started — disk monitoring active",
        "vd_bad": "Virtual drive {dgvd} ({vtype}) is {state}",
        "vd_ok": "Virtual drive {dgvd} recovered — {state}",
        "pd_bad": "Physical drive slot {slot} ({model} / {sn}) is {state}",
        "pd_ok": "Physical drive slot {slot} recovered — {state}",
        "pd_predictive": "Predictive failure on slot {slot} ({sn}) — count {count}",
        "pd_media": "Media errors on slot {slot} ({sn}) — {count}",
        "pd_smart": "SMART alert on slot {slot} ({sn})",
        "ctrl_degraded": "Controller array status: {status}",
        "ctrl_ok": "Controller arrays Optimal again",
        "test": "Test notification — {ts}",
    },
    "fr": {
        "started": "smart-ui démarré — surveillance disques active",
        "vd_bad": "Volume virtuel {dgvd} ({vtype}) en état {state}",
        "vd_ok": "Volume virtuel {dgvd} rétabli — {state}",
        "pd_bad": "Disque slot {slot} ({model} / {sn}) en état {state}",
        "pd_ok": "Disque slot {slot} rétabli — {state}",
        "pd_predictive": "Échec prédictif slot {slot} ({sn}) — compteur {count}",
        "pd_media": "Erreurs média slot {slot} ({sn}) — {count}",
        "pd_smart": "Alerte SMART slot {slot} ({sn})",
        "ctrl_degraded": "État contrôleur : {status}",
        "ctrl_ok": "Contrôleur Optimal à nouveau",
        "test": "Test notification — {ts}",
    },
}


def t(key: str, **kwargs) -> str:
    lang = NOTIFY_LANG if NOTIFY_LANG in MSG else "en"
    template = MSG[lang].get(key) or MSG["en"].get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def notify(msg: str, priority: str = "high", tags: str = "") -> bool:
    if not NTFY_URL:
        print(f"[NOTIFY SKIP] NTFY_URL not set — {msg}")
        return False
    try:
        headers = {"Title": NTFY_TITLE, "Priority": priority, "Tags": tags}
        auth = (NTFY_USER, NTFY_PASS) if NTFY_USER else None
        r = requests.post(
            NTFY_URL,
            data=msg.encode("utf-8"),
            headers=headers,
            auth=auth,
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[NOTIFY ERROR] {e}")
        return False


def init_db() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                message TEXT,
                event_key TEXT,
                event_params TEXT
            )"""
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        if "event_key" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN event_key TEXT")
        if "event_params" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN event_params TEXT")


def log_event(key: str, **params) -> str:
    msg = t(key, **params)
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO events (ts, message, event_key, event_params) VALUES (?, ?, ?, ?)",
            (
                datetime.now().strftime("%d/%m %H:%M:%S"),
                msg,
                key,
                json.dumps(params, ensure_ascii=False),
            ),
        )
    print(f"[EVENT] {key} {params} → {msg}")
    return msg


def run_storcli(args: str) -> str:
    cmd = f"{STORCLI} {args}"
    try:
        return subprocess.check_output(
            cmd,
            shell=True,
            stderr=subprocess.DEVNULL,
            timeout=120,
        ).decode(errors="replace")
    except Exception as e:
        print(f"[STORCLI ERROR] {e}")
        return ""


def get_controller_info() -> dict:
    out = run_storcli(f"/c{CONTROLLER} show")
    info: dict = {}
    if not out:
        return {"_error": f"storcli failed or not found: {STORCLI}", "status": "Unknown"}

    for line in out.splitlines():
        for key, label in [
            ("Product Name", "model"),
            ("Serial Number", "sn"),
            ("FW Package Build", "fw"),
            ("Driver Version", "driver"),
        ]:
            if line.strip().startswith(key) and "=" in line:
                info[label] = line.split("=", 1)[1].strip()

    degraded = False
    for line in out.splitlines():
        m = re.match(r"^\s*\d+\s+-\s+-\s+-\s+-\s+RAID\d+\s+(\S+)", line)
        if m and m.group(1) in VD_BAD:
            degraded = True
            break

    info["status"] = "Degraded" if degraded else "Optimal"
    return info


def get_virtual_drives() -> list[dict]:
    out = run_storcli(f"/c{CONTROLLER} show")
    drives: list[dict] = []
    in_table = False
    for line in out.splitlines():
        if re.match(r"^-{10,}", line.strip()):
            in_table = not in_table
            continue
        if in_table and re.match(r"^\d+/\d+\s+RAID", line.strip()):
            parts = line.split()
            if len(parts) < 3:
                continue
            m = re.search(r"(\d+\.\d+\s+(?:TB|GB))", line)
            drives.append(
                {
                    "dgvd": parts[0],
                    "type": parts[1],
                    "state": parts[2],
                    "size": m.group(1) if m else "?",
                }
            )
    return drives


def get_physical_drives() -> list[dict]:
    out = run_storcli(f"/c{CONTROLLER}/eall/sall show all")
    drives: list[dict] = []
    blocks = re.split(r"Drive /c\d+/e\d+/s(\d+) :", out)
    i = 1
    while i < len(blocks) - 1:
        slot = int(blocks[i])
        content = blocks[i + 1]
        i += 2
        d: dict = {"slot": slot}

        m = re.search(
            r"\d+:\d+\s+(\d+)\s+(\w+)\s+(\S+)\s+(\d+\.\d+\s+(?:TB|GB))\s+(\w+)\s+(\w+)",
            content,
        )
        if m:
            d["did"] = m.group(1)
            d["state"] = m.group(2)
            d["dg"] = m.group(3)
            d["size"] = m.group(4)
            d["intf"] = m.group(5)
            d["med"] = m.group(6)

        for key, label in [
            ("Media Error Count", "media_errors"),
            ("Other Error Count", "other_errors"),
            ("Predictive Failure Count", "predictive"),
            ("S.M.A.R.T alert flagged by drive", "smart_alert"),
        ]:
            m = re.search(rf"{re.escape(key)}\s*=\s*(.+)", content)
            d[label] = m.group(1).strip() if m else "?"

        m = re.search(r"Drive Temperature\s*=\s*(\d+)C", content)
        d["temp"] = int(m.group(1)) if m else None

        m = re.search(r"Model Number\s*=\s*(.+)", content)
        d["model"] = m.group(1).strip() if m else "?"

        m = re.search(r"SN\s*=\s*(.+)", content)
        d["sn"] = m.group(1).strip() if m else "?"

        m = re.search(r"Firmware Revision\s*=\s*(.+)", content)
        d["fw"] = m.group(1).strip() if m else "?"

        m = re.search(r"Manufacturer Id\s*=\s*(.+)", content)
        d["vendor"] = m.group(1).strip() if m else "?"

        drives.append(d)

    return drives


def collect_status() -> dict:
    controller = get_controller_info()
    if controller.get("_error"):
        return {
            "controller": controller,
            "vdrives": [],
            "pdrives": [],
            "_error": controller["_error"],
        }
    return {
        "controller": controller,
        "vdrives": get_virtual_drives(),
        "pdrives": get_physical_drives(),
    }


# --- Monitor state ---
_prev: dict = {
    "vd": {},  # dgvd -> state
    "pd": {},  # slot -> state
    "pred": {},  # slot -> count str
    "media": {},  # slot -> count str
    "smart": {},  # slot -> alert
    "ctrl": None,
    "primed": False,
}


def _intish(val) -> int:
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return 0


def monitor() -> None:
    while True:
        try:
            data = collect_status()
            if data.get("_error"):
                time.sleep(POLL_SEC)
                continue

            ctrl_status = data["controller"].get("status", "Unknown")
            vd_map = {v["dgvd"]: v for v in data["vdrives"]}
            pd_map = {str(p["slot"]): p for p in data["pdrives"]}

            if not _prev["primed"]:
                _prev["vd"] = {k: v["state"] for k, v in vd_map.items()}
                _prev["pd"] = {k: p.get("state", "?") for k, p in pd_map.items()}
                _prev["pred"] = {k: p.get("predictive", "0") for k, p in pd_map.items()}
                _prev["media"] = {k: p.get("media_errors", "0") for k, p in pd_map.items()}
                _prev["smart"] = {k: p.get("smart_alert", "No") for k, p in pd_map.items()}
                _prev["ctrl"] = ctrl_status
                _prev["primed"] = True
                # Alert immediately if already unhealthy at startup
                for dgvd, v in vd_map.items():
                    if v["state"] in VD_BAD:
                        msg = log_event(
                            "vd_bad",
                            dgvd=dgvd,
                            vtype=v.get("type", "?"),
                            state=v["state"],
                        )
                        notify(msg, priority="high", tags="warning,floppy_disk")
                for slot, p in pd_map.items():
                    if p.get("state") in PD_BAD:
                        msg = log_event(
                            "pd_bad",
                            slot=slot,
                            model=p.get("model", "?"),
                            sn=p.get("sn", "?"),
                            state=p.get("state", "?"),
                        )
                        notify(msg, priority="urgent", tags="rotating_light,hdd")
                if ctrl_status != "Optimal":
                    msg = log_event("ctrl_degraded", status=ctrl_status)
                    notify(msg, priority="high", tags="warning")
                time.sleep(POLL_SEC)
                continue

            # Controller
            if ctrl_status != _prev["ctrl"]:
                if ctrl_status != "Optimal":
                    msg = log_event("ctrl_degraded", status=ctrl_status)
                    notify(msg, priority="high", tags="warning")
                elif _prev["ctrl"] and _prev["ctrl"] != "Optimal":
                    msg = log_event("ctrl_ok")
                    notify(msg, priority="default", tags="white_check_mark")
                _prev["ctrl"] = ctrl_status

            # Virtual drives
            for dgvd, v in vd_map.items():
                state = v["state"]
                prev = _prev["vd"].get(dgvd)
                if prev is None:
                    _prev["vd"][dgvd] = state
                    continue
                if state != prev:
                    if state in VD_BAD:
                        msg = log_event(
                            "vd_bad",
                            dgvd=dgvd,
                            vtype=v.get("type", "?"),
                            state=state,
                        )
                        notify(msg, priority="high", tags="warning,floppy_disk")
                    elif prev in VD_BAD:
                        msg = log_event("vd_ok", dgvd=dgvd, state=state)
                        notify(msg, priority="default", tags="white_check_mark")
                    _prev["vd"][dgvd] = state

            # Physical drives
            for slot, p in pd_map.items():
                state = p.get("state", "?")
                prev = _prev["pd"].get(slot)
                if prev is None:
                    _prev["pd"][slot] = state
                elif state != prev:
                    if state in PD_BAD:
                        msg = log_event(
                            "pd_bad",
                            slot=slot,
                            model=p.get("model", "?"),
                            sn=p.get("sn", "?"),
                            state=state,
                        )
                        notify(msg, priority="urgent", tags="rotating_light,hdd")
                    elif prev in PD_BAD:
                        msg = log_event("pd_ok", slot=slot, state=state)
                        notify(msg, priority="default", tags="white_check_mark")
                    _prev["pd"][slot] = state

                pred = p.get("predictive", "0")
                if pred != _prev["pred"].get(slot) and _intish(pred) > 0:
                    msg = log_event(
                        "pd_predictive",
                        slot=slot,
                        sn=p.get("sn", "?"),
                        count=pred,
                    )
                    notify(msg, priority="high", tags="warning")
                _prev["pred"][slot] = pred

                media = p.get("media_errors", "0")
                if media != _prev["media"].get(slot) and _intish(media) > 0:
                    msg = log_event(
                        "pd_media",
                        slot=slot,
                        sn=p.get("sn", "?"),
                        count=media,
                    )
                    notify(msg, priority="high", tags="warning")
                _prev["media"][slot] = media

                smart = p.get("smart_alert", "No")
                if smart != _prev["smart"].get(slot) and str(smart).lower() not in (
                    "no",
                    "n",
                    "0",
                    "?",
                    "",
                ):
                    msg = log_event("pd_smart", slot=slot, sn=p.get("sn", "?"))
                    notify(msg, priority="urgent", tags="rotating_light")
                _prev["smart"][slot] = smart

        except Exception as e:
            print(f"[MONITOR ERROR] {e}")

        time.sleep(POLL_SEC)


@app.route("/")
def index():
    return render_template(
        "index.html",
        site_title=SITE_TITLE,
        default_lang=DEFAULT_LANG,
        default_theme=DEFAULT_THEME,
        default_refresh_sec=DEFAULT_REFRESH_SEC,
    )


@app.route("/api/status")
def api_status():
    return jsonify(collect_status())


@app.route("/api/events")
def api_events():
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            "SELECT ts, message, event_key, event_params FROM events ORDER BY id DESC LIMIT 100"
        ).fetchall()
    out = []
    for ts, message, event_key, event_params in rows:
        params = {}
        if event_params:
            try:
                params = json.loads(event_params)
            except json.JSONDecodeError:
                params = {}
        out.append(
            {
                "ts": ts,
                "message": message,
                "key": event_key,
                "params": params,
            }
        )
    return jsonify(out)


@app.route("/api/test-notify")
def test_notify():
    ts = datetime.now().strftime("%d/%m %H:%M:%S")
    msg = log_event("test", ts=ts)
    ok = notify(msg, priority="default", tags="test_tube")
    return jsonify({"sent": ok, "message": msg})


@app.route("/api/health")
def api_health():
    data = collect_status()
    ok = not data.get("_error") and "status" in data.get("controller", {})
    return jsonify(
        {
            "ok": ok,
            "storcli": STORCLI,
            "controller": CONTROLLER,
            "ntfy_configured": bool(NTFY_URL),
            "error": data.get("_error"),
            "array_status": data.get("controller", {}).get("status"),
        }
    ), (200 if ok else 503)


@app.route("/api/config")
def api_config():
    return jsonify(
        {
            "site_title": SITE_TITLE,
            "default_lang": DEFAULT_LANG,
            "default_theme": DEFAULT_THEME,
            "default_refresh_sec": DEFAULT_REFRESH_SEC,
            "ntfy_configured": bool(NTFY_URL),
            "storcli": STORCLI,
        }
    )


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        app.static_folder, "favicon.svg", mimetype="image/svg+xml"
    )


def main() -> None:
    init_db()
    print(f"[smart-ui] storcli: {STORCLI} /c{CONTROLLER}")
    print(f"[smart-ui] Listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    notify(t("started"), tags="rocket")
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host=LISTEN_HOST, port=LISTEN_PORT)


if __name__ == "__main__":
    main()
