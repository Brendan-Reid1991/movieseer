#!/usr/bin/env python3
import asyncio
import subprocess
import logging
from aiohttp import web, ClientSession, ClientTimeout, WSMsgType, ClientConnectionResetError

JELLYFIN_BASE = "http://jellyfin:8096"
MEDIA_PATH = "/media"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("jellyfin-proxy")

HOP_BY_HOP = frozenset([
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
])


def filter_headers(headers, remove_host=False):
    skip = HOP_BY_HOP | ({"host"} if remove_host else set())
    return {k: v for k, v in headers.items() if k.lower() not in skip}


async def clean_media():
    log.info("Cleaning AppleDouble files before library scan...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["find", MEDIA_PATH, "-name", "._*", "-delete"],
            capture_output=True,
        ),
    )
    log.info("Cleanup complete.")


async def handle_websocket(request):
    ws_server = web.WebSocketResponse()
    await ws_server.prepare(request)

    headers = filter_headers(request.headers, remove_host=True)
    url = f"ws://jellyfin:8096{request.path_qs}"

    async with ClientSession() as session:
        async with session.ws_connect(url, headers=headers) as ws_client:
            async def forward(src, dst):
                async for msg in src:
                    if msg.type == WSMsgType.TEXT:
                        await dst.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await dst.send_bytes(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break

            tasks = [
                asyncio.ensure_future(forward(ws_server, ws_client)),
                asyncio.ensure_future(forward(ws_client, ws_server)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()

    return ws_server


async def handle(request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await handle_websocket(request)

    if request.method == "POST" and (
        request.path == "/Library/Refresh"
        or request.path.startswith("/ScheduledTasks/Running/")
    ):
        await clean_media()

    headers = filter_headers(request.headers, remove_host=True)
    body = await request.read()

    async with ClientSession(timeout=ClientTimeout(total=None), auto_decompress=False) as session:
        async with session.request(
            method=request.method,
            url=f"{JELLYFIN_BASE}{request.path_qs}",
            headers=headers,
            data=body,
            allow_redirects=False,
        ) as resp:
            response = web.StreamResponse(
                status=resp.status,
                reason=resp.reason,
                headers=filter_headers(resp.headers),
            )
            await response.prepare(request)
            try:
                async for chunk in resp.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
            except (ClientConnectionResetError, ConnectionResetError, asyncio.CancelledError):
                pass  # client disconnected mid-stream (e.g. stopped video playback)
            return response


app = web.Application(client_max_size=0)
app.router.add_route("*", "/", handle)
app.router.add_route("*", "/{path_info:.*}", handle)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8096, access_log=None)
