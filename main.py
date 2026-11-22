import os
import io
import mimetypes
import asyncio
import logging

from telethon import TelegramClient, events, types
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("saver")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]

SAVE_ALL_BOTS = True
IGNORE_BOTS = {
    "BotFather",
}
SKIP_STICKERS_GIFS = True
MAX_SIZE_MB = 200


def _norm(x) -> str:
    return str(x).lstrip("@").lower()


IGNORE_SET = {_norm(x) for x in IGNORE_BOTS}

client = TelegramClient(StringSession(os.environ["SESSION"]), API_ID, API_HASH)

seen: set = set()


def once(key) -> bool:
    if key in seen:
        return False
    if len(seen) > 20000:
        seen.clear()
    seen.add(key)
    return True


def guess_name(media) -> str:
    if isinstance(media, types.MessageMediaPhoto):
        return "photo.jpg"
    if isinstance(media, types.MessageMediaDocument):
        doc = getattr(media, "document", None)
        if isinstance(doc, types.Document):
            for a in doc.attributes:
                if isinstance(a, types.DocumentAttributeFilename):
                    return a.file_name
            ext = mimetypes.guess_extension(doc.mime_type or "") or ""
            if doc.mime_type == "video/mp4":
                ext = ".mp4"
            return f"file{ext or '.bin'}"
    return "file.bin"


def media_size(media) -> int:
    doc = getattr(media, "document", None)
    return getattr(doc, "size", 0) or 0


def is_ignored_bot(sender) -> bool:
    return str(sender.id) in IGNORE_SET or _norm(sender.username or "") in IGNORE_SET


async def send_saved(data: bytes, fname: str, caption: str) -> bool:
    for force_doc in (False, True):
        for _ in range(3):
            try:
                bio = io.BytesIO(data)
                bio.name = fname
                await client.send_file("me", bio, caption=caption, force_document=force_doc)
                return True
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                log.warning("ارسال ناموفق (force_document=%s): %s", force_doc, e)
                break
    return False


async def save_media(msg, label: str):
    key = (msg.chat_id, msg.id)
    if not once(key):
        return

    try:
        data = await client.download_media(msg, file=bytes)
    except Exception as e:
        log.warning("دانلود ناموفق: %s", e)
        return
    if not data:
        log.info("بایتی پیدا نشد: %s", key)
        return

    caption = f"از: {label}"
    if msg.text:
        caption += f"\n\n{msg.text}"
    caption = caption[:1000]

    if await send_saved(data, guess_name(msg.media), caption):
        log.info("ذخیره شد (%s بایت) از %s", len(data), label)
    else:
        log.error("ذخیره نشد: %s", key)


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def saver(event):
    m = event.message
    if not isinstance(m.media, (types.MessageMediaPhoto, types.MessageMediaDocument)):
        return

    if SKIP_STICKERS_GIFS and (m.sticker or m.gif):
        return

    if MAX_SIZE_MB and media_size(m.media) > MAX_SIZE_MB * 1024 * 1024:
        return

    sender = await event.get_sender()
    if sender is None:
        return

    timed = bool(getattr(m.media, "ttl_seconds", None))
    is_bot = bool(getattr(sender, "bot", False))

    if is_bot:
        if not SAVE_ALL_BOTS or is_ignored_bot(sender):
            return
    elif not timed:
        return

    name = getattr(sender, "first_name", "") or getattr(sender, "username", "") or "?"
    await save_media(m, name)


async def main():
    await client.connect()
    if not await client.is_authorized():
        raise SystemExit("SESSION نامعتبره؛ دوباره StringSession بساز.")
    log.info("آماده‌ست و منتظر پیام‌هاست...")
    await client.run_until_disconnected()


client.loop.run_until_complete(main())
