import time
import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger("mcp-http-proxy.observability")

class ObservabilityTracker:
    def __init__(self, tool_name: str, arguments: Dict[str, Any]):
        self.tool_name = tool_name
        self.arguments = arguments
        self.metrics = {"status": "started", "tokens": 0, "response_summary": ""}
        self.start_time = 0
        self.input_tokens = 0
        self.mlflow_available = False
        
        try:
            import mlflow
            # Read from system environment variables (Defaults to local fallback if unset)
            tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
            mlflow.set_tracking_uri(tracking_uri)
            mlflow.set_experiment("mcp-proxy-observability")
            self.mlflow_available = True
        except ImportError:
            logger.warning("MLflow library package is missing. Observability logging will drop back to disk files.")
        except Exception as e:
            logger.warning(f"Could not reach external MLflow host context tracking server: {e}")

    def _estimate_tokens(self, target_input: Any) -> int:
        """Recursively flattens data types to estimate string byte token depths"""
        try:
            import tiktoken
            encoder = tiktoken.get_encoding("cl100k_base")
            if target_input is None:
                return 0
            if isinstance(target_input, (dict, list)):
                return len(encoder.encode(json.dumps(target_input)))
            return len(encoder.encode(str(target_input)))
        except ImportError:
            return 0

    async def __aenter__(self):
        self.start_time = time.perf_counter()
        self.input_tokens = self._estimate_tokens(self.arguments)
        logger.info(f"[Telemetry Start] Logging run span trace for tool: '{self.tool_name}'")
        return self.metrics

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        latency = time.perf_counter() - self.start_time
        status = self.metrics.get("status", "unknown")
        
        output_tokens = self._estimate_tokens(self.metrics.get("response_summary", ""))
        total_tokens = self.input_tokens + output_tokens
        
        target_server = "native"
        original_tool = self.tool_name
        if "__" in self.tool_name:
            target_server, original_tool = self.tool_name.split("__", 1)

        logger.info(
            f"[Telemetry End] Tool: {self.tool_name} | Latency: {latency:.4f}s | "
            f"Tokens: In={self.input_tokens}/Out={output_tokens} | Status: {status}"
        )

        # Fail-safe check wrapper: Logs telemetry metadata securely without crashing proxy logic if MLflow goes down
        if self.mlflow_available:
            try:
                import mlflow
                with mlflow.start_run(run_name=f"mcp_call_{self.tool_name}", nested=True):
                    mlflow.log_param("tool_name", self.tool_name)
                    mlflow.log_param("target_server", target_server)
                    mlflow.log_param("original_tool", original_tool)
                    mlflow.log_param("status", status)
                    mlflow.log_param("arguments_payload", json.dumps(self.arguments)[:500])
                    
                    mlflow.log_metric("latency_seconds", latency)
                    mlflow.log_metric("tokens_input_estimated", self.input_tokens)
                    mlflow.log_metric("tokens_output_estimated", output_tokens)
                    mlflow.log_metric("tokens_total_count", total_tokens)

                    if status == "failed" or "error" in self.metrics:
                        mlflow.log_param("error_message", self.metrics.get("error", "Unknown Execution Exception"))
                        mlflow.set_tag("execution_state", "error")
                    else:
                        mlflow.set_tag("execution_state", "success")
            except Exception as e:
                logger.error(f"⚠️ Failed forwarding analytical traces over to external MLflow gateway instance: {e}")
