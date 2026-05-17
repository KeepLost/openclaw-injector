import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

from .config import Config
from .device_identity import DeviceIdentity


logger = logging.getLogger(__name__)


class GatewayClient:
    def __init__(self, config: Config):
        self.config = config
        self.ws: WebSocketClientProtocol | None = None
        self.connected = False
        self.pending_requests: dict[str, asyncio.Future] = {}
        self.pending_events: dict[str, asyncio.Future] = {}
        self.request_id_counter = 0
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 30.0
        self._receive_task: asyncio.Task | None = None
        self._connect_lock = asyncio.Lock()
        self.device_identity = DeviceIdentity(config.device_identity_path)
        self.client_metadata = self._load_json("client_metadata.json")
        self.message_metadata = self._load_json("message_metadata.json")
    
    def _load_json(self, filename: str) -> dict[str, Any]:
        file_path = Path(filename)
        if not file_path.exists():
            logger.warning(f"Metadata file not found: {filename}, using empty dict")
            return {}
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {filename}: {e}")
            return {}
    
    async def connect(self) -> None:
        async with self._connect_lock:
            if self.connected:
                return
            
            try:
                self.ws = await websockets.connect(
                    self.config.gateway_url,
                    ping_interval=30,
                    ping_timeout=10
                )
                logger.info(f"Connected to Gateway at {self.config.gateway_url}")
                
                self._receive_task = asyncio.create_task(self._receive_loop())
                
                await self._authenticate()
                self.connected = True
                self.reconnect_delay = 1.0
            except Exception as e:
                logger.error(f"Failed to connect: {e}")
                raise
    
    async def _authenticate(self) -> None:
        challenge_event = await self._wait_for_event("connect.challenge", timeout=10.0)
        nonce = challenge_event["payload"]["nonce"]
        
        signed_at_ms = int(time.time() * 1000)
        scopes = "operator.admin,operator.read,operator.write"
        
        if not self.client_metadata:
            raise ValueError("client_metadata.json is empty or failed to load")
        
        try:
            client_id = self.client_metadata["id"]
            mode = self.client_metadata["mode"]
            platform = self.client_metadata["platform"]
        except KeyError as e:
            raise ValueError(f"Missing required field in client_metadata.json: {e}")
        
        payload = (
            f"v3|{self.device_identity.device_id}|"
            f"{client_id}|{mode}|operator|{scopes}|"
            f"{signed_at_ms}|{self.config.gateway_token}|{nonce}|"
            f"{platform}|"
        )
        
        signature = self.device_identity.sign_payload(payload)
        public_key = self.device_identity.get_public_key_b64url()
        
        if not self.client_metadata:
            raise ValueError("client_metadata.json is empty or failed to load")
        
        connect_request = {
            "id": self._next_request_id(),
            "type": "req",
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 4,
                "client": self.client_metadata,
                "device": {
                    "id": self.device_identity.device_id,
                    "publicKey": public_key,
                    "signature": signature,
                    "signedAt": signed_at_ms,
                    "nonce": nonce
                },
                "auth": {
                    "token": self.config.gateway_token
                },
                "scopes": ["operator.admin", "operator.read", "operator.write"]
            }
        }
        
        await self.ws.send(json.dumps(connect_request))
        logger.info("Sent connect request with device identity")
        
        response = await self._wait_for_response(connect_request["id"], timeout=10.0)
        if not response.get("ok"):
            raise RuntimeError(f"Authentication failed: {response}")
        
        logger.info("Authentication successful with device identity")
    
    async def _wait_for_event(self, event_type: str, timeout: float) -> dict[str, Any]:
        future = asyncio.Future()
        self.pending_events[event_type] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.pending_events.pop(event_type, None)
    
    async def _wait_for_response(self, request_id: str, timeout: float) -> dict[str, Any]:
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.pending_requests.pop(request_id, None)
    
    async def _receive_loop(self) -> None:
        try:
            async for message in self.ws:
                try:
                    frame = json.loads(message)
                    await self._handle_frame(frame)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {e}")
                except Exception as e:
                    logger.error(f"Error handling frame: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.connected = False
            await self._handle_disconnect()
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
            self.connected = False
            await self._handle_disconnect()
    
    async def _handle_frame(self, frame: dict[str, Any]) -> None:
        frame_type = frame.get("type")
        
        if frame_type == "res":
            request_id = frame.get("id")
            if request_id in self.pending_requests:
                future = self.pending_requests[request_id]
                if not future.done():
                    future.set_result(frame)
        elif frame_type == "event":
            event_name = frame.get("event")
            logger.debug(f"Received event: {event_name}")
            if event_name and event_name in self.pending_events:
                future = self.pending_events[event_name]
                if not future.done():
                    future.set_result(frame)
    
    async def _handle_disconnect(self) -> None:
        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(ConnectionError("WebSocket disconnected"))
        self.pending_requests.clear()
        
        await self._reconnect()
    
    async def _reconnect(self) -> None:
        while not self.connected:
            logger.info(f"Reconnecting in {self.reconnect_delay}s...")
            await asyncio.sleep(self.reconnect_delay)
            
            try:
                await self.connect()
                logger.info("Reconnected successfully")
                return
            except Exception as e:
                logger.error(f"Reconnect failed: {e}")
                self.reconnect_delay = min(
                    self.reconnect_delay * 2,
                    self.max_reconnect_delay
                )
    
    def _next_request_id(self) -> str:
        self.request_id_counter += 1
        return f"req_{self.request_id_counter}"
    
    async def send_message(
        self, 
        session_key: str, 
        message: str,
        system_input_provenance: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.connected:
            raise ConnectionError("Not connected to Gateway")
        
        request_id = self._next_request_id()
        idempotency_key = str(uuid.uuid4())
        
        params = {
            "sessionKey": session_key,
            "message": message,
            "deliver": True,
            "idempotencyKey": idempotency_key
        }
        
        provenance = None
        if "systemInputProvenance" in self.message_metadata:
            provenance = self.message_metadata["systemInputProvenance"].copy()
            logger.debug(f"Loaded default provenance from config: {provenance}")
        
        if system_input_provenance is not None:
            logger.debug(f"User provided provenance: {system_input_provenance}")
            if provenance is None:
                provenance = {}
            provenance.update(system_input_provenance)
            logger.debug(f"Merged provenance: {provenance}")
        
        if provenance is not None:
            params["systemInputProvenance"] = provenance
            logger.debug(f"Final provenance in params: {params['systemInputProvenance']}")
        
        request = {
            "id": request_id,
            "type": "req",
            "method": "chat.send",
            "params": params
        }
        
        await self.ws.send(json.dumps(request))
        logger.info(f"Sent chat.send request: {request_id}, idempotencyKey: {idempotency_key}")
        
        response = await self._wait_for_response(request_id, timeout=30.0)
        
        if not response.get("ok"):
            logger.error(f"chat.send failed: {response.get('error')}")
        
        return response
    
    async def close(self) -> None:
        self.connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        
        if self.ws:
            await self.ws.close()
            logger.info("WebSocket connection closed")
