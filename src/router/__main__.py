import asyncio
import logging
import signal
import sys
from dotenv import load_dotenv

load_dotenv()

from .config import Config
from .gateway_client import GatewayClient
from .https_server import HTTPSServer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


class Router:
    def __init__(self, config: Config):
        self.config = config
        self.gateway_client = GatewayClient(config)
        self.https_server = HTTPSServer(config, self.gateway_client)
        self.shutdown_event = asyncio.Event()
    
    async def start(self) -> None:
        logger.info("Starting OpenClaw WebSocket Router...")
        
        await self.gateway_client.connect()
        await self.https_server.start()
        
        logger.info("Router started successfully")
        await self.shutdown_event.wait()
    
    async def stop(self) -> None:
        logger.info("Shutting down gracefully...")
        
        await self.https_server.stop()
        
        await asyncio.sleep(5)
        
        await self.gateway_client.close()
        
        logger.info("Shutdown complete")
    
    def handle_signal(self, signum: int) -> None:
        logger.info(f"Received signal {signum}")
        self.shutdown_event.set()


async def main() -> None:
    try:
        config = Config()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    
    router = Router(config)
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: router.handle_signal(s)
        )
    
    try:
        await router.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await router.stop()


if __name__ == "__main__":
    asyncio.run(main())
