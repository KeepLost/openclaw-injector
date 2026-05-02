import asyncio
import json
import logging
import ssl
from pathlib import Path

from aiohttp import web

from .config import Config
from .gateway_client import GatewayClient
from .models import SendRequest, SendResponse, ErrorResponse


logger = logging.getLogger(__name__)


class HTTPSServer:
    def __init__(self, config: Config, gateway_client: GatewayClient):
        self.config = config
        self.gateway_client = gateway_client
        self.app = web.Application()
        self._setup_routes()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
    
    def _setup_routes(self) -> None:
        self.app.router.add_post("/send", self.handle_send)
        self.app.router.add_get("/health", self.handle_health)
    
    def _verify_token(self, request: web.Request) -> bool:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        
        token = auth_header[7:]
        return token == self.config.websocket_token
    
    async def handle_send(self, request: web.Request) -> web.Response:
        if not self._verify_token(request):
            error = ErrorResponse(
                error="unauthorized",
                detail="Invalid or missing Authorization token"
            )
            return web.json_response(
                {"error": error.error, "detail": error.detail},
                status=401
            )
        
        try:
            data = await request.json()
            send_req = SendRequest(
                session_key=data["session_key"],
                message=data["message"],
                system_input_provenance=data.get("system_input_provenance")
            )
        except (KeyError, json.JSONDecodeError) as e:
            error = ErrorResponse(
                error="invalid_request",
                detail=str(e)
            )
            return web.json_response(
                {"error": error.error, "detail": error.detail},
                status=400
            )
        
        try:
            response = await self.gateway_client.send_message(
                send_req.session_key,
                send_req.message,
                send_req.system_input_provenance
            )
            
            payload = response.get("payload", {})
            send_resp = SendResponse(
                run_id=payload.get("runId", ""),
                status="queued"
            )
            
            return web.json_response({
                "run_id": send_resp.run_id,
                "status": send_resp.status
            })
        except ConnectionError as e:
            error = ErrorResponse(
                error="gateway_unavailable",
                detail=str(e)
            )
            return web.json_response(
                {"error": error.error, "detail": error.detail},
                status=503
            )
        except asyncio.TimeoutError:
            error = ErrorResponse(
                error="gateway_timeout",
                detail="Gateway did not respond within 30s"
            )
            return web.json_response(
                {"error": error.error, "detail": error.detail},
                status=504
            )
        except Exception as e:
            logger.error(f"Error handling send request: {e}")
            error = ErrorResponse(
                error="internal_error",
                detail=str(e)
            )
            return web.json_response(
                {"error": error.error, "detail": error.detail},
                status=500
            )
    
    async def handle_health(self, request: web.Request) -> web.Response:
        status = "healthy" if self.gateway_client.connected else "unhealthy"
        return web.json_response({"status": status})
    
    def _create_ssl_context(self) -> ssl.SSLContext:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(
            certfile=self.config.cert_file,
            keyfile=self.config.key_file
        )
        
        if self.config.client_ca_file:
            ssl_context.load_verify_locations(cafile=self.config.client_ca_file)
            ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        return ssl_context
    
    async def start(self) -> None:
        ssl_context = self._create_ssl_context()
        
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        self.site = web.TCPSite(
            self.runner,
            host=self.config.https_host,
            port=self.config.https_port,
            ssl_context=ssl_context
        )
        await self.site.start()
        
        logger.info(
            f"HTTPS server started on {self.config.https_host}:{self.config.https_port}"
        )
    
    async def stop(self) -> None:
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("HTTPS server stopped")
