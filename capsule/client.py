"""Explicit push-to-talk Linux ALSA client; no always-on microphone or claimed AEC."""

import argparse
import base64
import os
import subprocess

import httpx


def main():
    parser = argparse.ArgumentParser(description="Запись одной фразы через ALSA и ответ сервера")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--device", default="default")
    parser.add_argument("--seconds", type=int, default=6, choices=range(1, 31))
    args = parser.parse_args()
    token = os.environ.get("CAPSULE_TOKEN", "")
    headers = {"Authorization": "Bearer " + token} if token else {}
    with httpx.Client(timeout=90, headers=headers) as client:
        device = client.get(args.server + "/api/v1/device")
        device.raise_for_status()
        if device.json()["preferences"]["microphone_muted"]:
            parser.error("Микрофон выключен в приложении")
        input("Нажмите Enter и произнесите одну команду: ")
        recording = subprocess.run(
            [
                "arecord",
                "-q",
                "-D",
                args.device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                "-d",
                str(args.seconds),
            ],
            check=True,
            capture_output=True,
            timeout=args.seconds + 5,
        )
        reply = client.post(
            args.server + "/api/v1/voice/transcribe",
            content=recording.stdout,
            headers={"Content-Type": "application/octet-stream"},
        )
        reply.raise_for_status()
        value = reply.json()
        print(value["text"])
        if value.get("audio"):
            subprocess.run(
                ["aplay", "-q"], input=base64.b64decode(value["audio"]), check=True, timeout=130
            )
