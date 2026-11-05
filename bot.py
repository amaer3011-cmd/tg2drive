import os, re, json, time, asyncio, tempfile, shutil, threading, itertools
from urllib.parse import urlparse, unquote
import requests
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommandScopeDefault, BotCommand
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

load_dotenv()
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
G_ID = os.environ["GOOGLE_CLIENT_ID"]
G_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()}
MAX_JOBS = int(os.getenv("MAX_JOBS", "2"))
DEFAULT_FOLDER = os.getenv("DEFAULT_FOLDER", "Telegram Uploads")
DATA_DIR = os.getenv("DATA_DIR", ".")
TMP_DIR = os.getenv("TMP_DIR") or None
SESSION = os.getenv("SESSION_STRING", "").strip()

SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKENS = os.path.join(DATA_DIR, "tokens.json")
CHUNK = 64 * 1024 * 1024  # مضاعف 256KB

os.makedirs(DATA_DIR, exist_ok=True)
if TMP_DIR:
    os.makedirs(TMP_DIR, exist_ok=True)

client = TelegramClient(os.path.join(DATA_DIR, "bot"), API_ID, API_HASH)
user_client = TelegramClient(StringSession(SESSION), API_ID, API_HASH) if SESSION else None

LOOP = None
SEM = None
JOBS = {}
_ids = itertools.count(1)
pending_links = set()
_lock = threading.Lock()


# ================= أدوات مساعدة =================
class Cancelled(Exception):
    pass


class Job:
    def __init__(self, owner):
        self.id, self.owner, self.cancelled = next(_ids), owner, False

    def check(self):
        if self.cancelled:
            raise Cancelled()


def hsize(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.2f} TB"


def hms(s):
    s = int(s)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02}:{sec:02}" if h else f"{m}:{sec:02}"


def safe_name(n):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", n).strip() or "file"


def free_check(path, need):
    free = shutil.disk_usage(path).free
    if need and free < need + 200 * 1024 * 1024:
        raise RuntimeError(f"المساحة على السيرفر مش كفاية (متاح {hsize(free)}، المطلوب {hsize(need)})")


# ================= التخزين =================
def load():
    with _lock:
        try:
            with open(TOKENS) as f:
                return json.load(f)
        except Exception:
            return {}


def save(d):
    with _lock:
        tmp = TOKENS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, TOKENS)


def update_user(uid, **kw):
    d = load()
    d.setdefault(str(uid), {}).update(kw)
    save(d)


def get_creds(u):
    c = Credentials(None, refresh_token=u["refresh_token"],
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=G_ID, client_secret=G_SECRET, scopes=[SCOPE])
    c.refresh(Request())
    return c


