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


def setting_int(name, fallback, low, high):
    raw = os.environ.get(name, "").strip()
    value = fallback if not raw else raw
    try:
        number = int(value)
    except ValueError:
        raise SystemExit(f"{name} must be a whole number")
    if not low <= number <= high:
        raise SystemExit(f"{name} must be from {low} to {high}")
    return number


def setting_color(name, fallback):
    raw = (os.environ.get(name, "").strip() or fallback).removeprefix("#").removeprefix("0x").removeprefix("0X")
    try:
        number = int(raw, 16)
    except ValueError:
        raise SystemExit(f"{name} must be a hex color")
    if not 0 <= number <= 0xFFFFFF:
        raise SystemExit(f"{name} must be a hex color")
    return number


def embed_color():
    return setting_color("EMBED_COLOR", "8B7CF0")


def error_color():
    return setting_color("ERROR_COLOR", "D4534E")


def default_license_days():
    return setting_int("DEFAULT_LICENSE_DAYS", 30, 1, 3650)


def max_license_days():
    return setting_int("MAX_LICENSE_DAYS", 3650, 1, 3650)


def command_permission():
    raw = os.environ.get("COMMAND_PERMISSION", "8").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise SystemExit("COMMAND_PERMISSION must be a permission number")
    return raw


def ephemeral():
    raw = os.environ.get("EPHEMERAL", "true").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise SystemExit("EPHEMERAL must be true or false")


def check_settings():
    embed_color()
    error_color()
    command_permission()
    ephemeral()
    if default_license_days() > max_license_days():
        raise SystemExit("DEFAULT_LICENSE_DAYS cannot be greater than MAX_LICENSE_DAYS")


def clip(value, limit=1024):
    text = str(value).strip()
    return (text or "—")[:limit]


def embed(title, description=None, fields=None, color=None):
    body = {"title": clip(title, 256), "color": embed_color() if color is None else color}
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


registry = []


def text_option(name, description, required=True):
    return {"type": 3, "name": name, "description": description, "required": required}


def number_option(name, description, required=True):
    return {"type": 4, "name": name, "description": description, "required": required}


def command(name, description, *options):
    def decorate(func):
        registry.append({"name": name, "description": description, "options": options, "func": func})
        return func
    return decorate


class SlashGroup:
    def __init__(self, name, description):
        self.name = name
        self.description = description

    def command(self, name, description, *options):
        def decorate(func):
            registry.append({
                "group": self.name,
                "group_description": self.description,
                "name": name,
                "description": description,
                "options": options,
                "func": func,
            })
            return func
        return decorate


app = SlashGroup("app", "Manage an application")
license = SlashGroup("license", "Manage a license")


@command("apps", "List applications")
def apps():
    rows = api("GET", "/v1/workspace/apps")["applications"]
    return cards("Applications", rows, lambda row: field(row["name"], f"{row['status']}\n{code(row['id'])}", False), "No applications.")


@app.command("create", "Create an application", text_option("name", "Name"))
def app_create(name):
    return [app_embed(api("POST", "/v1/workspace/apps", {"name": name})["application"], "Application created")]


@app.command("pause", "Pause an application", text_option("id", "Application id"))
def app_pause(id):
    return [app_embed(api("POST", f"/v1/workspace/apps/{id}/pause")["application"], "Application")]


@app.command("unpause", "Unpause an application", text_option("id", "Application id"))
def app_unpause(id):
    return [app_embed(api("POST", f"/v1/workspace/apps/{id}/unpause")["application"], "Application")]


@app.command("delete", "Delete an application", text_option("id", "Application id"))
def app_delete(id):
    api("DELETE", f"/v1/workspace/apps/{id}")
    return [embed("Application deleted", code(id))]


@command("licenses", "List licenses", text_option("app", "Application id"))
def licenses(app):
    rows = api("GET", f"/v1/workspace/apps/{app}/licenses")["licenses"]
    return cards(
        "Licenses",
        rows,
        lambda row: field(row.get("key_prefix") or "License", f"{row['status']}\n{row.get('expires_at') or 'Lifetime'}\n{code(row['id'])}", False),
        "No licenses.",
    )


@license.command("create", "Create a license", text_option("app", "Application id"), number_option("days", "Days", False))
def license_create(app, days=None):
    made = api("POST", f"/v1/workspace/apps/{app}/licenses", duration(default_license_days() if days is None else days))
    return [license_embed(item["license"], "License created", item["license_key"]) for item in made["licenses"][:10]]


@license.command("pause", "Pause a license", text_option("id", "License id"))
def license_pause(id):
    return [license_embed(api("POST", f"/v1/workspace/licenses/{id}/pause")["license"], "License")]


@license.command("unpause", "Unpause a license", text_option("id", "License id"))
def license_unpause(id):
    return [license_embed(api("POST", f"/v1/workspace/licenses/{id}/unpause")["license"], "License")]


@license.command("extend", "Extend a license", text_option("id", "License id"), number_option("days", "Days"))
def license_extend(id, days):
    return [license_embed(api("POST", f"/v1/workspace/licenses/{id}/extend", duration(days))["license"], "License extended")]


@license.command("delete", "Delete a license", text_option("id", "License id"))
def license_delete(id):
    api("DELETE", f"/v1/workspace/licenses/{id}")
    return [embed("License deleted", code(id))]


@license.command("reset", "Reset the computer slot", text_option("id", "License id"))
def license_reset(id):
    api("POST", f"/v1/workspace/licenses/{id}/reset-devices")
    return [embed("Computer slot reset", code(id))]


@license.command("key", "Show the license key", text_option("id", "License id"))
def license_key(id):
    return [embed("License key", code(api("GET", f"/v1/workspace/licenses/{id}/key")["license_key"]))]


def slash_payload():
    permission = command_permission()
    commands = []
    groups = {}
    for item in registry:
        if "group" not in item:
            body = {"name": item["name"], "description": item["description"], "dm_permission": False}
            if permission is not None:
                body["default_member_permissions"] = permission
            if item["options"]:
                body["options"] = prepared(item["options"])
            commands.append(body)
            continue
        if item["group"] not in groups:
            body = {"name": item["group"], "description": item["group_description"], "dm_permission": False, "options": []}
            if permission is not None:
                body["default_member_permissions"] = permission
            groups[item["group"]] = body
            commands.append(body)
        groups[item["group"]]["options"].append({
            "type": 1,
            "name": item["name"],
            "description": item["description"],
            "options": prepared(item["options"]),
        })
    return commands


def prepared(options):
    made = []
    for option in options:
        item = dict(option)
        if item["type"] == 4:
            item["min_value"] = 1
            item["max_value"] = max_license_days()
        made.append(item)
    return made


def perform(data):
    options = data.get("options") or []
    try:
        if options and "value" not in options[0]:
            func = find(data.get("name", ""), options[0]["name"])
            args = {item["name"]: item["value"] for item in options[0].get("options") or []}
        else:
            func = find(data.get("name", ""), None)
            args = {item["name"]: item["value"] for item in options}
        if func is None:
            return [embed("Unknown command")]
        return func(**args)[:10]
    except Exception as error:
        return [embed("Error", text_of(error), color=error_color())]


def find(name, sub):
    for item in registry:
        grouped = item.get("group")
        if sub is None and grouped is None and item["name"] == name:
            return item["func"]
        if grouped == name and item["name"] == sub:
            return item["func"]
    return None


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
            {"type": 5, "data": {"flags": 64}} if ephemeral() else {"type": 5},
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
            {"embeds": embeds, "flags": 64} if ephemeral() else {"embeds": embeds},
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
    check_settings()
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
                slash_payload(),
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
