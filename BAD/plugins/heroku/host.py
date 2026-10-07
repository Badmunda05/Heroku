import asyncio
import os
import time

import aiohttp
import requests
import urllib3
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyromod.exceptions import ListenerTimeout

from BAD import app
from BAD.helpers import batbin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEROKU_API_URL = "https://api.heroku.com"
HEROKU_API_KEY = os.getenv("HEROKU_API_KEY")  # Pre-defined variable
REPO_URL = "https://github.com/Badmunda05/ShizuMusic"
BRANCH_NAME = None
BUILDPACK_URL = "https://github.com/heroku/heroku-buildpack-python"
UPSTREAM_REPO = "https://github.com/Badmunda05/ShizuMusic"  # Pre-defined variable
UPSTREAM_BRANCH = "master"  # Pre-defined variable
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

import re


def convert_to_small_caps(text):
    # Mapping for regular letters to small caps
    mapping = str.maketrans(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘϙʀꜱᴛᴜᴠᴡxʏᴢABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )

    # Function to apply the translation, skipping special parts
    def replace(match):
        # Skip text that starts with {, /, is inside `...`, or looks like a URL
        if (
            match.group(0).startswith("{")
            or match.group(0).startswith("/")
            or match.group(0).startswith("`")
        ):
            return match.group(0)
        if re.match(r"https?://", match.group(0)):  # Detect URLs
            return match.group(0)
        return match.group(0).translate(mapping)

    # Regex to match text outside {}, `...`, /commands, and URLs
    pattern = r"\{.*?\}|`[^`]+`|/\w+|https?://\S+|\w+"

    # Apply translation to matches outside the excluded parts
    return re.sub(pattern, replace, text)


def fetch_app_json(repo_url, branch_name):
    app_json_url = f"{repo_url}/raw/{branch_name}/app.json"  # Use the provided branch
    response = requests.get(app_json_url)
    return response.json() if response.status_code == 200 else None


def make_heroku_request(endpoint, api_key, method="get", payload=None):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
    }
    url = f"{HEROKU_API_URL}/{endpoint}"
    response = getattr(requests, method)(url, headers=headers, json=payload)
    return response.status_code, (
        response.json() if response.status_code == 200 else None
    )


async def fetch_apps():
    status, apps = make_heroku_request("apps", HEROKU_API_KEY)
    return apps if status == 200 else None


def _default_of(var_info):
    """Default value from app.json (as string) or None when there is none."""
    value = var_info.get("value")
    if value is None or str(value) == "":
        return None
    return str(value)


async def collect_env_variables(message, env_vars):
    user_inputs = {}
    used_default, not_set = [], []
    await message.reply_text(
        convert_to_small_caps(
            "Provide the values for the environment variables.\n\n"
            "/skip - use the default value (if no default, the variable is left empty)\n"
            "/cancel - cancel the deployment"
        )
    )

    for var_name, var_info in env_vars.items():
        if var_name in [
            "HEROKU_APP_NAME",
            "HEROKU_API_KEY",
            "UPSTREAM_REPO",
            "UPSTREAM_BRANCH",
            "API_ID",
            "API_HASH",
        ]:
            continue  # Skip hardcoded variables

        description = var_info.get("description", "")
        default = _default_of(var_info)
        required = var_info.get("required", True)

        default_line = (
            f"`{default[:300]}`"
            if default is not None
            else "none (variable stays empty if you skip)"
        )
        prompt = (
            f"Provide a value for **{var_name}**\n\n"
            f"**About:** {description}\n"
            f"**Default:** {default_line}\n"
            f"**Required:** {'Yes' if required else 'No'}\n\n"
            + (
                "Send the value, or /skip to use the default, or /cancel to stop hosting."
                if default is not None
                else "Send the value, or /skip to leave it empty, or /cancel to stop hosting."
            )
        )

        try:
            while True:
                response = await app.ask(message.chat.id, prompt, timeout=300)
                text = (response.text or "").strip()
                if text:
                    break
                await message.reply_text("Please send the value as text.")
        except ListenerTimeout:
            await message.reply_text(
                "Timeout! You must provide the variables within 5 Minutes. Restart the process to deploy."
            )
            return None

        command = text.split("@")[0].lower()
        if command == "/cancel":
            await message.reply_text("**Deployment canceled.**")
            return None
        if command == "/skip":
            if default is not None:
                user_inputs[var_name] = default
                used_default.append(var_name)
            else:
                not_set.append(var_name)
            continue
        user_inputs[var_name] = response.text

    summary = []
    if used_default:
        summary.append("Default used: " + ", ".join(used_default))
    if not_set:
        summary.append("Not set (skipped): " + ", ".join(not_set))
    if summary:
        await message.reply_text("\n".join(summary))

    # Add hardcoded variables
    user_inputs["HEROKU_APP_NAME"] = app_name
    user_inputs["HEROKU_API_KEY"] = HEROKU_API_KEY
    user_inputs["UPSTREAM_REPO"] = UPSTREAM_REPO
    user_inputs["UPSTREAM_BRANCH"] = UPSTREAM_BRANCH
    user_inputs["API_ID"] = API_ID
    user_inputs["API_HASH"] = API_HASH

    return user_inputs


