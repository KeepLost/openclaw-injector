import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        self._load()
    
    def _load(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path) as f:
            self._config = yaml.safe_load(f) or {}
    
    def _get_env(self, key: str, default: str | None = None) -> str:
        value = os.getenv(key, default)
        if value is None:
            raise ValueError(f"Missing required environment variable: {key}")
        return value
    
    @property
    def gateway_url(self) -> str:
        return self._get_env(
            "GATEWAY_URL",
            self._config.get("gateway", {}).get("url", "ws://localhost:18789")
        )
    
    @property
    def gateway_token(self) -> str:
        token = os.getenv("GATEWAY_TOKEN")
        if not token:
            raise ValueError("Missing required environment variable: GATEWAY_TOKEN")
        return token
    
    @property
    def websocket_token(self) -> str:
        token = os.getenv("WEBSOCKET_TOKEN")
        if not token:
            raise ValueError("Missing required environment variable: WEBSOCKET_TOKEN")
        return token
    
    @property
    def https_host(self) -> str:
        return self._get_env(
            "HTTPS_HOST",
            self._config.get("https", {}).get("host", "0.0.0.0")
        )
    
    @property
    def https_port(self) -> int:
        port_str = self._get_env(
            "HTTPS_PORT",
            str(self._config.get("https", {}).get("port", 8443))
        )
        return int(port_str)
    
    @property
    def cert_file(self) -> str:
        return self._get_env(
            "CERT_FILE",
            self._config.get("https", {}).get("cert_file", "/root/.secrets/certs_server/cert.pem")
        )
    
    @property
    def key_file(self) -> str:
        return self._get_env(
            "KEY_FILE",
            self._config.get("https", {}).get("key_file", "/root/.secrets/certs_server/key.pem")
        )
    
    @property
    def client_ca_file(self) -> str | None:
        return os.getenv(
            "CLIENT_CA_FILE",
            self._config.get("https", {}).get("client_ca_file")
        )
    
    @property
    def device_identity_path(self) -> str:
        return self._get_env(
            "DEVICE_IDENTITY_PATH",
            self._config.get("gateway", {}).get("device_identity_path", "device.json")
        )
