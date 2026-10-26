import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request

FATAL = {4004, 4010, 4011, 4012, 4013, 4014}


def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def call(url, payload, token, method):
    headers = {"Content-Type": "application/json", "User-Agent": "KernAuth"}
    if token:
        headers["Authorization"] = token
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode() or str(error.code))
    except urllib.error.URLError as error:
        raise RuntimeError(str(error.reason))


def api(method, path, payload=None):
    base = os.environ["KERNAUTH_API_BASE"].rstrip("/")
    return call(f"{base}{path}", payload, f"Bearer {os.environ['KERNAUTH_API_KEY']}", method)


def duration(days):
    return {"duration": {"unit": "days", "amount": int(days)}}


COLOR = 0x8B7CF0


def clip(value, limit=1024):
    text = str(value).strip()
    return (text or "—")[:limit]


def embed(title, description=None, fields=None, color=COLOR):
    body = {"title": clip(title, 256), "color": color}
    if description:
        body["description"] = clip(description, 4096)
    if fields:
        body["fields"] = fields[:25]
    return body


def field(name, value, inline=True):
    return {"name": clip(name, 256), "value": clip(value), "inline": inline}


def code(value):
    return f"`{clip(value, 1000).replace('`', '\'')}`"


def cards(title, rows, make, empty):
    if not rows:
        return [embed(title, empty)]
    made = []
    for start in range(0, len(rows), 25):
        made.append(embed(
            title if not made else f"{title} {len(made) + 1}",
            fields=[make(row) for row in rows[start:start + 25]],
        ))
        if len(made) == 10:
            break
    return made


def app_embed(row, title):
    return embed(title, fields=[
        field("Name", row["name"]),
        field("Status", row["status"]),
        field("Slug", row.get("slug") or "—"),
        field("Id", code(row["id"]), False),
    ])


def license_embed(row, title, key=None):
    return embed(title, fields=[
        field("Key", code(key or row.get("key_prefix") or "—"), False),
        field("Status", row.get("status") or "—"),
        field("Expires", row.get("expires_at") or "Lifetime"),
        field("Id", code(row["id"]), False),
    ])


def text_of(error):
    text = str(error)
    try:
        text = json.loads(text).get("message") or text
    except json.JSONDecodeError:
        pass
    return str(text)[:4096]


def handle(name, sub, picked):
    if name == "apps":
        rows = api("GET", "/v1/workspace/apps")["applications"]
        return cards("Applications", rows, lambda row: field(row["name"], f"{row['status']}\n{code(row['id'])}", False), "No applications.")
    if name == "app" and sub == "create":
        return [app_embed(api("POST", "/v1/workspace/apps", {"name": picked["name"]})["application"], "Application created")]
    if name == "app" and sub in {"pause", "unpause"}:
        return [app_embed(api("POST", f"/v1/workspace/apps/{picked['id']}/{sub}")["application"], "Application")]
    if name == "app" and sub == "delete":
        api("DELETE", f"/v1/workspace/apps/{picked['id']}")
        return [embed("Application deleted", code(picked["id"]))]
    if name == "licenses":
        rows = api("GET", f"/v1/workspace/apps/{picked['app']}/licenses")["licenses"]
        return cards(
            "Licenses",
            rows,
            lambda row: field(row.get("key_prefix") or "License", f"{row['status']}\n{row.get('expires_at') or 'Lifetime'}\n{code(row['id'])}", False),
            "No licenses.",
        )
    if name == "license" and sub == "create":
        made = api("POST", f"/v1/workspace/apps/{picked['app']}/licenses", duration(picked.get("days", 30)))
        return [license_embed(item["license"], "License created", item["license_key"]) for item in made["licenses"][:10]]
    if name == "license" and sub == "extend":
        return [license_embed(api("POST", f"/v1/workspace/licenses/{picked['id']}/extend", duration(picked["days"]))["license"], "License extended")]
    if name == "license" and sub in {"pause", "unpause"}:
        return [license_embed(api("POST", f"/v1/workspace/licenses/{picked['id']}/{sub}")["license"], "License")]
    if name == "license" and sub == "delete":
        api("DELETE", f"/v1/workspace/licenses/{picked['id']}")
        return [embed("License deleted", code(picked["id"]))]
    if name == "license" and sub == "reset":
        api("POST", f"/v1/workspace/licenses/{picked['id']}/reset-devices")
        return [embed("Computer slot reset", code(picked["id"]))]
    if name == "license" and sub == "key":
        return [embed("License key", code(api("GET", f"/v1/workspace/licenses/{picked['id']}/key")["license_key"]))]
    return [embed("Unknown command")]