# ================= شريط التقدم =================
class Progress:
    def __init__(self, msg, label, job, bot_mode):
        self.msg, self.label, self.job, self.bot_mode = msg, label, job, bot_mode
        self.start, self.last = time.time(), 0

    async def __call__(self, cur, total):
        self.job.check()
        now = time.time()
        if now - self.last < 3 and cur != total:
            return
        self.last = now
        speed = cur / max(now - self.start, 1e-6)
        pct = int(cur * 100 / total) if total else 0
        eta = (total - cur) / speed if speed and total else 0
        bar = "▰" * (pct // 10) + "▱" * (10 - pct // 10)
        text = (f"{self.label}\n{bar} {pct}%\n{hsize(cur)} / {hsize(total)}\n"
                f"⚡ {hsize(speed)}/s  ⏳ {hms(eta)}")
        try:
            await self.msg.edit(text, buttons=cancel_btn(self.job) if self.bot_mode else None)
        except Exception:
            pass

    def sync(self, cur, total):  # من thread
        self.job.check()
        asyncio.run_coroutine_threadsafe(self(cur, total), LOOP)


def cancel_btn(job):
    return [Button.inline("❌ إلغاء", f"c:{job.id}".encode())]


# ================= Google Drive =================
def ensure_folder(svc, name):
    name = name.replace("\\", "\\\\").replace("'", "\\'")
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    r = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    if r.get("files"):
        return r["files"][0]["id"]
    return svc.files().create(
        body={"name": name.replace("\\'", "'"), "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()["id"]


def upload_to_drive(creds, path, name, share, folder, job, progress):
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    parent = ensure_folder(svc, folder)
    media = MediaFileUpload(path, chunksize=CHUNK, resumable=True)
    req = svc.files().create(body={"name": name, "parents": [parent]},
                             media_body=media, fields="id,webViewLink")
    size, resp = os.path.getsize(path), None
    while resp is None:
        job.check()
        status, resp = req.next_chunk(num_retries=5)
        if status:
            progress.sync(int(status.progress() * size), size)
    progress.sync(size, size)
    if share:
        svc.permissions().create(fileId=resp["id"], body={"type": "anyone", "role": "reader"}).execute()
    return resp["webViewLink"], resp["id"]


def delete_from_drive(creds, file_id):
    build("drive", "v3", credentials=creds, cache_discovery=False).files().delete(fileId=file_id).execute()


# ================= تحميل من رابط =================
def download_url(url, dest, progress):
    with requests.get(url, stream=True, timeout=30, allow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        free_check(dest, total)
        name = None
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", r.headers.get("content-disposition", ""))
        if m:
            name = unquote(m.group(1))
        name = safe_name(name or unquote(os.path.basename(urlparse(r.url).path)) or "file")
        path = os.path.join(dest, name)
        done = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(8 * 1024 * 1024):
                f.write(chunk)
                done += len(chunk)
                progress.sync(done, total or done)
    return path, name


# ================= المعالجة الرئيسية =================
async def process(event, source, bot_mode):
    uid = event.sender_id
    u = load().get(str(uid))
    if not u or "refresh_token" not in u:
        return await event.reply("اربط حسابك الأول بـ /link")

    job = Job(uid)
    JOBS[job.id] = job
    status = await event.reply("⏳ في الانتظار...", buttons=cancel_btn(job) if bot_mode else None)
    tmp = None
    try:
        async with SEM:
            job.check()
            creds = await asyncio.to_thread(get_creds, u)
            tmp = tempfile.mkdtemp(dir=TMP_DIR)

            if source == "telegram":
                free_check(tmp, event.file.size or 0)
                name = safe_name(event.file.name or f"file_{event.id}{event.file.ext or ''}")
                path = await event.download_media(
                    file=os.path.join(tmp, name),
                    progress_callback=Progress(status, "⬇️ تحميل من تليجرام", job, bot_mode))
            else:
                p = Progress(status, "⬇️ تحميل من الرابط", job, bot_mode)
                path, name = await asyncio.to_thread(download_url, source, tmp, p)

            job.check()
            size = os.path.getsize(path)
            up = Progress(status, f"⬆️ رفع إلى Drive\n📄 {name}", job, bot_mode)
            link, fid = await asyncio.to_thread(
                upload_to_drive, creds, path, name, u.get("share", False),
                u.get("folder", DEFAULT_FOLDER), job, up)

        hist = (load().get(str(uid), {}).get("history", []) + [
            {"name": name, "link": link, "t": int(time.time())}])[-10:]
        update_user(uid, history=hist)
        btns = [[Button.url("🔗 فتح الملف", link)],
                [Button.inline("🗑 حذف من Drive", f"d:{fid}".encode())]] if bot_mode else None
        await status.edit(f"✅ تم الرفع\n📄 {name}\n📦 {hsize(size)}\n🔗 {link}",
                          buttons=btns, link_preview=False)
    except Cancelled:
        await status.edit("🚫 تم الإلغاء", buttons=None)
    except RefreshError:
        await status.edit("⚠️ انتهى الربط مع جوجل، ابعت /link تاني.", buttons=None)
    except Exception as e:
        await status.edit(f"❌ حصل خطأ: {str(e)[:300]}", buttons=None)
    finally:
        JOBS.pop(job.id, None)
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# ================= ربط الحساب (Device Flow) =================
async def link_flow(event):
    uid = event.sender_id
    if uid in pending_links:
        return await event.reply("في عملية ربط شغالة بالفعل.")
    r = (await asyncio.to_thread(requests.post, "https://oauth2.googleapis.com/device/code",
                                 data={"client_id": G_ID, "scope": SCOPE})).json()
    if "device_code" not in r:
        return await event.reply(f"خطأ من جوجل: {r}")
    await event.reply(
        f"1) افتح: {r['verification_url']}\n2) اكتب الكود: `{r['user_code']}`\n"
        f"3) وافق على الصلاحيات.\nمعاك {r['expires_in'] // 60} دقيقة، وهبلغك أول ما يتم.",
        link_preview=False)
    pending_links.add(uid)
    interval, deadline = r.get("interval", 5), time.time() + r["expires_in"]
    try:
        while time.time() < deadline:
            await asyncio.sleep(interval)
            t = (await asyncio.to_thread(
                requests.post, "https://oauth2.googleapis.com/token",
                data={"client_id": G_ID, "client_secret": G_SECRET, "device_code": r["device_code"],
                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})).json()
            if "refresh_token" in t:
                update_user(uid, refresh_token=t["refresh_token"], share=False)
                return await event.reply("✅ تم ربط Google Drive. ابعت أي ملف أو رابط مباشر.")
            err = t.get("error")
            if err == "slow_down":
                interval += 5
            elif err != "authorization_pending":
                return await event.reply(f"❌ فشل الربط: {err}")
        await event.reply("⌛ انتهى الوقت، ابعت /link تاني.")
    finally:
        pending_links.discard(uid)


# ================= الهاندلرز =================
HELP = ("أهلاً 👋\n/link ربط Google Drive\n/unlink فصل الحساب\n/status حالة الربط\n"
        "/share تشغيل/إيقاف الروابط العامة\n/folder <اسم> تغيير فولدر الرفع\n"
        "/history آخر 10 ملفات\n/cancel إلغاء كل عملياتك الحالية\n\n"
        "ابعت ملف أو رابط مباشر (ممكن أكتر من رابط في رسالة) وهرفعه وأديك اللينك.")


def register(c, bot_mode):
    kw = dict(incoming=True) if bot_mode else dict(outgoing=True, chats="me")

    def allowed(e):
        return (not bot_mode) or (not ALLOWED) or e.sender_id in ALLOWED

    def cmd(p):
        return c.on(events.NewMessage(pattern=p, func=allowed, **kw))

    @cmd(r"^/start")
    async def _(e):
        await e.reply(HELP)

    @cmd(r"^/link")
    async def _(e):
        await link_flow(e)

    @cmd(r"^/unlink")
    async def _(e):
        d = load()
        d.pop(str(e.sender_id), None)
        save(d)
        await e.reply("تم فصل الحساب.")

    @cmd(r"^/status")
    async def _(e):
        u = load().get(str(e.sender_id))
        if not u or "refresh_token" not in u:
            return await e.reply("غير مربوط ❌")
        await e.reply(f"مربوط ✅\nروابط عامة: {'نعم' if u.get('share') else 'لا'}\n"
                      f"الفولدر: {u.get('folder', DEFAULT_FOLDER)}\n"
                      f"عمليات شغالة: {sum(1 for j in JOBS.values() if j.owner == e.sender_id)}")

    @cmd(r"^/share")
    async def _(e):
        u = load().get(str(e.sender_id))
        if not u:
            return await e.reply("اربط حسابك الأول بـ /link")
        update_user(e.sender_id, share=not u.get("share", False))
        await e.reply("الروابط الجاية: " + ("عامة (أي حد معاه اللينك)" if not u.get("share") else "خاصة (ليك بس)"))

    @cmd(r"^/folder(?:\s+(.+))?$")
    async def _(e):
        arg = e.pattern_match.group(1)
        if not load().get(str(e.sender_id)):
            return await e.reply("اربط حسابك الأول بـ /link")
        if not arg:
            cur = load()[str(e.sender_id)].get("folder", DEFAULT_FOLDER)
            return await e.reply(f"الفولدر الحالي: {cur}\nلتغييره: /folder اسم الفولدر")
        update_user(e.sender_id, folder=arg.strip())
        await e.reply(f"✅ الفولدر دلوقتي: {arg.strip()} (هيتعمل تلقائي لو مش موجود)")

    @cmd(r"^/history")
    async def _(e):
        h = load().get(str(e.sender_id), {}).get("history", [])
        if not h:
            return await e.reply("لسه مفيش ملفات اترفعت.")
        await e.reply("\n\n".join(f"📄 {x['name']}\n🔗 {x['link']}" for x in reversed(h)),
                      link_preview=False)

    @cmd(r"^/cancel")
    async def _(e):
        n = 0
        for j in JOBS.values():
            if j.owner == e.sender_id:
                j.cancelled, n = True, n + 1
        await e.reply(f"تم إلغاء {n} عملية." if n else "مفيش عمليات شغالة.")

    @c.on(events.NewMessage(func=lambda e: allowed(e) and e.file, **kw))
    async def _(e):
        await process(e, "telegram", bot_mode)

    @c.on(events.NewMessage(func=lambda e: allowed(e) and not e.file and e.raw_text
                            and not e.raw_text.startswith("/") and "http" in e.raw_text, **kw))
    async def _(e):
        for url in dict.fromkeys(re.findall(r"https?://\S+", e.raw_text)):
            asyncio.create_task(process(e, url, bot_mode))

    if bot_mode:
        @c.on(events.CallbackQuery(pattern=rb"^c:(\d+)$"))
        async def _(e):
            j = JOBS.get(int(e.pattern_match.group(1)))
            if j and j.owner == e.sender_id:
                j.cancelled = True
                await e.answer("جاري الإلغاء...")
            else:
                await e.answer("العملية انتهت.", alert=False)

        @c.on(events.CallbackQuery(pattern=rb"^d:(.+)$"))
        async def _(e):
            fid = e.pattern_match.group(1).decode()
            u = load().get(str(e.sender_id))
            if not u:
                return await e.answer("اربط حسابك الأول.", alert=True)
            try:
                creds = await asyncio.to_thread(get_creds, u)
                await asyncio.to_thread(delete_from_drive, creds, fid)
                await e.edit("🗑 تم حذف الملف من Drive.", buttons=None)
            except Exception as ex:
                await e.answer(f"فشل الحذف: {str(ex)[:150]}", alert=True)


register(client, True)
if user_client:
    register(user_client, False)


async def main():
    global LOOP, SEM
    LOOP, SEM = asyncio.get_running_loop(), asyncio.Semaphore(MAX_JOBS)
    await client.start(bot_token=BOT_TOKEN)
    await client(SetBotCommandsRequest(scope=BotCommandScopeDefault(), lang_code="", commands=[
        BotCommand("link", "ربط Google Drive"), BotCommand("unlink", "فصل الحساب"),
        BotCommand("status", "حالة الربط"), BotCommand("share", "روابط عامة/خاصة"),
        BotCommand("folder", "تغيير فولدر الرفع"), BotCommand("history", "آخر الملفات"),
        BotCommand("cancel", "إلغاء العمليات")]))
    if user_client:
        await user_client.start()
        print("Userbot mode ON: ابعت الملفات الكبيرة في Saved Messages")
    print("Bot running...")
    await asyncio.gather(client.run_until_disconnected(),
                         *([user_client.run_until_disconnected()] if user_client else []))


if __name__ == "__main__":
    asyncio.run(main())
