"""OpenTelemetry distributed tracing configuration."""

from __future__ import annotations

import os
import logging
from typing import Optional
from contextlib import contextmanager

# OpenTelemetry imports
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.exporter.jaeger import JaegerExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry import propagators
    from opentelemetry.propagators.b3 import B3SingleFormat
    from opentelemetry.propagators.jaeger import JaegerPropagator
    
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    # Create dummy implementations for graceful degradation
    class DummyTracer:
        def start_as_current_span(self, name, **kwargs):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def add_event(self, name, **kwargs):
            pass
        def set_attribute(self, key, value):
            pass
        def record_exception(self, exception):
            pass
    
    class DummyContext:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    
    trace = type('trace', (), {
        'get_tracer': lambda *args, **kwargs: DummyTracer(),
        'set_span_in_context': lambda *args, **kwargs: None,
        'get_current_span': lambda: DummyTracer()
    })()


logger = logging.getLogger(__name__)


class TracingConfig:
    """Configuration for OpenTelemetry tracing."""
    
    def __init__(
        self,
        service_name: str = "aop-orchestrator",
        service_version: str = "1.0.0",
        environment: str = "production",
        jaeger_endpoint: Optional[str] = None,
        otlp_endpoint: Optional[str] = None,
        enable_console_export: bool = False,
        sample_rate: float = 1.0
    ):
        self.service_name = service_name
        self.service_version = service_version
        self.environment = environment
        self.jaeger_endpoint = jaeger_endpoint or os.getenv("JAEGER_ENDPOINT")
        self.otlp_endpoint = otlp_endpoint or os.getenv("OTLP_ENDPOINT")
        self.enable_console_export = enable_console_export or os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() == "true"
        self.sample_rate = sample_rate


def setup_tracing(config: TracingConfig) -> bool:
    """Setup OpenTelemetry tracing with the given configuration."""
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available, tracing disabled")
        return False
    
    try:
        # Create resource
        resource = Resource.create({
            SERVICE_NAME: config.service_name,
            "service.version": config.service_version,
            "deployment.environment": config.environment,
        })
        
        # Create tracer provider
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        
        # Add exporters
        if config.jaeger_endpoint:
            jaeger_exporter = JaegerExporter(
                agent_host_name=config.jaeger_endpoint.split(":")[0],
                agent_port=int(config.jaeger_endpoint.split(":")[1]) if ":" in config.jaeger_endpoint else 6831,
            )
            provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
            logger.info(f"Jaeger exporter configured: {config.jaeger_endpoint}")
        
        if config.otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info(f"OTLP exporter configured: {config.otlp_endpoint}")
        
        if config.enable_console_export:
            console_exporter = ConsoleSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(console_exporter))
            logger.info("Console exporter enabled")
        
        # Configure propagators
        propagators.set_global_textmap(B3SingleFormat())
        
        logger.info(f"OpenTelemetry tracing enabled for {config.service_name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry tracing: {e}")
        return False


def instrument_fastapi(app):
    """Instrument FastAPI application for tracing."""
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available, FastAPI instrumentation disabled")
        return
    
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI: {e}")


def instrument_httpx():
    """Instrument HTTPX client for tracing."""
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available, HTTPX instrumentation disabled")
        return
    
    try:
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument HTTPX: {e}")


def instrument_redis():
    """Instrument Redis client for tracing."""
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available, Redis instrumentation disabled")
        return
    
    try:
        RedisInstrumentor().instrument()
        logger.info("Redis instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument Redis: {e}")


def get_tracer(name: str = __name__):
    """Get a tracer for the given component name."""
    if OTEL_AVAILABLE:
        return trace.get_tracer(name)
    return DummyTracer()


@contextmanager
def trace_operation(name: str, tracer_name: str = __name__, **attributes):
    """Context manager for tracing operations."""
    tracer = get_tracer(tracer_name)
    
    if OTEL_AVAILABLE:
        with tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span
    else:
        # Dummy context for when tracing is not available
        yield DummyTracer()


def add_span_event(name: str, **attributes):
    """Add an event to the current span."""
    if OTEL_AVAILABLE:
        current_span = trace.get_current_span()
        if current_span:
            current_span.add_event(name, attributes=attributes)


def set_span_attribute(key: str, value):
    """Set an attribute on the current span."""
    if OTEL_AVAILABLE:
        current_span = trace.get_current_span()
        if current_span:
            current_span.set_attribute(key, value)


def record_span_exception(exception: Exception):
    """Record an exception on the current span."""
    if OTEL_AVAILABLE:
        current_span = trace.get_current_span()
        if current_span:
            current_span.record_exception(exception)


# Initialize tracing when module is imported
def initialize_tracing():
    """Initialize tracing with default configuration."""
    config = TracingConfig(
        service_name="aop-orchestrator",
        service_version="1.0.0",
        environment=os.getenv("ENVIRONMENT", "development"),
        sample_rate=float(os.getenv("OTEL_SAMPLE_RATE", "1.0"))
    )
    
    if setup_tracing(config):
        # Instrument common libraries
        instrument_httpx()
        instrument_redis()
        return True
    return False


# Auto-initialize tracing
_tracing_initialized = False

def ensure_tracing_initialized():
    """Ensure tracing is initialized (idempotent)."""
    global _tracing_initialized
    if not _tracing_initialized:
        _tracing_initialized = initialize_tracing()
    return _tracing_initialized