from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)
    capsule_mode: Literal["simulation", "host"] = "simulation"
    capsule_host: str = "127.0.0.1"
    capsule_port: int = Field(default=8080, ge=1024, le=65535)
    capsule_allow_lan: bool = False
    capsule_token: SecretStr = SecretStr("")
    capsule_state_dir: Path = Path("state")
    google_api_key: SecretStr = SecretStr("")
    gemini_primary_model: str = "gemini-3.8-live"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_routing: Literal["auto", "live_only", "fallback_only"] = "auto"
    gemini_cooldown_seconds: int = Field(default=120, ge=1)
    assistant_max_volume: int = Field(default=75, ge=1, le=100)
    radio_max_volume: int = Field(default=75, ge=1, le=100)
    radio_resume_after_reboot: bool = False
    radio_directory_url: str = "https://de1.api.radio-browser.info"
    radio_default_station: str = "Радио Дача"
    vosk_model_path: str = ""
    piper_model_path: str = ""
    marusya_server_url: str = ""
    marusya_device_id: str = ""
    gemini_capsula_url: str = ""
    gemini_capsula_device_id: str = ""
    gemini_capsula_panel_password: SecretStr = SecretStr("")
    capsule_ssh_host: str = Field(default="", pattern=r"^$|^[A-Za-z0-9:][A-Za-z0-9_.:-]*$")
    capsule_ssh_user: str = Field(default="root", pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    capsule_ssh_port: int = Field(default=22, ge=1, le=65535)
    capsule_ssh_identity_file: str = ""
    capsule_ssh_known_hosts_file: str = ""

    @model_validator(mode="after")
    def require_lan_auth(self):
        if self.capsule_host not in {"localhost", "127.0.0.1", "::1"} and (
            not self.capsule_allow_lan or len(self.capsule_token.get_secret_value()) < 24
        ):
            raise ValueError("LAN requires CAPSULE_ALLOW_LAN=true and a token >=24 characters")
        return self