async def check_app_name_availability(app_name):
    # Try to create a temporary app with the provided name
    status, result = make_heroku_request(
        "apps",
        HEROKU_API_KEY,
        method="post",
        payload={"name": app_name, "region": "us", "stack": "container"},
    )
    if status == 201:
        # App created successfully, now delete it
        delete_status, delete_result = make_heroku_request(
            f"apps/{app_name}",
            HEROKU_API_KEY,
            method="delete",
        )
        if delete_status == 200:
            return True  # App name is available
    else:
        return False  # App name is not available


async def fetch_repo_branches(REPO_URL):
    owner_repo = REPO_URL.replace("https://github.com/", "").split("/")
    api_url = f"https://api.github.com/repos/{owner_repo[0]}/{owner_repo[1]}/branches"

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 200:
                branches_data = await response.json()
                return [branch["name"] for branch in branches_data]
            else:
                return []  # Return empty if fetch fails


# Add this new function to display buttons for upstream or external repo
async def ask_repo_choice(message):
    buttons = [
        [
            InlineKeyboardButton(
                convert_to_small_caps("sʜɪᴢᴜ ᴍᴜsɪᴄ"), callback_data="deploy_upstream"
            ),
        ],
        [
            InlineKeyboardButton(
                convert_to_small_caps("ᴏᴛʜᴇʀ ʀᴇᴘᴏ"), callback_data="deploy_external"
            ),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text(
        convert_to_small_caps(
            "From which repo do you want to deploy from the **SHIZU MUSIC** or an **Any External Other Repo**?"
        ),
        reply_markup=reply_markup,
    )


async def ask_for_branch(callback_query, branches, default_branch):
    branch_buttons = [
        [
            InlineKeyboardButton(
                convert_to_small_caps(branch), callback_data=f"branch_{branch}"
            )
        ]
        for branch in branches
    ]
    reply_markup = InlineKeyboardMarkup(branch_buttons)

    await callback_query.message.reply_text(
        convert_to_small_caps(
            f"Select the branch to deploy from (default is **{default_branch}**):"
        ),
        reply_markup=reply_markup,
    )


# This handles the /host command and displays the repo choice buttons
@app.on_message(filters.command("host") & filters.private & filters.sudo)
async def host_app(client, message):
    await ask_repo_choice(message)


@app.on_callback_query(filters.regex(r"deploy_(upstream|external)") & filters.sudo)
async def handle_repo_choice(client, callback_query):
    global REPO_URL
    choice = callback_query.data.split("_")[1]

    if choice == "upstream":
        REPO_URL = "https://github.com/Badmunda05/ShizuMusic"
        branches = await fetch_repo_branches(REPO_URL)
        default_branch = "master"
        await ask_for_branch(callback_query, branches, default_branch)

    elif choice == "external":
        try:
            response = await app.ask(
                callback_query.message.chat.id,
                convert_to_small_caps(
                    "**Please provide me any public external GitHub repo URL:**\n\nType /cancel for cancel the process"
                ),
                timeout=300,
            )

            if response.text == "/cancel":
                await response.reply_text(
                    convert_to_small_caps("**Deployment canceled.**")
                )
                REPO_URL = "https://github.com/Badmunda05/ShizuMusic"
                return None

            REPO_URL = response.text
            branches = await fetch_repo_branches(REPO_URL)

            if branches is None:
                await callback_query.message.reply_text(
                    convert_to_small_caps(
                        "No Branches Found. I think your repo is invalid or has no branches. Please try again."
                    )
                )
                return await handle_repo_choice(client, callback_query)

            default_branch = "master"
            UPSTREAM_REPO = REPO_URL
            await ask_for_branch(callback_query, branches, default_branch)

        except Exception as e:
            if response.text == "/cancel":
                await response.reply_text(
                    convert_to_small_caps("**Deployment canceled.**")
                )
                REPO_URL = "https://github.com/Badmunda05/ShizuMusic"
                return None

            await callback_query.message.reply_text(
                convert_to_small_caps(
                    "**You have provided either a private repo or an invalid public repo.**"
                )
            )
            return await handle_repo_choice(client, callback_query)

        except ListenerTimeout:
            REPO_URL = "https://github.com/Badmunda05/ShizuMusic"
            await callback_query.message.edit_text(
                convert_to_small_caps(
                    "Timeout! You must provide the external repo URL within 5 minutes."
                )
            )
            return


@app.on_callback_query(filters.regex(r"branch_") & filters.sudo)
async def handle_branch_selection(client, callback_query):
    global BRANCH_NAME
    BRANCH_NAME = callback_query.data.split("_")[1]
    await collect_app_info(callback_query.message)


def create_build(app_name, source_url):
    """Start a build and return (status_code, json). The JSON holds the build id
    and its live `output_stream_url` (make_heroku_request drops 201 bodies)."""
    headers = {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
    }
    response = requests.post(
        f"{HEROKU_API_URL}/apps/{app_name}/builds",
        headers=headers,
        json={"source_blob": {"url": source_url}},
        timeout=60,
    )
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


BUILD_POLL_SECONDS = 10  # how often the live log message is refreshed
BUILD_TIMEOUT_SECONDS = 30 * 60


async def _stream_build_output(url, lines):
    """Read Heroku's live build output into `lines` until the stream closes."""
    try:
        timeout = aiohttp.ClientTimeout(total=None, sock_read=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                async for raw in resp.content:
                    lines.append(raw.decode(errors="replace").rstrip("\r\n"))
    except Exception:
        pass  # the status poll below still tells us how the build ended


async def _build_result_lines(app_name, build_id):
    """Fallback: fetch the finished build's log from the result endpoint."""
    status, data = await asyncio.to_thread(
        make_heroku_request,
        f"apps/{app_name}/builds/{build_id}/result",
        HEROKU_API_KEY,
    )
    if status == 200 and isinstance(data, dict):
        return [item.get("line", "").rstrip("\r\n") for item in data.get("lines", [])]
    return []


def _progress_text(app_name, title, link, lines):
    tail = "\n".join(lines[-12:]).replace("`", "'")[-1500:]
    text = f"{title}\n\nApp: {app_name}"
    if link:
        text += f"\nFull logs: {link}"
    if tail:
        text += f"\n\n```\n{tail}\n```"
    return text


async def watch_build(message, app_name, build, reply_markup):
    """Show live build logs (refreshed every 10s) until the build finishes."""
    build_id = build["id"]
    lines = []
    reader = None
    if build.get("output_stream_url"):
        reader = asyncio.create_task(
            _stream_build_output(build["output_stream_url"], lines)
        )

    progress = await message.reply_text(
        convert_to_small_caps(
            f"⌛ Deploying. Live logs refresh every {BUILD_POLL_SECONDS} seconds..."
        )
    )
    started = time.monotonic()
    state = "pending"
    last_len, link = -1, None

    try:
        while True:
            await asyncio.sleep(BUILD_POLL_SECONDS)

            code, info = await asyncio.to_thread(
                make_heroku_request,
                f"apps/{app_name}/builds/{build_id}",
                HEROKU_API_KEY,
            )
            if code == 200 and isinstance(info, dict):
                state = info.get("status", state)
            finished = state != "pending"
            if not finished and time.monotonic() - started > BUILD_TIMEOUT_SECONDS:
                state, finished = "timeout", True

            if finished and not lines:
                lines.extend(await _build_result_lines(app_name, build_id))

            if len(lines) != last_len:  # upload only when there is new output
                last_len = len(lines)
                link = await batbin("\n".join(lines)) or link

            if finished:
                break
            try:
                await progress.edit_text(
                    _progress_text(app_name, "⌛ Deploying... (live logs)", link, lines),
                )
            except Exception:
                pass  # e.g. message not modified / flood wait
    finally:
        if reader:
            reader.cancel()

    try:
        await progress.delete()
    except Exception:
        pass

    if state == "succeeded":
        await message.reply_text(
            convert_to_small_caps("✅ Deployed Successfully...✨\n\n🥀 Please turn on dynos 👇")
            + (f"\n\nBuild logs: {link}" if link else ""),
            reply_markup=reply_markup,
        )
    else:
        reason = "timed out" if state == "timeout" else f"status: {state}"
        await message.reply_text(
            _progress_text(app_name, f"❌ Build did not succeed ({reason})", link, lines),
        )


async def collect_app_info(message):
    global app_name
    global BRANCH_NAME
    global REPO_URL
    while True:
        try:
            response = await app.ask(
                message.chat.id,
                convert_to_small_caps(
                    "**Provide a Heroku app name (small letters):**\n\n**Type /cancel to stop the process**"
                ),
                timeout=300,
            )
            app_name = response.text
            if app_name == "/cancel":
                await message.reply_text(
                    convert_to_small_caps("**Deployment canceled.**")
                )
                REPO_URL = "https://github.com/Badmunda05/ShizuMusic"
                return None
        except ListenerTimeout:
            await message.reply_text(
                convert_to_small_caps("Timeout! Restart the process again to deploy.")
            )
            return await collect_app_info(message)

        if await check_app_name_availability(app_name):
            await message.reply_text(
                convert_to_small_caps(
                    f"App name `{app_name}` is available. Proceeding..."
                )
            )
            break
        else:
            await message.reply_text(
                convert_to_small_caps(
                    "This app name is not available. Try another one."
                )
            )

    app_json = fetch_app_json(REPO_URL, BRANCH_NAME)

    if not app_json:
        await message.reply_text(
            convert_to_small_caps("Could not fetch app.json from the selected branch.")
        )
        return

    env_vars = app_json.get("env", {})
    user_inputs = await collect_env_variables(message, env_vars)
    if user_inputs is None:
        return

    status, result = make_heroku_request(
        "apps",
        HEROKU_API_KEY,
        method="post",
        payload={"name": app_name, "region": "us", "stack": "container"},
    )
    if status == 201:
        await message.reply_text(
            convert_to_small_caps("✅ Done! Your app has been created.")
        )

        make_heroku_request(
            f"apps/{app_name}/config-vars",
            HEROKU_API_KEY,
            method="patch",
            payload=user_inputs,
        )

        status, result = await asyncio.to_thread(
            create_build, app_name, f"{REPO_URL}/tarball/{BRANCH_NAME}"
        )

        buttons = [
            [
                InlineKeyboardButton(
                    convert_to_small_caps("Turn On Dynos"),
                    callback_data=f"dyno_on:{app_name}",
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        if status == 201 and isinstance(result, dict) and result.get("id"):
            await watch_build(message, app_name, result, reply_markup)
        else:
            await message.reply_text(
                convert_to_small_caps(f"Error triggering build: {status} {result}")
            )

    else:
        await message.reply_text(
            convert_to_small_caps(f"Error deploying app: {result}")
        )


# ============================CHECK APP==================================#


@app.on_message(
    filters.command(["heroku", "hosts", "hosted", "mybots", "myhost"]) & filters.sudo
)
async def get_deployed_apps(client, message):
    apps = await fetch_apps()

    if not apps:
        await message.reply_text(convert_to_small_caps("No apps found on Heroku."))
        return

    buttons = [
        [
            InlineKeyboardButton(
                convert_to_small_caps(app["name"]), callback_data=f"app:{app['name']}"
            )
        ]
        for app in apps
    ]

    buttons.append(
        [InlineKeyboardButton(convert_to_small_caps("Back"), callback_data="main_menu")]
    )

    # Send the inline keyboard markup
    reply_markup = InlineKeyboardMarkup(buttons)

    await message.reply_text(
        convert_to_small_caps("Select an app:"), reply_markup=reply_markup
    )


