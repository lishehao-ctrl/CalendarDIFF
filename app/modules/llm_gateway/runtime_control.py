from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Callable

from app.modules.llm_gateway.contracts import LlmInvokeRequest, LlmInvokeResult, SessionCacheModeLiteral
from app.modules.llm_gateway.tracing import LlmGatewayTraceEvent

LlmInvokeObserver = Callable[[LlmInvokeRequest, LlmInvokeResult], None]
LlmTraceObserver = Callable[[LlmGatewayTraceEvent], None]

_OBSERVER: ContextVar[LlmInvokeObserver | None] = ContextVar("llm_invoke_observer", default=None)
_TRACE_OBSERVER: ContextVar[LlmTraceObserver | None] = ContextVar("llm_trace_observer", default=None)
_SESSION_CACHE_MODE_OVERRIDE: ContextVar[SessionCacheModeLiteral | None] = ContextVar(
    "llm_session_cache_mode_override",
    default=None,
)


def set_llm_invoke_observer(observer: LlmInvokeObserver | None) -> Token:
    return _OBSERVER.set(observer)



def reset_llm_invoke_observer(token: Token) -> None:
    _OBSERVER.reset(token)



def get_llm_invoke_observer() -> LlmInvokeObserver | None:
    return _OBSERVER.get()


def set_llm_trace_observer(observer: LlmTraceObserver | None) -> Token:
    return _TRACE_OBSERVER.set(observer)


def reset_llm_trace_observer(token: Token) -> None:
    _TRACE_OBSERVER.reset(token)


def get_llm_trace_observer() -> LlmTraceObserver | None:
    return _TRACE_OBSERVER.get()



def set_session_cache_mode_override(mode: SessionCacheModeLiteral | None) -> Token:
    return _SESSION_CACHE_MODE_OVERRIDE.set(mode)



def reset_session_cache_mode_override(token: Token) -> None:
    _SESSION_CACHE_MODE_OVERRIDE.reset(token)



def get_session_cache_mode_override() -> SessionCacheModeLiteral | None:
    return _SESSION_CACHE_MODE_OVERRIDE.get()
