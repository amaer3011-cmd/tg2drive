# Telegram → Google Drive Bot

بوت بيرفع الملفات (أو الروابط المباشرة) من تليجرام إلى Google Drive ويرجعلك لينك.

## 1) تجهيز المفاتيح
- **تليجرام**: `API_ID` و`API_HASH` من https://my.telegram.org ، و`BOT_TOKEN` من @BotFather.
- **جوجل**: في Google Cloud Console
  1. فعّل **Google Drive API**.
  2. اعمل **OAuth client ID** من نوع **TVs and Limited Input devices**.
  3. في **OAuth consent screen** اضغط **Publish app** (يبقى In production).
     > لو سيبته على Testing، الـ refresh token بيخلص بعد 7 أيام وهتضطر تعمل /link كل أسبوع.
     > الصلاحية المستخدمة `drive.file` مش حساسة فمش محتاجة مراجعة من جوجل.

## 2) النشر على Railway
1. ارفع الفولدر ده على GitHub (ملف `.env` متجاهَل تلقائياً).
2. في Railway: **New Project → Deploy from GitHub repo** واختار الريبو. هيتبني من `Dockerfile` تلقائي.
3. من تبويب **Variables** ضيف:
   ```
   API_ID, API_HASH, BOT_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
   DATA_DIR=/data
   TMP_DIR=/data/tmp
   ```
   (واختياري: `ALLOWED_USERS`, `MAX_JOBS`, `SESSION_STRING`)
4. **مهم جداً – Volume**: على الخدمة اضغط **Add Volume** (أو Ctrl/Cmd+K → Volume) واعمل Mount Path = `/data`.
   من غيره التوكنات وجلسة البوت هتتمسح مع كل Deploy، وكمان الملفات المؤقتة محتاجة مساحة.
   - حجم الـ Volume لازم يكون أكبر من أكبر ملف هترفعه (+ هامش). الخطة المجانية/Hobby مساحتها محدودة، فراجع حدود خطتك.
5. اضغط **Deploy** وراجع الـ Logs، لازم تشوف `Bot running...`.
6. افتح البوت في تليجرام وابعت `/start` ثم `/link`.

## 3) للملفات الأكبر من 2 جيجا
- الحل الأسهل: ابعت **رابط مباشر** وهينزله البوت ويرفعه بدون حد.
- حساب Premium: شغّل `python gen_session.py` على جهازك، حط الناتج في `SESSION_STRING` على Railway، وابعت الملف في **Saved Messages**.
  (`SESSION_STRING` بيدي صلاحية كاملة على حسابك، خليه سري.)

## 4) تشغيل محلي
```bash
pip install -r requirements.txt
cp .env.example .env   # واملاه (وامسح سطور DATA_DIR/TMP_DIR أو خليهم ./data)
python bot.py
```

## الأوامر
`/link` `/unlink` `/status` `/share` `/folder` `/history` `/cancel`

## ملاحظات
- لازم نسخة واحدة بس من البوت شغالة (Replicas = 1)، ومتشغلوش على جهازك وعلى Railway في نفس الوقت بنفس التوكن.
- الرفع بيعدي على السيرفر، فاستهلاك الـ bandwidth والمساحة على حسب حجم الملفات.
