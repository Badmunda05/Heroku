import asyncio
import os
import re
import shutil
import tarfile
import tempfile

import requests
from pyrogram import filters
from pyromod.exceptions import ListenerTimeout

from BAD import app
from BAD.plugins.heroku.callback import convert_to_small_caps
from config import GITHUB_TOKEN, GIT_USER_EMAIL, GIT_USER_NAME, HEROKU_API_KEY
from config import OWNER_ID as SUDOERS

HEROKU_API_URL = "https://api.heroku.com"
HEADERS = {
    "Authorization": f"Bearer {HEROKU_API_KEY}",
    "Accept": "application/vnd.heroku+json; version=3",
}

# Buildpack/runtime folders that are not part of the app's own code
TOP_LEVEL_EXCLUDE = {".git", ".apt", ".heroku", ".chrome-for-testing", ".profile.d", "vendor"}
GITIGNORE_LINES = [
    ".git/",
    ".apt/",
    ".heroku/",
    ".chrome-for-testing/",
    ".profile.d/",
    "vendor/",
    "__pycache__/",
    "*.pyc",
    ".env",
    "*.session",
]
GITHUB_URL_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def sc(text):
    return convert_to_small_caps(text)


# ----------------------------- Heroku helpers -----------------------------#


def _get_json(path, extra_headers=None):
    headers = dict(HEADERS)
    headers.update(extra_headers or {})
    r = requests.get(f"{HEROKU_API_URL}/{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _find_source(app_name):
    """Return (download_url, kind). kind is 'slug' (running code) or 'build' (deploy source)."""
    releases = _get_json(
        f"apps/{app_name}/releases", {"Range": "version ..; order=desc,max=20"}
    )
    for rel in releases:
        slug = rel.get("slug")
        if slug and slug.get("id"):
            data = _get_json(f"apps/{app_name}/slugs/{slug['id']}")
            url = (data.get("blob") or {}).get("url")
            if url:
                return url, "slug"

    # Container-stack apps have no slug: fall back to the source of the last good build
    builds = _get_json(
        f"apps/{app_name}/builds", {"Range": "created_at ..; order=desc,max=10"}
    )
    for build in builds:
        if build.get("status") == "succeeded":
            url = (build.get("source_blob") or {}).get("url")
            if url:
                return url, "build"
    return None, None


def _download_and_extract(url, kind, dest_dir, workdir):
    """Download the tarball and extract only the app's own files. Returns file count."""
    tgz = os.path.join(workdir, "source.tgz")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tgz, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                f.write(chunk)

    os.makedirs(dest_dir, exist_ok=True)
    root = os.path.realpath(dest_dir)
    count = 0
    with tarfile.open(tgz) as tar:
        for member in tar:
            parts = [p for p in member.name.split("/") if p not in ("", ".")]
            if kind == "slug":  # slug layout: ./app/<files>
                if not parts or parts[0] != "app":
                    continue
            parts = parts[1:]  # strip "app" (slug) or the GitHub "owner-repo-sha" folder
            if not parts:
                continue
            if (
                parts[0] in TOP_LEVEL_EXCLUDE
                or "__pycache__" in parts
                or parts[-1].endswith(".pyc")
            ):
                continue

            target = os.path.realpath(os.path.join(root, *parts))
            if target != root and not target.startswith(root + os.sep):
                continue  # path traversal guard

            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with tar.extractfile(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, member.mode & 0o777 or 0o644)
                count += 1
            # symlinks/hardlinks/devices are skipped on purpose
    return count


async def _fetch_app_source(app_name, workdir):
    """Download the app's code into workdir/<app_name>. Returns (folder, file_count, kind)."""
    url, kind = await asyncio.to_thread(_find_source, app_name)
    if not url:
        return None, 0, None
    dest = os.path.join(workdir, app_name)
    count = await asyncio.to_thread(_download_and_extract, url, kind, dest, workdir)
    return dest, count, kind


def _short_error(e):
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code} from Heroku/source server"
    return f"{type(e).__name__}: {str(e)[:200]}"


# ------------------------------ Git helpers -------------------------------#


async def _git(args, cwd, secret=None):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode(errors="replace")
    if secret:
        text = text.replace(secret, "***")
    return proc.returncode, text


