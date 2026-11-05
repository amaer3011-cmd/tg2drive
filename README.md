# Telegram → Google Drive Bot

بوت يرفع الملفات والروابط المباشرة من تليجرام إلى Google Drive ويرسل رابط الملف.

## المتطلبات قبل النشر

1. أنشئ بوت Telegram من [@BotFather](https://t.me/BotFather)، وخذ `BOT_TOKEN`.
2. خذ `API_ID` و`API_HASH` من [my.telegram.org](https://my.telegram.org).
3. في Google Cloud فعّل **Google Drive API** وأنشئ OAuth client من نوع **TVs and Limited Input devices**. ضع `GOOGLE_CLIENT_ID` و`GOOGLE_CLIENT_SECRET` في إعدادات الخدمة، ولا ترفعها إلى GitHub.
4. أكمل إعداد شاشة موافقة OAuth وأضف حساب Google الذي سيجري الربط إلى المستخدمين المسموح لهم أثناء الاختبار، أو أكمل متطلبات Google المناسبة لاستخدامك. تفاصيل التدفق في [توثيق Google الرسمي](https://developers.google.com/identity/protocols/oauth2/limited-input-device).

## النشر على Railway

هذا المشروع **عامل خلفي دائم التشغيل** وليس موقعاً؛ لا يحتاج نطاقاً عاماً أو متغير `PORT` أو فحص صحة HTTP.

1. في Railway أنشئ مشروعاً جديداً واختر **Deploy from GitHub repo** ثم المستودع `amaer3011-cmd/tg2drive`. اترك مجلد الجذر على جذر المستودع. Railway سيكتشف `Dockerfile` ويستخدمه لتشغيل `python bot.py`.
2. أضف هذه المتغيرات في إعدادات الخدمة، مع استبدال القيم التجريبية بالقيم الحقيقية:

   ```text
   API_ID=1234567
   API_HASH=...
   BOT_TOKEN=...
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   DATA_DIR=/data
   TMP_DIR=/data/tmp
   ```

   المتغيرات `API_ID`, `API_HASH`, `BOT_TOKEN`, `GOOGLE_CLIENT_ID`, و`GOOGLE_CLIENT_SECRET` مطلوبة؛ غياب أي منها يمنع التطبيق من بدء التشغيل. أضف `ALLOWED_USERS` اختيارياً كقائمة أرقام Telegram مفصولة بفواصل، و`MAX_JOBS` و`DEFAULT_FOLDER` حسب الحاجة.

3. أضف **Volume** إلى خدمة البوت واجعل مسار التركيب `/data`. التطبيق يخزن ربط Google وملف جلسة Telegram في هذا المسار؛ من دون Volume ستفقد هذه البيانات عند إعادة إنشاء الحاوية. كما يستخدم `/data/tmp` للملفات الجاري نقلها، لذلك وفّر مساحة تكفي لأكبر ملف تتوقع نقله.
4. اضبط عدد النسخ (replicas) على **1**، وسياسة إعادة التشغيل على **Always**. لا تشغّل النسخة نفسها في مكان آخر باستخدام `BOT_TOKEN` نفسه في الوقت ذاته.
5. ابدأ النشر وراجع سجلات الخدمة حتى تظهر `Bot running...`. افتح البوت، أرسل `/start` ثم `/link` لإتمام ربط Google Drive.

لا يوجد `railway.toml` في المشروع عمداً: Railway أوقف صيغة Config as Code القديمة للخدمات الجديدة، وسيتوقف عن قراءتها نهائياً في 1 ديسمبر 2026. يكفي `Dockerfile` لهذا العامل؛ إعدادات Railway المتغيرة مثل الـVolume والمتغيرات وعدد النسخ تُضبط في لوحة Railway. راجع [توثيق Railway للـVolumes](https://docs.railway.com/volumes) و[إشعار إيقاف صيغة الإعداد القديمة](https://docs.railway.com/config-as-code).

## التشغيل محلياً باستخدام Docker Compose

```bash
cp .env.example .env
```

املأ القيم الحقيقية في `.env`، واترك `DATA_DIR=/data` و`TMP_DIR=/data/tmp` كما هما في التشغيل باستخدام Compose. ثم شغّل:

```bash
docker compose up --build -d
docker compose logs -f tg2drive
```

يتم حفظ البيانات في مجلد `data/` المحلي. لإيقاف الخدمة استخدم `docker compose down`؛ لا تستخدم `down -v` إذا كنت تريد الاحتفاظ بالبيانات.

## التشغيل محلياً باستخدام Python

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
```

املأ بيانات `.env`، ثم احذف أو غيّر `DATA_DIR=/data` و`TMP_DIR=/data/tmp` إلى مسارات محلية قابلة للكتابة، مثلاً `DATA_DIR=./data` و`TMP_DIR=./data/tmp`، وشغّل:

```bash
python bot.py
```

## الملفات الكبيرة وحساب Premium

يمكن تشغيل وضع الحساب الشخصي للملفات الكبيرة بإعداد `SESSION_STRING`. أنشئ القيمة محلياً عبر `python gen_session.py` بعد إعداد `.env`، ثم احفظها كسِرّ في إعدادات الاستضافة. هذه القيمة تمنح صلاحية كاملة على حساب Telegram، فلا تضعها في المستودع أو تشاركها. أرسل الملفات الكبيرة إلى **Saved Messages**.

## الأوامر

`/link` لربط Google Drive، و`/unlink` لفصل الحساب، و`/status` لعرض الحالة، و`/share` للتبديل بين الروابط العامة والخاصة، و`/folder` لتغيير مجلد الرفع، و`/history` لعرض آخر الملفات، و`/cancel` لإلغاء عمليات الرفع.

## ملاحظات تشغيلية

- تُرفع الملفات عبر الخدمة، لذا تحتاج مساحة مؤقتة كافية على Volume واتصالاً مستقراً.
- `cryptg` غير مطلوب؛ Telethon يعمل بدونه، لكن تشفير الملفات قد يكون أبطأ قليلاً. استبعاده يمنع فشل بناء صورة `python:3.12-slim` بسبب غياب Rust.
- إذا فشل بدء الخدمة، راجع أول خطأ في سجلات Railway وتأكد من أسماء المتغيرات وقيمها ومسار الـVolume.
