import json
import os
import sys
import urllib.error
import urllib.request

USAGE = """apps
app create <name>
app pause <id>
app unpause <id>
app delete <id>
licenses <app-id>
license create <app-id> [days]
license pause <id>
license unpause <id>
license extend <id> <days>
license delete <id>
license reset <id>
license key <id>"""


def call(url, payload, token, method):
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": token, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise SystemExit(error.read().decode() or str(error.code))


def api(method, path, payload=None):
    base = os.environ["KERNAUTH_API_BASE"].rstrip("/")
    return call(path and f"{base}{path}", payload, f"Bearer {os.environ['KERNAUTH_API_KEY']}", method)


def discord(text):
    call(
        f"https://discord.com/api/v10/channels/{os.environ['DISCORD_CHANNEL_ID']}/messages",
        {"content": text[:1900]},
        f"Bot {os.environ['DISCORD_TOKEN']}",
        "POST",
    )


def duration(days):
    return {"duration": {"unit": "days", "amount": int(days)}}


def app_line(row):
    return f"{row['id']} {row['name']} {row['status']}"


def license_line(row):
    return f"{row['id']} {row['key_prefix']} {row['status']}"


def run(args):
    if not args:
        return USAGE
    command, *rest = args
    if command == "apps" and not rest:
        rows = api("GET", "/v1/workspace/apps")["applications"]
        return "\n".join(app_line(row) for row in rows) or "No applications."
    if command == "app" and rest[:1] == ["create"] and len(rest) > 1:
        return app_line(api("POST", "/v1/workspace/apps", {"name": " ".join(rest[1:])})["application"])
    if command == "app" and len(rest) == 2 and rest[0] in {"pause", "unpause"}:
        return app_line(api("POST", f"/v1/workspace/apps/{rest[1]}/{rest[0]}")["application"])
    if command == "app" and len(rest) == 2 and rest[0] == "delete":
        api("DELETE", f"/v1/workspace/apps/{rest[1]}")
        return f"Deleted {rest[1]}"
    if command == "licenses" and len(rest) == 1:
        rows = api("GET", f"/v1/workspace/apps/{rest[0]}/licenses")["licenses"]
        return "\n".join(license_line(row) for row in rows) or "No licenses."
    if command == "license" and rest[:1] == ["create"] and len(rest) in {2, 3}:
        made = api("POST", f"/v1/workspace/apps/{rest[1]}/licenses", duration(rest[2] if len(rest) == 3 else 30))
        return "\n".join(f"{item['license']['id']} {item['license_key']}" for item in made["licenses"])
    if command == "license" and rest[:1] == ["extend"] and len(rest) == 3:
        return license_line(api("POST", f"/v1/workspace/licenses/{rest[1]}/extend", duration(rest[2]))["license"])
    if command == "license" and len(rest) == 2 and rest[0] in {"pause", "unpause"}:
        return license_line(api("POST", f"/v1/workspace/licenses/{rest[1]}/{rest[0]}")["license"])
    if command == "license" and len(rest) == 2 and rest[0] == "delete":
        api("DELETE", f"/v1/workspace/licenses/{rest[1]}")
        return f"Deleted {rest[1]}"
    if command == "license" and len(rest) == 2 and rest[0] == "reset":
        api("POST", f"/v1/workspace/licenses/{rest[1]}/reset-devices")
        return f"Reset {rest[1]}"
    if command == "license" and len(rest) == 2 and rest[0] == "key":
        return api("GET", f"/v1/workspace/licenses/{rest[1]}/key")["license_key"]
    return USAGE


def main():
    discord(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
