#!/usr/bin/env python3

import base64
import json
import os
import sys

import a0
from aiohttp import web, WSMsgType
import aiohttp_cors


# fetch(`http://${api_addr}/api/ls`)
# .then((r) => { return r.text() })
# .then((msg) => { console.log(msg) })
async def ls_handler(request):
    cmd = None
    if request.can_read_body:
        cmd = await request.json()

    def describe(filename):
        if cmd and cmd.get("long", False):
            print("TODO: ls -l", file=sys.stderr)
        if cmd and cmd.get("all", False):
            print("TODO: ls -a", file=sys.stderr)

        description = {"filename": filename}

        if not filename.startswith("a0_"):
            return

        parts = filename.split("__")
        description["protocol"] = parts[0][3:]
        if len(parts) >= 2:
            description["container"] = parts[1]
        if len(parts) >= 3:
            description["topic"] = parts[2]

        return description

    filenames = os.listdir(os.environ.get("A0_ROOT", "/dev/shm"))
    return web.json_response(
        [describe(filename) for filename in sorted(filenames)])


# fetch(`http://${api_addr}/api/pub`, {
#     method: "POST",
#     body: JSON.stringify({
#         container: "...",
#         topic: "...",
#         packet: {
#             headers: [
#                 ["key", "val"],
#                 ...
#             ],
#             payload: window.btoa("..."),
#         },
#     })
# })
# .then((r) => { return r.text() })
# .then((msg) => { console.assert(msg == "success", msg) })
async def pub_handler(request):
    cmd = await request.json()

    if "packet" not in cmd:
        cmd["packet"] = {}
    if "headers" not in cmd["packet"]:
        cmd["packet"]["headers"] = []
    if "payload" not in cmd["packet"]:
        cmd["packet"]["payload"] = ""

    tm = a0.TopicManager(container=cmd["container"])

    p = a0.Publisher(tm.publisher_topic(cmd["topic"]))
    p.pub(
        a0.Packet(cmd["packet"]["headers"],
                  base64.b64decode(cmd["packet"]["payload"])))

    return web.Response(text="success")


# ws = new WebSocket(`ws://${api_addr}/wsapi/pub`)
# ws.onopen = () => {
#     ws.send(JSON.stringify({
#         container: "...",
#         topic: "...",
#     }))
# }
# // later, after onopen completes:
# ws.send(JSON.stringify({
#         packet: {
#             headers: [
#                 ["key", "val"],
#                 ...
#             ],
#             payload: window.btoa("..."),
#         },
# }))
async def pub_wshandler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    publisher = None

    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            break

        cmd = json.loads(msg.data)

        if publisher is None:
            # TODO: Guard printing behind "verbose" flag.
            print(f"Setting up publisher - {cmd}", flush=True)
            tm = a0.TopicManager(container=cmd["container"])
            publisher = a0.Publisher(tm.publisher_topic(cmd["topic"]))
            continue

        publisher.pub(
            a0.Packet(cmd["packet"]["headers"],
                      base64.b64decode(cmd["packet"]["payload"])))


# ws = new WebSocket(`ws://${api_addr}/wsapi/sub`)
# ws.onopen = () => {
#     ws.send(JSON.stringify({
#         container: "...",
#         topic: "...",
#         init: "OLDEST",  // or "MOST_RECENT" or "AWAIT_NEW"
#         iter: "NEXT",  // or "NEWEST"
#     }))
# }
# ws.onmessage = (evt) => {
#     ... evt.data ...
# }
async def sub_wshandler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    msg = await ws.receive()
    cmd = json.loads(msg.data)

    tm = a0.TopicManager(container="api", subscriber_aliases={"topic": cmd})

    init_ = {
        "OLDEST": a0.INIT_OLDEST,
        "MOST_RECENT": a0.INIT_MOST_RECENT,
        "AWAIT_NEW": a0.INIT_AWAIT_NEW,
    }[cmd["init"]]
    iter_ = {"NEXT": a0.ITER_NEXT, "NEWEST": a0.ITER_NEWEST}[cmd["iter"]]

    scheduler = cmd.get("scheduler", "IMMEDIATE")

    async for pkt in a0.aio_sub(tm.subscriber_topic("topic"), init_, iter_):
        await ws.send_json({
            "headers": pkt.headers,
            "payload": base64.b64encode(pkt.payload).decode("utf-8"),
        })
        if scheduler == "IMMEDIATE":
            pass
        elif scheduler == "ON_ACK":
            await ws.receive()


# fetch(`http://${api_addr}/api/rpc`, {
#     method: "POST",
#     body: JSON.stringify({
#         container: "...",
#         topic: "...",
#         packet: {
#             headers: [
#                 ["key", "val"],
#                 ...
#             ],
#             payload: window.btoa("..."),
#         },
#     })
# })
# .then((r) => { return r.text() })
# .then((msg) => { console.log(msg) })
async def rpc_handler(request):
    cmd = await request.json()

    tm = a0.TopicManager(container="api", rpc_client_aliases={
        "topic": cmd,
    })

    client = a0.AioRpcClient(tm.rpc_client_topic("topic"))
    resp = await client.send(
        a0.Packet(cmd["packet"]["headers"],
                  base64.b64decode(cmd["packet"]["payload"])))

    return web.Response(text=json.dumps({
        "headers": resp.headers,
        "payload": base64.b64encode(resp.payload).decode("utf-8"),
    }))


a0.InitGlobalTopicManager({"container": "api"})
heartbeat = a0.Heartbeat()

app = web.Application()
app.add_routes([
    web.get("/api/ls", ls_handler),
    web.post("/api/pub", pub_handler),
    web.post("/api/rpc", rpc_handler),
    web.get("/wsapi/pub", pub_wshandler),
    web.get("/wsapi/sub", sub_wshandler),
])
cors = aiohttp_cors.setup(
    app,
    defaults={
        "*":
            aiohttp_cors.ResourceOptions(allow_credentials=True,
                                         expose_headers="*",
                                         allow_headers="*")
    },
)
for route in list(app.router.routes()):
    cors.add(route)

web.run_app(app, port=24880)
