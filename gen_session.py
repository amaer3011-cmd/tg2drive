"""شغّله مرة واحدة على جهازك عشان تطلع SESSION_STRING لحسابك (Premium) """
import os
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

load_dotenv()
with TelegramClient(StringSession(), int(os.environ["API_ID"]), os.environ["API_HASH"]) as c:
    print("\nSESSION_STRING=" + c.session.save())
    print("\n⚠️ ده بيدي صلاحية كاملة على حسابك، متشاركوش مع حد.")
