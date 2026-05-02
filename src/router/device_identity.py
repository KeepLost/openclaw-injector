import json
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


class DeviceIdentity:
    """Device identity for OpenClaw Gateway authentication."""
    
    def __init__(self, device_json_path: str):
        """Load device identity from device.json file.
        
        Args:
            device_json_path: Path to device.json file
        """
        with open(device_json_path) as f:
            data = json.load(f)
        
        self.device_id = data["deviceId"]
        private_key_pem = data["privateKeyPem"]
        
        # Load Ed25519 private key
        self.private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=None
        )
    
    def sign_payload(self, payload: str) -> str:
        """Sign payload with Ed25519 private key.
        
        Args:
            payload: UTF-8 string to sign
            
        Returns:
            Base64url-encoded signature (without padding)
        """
        signature_bytes = self.private_key.sign(payload.encode('utf-8'))
        return base64.urlsafe_b64encode(signature_bytes).decode().rstrip('=')
    
    def get_public_key_b64url(self) -> str:
        """Get base64url-encoded public key (32 bytes raw).
        
        Returns:
            Base64url-encoded Ed25519 public key (without padding)
        """
        public_key = self.private_key.public_key()
        public_key_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.urlsafe_b64encode(public_key_raw).decode().rstrip('=')
