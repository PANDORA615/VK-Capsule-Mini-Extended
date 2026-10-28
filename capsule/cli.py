import hashlib
import json
import shutil
import struct
import time
from pathlib import Path

import typer
import uvicorn

from capsule.config import Settings
from capsule.storage import Store

app = typer.Typer(help="Капсула: приложение, диагностика и безопасное исследование")
firmware = typer.Typer(help="Только чтение локальных образов")
backup = typer.Typer(help="Копирование ранее экспортированных файлов; не читает NAND")
recovery = typer.Typer(help="Планирование; запись заблокирована")
app.add_typer(firmware, name="firmware")
app.add_typer(backup, name="backup")
app.add_typer(recovery, name="recovery")


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def digest(path: Path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def regular(path: Path):
    if not path.is_file() or path.is_symlink():
        raise typer.BadParameter("Нужен обычный локальный файл, не устройство и не symlink")


@app.command()
def serve():
    """Запустить меню в браузере. Режим выбирается через .env."""
    cfg = Settings()
    uvicorn.run(
        "capsule.api:create_app",
        factory=True,
        host=cfg.capsule_host,
        port=cfg.capsule_port,
        access_log=False,
        ws_max_size=1_300_000,
    )


@app.command()
def doctor():
    cfg = Settings()
    emit(
        {
            "mode": cfg.capsule_mode,
            "python": "3.12+",
            "arecord": bool(shutil.which("arecord")),
            "aplay": bool(shutil.which("aplay")),
            "piper": bool(shutil.which("piper")),
            "stt_model": bool(cfg.vosk_model_path),
            "google_key_configured": bool(cfg.google_api_key.get_secret_value()),
            "hardware_verification_required": True,
            "flash_write": "blocked",
        }
    )


@app.command()
def identify(
    compatible: Path = typer.Argument(..., help="Сохранённый /proc/device-tree/compatible"),
):
    regular(compatible)
    text = compatible.read_bytes().replace(b"\0", b" ").decode(errors="replace").lower()
    profile = (
        "amlogic_a113x"
        if "a113x" in text
        else "rockchip_rk3308b"
        if "rk3308b" in text
        else "unknown"
    )
    emit(
        {
            "profile": profile,
            "evidence": "provided_device_tree_only",
            "board_revision": "unknown",
            "hardware_verification_required": True,
            "flash_write": "blocked",
        }
    )


@app.command()
def discover():
    """Пассивно перечислить USB-дескрипторы; без scan сети, control transfer или UART TX."""
    try:
        import usb.core

        devices = [
            {
                "vid": f"{d.idVendor:04x}",
                "pid": f"{d.idProduct:04x}",
                "bus": d.bus,
                "address": d.address,
            }
            for d in usb.core.find(find_all=True)
        ]
        emit({"usb": devices, "identification": "No VK VID/PID assumptions"})
    except ImportError:
        raise typer.BadParameter("Установите пакет с extra [hardware]") from None


@app.command("uart-log")
def uart_log(
    port: str,
    output: Path,
    seconds: int = typer.Option(20, min=1, max=600),
    baud: int = typer.Option(115200, min=300),
):
    """Явно указанный порт; RX-only на уровне приложения. Подключайте только RX/GND."""
    import serial

    if output.exists():
        raise typer.BadParameter("Файл уже существует")
    connection = serial.Serial(port=None, baudrate=baud, timeout=0.2)
    connection.dtr = connection.rts = False
    connection.port = port
    connection.open()
    try:
        with output.open("xb") as handle:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                handle.write(connection.read(4096))
    finally:
        connection.close()


@firmware.command("inspect")
def inspect_image(path: Path):
    regular(path)
    with path.open("rb") as handle:
        magic = handle.read(8)
    kind = (
        "dtb"
        if magic[:4] == struct.pack(">I", 0xD00DFEED)
        else "gzip"
        if magic[:2] == b"\x1f\x8b"
        else "unknown"
    )
    emit(
        {
            "size": path.stat().st_size,
            "sha256": digest(path),
            "type": kind,
            "partitions": "unknown; no inferred offsets",
            "flash_write": "blocked",
        }
    )


@firmware.command("verify")
def verify_image(path: Path, sha256: str):
    regular(path)
    ok = digest(path) == sha256.lower()
    emit({"verified": ok})
    if not ok:
        raise typer.Exit(1)


@firmware.command("partitions")
def partitions(proc_mtd: Path):
    """Показать сохранённую карту /proc/mtd без вычисления смещений."""
    regular(proc_mtd)
    emit({"source": "owner_provided_proc_mtd", "text": proc_mtd.read_text(), "offsets": "unknown"})


@backup.command("plan")
def backup_plan(source: Path):
    regular(source)
    emit(
        {
            "operation": "copy_exported_regular_file",
            "size": source.stat().st_size,
            "sha256": digest(source),
            "nand_access": False,
            "warning": "Экспорт должен включать нужные разделы/OOB/ECC; целостность не доказывает восстановимость",
        }
    )


@backup.command("create")
def backup_create(source: Path, destination: Path):
    regular(source)
    manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    if destination.exists() or manifest.exists():
        raise typer.BadParameter("Файл назначения или manifest уже существует")
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    destination.chmod(0o600)
    source_hash = digest(source)
    if source_hash != digest(destination):
        raise typer.BadParameter("Копия не совпадает с исходником")
    Store(manifest).write(
        {"file": destination.name, "size": destination.stat().st_size, "sha256": source_hash}
    )
    emit({"verified": True, "manifest": str(manifest), "recovery_verified": False})


@backup.command("verify")
def backup_verify(manifest: Path):
    data = Store(manifest).read()
    name = data.get("file", "")
    if not name or Path(name).name != name:
        raise typer.BadParameter("Invalid manifest filename")
    path = manifest.parent / name
    regular(path)
    ok = path.stat().st_size == data.get("size") and digest(path) == data.get("sha256")
    emit({"verified": ok, "recovery_verified": False})
    if not ok:
        raise typer.Exit(1)


@recovery.command("plan")
def recovery_plan(profile: str = "unknown"):
    emit(
        {
            "profile": profile,
            "dry_run": True,
            "write_allowed": False,
            "requirements": [
                "точная ревизия платы",
                "полный verified backup",
                "проверенный recovery интерфейс",
                "проверка восстановления на данной плате",
            ],
            "status": "hardware_verification_required",
        }
    )


@recovery.command("validate")
def recovery_validate(profile: str = "unknown"):
    recovery_plan(profile)
    raise typer.Exit(2)


@app.command("models")
def models():
    """Проверить наличие настроенных моделей в API без генерации; не доказывает доступность Live."""
    from google import genai

    cfg = Settings()
    if not cfg.google_api_key.get_secret_value():
        raise typer.BadParameter("GOOGLE_API_KEY не настроен")
    try:
        with genai.Client(api_key=cfg.google_api_key.get_secret_value()) as client:
            available = {m.name.removeprefix("models/") for m in client.models.list() if m.name}
        emit(
            {
                m: {"listed": m in available, "invocation_verified": False}
                for m in (cfg.gemini_primary_model, cfg.gemini_fallback_model)
            }
        )
    except Exception:
        raise typer.BadParameter(
            "API недоступен; проверьте ключ, права и сеть. Секрет не выводится."
        ) from None
