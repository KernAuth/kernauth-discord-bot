import json
import os
import urllib.request


def post(url, payload, token):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def main():
    base = os.environ["KERNAUTH_API_BASE"].rstrip("/")
    allowed = post(
        f"{base}/v1/customer/api-keys/use",
        {
            "organization_id": os.environ["KERNAUTH_ORGANIZATION_ID"],
            "scope": "licenses:read",
        },
        f"Bearer {os.environ['KERNAUTH_API_KEY']}",
    )
    if allowed.get("authorized") is not True:
        raise SystemExit(1)
    post(
        f"https://discord.com/api/v10/channels/{os.environ['DISCORD_CHANNEL_ID']}/messages",
        {"content": "KernAuth developer key can read licenses."},
        f"Bot {os.environ['DISCORD_TOKEN']}",
    )


if __name__ == "__main__":
    main()
