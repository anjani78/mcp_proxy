import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger("mcp-http-proxy.config")

# FIX: Resolve path relative to this file's folder (config/) instead of the root execution directory
CONFIG_FILE = Path(__file__).parent / "proxy_servers.json"

class ConfigManager:
    @staticmethod
    def load_config() -> Dict[str, str]:
        if CONFIG_FILE.exists():
            try:
                config_data = json.loads(CONFIG_FILE.read_text())
                logger.info(f"Loaded {len(config_data)} remote servers from configuration: {list(config_data.keys())}")
                return config_data
            except Exception as e:
                logger.error(f"Failed to parse registry configuration tracker file: {e}")
                return {}
        logger.warning(f"No configuration registry file detected at '{CONFIG_FILE.resolve()}'. Starting clean.")
        return {}

    @staticmethod
    def save_config(remote_configs: Dict[str, str]):
        try:
            CONFIG_FILE.write_text(json.dumps(remote_configs, indent=2))
            logger.info(f"Successfully updated internal proxy registry storage target state at: {CONFIG_FILE.resolve()}")
        except Exception as e:
            logger.critical(f"Failed writing state updates securely down to storage layer: {e}")
