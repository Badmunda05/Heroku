import pyromod.listen  # noqa
from pyrogram import Client, filters
from config import *

app = Client(
    name="BAD",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)

filters.sudo = filters.create(
    lambda _, __, m: bool(m.from_user and m.from_user.id in OWNER_ID),
    "SudoFilter",
)