async def _commit_and_push(folder, remote_url, secret=None):
    """init -> commit -> push to main. Returns (ok, output)."""
    with open(os.path.join(folder, ".gitignore"), "a") as f:
        f.write("\n" + "\n".join(GITIGNORE_LINES) + "\n")

    identity = ["-c", f"user.name={GIT_USER_NAME}", "-c", f"user.email={GIT_USER_EMAIL}"]
    steps = [
        ["init"],
        ["add", "-A"],
        [*identity, "commit", "-m", "Initial commit"],
        ["branch", "-M", "main"],
        ["remote", "add", "origin", remote_url],
        ["push", "-u", "origin", "main"],
    ]
    for step in steps:
        code, out = await _git(step, folder, secret)
        if code != 0:
            return False, f"git {step[0] if step[0] != '-c' else 'commit'} failed:\n{out}"
    return True, "ok"


# -------------------------------- Handlers --------------------------------#


@app.on_callback_query(filters.regex(r"^dl_code:(.+)") & filters.sudo)
async def download_code(client, callback_query):
    app_name = callback_query.data.split(":", 1)[1]
    await callback_query.answer()
    status = await callback_query.message.reply_text(
        sc(f"Fetching code of {app_name} from Heroku...")
    )
    workdir = tempfile.mkdtemp(prefix="hsrc_")
    try:
        folder, count, kind = await _fetch_app_source(app_name, workdir)
        if not folder or count == 0:
            await status.edit_text(
                sc("No downloadable code found for this app (no slug and no successful build).")
            )
            return

        zip_path = await asyncio.to_thread(
            shutil.make_archive, os.path.join(workdir, app_name), "zip", folder
        )
        origin = "running slug (/app)" if kind == "slug" else "last build source"
        await callback_query.message.reply_document(
            zip_path,
            caption=sc(f"Code of {app_name}\nFiles: {count}\nSource: {origin}"),
        )
        await status.delete()
    except Exception as e:
        await status.edit_text(f"Failed to download code: {_short_error(e)}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.on_callback_query(filters.regex(r"^push_code:(.+)") & filters.sudo)
async def push_code(client, callback_query):
    app_name = callback_query.data.split(":", 1)[1]
    await callback_query.answer()
    chat_id = callback_query.message.chat.id

    if not GITHUB_TOKEN:
        await callback_query.message.reply_text(
            sc("GITHUB_TOKEN is not set. Add a GitHub token (repo access) as a config var and restart the bot.")
        )
        return

    try:
        response = await app.ask(
            chat_id,
            sc(
                "Send the target GitHub repo URL (e.g. https://github.com/user/repo). "
                "It should be an empty repo. Send /cancel to stop."
            ),
            timeout=90,
        )
    except ListenerTimeout:
        await callback_query.message.reply_text(sc("Timeout! Push canceled."))
        return

    if not response.from_user or response.from_user.id not in SUDOERS:
        await callback_query.message.reply_text(sc("Only SUDOERS can answer. Push canceled."))
        return
    text = (response.text or "").strip()
    if text == "/cancel":
        await callback_query.message.reply_text(sc("Push canceled."))
        return
    match = GITHUB_URL_RE.match(text)
    if not match:
        await callback_query.message.reply_text(
            sc("That is not a valid https://github.com/owner/repo URL. Push canceled.")
        )
        return

    owner, repo = match.groups()
    clean_url = f"https://github.com/{owner}/{repo}"
    remote_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{owner}/{repo}.git"

    status = await callback_query.message.reply_text(
        sc(f"Downloading code of {app_name}...")
    )
    workdir = tempfile.mkdtemp(prefix="hpush_")
    try:
        folder, count, _ = await _fetch_app_source(app_name, workdir)
        if not folder or count == 0:
            await status.edit_text(sc("No downloadable code found for this app."))
            return

        await status.edit_text(sc(f"Pushing {count} files to {clean_url} ..."))
        ok, output = await _commit_and_push(folder, remote_url, secret=GITHUB_TOKEN)
        if ok:
            await status.edit_text(
                sc("Code pushed successfully!") + f"\n\n{clean_url}",
            )
        else:
            await status.edit_text(f"Push failed.\n\n`{output[-800:]}`")
    except Exception as e:
        await status.edit_text(f"Failed to push code: {_short_error(e)}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
