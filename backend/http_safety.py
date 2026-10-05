"""Small ASGI guard: bounded bodies, same-origin data, bounded rate-limit memory.

This is a demo abuse boundary, not authentication or a distributed DDoS service.
Only explicitly trusted proxy addresses may supply the client IP header.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import secrets
import time
from collections import OrderedDict
from typing import Callable

from starlette.responses import JSONResponse


class TokenBuckets:
    def __init__(self, maximum: int = 4096, clock: Callable[[], float] = time.monotonic):
        self.maximum, self.clock = maximum, clock
        self.buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def take(self, key: str, capacity: float, per_second: float) -> bool:
        now = self.clock()
        tokens, previous = self.buckets.pop(key, (capacity, now))
        tokens = min(capacity, tokens + max(0, now - previous) * per_second)
        allowed = tokens >= 1
        self.buckets[key] = (tokens - 1 if allowed else tokens, now)
        while len(self.buckets) > self.maximum:
            self.buckets.popitem(last=False)
        return allowed


class DemoSafetyMiddleware:
    def __init__(self, app, public: bool, origins: list[str]):
        self.app, self.public, self.origins = app, public, set(origins)
        self.rate = TokenBuckets()
        raw_networks = os.getenv("TRUSTED_PROXY_NETWORKS", "")
        self.trusted_networks = [ipaddress.ip_network(value.strip()) for value in raw_networks.split(",") if value.strip()]
        if any(network.prefixlen == 0 for network in self.trusted_networks):
            raise RuntimeError("TRUSTED_PROXY_NETWORKS cannot trust every address")

    def client_ip(self, scope, headers: dict[str, str]) -> str:
        peer = (scope.get("client") or ("unknown", 0))[0]
        try:
            parsed = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        if any(parsed in network for network in self.trusted_networks):
            claimed = headers.get("x-real-ip", "")
            try:
                return str(ipaddress.ip_address(claimed))
            except ValueError:
                pass
        return str(parsed)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode("latin1"): value.decode("latin1") for key, value in scope.get("headers", [])}
        path = scope.get("path", "")
        api = path.startswith("/api/")

        async def fail(status: int, code: str, message: str, retryable: bool = False):
            response_headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
            if status == 429:
                response_headers["Retry-After"] = "20"
            if status in (408, 413, 431):
                response_headers["Connection"] = "close"
            response = JSONResponse(status_code=status, content={"code": code, "message": message,
                "retryable": retryable, "correlation_id": secrets.token_hex(8)}, headers=response_headers)
            await response(scope, receive, send)

        if len(scope.get("raw_path", path.encode())) + len(scope.get("query_string", b"")) > 2048:
            return await fail(414, "request_too_large", "The request URL is too long.")
        if sum(len(k) + len(v) for k, v in scope.get("headers", [])) > 16_384:
            return await fail(431, "request_too_large", "The request headers are too large.")
        if self.public and api:
            if headers.get("origin") and headers["origin"] not in self.origins:
                return await fail(403, "origin_not_allowed", "Use the demo from its own website.")
            if path != "/api/health" and scope["method"] != "OPTIONS":
                peer = self.client_ip(scope, headers)
                ip_key = hashlib.sha256(peer.encode()).hexdigest()
                if not self.rate.take("global", 120, 40) or not self.rate.take("ip:" + ip_key, 60, 20):
                    return await fail(429, "rate_limited", "The demo is busy. Please try again shortly.", True)
                if path == "/api/sessions" and scope["method"] == "POST":
                    if not self.rate.take("create:" + ip_key, 6, 1 / 20):
                        return await fail(429, "rate_limited", "Please wait a moment before starting another replay.", True)
                authorization = headers.get("authorization", "")
                if authorization.startswith("Bearer ") and len(authorization) <= 135:
                    owner_key = hashlib.sha256(authorization[7:].encode()).hexdigest()
                    mutation = scope["method"] in ("POST", "PATCH")
                    key = ("write:" if mutation else "read:") + owner_key
                    if not self.rate.take(key, 12 if mutation else 20, 1 / 6 if mutation else 8):
                        return await fail(429, "rate_limited", "Please wait a moment and try again.", True)

        # Read before dispatch with a hard bound, including chunked requests. A
        # malicious chunk stream cannot allocate an unbounded request.body().
        replay_receive = receive
        if scope["method"] in ("POST", "PATCH", "PUT"):
            try:
                announced = int(headers.get("content-length", "0"))
                if announced < 0:
                    raise ValueError()
            except ValueError:
                return await fail(400, "invalid_request", "Invalid request size.")
            if announced > 16_384:
                return await fail(413, "request_too_large", "The request body is too large.")
            body = bytearray()
            deadline = time.monotonic() + 5
            while True:
                try:
                    message = await asyncio.wait_for(receive(), timeout=max(.001, deadline - time.monotonic()))
                except TimeoutError:
                    return await fail(408, "request_timeout", "The request took too long.", True)
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > 16_384:
                    return await fail(413, "request_too_large", "The request body is too large.")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False
            async def replay_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

        async def guarded_send(message):
            if message["type"] == "http.response.start" and api:
                response_headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"cache-control", b"x-content-type-options", b"referrer-policy")]
                response_headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")])
                message = {**message, "headers": response_headers}
            await send(message)
        await self.app(scope, replay_receive, guarded_send)
