"""Real wall-clock radio soak; keep the resulting report with device evidence."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--server", default="http://127.0.0.1:8080")
parser.add_argument("--station", required=True)
parser.add_argument("--hours", type=float, default=24)
parser.add_argument("--output", type=Path, default=Path("state/soak-report.json"))
args = parser.parse_args()
if not 0 < args.hours <= 168:
    parser.error("hours must be in (0, 168]")
headers = (
    {"Authorization": "Bearer " + os.environ["CAPSULE_TOKEN"]}
    if os.environ.get("CAPSULE_TOKEN")
    else {}
)
with httpx.Client(timeout=15, headers=headers) as client:
    initial = client.get(args.server + "/api/v1/radio/status")
    initial.raise_for_status()
    if initial.json()["simulation"]:
        parser.error("Real soak requires CAPSULE_MODE=host; simulation is a separate test")
    start = client.post(args.server + "/api/v1/radio/play", json={"station": args.station})
    start.raise_for_status()
    started = time.monotonic()
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "requested_hours": args.hours,
        "hardware_verified": False,
        "samples": [],
        "finished": False,
    }
    try:
        while time.monotonic() - started < args.hours * 3600:
            try:
                response = client.get(args.server + "/api/v1/radio/status")
                response.raise_for_status()
                status = response.json()
                sample = {key: status[key] for key in ["state", "reconnects", "volume", "error"]}
            except (httpx.HTTPError, ValueError):
                sample = {"state": "SERVER_UNREACHABLE"}
            report["samples"].append({"at": datetime.now(UTC).isoformat(), **sample})
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            time.sleep(min(10, max(0, args.hours * 3600 - (time.monotonic() - started))))
        report["finished"] = True
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["ended_at"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(args.output)
