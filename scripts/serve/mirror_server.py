#!/usr/bin/env python3
"""Serve the Mirror over HTTP so it can back a UI, a Shortcut, or an app.

Reuses the exact serving logic from mirror_chat.py (style card + RAG + path A/B/C)
but loads the model/retriever ONCE at startup (mirror_chat.py rebuilds the RAG
index on every invocation). Exposes a simple endpoint plus an OpenAI-compatible
one so existing chat clients work unchanged.

    pip install fastapi uvicorn        # not part of the stdlib core
    python scripts/serve/mirror_server.py --path A \
        --style-card persona/style_card.md --corpus data/scrubbed.jsonl --rag

    curl localhost:8000/chat -H 'Content-Type: application/json' \
        -d '{"messages":[{"role":"user","content":"yo"}]}'
    # or point any OpenAI client at http://localhost:8000/v1

Auth: with --rag this server can quote your real messages to any caller, so
set MIRROR_TOKEN to require 'Authorization: Bearer $MIRROR_TOKEN' on the chat
endpoints. Binding a non-loopback --host REQUIRES it. On loopback, the Host
header is also validated to block DNS-rebinding pages.

Endpoints:
    POST /chat                    {"messages":[...]} -> {"reply": "..."}
    POST /v1/chat/completions     OpenAI-compatible shim
    GET  /healthz
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mirror_chat  # noqa: E402  (same dir; reuse its Mirror/Retriever/loaders)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def make_app(mirror):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException
        from fastapi.middleware.trustedhost import TrustedHostMiddleware
    except ImportError:
        sys.exit("Install the server deps:  pip install fastapi uvicorn")

    app = FastAPI(title="Mirror")
    if mirror.args.host in LOOPBACK_HOSTS:
        # Reject requests whose Host header isn't local: a malicious page can
        # DNS-rebind its origin onto 127.0.0.1 and read responses; the rebound
        # request still carries the attacker's hostname in Host.
        app.add_middleware(TrustedHostMiddleware,
                           allowed_hosts=["127.0.0.1", "localhost", "::1"])

    token = os.environ.get("MIRROR_TOKEN", "")

    def require_token(authorization: str = Header(default="")):
        if token and not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "send 'Authorization: Bearer $MIRROR_TOKEN'")

    def extract_turns(payload: dict) -> list[dict]:
        """Validate the request body into non-system turns, or raise a 400."""
        msgs = payload.get("messages")
        if not msgs or not isinstance(msgs, list):
            raise HTTPException(400, "body must include a non-empty 'messages' list")
        try:
            turns = [{"role": m["role"], "content": m["content"]}
                     for m in msgs if m.get("role") != "system"]
        except (TypeError, KeyError, AttributeError):  # e.g. a bare-string entry
            raise HTTPException(400, "each message needs 'role' and 'content'") from None
        if not turns:
            raise HTTPException(400, "'messages' must contain at least one non-system message")
        return turns

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "path": mirror.args.path}

    @app.post("/chat", dependencies=[Depends(require_token)])
    def chat(payload: dict):
        return {"reply": mirror.reply(extract_turns(payload))}

    @app.post("/v1/chat/completions", dependencies=[Depends(require_token)])
    def openai_compat(payload: dict):
        reply = mirror.reply(extract_turns(payload))
        return {
            "id": f"mirror-{int(time.time()*1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"mirror-path-{mirror.args.path}",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": reply}}],
        }

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the Mirror over HTTP.")
    # Same flags, validation, and bootstrap as the CLI — defined once in
    # mirror_chat so the two entry points can't drift apart.
    mirror_chat.add_serving_args(ap)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    mirror_chat.validate_serving_args(ap, args)
    if args.host not in LOOPBACK_HOSTS and not os.environ.get("MIRROR_TOKEN"):
        ap.error(f"--host {args.host} exposes your message corpus beyond this machine. "
                 "Set MIRROR_TOKEN first; clients must then send "
                 "'Authorization: Bearer $MIRROR_TOKEN'.")
    if not os.environ.get("MIRROR_TOKEN"):
        print("NOTE: MIRROR_TOKEN not set — any process on this machine can query "
              "this Mirror (and, with --rag, retrieve your real messages).",
              file=sys.stderr)

    mirror = mirror_chat.build_mirror(args)
    app = make_app(mirror)

    try:
        import uvicorn
    except ImportError:
        sys.exit("Install the server deps:  pip install fastapi uvicorn")
    leaves = {"A": "style card + retrieved snippets go to Anthropic per request",
              "B": "requests go to your OpenAI fine-tune", "C": "nothing leaves this machine"}
    print(f"Serving Mirror (path {args.path}) on http://{args.host}:{args.port} — "
          f"{leaves[args.path]}", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
