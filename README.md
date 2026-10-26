# KernAuth Discord bot

A small Discord bot that manages KernAuth applications and licenses with slash commands. It stays online, registers its commands in one server, and answers with embeds.

The bot is one Python file, `bot.py`. It uses the Python standard library and talks to the [KernAuth developer API](https://kernauth.apidog.io) at `https://api.kernauth.com`. There is nothing to install with pip.

Anyone who can run a command can create, pause, and delete licenses for the organization that owns the API key. Put the bot in a private server, and leave the commands limited to administrators.

## Requirements

- Python 3.9 or newer. Check with `python3 --version`.
- A KernAuth organization on the Pro or Business plan. Free and Starter cannot create a developer API key, and the API rejects those plans with `plan_limit_exceeded`.
- A Discord application with a bot token.
- The server id of the Discord server where the commands should appear.

The process has to keep running. Closing the terminal stops the bot, and Discord then reports that the command failed.

## 1. Create the Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and create an application.
2. Open **Bot** and click **Reset Token**. Copy the token. This is `DISCORD_TOKEN`.
3. Leave the privileged gateway intents off. This bot does not read messages.
4. In the Discord app, open **User Settings → Advanced** and turn on **Developer Mode**.
5. Right-click the server icon and choose **Copy Server ID**. This is `DISCORD_GUILD_ID`.

You invite the bot after the first start. The script prints the invite link.

## 2. Create the KernAuth API key

In the KernAuth dashboard, open **Developers** and create an API key. Copy the `ka_…` secret when it is shown. KernAuth does not show it again.

Give the key these scopes:

| Scope | Used by |
| --- | --- |
| `apps:read` | `/apps` |
| `apps:write` | `/app create`, `/app pause`, `/app unpause`, `/app delete` |
| `licenses:read` | `/licenses` |
| `licenses:write` | `/license create`, `/license pause`, `/license unpause`, `/license extend`, `/license delete`, `/license reset` |
| `licenses:reveal` | `/license key` |

`/license key` is the only command that needs `licenses:reveal`. The other license commands work without it. `/licenses` shows the stored key prefix, not the full key.

A key locked to one application can manage only that application. It cannot create an application, and it cannot touch licenses on another application. A key with no application selected can manage every application in its organization.

The key cannot change billing, team members, webhooks, or other API keys. It also cannot read an application's payload key.

## 3. Configure

```bash
cp .env.example .env
```

`.env.example` looks like this:

```
KERNAUTH_API_BASE=https://api.kernauth.com
KERNAUTH_API_KEY=ka_replace_me
DISCORD_TOKEN=replace_me
DISCORD_GUILD_ID=replace_me
EMBED_COLOR=8B7CF0
ERROR_COLOR=D4534E
DEFAULT_LICENSE_DAYS=30
MAX_LICENSE_DAYS=3650
COMMAND_PERMISSION=8
EPHEMERAL=true
```

| Variable | Meaning |
| --- | --- |
| `KERNAUTH_API_BASE` | API origin, without a trailing path. Use `https://api.kernauth.com` unless you are running the API yourself. |
| `KERNAUTH_API_KEY` | The `ka_…` developer key. |
| `DISCORD_TOKEN` | The bot token. A leading `Bot ` is optional. The script strips it. |
| `DISCORD_GUILD_ID` | The server where slash commands are registered. Commands do not appear in any other server. |
| `EMBED_COLOR` | Hex color for successful embeds. The default is `8B7CF0`. A leading `#` is optional. |
| `ERROR_COLOR` | Hex color for the error embed. The default is `D4534E`. |
| `DEFAULT_LICENSE_DAYS` | Days used by `/license create` when Days is left empty. The default is 30. |
| `MAX_LICENSE_DAYS` | Largest day count Discord will accept. The default and the API cap are 3650. |
| `COMMAND_PERMISSION` | Discord permission number required to see the commands. `8` is Administrator. Leave it empty so every member can use them. |
| `EPHEMERAL` | `true` shows the embed only to the person who ran the command. `false` posts it in the channel. |

The first four variables are required. The rest have the defaults above when they are omitted. `DEFAULT_LICENSE_DAYS` cannot be higher than `MAX_LICENSE_DAYS`, and both must be from 1 to 3650.

`bot.py` reads `.env` from the same directory. A variable that is already set in the environment wins over the file. Do not commit `.env`. It contains the API key and the bot token.

## 4. Run

From the directory that contains `bot.py` and `.env`:

```bash
python3 bot.py
```

On Windows, `python bot.py` is the same command if that executable is Python 3.9 or newer.

On startup the script:

1. Checks that the four required variables are set. If one is missing, it exits with `Missing …`. It also checks the customization values.
2. Calls Discord and prints an invite URL:

   `https://discord.com/oauth2/authorize?client_id=…&scope=bot%20applications.commands`

3. Registers the slash commands in `DISCORD_GUILD_ID`. If the bot is not in that server yet, Discord rejects the registration. The script prints the error and tries again every 10 seconds. Open the invite URL, add the bot to that server, and wait for `Registered commands`.
4. Connects to the Discord gateway and prints `Ready`.

The invite URL requests the `bot` and `applications.commands` scopes. It does not request channel permissions. The bot answers through the interaction, so it does not need Send Messages.

Leave this process running. If the gateway connection drops, the script reconnects after 5 seconds. A bad bot token makes Discord close the session, and the script exits with `Discord closed 4004`.

Guild commands show up in that server as soon as registration succeeds. Restart `bot.py` after you change a command or `.env`. Each start replaces this application's commands in that server.

## Commands

Commands work in the registered server. They do not work in direct messages. Discord shows them to members who have the permission in `COMMAND_PERMISSION`. The default, `8`, is Administrator, which includes the server owner. Leave that value empty to allow every member. A server admin can change a command later in **Server Settings → Integrations → KernAuth**.

Type `/` in a channel and choose the command. With `EPHEMERAL=true`, only the person who ran the command can see the embed.

### Applications

| Command | What it does |
| --- | --- |
| `/apps` | Lists applications. Each field shows the name, status, and id. |
| `/app create name:<name>` | Creates an application in the API key's organization. The slug is generated by KernAuth. |
| `/app pause id:<app id>` | Pauses an application. |
| `/app unpause id:<app id>` | Unpauses an application. |
| `/app delete id:<app id>` | Deletes an application. |

An application embed shows the name, status, slug, and id. Copy the id from `/apps` for the other commands. Application ids look like `app_…`.

### Licenses

| Command | What it does |
| --- | --- |
| `/licenses app:<app id>` | Lists licenses for one application. Each field shows the key prefix, status, expiry, and license id. |
| `/license create app:<app id> days:<days>` | Creates one license. `days` is optional and uses `DEFAULT_LICENSE_DAYS`. The allowed range is 1 to `MAX_LICENSE_DAYS`. |
| `/license pause id:<license id>` | Pauses a license. |
| `/license unpause id:<license id>` | Unpauses a license. |
| `/license extend id:<license id> days:<days>` | Adds days to the license. `days` is required, from 1 to `MAX_LICENSE_DAYS`. |
| `/license delete id:<license id>` | Deletes a license. |
| `/license reset id:<license id>` | Clears the saved computer on that license so the next activation can take the slot. |
| `/license key id:<license id>` | Shows the stored license key. Needs the `licenses:reveal` scope. |

License ids look like `lic_…`.

`/license create` asks KernAuth to generate the key. The bot does not invent the key. The embed titled **License created** includes the full key once. Copy it from there. Later, `/licenses` shows only the prefix. Run `/license key` when you need the stored key again.

An empty list is an embed whose description is `No applications.` or `No licenses.` A long list uses up to 25 fields on an embed and up to 10 embeds.

Expiry is the license `expires_at` time, or `Lifetime` when the license has no expiry. The create command in this bot always sends a day count, so a license it creates is not lifetime.

## Replies

Successful embeds use `EMBED_COLOR`. A KernAuth or Discord error becomes an embed titled **Error** in `ERROR_COLOR`. The description is the API `message` when the body is JSON, otherwise the response text.

The bot acknowledges the slash command immediately. KernAuth is called next, and the embed is sent as the command reply. KernAuth calls time out after 30 seconds.

## Access and safety

- The bot holds one developer key for one organization. It does not ask the Discord user to sign in, and it does not check which KernAuth user they are.
- `COMMAND_PERMISSION=8` keeps the commands on administrators so a normal member cannot reveal or delete keys. That limit is a Discord permission. It is not a second KernAuth login.
- With `EPHEMERAL=true`, the reply is visible to the person who ran the command. Copy the key from that embed and treat it as a secret. `EPHEMERAL=false` posts the key in the channel.
- Pausing an application or a license blocks validation. Delete removes the record. Reset only clears the computer slot.
- Do not put the API key, the bot token, or a real license key in a screenshot of the embed, in git, or in a public channel.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `Missing KERNAUTH_API_KEY` (or another name) | Fill in `.env`, or export the variable, then start the script again. |
| Discord `401` before an invite URL | The bot token is wrong. Reset it in the Developer Portal and update `DISCORD_TOKEN`. |
| Registration error mentioning unknown guild, or missing access | `DISCORD_GUILD_ID` is not the server you invited, or the invite has not finished. Open the printed URL and add the bot to that server. The script keeps retrying. |
| Commands do not appear | Confirm the terminal printed `Registered commands` and `Ready`. In Discord, type `/` and look under this bot. Guild commands are only in `DISCORD_GUILD_ID`. |
| A command is missing for a non-admin | Expected. Give that member Administrator, or allow the command in the server's integration settings. |
| Red embed `plan_limit_exceeded` | The organization is on Free or Starter. Developer keys require Pro or Business. |
| Red embed `Organization access denied` | The key is missing the scope for that command, or it is locked to a different application. |
| Red embed `Authentication failed` | `KERNAUTH_API_KEY` is revoked, expired, or not a `ka_…` key. |
| `Discord closed 4004` | Discord rejected the bot token at the gateway. Reset the token and start again. |
| The interaction fails as soon as you click it | The Python process is not running, or it lost its connection and has not printed `Ready` again. |

## What this example does not do

- It does not validate a license from a game or desktop app. Use a KernAuth client SDK for that.
- It does not sell plans, issue invoices, or grant a plan because someone clicked a button.
- It does not read sessions, audit events, webhooks, team members, or the payload key.
- It does not register global slash commands. One server, registered on startup, is the whole scope.
- It does not keep a database. Discord is the interface. KernAuth stores the applications and licenses.