def perform(data):
    top = data.get("options") or []
    if top and "value" not in top[0]:
        sub = top[0]["name"]
        picked = {item["name"]: item["value"] for item in top[0].get("options") or []}
    else:
        sub = ""
        picked = {item["name"]: item["value"] for item in top}
    try:
        return handle(data.get("name", ""), sub, picked)[:10]
    except Exception as error:
        return [embed("Error", text_of(error), color=0xD4534E)]


class Socket:
    def __init__(self, sock, extra):
        self.sock = sock
        self.buf = extra
        self.lock = threading.Lock()

    def read(self, size):
        while len(self.buf) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:size], self.buf[size:]
        return out

    def send(self, payload, opcode=1):
        data = payload if isinstance(payload, (bytes, bytearray)) else payload.encode()
        mask = os.urandom(4)
        size = len(data)
        head = bytearray([0x80 | opcode])
        if size < 126:
            head.append(0x80 | size)
        elif size < 65536:
            head.append(0x80 | 126)
            head += struct.pack("!H", size)
        else:
            head.append(0x80 | 127)
            head += struct.pack("!Q", size)
        masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(data))
        with self.lock:
            self.sock.sendall(bytes(head) + mask + masked)

    def recv(self):
        parts = []
        while True:
            first, second = self.read(2)
            opcode = first & 15
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            if size > 1_000_000:
                raise ConnectionError("frame")
            mask = self.read(4) if second & 128 else None
            data = self.read(size)
            if mask:
                data = bytes(byte ^ mask[index & 3] for index, byte in enumerate(data))
            if opcode == 8:
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 0
                if code in FATAL:
                    raise SystemExit(f"Discord closed {code}")
                raise ConnectionError(code)
            if opcode == 9:
                self.send(data, 10)
                continue
            if opcode == 10 or opcode == 2:
                continue
            if opcode in {0, 1}:
                parts.append(data)
                if first & 128:
                    return json.loads(b"".join(parts))


