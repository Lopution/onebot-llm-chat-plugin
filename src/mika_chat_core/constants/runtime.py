"""Runtime and lifecycle constants."""

# TaskSupervisor
TASK_SUPERVISOR_SHUTDOWN_TIMEOUT: float = 5.0

# API validation (lifecycle)
API_VALIDATE_TIMEOUT_SECONDS: float = 10.0
API_VALIDATE_SUCCESS_STATUS: int = 200
API_VALIDATE_UNAUTHORIZED_STATUS: int = 401
API_VALIDATE_FORBIDDEN_STATUS: int = 403

# WebUI endpoint paths
HEALTH_ENDPOINT_PATH: str = "/health"
METRICS_ENDPOINT_PATH: str = "/metrics"
CORE_EVENTS_ENDPOINT_PATH: str = "/v1/events"

# Prometheus
METRICS_PROMETHEUS_CONTENT_TYPE: str = "text/plain; version=0.0.4; charset=utf-8"
