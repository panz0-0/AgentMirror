from __future__ import annotations
import uuid
from typing import Any, Callable
from app.agentflow_adapter.tool_gateway import ToolGateway
class DistributedToolGateway:
    """可替换的远程工具协议客户端；本地 provider 与 HTTP/消息队列 transport 解耦。"""
    def __init__(self, gateway=None, transport: Callable[..., Any] | None=None): self.gateway=gateway or ToolGateway(); self.transport=transport
    async def call(self,name,provider=None,*,trace_id=None,timeout=None,retries=0,fallback=None,**kwargs):
        trace_id=trace_id or uuid.uuid4().hex
        if self.transport is not None:
            async def remote():
                value=self.transport(name=name,trace_id=trace_id,kwargs=kwargs)
                if hasattr(value,"__await__"): value=await value
                return value
            result=await self.gateway.call(name,remote,timeout=timeout,retries=retries,fallback=fallback)
        elif provider is not None:
            result=await self.gateway.call(name,provider,timeout=timeout,retries=retries,fallback=fallback)
        else:
            return await self.gateway.call(name,lambda: (_ for _ in ()).throw(ValueError("provider or transport required")),fallback=fallback)
        result.trace_id=trace_id; return result