def connect(url):
    rest = url[len("wss://"):]
    hostport, _, tail = rest.partition("/")
    host = hostport.split(":")[0]
    path = "/" + tail if tail else "/"
    raw = socket.create_connection((host, 443), timeout=20)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    key = os.urandom(16)
    sock.sendall(
        (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {base64.b64encode(key).decode()}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("gateway closed")
        data += chunk
    head, extra = data.split(b"\r\n\r\n", 1)
    if b" 101 " not in head.split(b"\r\n", 1)[0]:
        raise ConnectionError(head.decode()[:300])
    sock.settimeout(None)
    return sock, extra


def answer(interaction):
    if interaction.get("type") != 2:
        return
    try:
        call(
            f"https://discord.com/api/v10/interactions/{interaction['id']}/{interaction['token']}/callback",
            {"type": 5, "data": {"flags": 64}},
            None,
            "POST",
        )
    except Exception as error:
        print(text_of(error))
        return
    embeds = perform(interaction.get("data") or {})
    try:
        call(
            f"https://discord.com/api/v10/webhooks/{interaction['application_id']}/{interaction['token']}",
            {"embeds": embeds, "flags": 64},
            None,
            "POST",
        )
    except Exception as error:
        print(text_of(error))


def listen(url, token):
    sock, extra = connect(f"{url}/?v=10&encoding=json")
    ws = Socket(sock, extra)
    hello = ws.recv()
    seq = [None]
    stop = threading.Event()
    interval = hello["d"]["heartbeat_interval"] / 1000

    def beat():
        while not stop.is_set():
            try:
                ws.send(json.dumps({"op": 1, "d": seq[0]}))
            except Exception:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                return
            if stop.wait(interval):
                return

    threading.Thread(target=beat, daemon=True).start()
    ws.send(json.dumps({
        "op": 2,
        "d": {
            "token": token,
            "intents": 0,
            "properties": {"os": "linux", "browser": "kernauth", "device": "kernauth"},
        },
    }))
    try:
        while True:
            payload = ws.recv()
            if payload.get("s") is not None:
                seq[0] = payload["s"]
            op = payload.get("op")
            if op == 1:
                ws.send(json.dumps({"op": 1, "d": seq[0]}))
            elif op in {7, 9}:
                return
            elif op == 0 and payload.get("t") == "READY":
                print("Ready")
            elif op == 0 and payload.get("t") == "INTERACTION_CREATE":
                threading.Thread(target=answer, args=(payload["d"],), daemon=True).start()
    finally:
        stop.set()
        sock.close()


def main():
    load_env()
    missing = [key for key in ("KERNAUTH_API_BASE", "KERNAUTH_API_KEY", "DISCORD_TOKEN", "DISCORD_GUILD_ID") if not os.environ.get(key)]
    if missing:
        raise SystemExit("Missing " + ", ".join(missing))
    token = os.environ["DISCORD_TOKEN"].removeprefix("Bot ").strip()
    auth = f"Bot {token}"
    try:
        app_id = call("https://discord.com/api/v10/oauth2/applications/@me", None, auth, "GET")["id"]
    except Exception as error:
        raise SystemExit(text_of(error))
    print(f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands")
    guild = os.environ["DISCORD_GUILD_ID"].strip()
    while True:
        try:
            call(
                f"https://discord.com/api/v10/applications/{app_id}/guilds/{guild}/commands",
                [
                    {
                        "name": "apps",
                        "description": "List applications",
                        "dm_permission": False,
                        "default_member_permissions": "8",
                    },
                    {
                        "name": "app",
                        "description": "Manage an application",
                        "dm_permission": False,
                        "default_member_permissions": "8",
                        "options": [
                            {"type": 1, "name": "create", "description": "Create an application", "options": [
                                {"type": 3, "name": "name", "description": "Name", "required": True},
                            ]},
                            {"type": 1, "name": "pause", "description": "Pause an application", "options": [
                                {"type": 3, "name": "id", "description": "Application id", "required": True},
                            ]},
                            {"type": 1, "name": "unpause", "description": "Unpause an application", "options": [
                                {"type": 3, "name": "id", "description": "Application id", "required": True},
                            ]},
                            {"type": 1, "name": "delete", "description": "Delete an application", "options": [
                                {"type": 3, "name": "id", "description": "Application id", "required": True},
                            ]},
                        ],
                    },
                    {
                        "name": "licenses",
                        "description": "List licenses",
                        "dm_permission": False,
                        "default_member_permissions": "8",
                        "options": [
                            {"type": 3, "name": "app", "description": "Application id", "required": True},
                        ],
                    },
                    {
                        "name": "license",
                        "description": "Manage a license",
                        "dm_permission": False,
                        "default_member_permissions": "8",
                        "options": [
                            {"type": 1, "name": "create", "description": "Create a license", "options": [
                                {"type": 3, "name": "app", "description": "Application id", "required": True},
                                {"type": 4, "name": "days", "description": "Days", "required": False, "min_value": 1, "max_value": 3650},
                            ]},
                            {"type": 1, "name": "pause", "description": "Pause a license", "options": [
                                {"type": 3, "name": "id", "description": "License id", "required": True},
                            ]},
                            {"type": 1, "name": "unpause", "description": "Unpause a license", "options": [
                                {"type": 3, "name": "id", "description": "License id", "required": True},
                            ]},
                            {"type": 1, "name": "extend", "description": "Extend a license", "options": [
                                {"type": 3, "name": "id", "description": "License id", "required": True},
                                {"type": 4, "name": "days", "description": "Days", "required": True, "min_value": 1, "max_value": 3650},
                            ]},
                            {"type": 1, "name": "delete", "description": "Delete a license", "options": [
                                {"type": 3, "name": "id", "description": "License id", "required": True},
                            ]},
                            {"type": 1, "name": "reset", "description": "Reset the computer slot", "options": [
                                {"type": 3, "name": "id", "description": "License id", "required": True},
                            ]},
                            {"type": 1, "name": "key", "description": "Show the license key", "options": [
                                {"type": 3, "name": "id", "description": "License id", "required": True},
                            ]},
                        ],
                    },
                ],
                auth,
                "PUT",
            )
            print("Registered commands")
            break
        except RuntimeError as error:
            print(text_of(error))
            time.sleep(10)
    while True:
        try:
            gateway = call("https://discord.com/api/v10/gateway/bot", None, auth, "GET")["url"]
            listen(gateway.rstrip("/"), token)
        except SystemExit:
            raise
        except Exception as error:
            print(text_of(error))
        time.sleep(5)


if __name__ == "__main__":
    main()
