# گزارش audit کامل پلتفرم MAS — باگ‌ها و مشکلات (Frontend / Backend / Database / DevOps)

- **مخزن:** `HosseinMAS651/MAS` — commit `dff15d3255f8ae334571ff359f12e543181c512e` (main)
- **سایت تولید:** `https://mas-xyrb.onrender.com`
- **تاریخ بررسی:** 2026-09-21
- **روش بررسی:**
  1. خواندن خط‌به‌خط همهٔ ۴۲ فایل مخزن (≈۳۴۰۰ خط پایتون/JS/HTML/CSS).
  2. اجرای واقعی پروژه روی `uvicorn` (همان کد production) و **ثبت‌نام و ساخت حساب کاربری به‌عنوان کاربر** و پیمایش کامل مسیر کاربری: register → profile → ساخت اتاق → ویرایش اتاق → آپلود فایل → صفحه پخش → تایمر (start/pause/reset/next/prev/finish/continue_overtime/goto) → حذف سخنران → ضبط صوت → آرشیو ضبط‌ها → حذف فایل → حذف اتاق → logout.
  3. اجرای ۲۰ تست موجود (`pytest`) → همه سبز.
  4. تست‌های مخرب/لبه‌ای: ورودی نامعتبر، همزمانی (concurrency)، IDOR، CSRF، rate limit، محدودیت آپلود، فیلد خالی، کاراکتر غیر ASCII، عدد بسیار بزرگ، اتاق ۱۰۰ نفره.
  5. بررسی دیتابیس با SQLite خام + ساخت دیتابیس legacy (مهاجرت‌شده) برای تست مسیر migration.
  6. پروب سایت زنده (به‌دلیل مسدود بودن egress سندباکس روی TLS/Cloudflare، فقط GET از طریق پروکسی ممکن بود؛ جریان ثبت‌نام روی نمونهٔ محلیِ **همان کد** انجام شد).

> **نکتهٔ مهم دربارهٔ سایت زنده:** در طول بررسی، سایت چند بار به‌جای پاسخ برنامه، صفحهٔ **«Render - Application loading»** را برگرداند (از جمله برای `/health`) و بعد از حدود یک دقیقه دوباره بالا آمد. یعنی سرویس در عمل **cold start / spin-down / restart** دارد (نگاه کنید به OPS-01).

### خلاصهٔ عددی

| شدت | تعداد |
|---|---|
| 🔴 بحرانی (P0) — کرش/ازدست‌رفتن داده/سایت از دسترس خارج | ۹ |
| 🟠 جدی (P1) — عملکرد شکسته یا خطر امنیتی/عملیاتی | ۱۸ |
| 🟡 متوسط (P2) — UX/کارایی/یکپارچگی | ۲۶ |
| 🔵 جزئی (P3) — کد مرده، مستندات، polish | ۲۰+ |

---

## فهرست باگ‌های بحرانی (P0)

| ID | عنوان | محل |
|---|---|---|
| C-01 | «حذف سخنران» در صفحه پخش → **HTTP 500** و حذف‌نشدن (تداخل index) | `main.py:750-790` |
| C-02 | تغییر رمز عبور با رمز غیر ASCII → **HTTP 500** (`TypeError`)؛ کاربر هرگز نمی‌تواند رمز را عوض کند | `main.py:397, 890-892` |
| C-03 | `global_min` غیر عددی/خالی → **HTTP 500** (بدون try/except) | `main.py:467` |
| C-04 | کاهش «ظرفیت» در ویرایش اتاق → **حذف بی‌صدا و بازگشت‌ناپذیر سخنران‌های نام‌دار و فایل‌هایشان** | `main.py:494-502` |
| C-05 | سخنران فریز‌شده **هیچ راه خروجی ندارد** (rename هم فریز را نگه می‌دارد؛ start/reset → 400) | `main.py:540-549`, `services.py:216-252` |
| C-06 | اگر خطایی **بعد از commit** در آپلود ضبط رخ دهد، فایلِ commit‌شده از دیسک پاک می‌شود ولی رکورد DB و سهمیه می‌مانند → فایل برای همیشه ۴۰۴ | `main.py:728-736` |
| C-07 | «حذف کامل اتاق» در صفحه اتاق **هیچ تأییدیه‌ای ندارد** (هندلر confirm در فایلی است که این صفحه هرگز load نمی‌کند) | `templates/room.html:22-26` |
| C-08 | startup روی دیتابیس legacy با username تکراری → **برنامه اصلاً بالا نمی‌آید** (crash loop) | `db.py:236-246`, `main.py:130` |
| C-09 | در production اگر `DATABASE_URL` ست نشود، بی‌صدا از SQLite روی دیسک موقت استفاده می‌شود → **کل داده‌ها در هر deploy/restart از بین می‌روند** | `config.py:65`, `render.yaml:16` |

---

# ۱) باگ‌های بحرانی — شرح کامل

## 🔴 C-01 — «حذف سخنران» در صفحه پخش ۵۰۰ می‌شود (UNIQUE constraint)

**محل:** `mas_app/main.py:750-790` (تابع `delete_speaker`) + `mas_app/models.py:165-168` (`UniqueConstraint("room_id","order_index")`)

`delete_speaker` فقط **سخنران‌های نام‌دار** را در لیست `speakers` می‌گیرد و سپس فقط روی همان‌ها شماره‌گذاری مجدد می‌کند:

```python
speakers = sorted([s for s in room.speakers if s.name], key=...)   # فقط نام‌دارها
...
remaining = [s for s in speakers if s.id != speaker_id]
for i, speaker in enumerate(remaining): speaker.order_index = -(i + 1)
db.flush()
for i, speaker in enumerate(remaining): speaker.order_index = i      # ۰،۱،۲...
```

اسلات‌های **خالی (بدون نام)** در این شماره‌گذاری شرکت نمی‌کنند و `order_index` قبلی خود را نگه می‌دارند. اگر یک اسلات خالی **قبل از** یک سخنران نام‌دار باشد، شمارهٔ جدید (۰ یا ۱) با شمارهٔ اسلات خالی تداخل می‌کند → `IntegrityError`.

**بازتولید واقعی (اجرا شد):**
```
step 1 (3 named):        [(0,'آقای الف'), (1,'آقای ب'), (2,'آقای پ')]
step 2 (name of #1 cleared): [(0,''), (1,'آقای ب'), (2,'آقای پ')]
step 3: POST /api/rooms/50/speakers/85/delete -> HTTP 500  {"detail":"خطای داخلی سرور."}
```
لاگ سرور:
```
sqlalchemy.exc.IntegrityError: (raised as a result of Query-invoked autoflush)
(sqlite3.IntegrityError) UNIQUE constraint failed: speakers.room_id, speakers.order_index
[SQL: UPDATE speakers SET order_index=? WHERE speakers.id = ?]  [parameters: (0, 6)]
```
حالت ساده‌تر هم reproduce شد: اتاق ۳ ظرفیتی که فقط اسلات ۲ و ۳ نام دارند → حذف اسلات ۲ → ۵۰۰.

**سناریوی واقعی کاربر:** وسط جلسه، نام سخنرانی که نیامده پاک می‌شود؛ بعد کاربر دکمهٔ «حذف سخنران» را می‌زند → خطای داخلی، سخنران حذف نمی‌شود، و هیچ پیام قابل‌فهمی نمایش داده نمی‌شود.

**تأثیر:** شکستن کامل قابلیت «حذف سخنران در حالت پخش» (که در CHANGELOG به‌عنوان ویژگی اصلی آمده) + پر شدن لاگ خطا + rollback شدن آزادسازی سهمیه.

**راه‌حل:** شماره‌گذاری مجدد باید روی **همهٔ** `room.speakers` (نام‌دار و بی‌نام) انجام شود، با یک pass موقت منفی روی کل مجموعه:
```python
all_speakers = sorted(room.speakers, key=lambda s: (s.order_index, s.id))
remaining_all = [s for s in all_speakers if s.id != speaker_id]
for i, s in enumerate(remaining_all): s.order_index = -(i + 1)
db.flush()
for i, s in enumerate(remaining_all): s.order_index = i
```
(همین اصلاح باید در `_repair_speaker_order` و `edit_room_save` هم بررسی شود — آنجا درست است چون روی همهٔ اسلات‌ها کار می‌کند.)

---

## 🔴 C-02 — تغییر رمز عبور با کاراکتر غیر ASCII → ۵۰۰ (`hmac.compare_digest`)

**محل:** `mas_app/main.py:397` و `main.py:890-892`

```python
if hmac_compare(new_password, current_password): ...
def hmac_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)      # ← برای رشتهٔ غیر ASCII استثنا می‌دهد
```

`hmac.compare_digest` روی `str` **فقط ASCII** را قبول می‌کند. لاگ واقعی سرور:
```
File "mas_app/main.py", line 397, in password_change
    if hmac_compare(new_password, current_password):
File "mas_app/main.py", line 892, in hmac_compare
    return hmac.compare_digest(a, b)
TypeError: comparing strings with non-ASCII characters is not supported
```

**بازتولید واقعی:**
```
change ASCII->Persian            : 500  (صفحهٔ «خطای داخلی»)
register با رمز فارسی + تغییر رمز: 500
login با همان رمز فارسی          : 303 / (ورود درست کار می‌کند)
```

**تأثیر:**
- کاربری که با **رمز فارسی/غیر ASCII ثبت‌نام کند** (فرم ثبت‌نام هیچ محدودیتی ندارد، فقط `minlength=8`) **تا ابد نمی‌تواند رمز خود را عوض کند** — هر تلاش = ۵۰۰.
- پیام «رمز عبور جدید باید با رمز فعلی متفاوت باشد» هم در این حالت هرگز نمایش داده نمی‌شود.
- این برای یک محصول فارسی‌زبان بسیار محتمل است (کاربر فارسی‌زبان ممکن است رمز فارسی بگذارد).

**راه‌حل:** مقایسهٔ ساده و بدون `compare_digest` (اینجا timing attack معنایی ندارد چون رمز فعلی قبلاً verify شده):
```python
if new_password == current_password: ...
```
یا `hmac.compare_digest(new_password.encode(), current_password.encode())`.

---

## 🔴 C-03 — `global_min` غیر عددی → ۵۰۰ (بدون مدیریت خطا)

**محل:** `mas_app/main.py:467`
```python
global_min = int(str(form.get("global_min", "5")))   # ← بدون try/except
if not 1 <= global_min <= 1440: raise HTTPException(400, ...)
```
در همان تابع `capacity` با try/except محافظت شده (خط ۴۷۱-۴۷۴) ولی `global_min` نه.

**بازتولید واقعی:**
```
global_min=''    -> 500 «خطای داخلی»
global_min='abc' -> 500
global_min='5.5' -> 500
```
**چرا از سمت مرورگر هم قابل وقوع است:** `<input type="number">` وقتی مقدارش نامعتبر باشد (مثلاً کاربر `5e` تایپ کند، یا در برخی localeها `۱۲۳`/`1,5`)، مرورگر مقدار را **خالی** submit می‌کند → `int("")` → `ValueError` → ۵۰۰.

**تأثیر:** خطای داخلی + از دست رفتن کل فرم ویرایش اتاق (همهٔ فیلدها و فایل‌های انتخاب‌شده).

**راه‌حل:** همان الگوی `capacity`:
```python
try: global_min = int(str(form.get("global_min", "5")).strip() or 0)
except ValueError: raise HTTPException(400, "زمان همگانی نامعتبر است.")
```
+ اصلاح ساختاری: برای فرم‌ها از Pydantic/`Form` با نوع درست استفاده شود تا `RequestValidationError` هندل شود و فرم با دادهٔ کاربر دوباره render شود (BE-06).

**هم‌خانواده:** `main.py:552`
```python
manual_ids = [int(x.strip()) for x in ... .split(",") if x.strip().isdigit()]
```
`str.isdigit()` برای کاراکترهایی مثل `²` یا `٣` غیر decimal هم True است و `int("²")` → `ValueError` → **۵۰۰** (تست شد: `manual_order='²' -> 500`).

---

## 🔴 C-04 — کوچک‌کردن ظرفیت = حذف بی‌صدا و غیرقابل‌بازگشت سخنران‌ها و فایل‌ها

**محل:** `mas_app/main.py:494-502`
```python
# Shrinking capacity deletes the last slots by current order.
if capacity < len(speakers):
    removed = speakers[capacity:]
    for speaker in removed:
        names, amount = collect_speaker_storage(db, speaker.id)
        release_room_storage(db, room.id, amount); enqueue_cleanup(db, names); db.delete(speaker)
```

**بازتولید واقعی:**
```
save with 3 speakers + 1 common file : 303
attach file to speaker 3 (مریم)      : 303
files listed: ['maryam-note.txt', 'shared.txt']
shrink to capacity=1                 : 303  /rooms/6
remaining speakers: [('12','علی')]
remaining files listed: ['shared.txt']      ← فایل مریم و کل رکورد سخنران حذف شد
```

**تأثیر:** فیلد «ظرفیت فعلی» در `edit_room.html` فقط یک `<input type=number min=0 max=100>` است؛ **هیچ هشدار، تأییدیه، یا نمایشی از اینکه چه کسانی حذف می‌شوند وجود ندارد**. کاربر با تغییر یک عدد، سخنران‌های نام‌دار + فایل‌های اختصاصی + زمان تایمر آن‌ها را برای همیشه از دست می‌دهد. بدتر: اگر `order_mode` چیز دیگری باشد (مثلاً random که در C/BE-04 توضیح داده شده)، «اسلات‌های آخر» می‌توانند سخنران‌های اصلی باشند.

**راه‌حل:**
1. در UI قبل از submit، اگر `capacity < تعداد اسلات‌های نام‌دار` → دیالوگ تأیید با لیست نام‌هایی که حذف می‌شوند.
2. در بک‌اند: اگر اسلات‌های حذف‌شونده **نام‌دار** هستند → ۴۰۰ با پیام صریح (یا flag `confirm_delete_named=1`).
3. حداقل: حذف «اسلات خالی» به‌جای «آخرین اسلات‌ها» (اول اسلات‌های بدون نام حذف/ادغام شوند).

---

## 🔴 C-05 — سخنران فریز‌شده بن‌بست کامل دارد (rename هم نجات نمی‌دهد)

**محل:** `main.py:540-549` (فقط پاک‌کردن نام، فریز را برمی‌گرداند)، `services.py:216-252` (start/reset/continue روی فریز → ۴۰۰)

**بازتولید واقعی:**
```
finished: True elapsed_ms: 1222
after rename -> name: حسن  is_finished: True  elapsed_ms: 1222  remaining_ms: 58778
start after rename: 400 {'detail': 'این سخنرانی پایان یافته و فریز شده است.'}
reset after rename: 400 {'detail': 'سخنران فریز شده است.'}
edit page shows freeze badge: True
buttons available in edit page: ['↑','↓','ذخیره تغییرات','خروج از حساب']   ← هیچ کنترل «رفع فریز» نیست
```
و وقتی **همهٔ** سخنران‌ها فریز شوند:
```
start             -> 400 این سخنرانی پایان یافته و فریز شده است.
reset             -> 400 سخنران فریز شده است.
continue_overtime -> 400 این سخنرانی پایان یافته است.
next / prev       -> 200 (فقط جابه‌جایی)
play page offers an 'unfreeze/reset all' control? False
```

**تأثیر:**
- اگر نام اسلات فریز‌شده را به فرد جدیدی تغییر دهید، فرد جدید **هم فریز است و هم زمان مصرف‌شدهٔ نفر قبلی را به ارث می‌برد** (`elapsed_ms: 2020` برای «بابک» بعد از تغییر نام «علی» — تست شد).
- تنها راه خروج: پاک‌کردن نام → ذخیره → نام‌گذاری مجدد → ذخیره (دو round trip، بدون هیچ راهنمایی در UI) و **حتی در این حالت هم `SpeakerTimerState.elapsed_ms` صفر نمی‌شود**.
- بعد از پایان یک جلسه، برای اجرای جلسهٔ بعد هیچ دکمهٔ «بازنشانی همه/شروع دوباره» وجود ندارد.

**راه‌حل:** افزودن اکشن `unfreeze` (و `reset_all`) به `apply_timer_action` + دکمه در صفحه پخش و ویرایش؛ و در `edit_room_save` اگر `name` تغییر کرد → `is_finished=False` و `SpeakerTimerState` مربوطه صفر شود.

---

## 🔴 C-06 — پاک‌شدن فایلِ commit‌شده هنگام خطای بعد از commit (نشتی سهمیه + فایل ۴۰۴ دائمی)

**محل:** `mas_app/main.py:692-736` (`save_recording`)

```python
                    db.commit()                        # ← رکورد ذخیره شد
        with SessionLocal() as db:
            process_cleanup_queue(db, cfg, limit=5)    # ← هنوز داخل try
        return JSONResponse({"ok": True, ...})
    except Exception:
        if stored:
            safe_storage_path(cfg, stored.storage_name).unlink(missing_ok=True)   # ← فایلِ commit‌شده پاک می‌شود!
        raise
```

**بازتولید واقعی** (با شبیه‌سازی یک خطای DB/دیسک در `process_cleanup_queue`):
```
normal upload                        : 200 {'ok': True, 'file': {'id': 1, 'name': 'ok.webm'}}
upload with failing post-commit step : 500 {"detail":"خطای داخلی سرور."}
DB rows still committed              : [(1,'ok.webm',...), (2,'lost.webm',...)]
files on disk now                    : ['...ok.webm']        ← فایل lost.webm حذف شد
room.storage_used_bytes still reserved: 1008                 ← سهمیهٔ فایلِ نبود، آزاد نشد
GET /files/2 (lost.webm)             -> 404 «فایل روی سرور وجود ندارد»
```

**تأثیر:** ضبط صوت کاربر برای همیشه از دست می‌رود، رکورد DB و سهمیهٔ اتاق (`storage_used_bytes`) تا ابد سنگین می‌ماند (چون `release_room_storage` فقط هنگام حذف رکورد اجرا می‌شود) و `reconcile_orphans` هم نمی‌تواند کمک کند.

**راه‌حل:** بلوک cleanup را **بیرون از try** ببرید یا پرچم `committed` بگذارید:
```python
committed = False
try:
    ... db.commit(); committed = True
except Exception:
    if stored and not committed: unlink(...)
    raise
# cleanup خارج از try
```
همین الگو در `edit_room_save` (`main.py:598-613`) هم باید بررسی شود (commit آخرین عملیات است، ولی `session.close()`/خروج از `with` هم داخل try است).

---

## 🔴 C-07 — «حذف کامل اتاق» بدون هیچ تأییدیه‌ای

**محل:** `mas_app/templates/room.html:22`
```html
<form method="post" action="/rooms/{{ room.id }}/delete" class="danger-zone" data-confirm-form>
```
و در انتهای همان فایل فقط این هست (بدون `<script src>`):
```html
<script type="application/json" id="room-data">{{ {'csrf': csrf}|tojson }}</script>
```
بررسی شد: **`room.html` و `base.html` هیچ اسکریپتی load نمی‌کنند.**
```
$ grep -n "script src" mas_app/templates/*.html
edit_room.html:39: room_editor.js
play.html:27:      play.js
recordings.html:6: files.js
```
هندلر `data-confirm-form` در `room_editor.js:70-74` است که **فقط در صفحه ویرایش** load می‌شود، نه در صفحهٔ اتاق.

**تأثیر:** یک کلیک ساده (بدون confirm، بدون undo) = حذف دائم اتاق + همهٔ سخنران‌ها + همهٔ فایل‌ها و ضبط‌ها. دکمه قرمز بزرگ در پایین صفحه است و روی موبایل هم به‌راحتی زده می‌شود.

**راه‌حل:** افزودن `<script src="/static/room_editor.js" defer>` به `room.html` (یا یک `confirm.js` مشترک در `base.html`) + تأیید دومحله‌ای (تایپ نام اتاق) + در بک‌اند soft-delete با سطل بازیافت.

**مرتبط (P2):** `mas_app/static/rooms.js` کاملاً مرده است — سلکتور `.delete-room-form` در هیچ template وجود ندارد؛ ولی فایل به‌صورت عمومی سرو می‌شود (`GET /static/rooms.js → 200`).

---

## 🔴 C-08 — migration می‌تواند برنامه را در boot بکُشد (crash loop)

**محل:** `db.py:236-246` (ساخت unique index) + `db.py:249-295` (`initialize_database`) + `main.py:130` (بدون try/except)

`initialize_database` برای `speech_files`، `file_cleanup_queue`، `room_states`، `speaker_timer_states` و `speakers` مرحلهٔ dedupe دارد، اما برای **`users.username`** و **`auth_sessions.token_hash`** هیچ dedupe/repair وجود ندارد؛ بعد هم unconditionally unique index می‌سازد.

**بازتولید واقعی** (دیتابیس legacy با username تکراری — حالتی که README صریحاً پشتیبانی از آن را ادعا می‌کند):
```
STARTUP CRASH -> IntegrityError
(sqlite3.IntegrityError) UNIQUE constraint failed: users.username
[SQL: CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_legacy ON users (username)]
```
چون این کد داخل `lifespan` و بدون try/except است → uvicorn بالا نمی‌آید → Render مدام restart می‌کند → **سایت کامل down**.

**تأثیر:** اگر دیتابیس قدیمی حتی یک username تکراری داشته باشد، deploy جدید = خاموشی کامل.

**راه‌حل:**
1. قبل از ساخت indexها: dedupe/merge برای `users.username` (مثلاً افزودن پسوند) و حذف `auth_sessions` تکراری.
2. `initialize_database` را در try/except بگذارید و در صورت شکست، پیام عملیاتی واضح لاگ کنید (و در حالت production fail-fast با پیام راهنما، نه traceback خام).
3. بهتر: مهاجرت به **Alembic** با نسخه‌بندی واقعی (DB-02).

---

## 🔴 C-09 — production بدون `DATABASE_URL` بی‌صدا روی SQLite می‌رود + فایل‌ها روی دیسک موقت

**محل:** `config.py:65`
```python
database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'mas.db'}")
```
و `render.yaml`:
```yaml
      - key: DATABASE_URL
        sync: false          # ← هیچ مقداری ندارد؛ اگر دستی ست نشود، fallback = SQLite
```
و `MAS_STORAGE_DIR` **اصلاً در render.yaml نیست** → uploads داخل `/app/uploads` (دیسک ephemeral).

**تأثیر:**
- هر deploy/restart/scale در Render = **پاک شدن کامل دیتابیس** (SQLite روی دیسک موقت) و **پاک شدن همهٔ فایل‌ها و ضبط‌ها**.
- اگر DB پاک شود ولی دیسک پایدار بماند، `reconcile_orphans` در startup (main.py:132-141) **همهٔ فایل‌های باقی‌مانده را بعد از ۱۵ دقیقه پاک می‌کند** چون در DB مرجعی ندارند → تخریب داده به‌جای محافظت از آن.
- هیچ warning در startup نیست که «داری با SQLite در production اجرا می‌شوی».

**راه‌حل:** در `load_settings`: اگر `env == "production"` و `DATABASE_URL` ست نباشد → `RuntimeError` (مثل کاری که برای `MAS_SECRET_KEY` انجام شده). افزودن `MAS_STORAGE_DIR` به render.yaml با Persistent Disk (یا S3-compatible) و health check روی mount.

---

# ۲) باگ‌های بک‌اند (API / منطق / کارایی)

## 🟠 BE-01 — Rate Limit با `X-Forwarded-For` ساختگی کاملاً دور زده می‌شود
**محل:** `render.yaml:6` (`--forwarded-allow-ips="*"`)، `README.md` (همان دستور)، `auth.py:60-62` (`client_key` = `request.client.host`)

با `--forwarded-allow-ips="*"`، uvicorn هدر `X-Forwarded-For` را از **هر** منبعی می‌پذیرد → مهاجم IP را در هر درخواست عوض می‌کند.

**بازتولید واقعی:**
```
12 failed logins, no XFF      : [401×10, 429, 429]      ← محدودیت درست کار کرد
12 failed logins, spoofed XFF : [401×12]                 ← هر بار IP جدید = بدون محدودیت
```
**تأثیر:** brute force نامحدود روی `/login` و `/register`؛ هر attempt = یک PBKDF2 با ۳۱۰هزار round (~۱۰۴ms روی این CPU، روی Render خیلی بیشتر) → **DoS مصرف CPU** هم همزمان ممکن است.

**نکتهٔ معکوس:** در `Dockerfile` (خط ۱۷) `--forwarded-allow-ips` وجود **ندارد** → در استقرار Docker، همهٔ کاربران با IP پروکسی دیده می‌شوند → کل سایت بعد از ۴۰ تلاش ورود در ۱۰ دقیقه **برای همه** قفل می‌شود. یعنی دو مسیر استقرار، دو باگ متضاد دارند.

**راه‌حل:** `--forwarded-allow-ips` را به CIDR واقعی پروکسی Render محدود کنید (یا از `--proxy-headers` با لیست مشخص)؛ و کلید rate limit را روی ترکیب «IP + fingerprint» با fallback امن بسازید؛ برای `/login` از backoff نمایی + (در صورت نیاز) CAPTCHA استفاده شود.

## 🟠 BE-02 — قفل‌شدن حساب کاربر (Account Lockout DoS)
**محل:** `main.py:271-278`، `auth.py:69-101`
`combo_key = hash(ip, username)` با سقف ۱۰ و پنجرهٔ ۶۰۰ ثانیه.

**بازتولید واقعی:**
```
correct password after 10 failed attempts -> 429 «تلاش‌های ورود برای این نام کاربری زیاد است.»
```
ترکیب با BE-01: مهاجم می‌تواند `X-Forwarded-For: <IP قربانی>` بگذارد و **قربانی را از حساب خودش بیرون نگه دارد** (۱۰ دقیقه در هر راند). همچنین در شبکه‌های NAT (دانشگاه/شرکت/موبایل) چند کاربر واقعی با هم قفل می‌شوند.

**راه‌حل:** lockout روی username نباید مطلق باشد؛ از تأخیر فزاینده + هشدار به کاربر + (بهتر) rate limit بر اساس session/cookie استفاده شود. حداقل پیام باید زمان باقی‌مانده را نشان دهد.

## 🟠 BE-03 — کوکی CSRF مهمان ۱ ساعته است ولی در پاسخ‌های خطا تمدید نمی‌شود
**محل:** `main.py:256` و `310` (`max_age=3600`) در مقابل پاسخ‌های ۴۰۱/۴۰۰/۴۲۹ که `set_cookie` ندارند (فقط مسیر ۴۰۰ اعتبارسنجی در `main.py:268` تمدید می‌کند).

**بازتولید واقعی:**
```
POST /login با توکن فرم ولی بدون کوکی (کوکی منقضی شده) -> 403 «درخواست امنیتی نامعتبر است. صفحه را تازه کنید.»
GET /login set-cookie: mas_guest_csrf=...; Max-Age=3600
401 response set-cookie: (هیچ)
```
**تأثیر:** کاربری که تب ورود/ثبت‌نام را بیش از یک ساعت باز نگه دارد (یا از bfcache/session restore برگردد) با خطای امنیتی گیج‌کننده مواجه می‌شود. در `POST /login` مسیر ۴۲۹ هم کوکی را تمدید نمی‌کند.

**راه‌حل:** در همهٔ پاسخ‌های `/login` و `/register` کوکی را (با همان Max-Age) ست کنید، یا `max_age` را برابر session کنید، یا بهتر: توکن مهمان را در `session` سمت سرور نگه دارید.

## 🟠 BE-04 — `order_mode=random` در **هر** ذخیره، ترتیب را دوباره قاطی می‌کند
**محل:** `services.py:344-345`
```python
elif mode == "random": secrets.SystemRandom().shuffle(items)
```
**بازتولید واقعی:**
```
order after save: ['پ','الف','ت','ب']
order after save: ['الف','ب','ت','پ']
order after save: ['پ','ت','الف','ب']
order after save: ['الف','ت','ب','پ']
```
**تأثیر:** کاربر «ترتیب تصادفی» را انتخاب می‌کند و هر بار که **چیز بی‌ربطی** (مثلاً توضیح یک سخنران یا یک فایل) را ویرایش و ذخیره کند، ترتیب جلسه عوض می‌شود و در DB هم persist می‌شود. وسط جلسه فاجعه است. همچنین `manual_order` در این حالت نادیده گرفته می‌شود بدون اینکه UI بگوید.

**راه‌حل:** random باید **یک عملیات صریح** باشد (دکمهٔ «قرعه‌کشی» که یک بار shuffle می‌کند و نتیجه به‌صورت manual ذخیره می‌شود)، نه یک حالت ماندگار که در هر save اعمال شود.

## 🟠 BE-05 — `capacity` در ساخت اتاق ۱..۱۰۰ ولی در ویرایش ۰..۱۰۰
**محل:** `main.py:425` (`validate_capacity(capacity, cfg.min_room_capacity=1, ...)`) در مقابل `main.py:475` (`if not 0 <= capacity <= cfg.max_room_capacity`).

**بازتولید واقعی:**
```
POST /rooms/new capacity=0  -> 400 «ظرفیت باید بین 1 تا 100 باشد.»
POST /rooms/{id}/edit capacity=0 -> 303 (موفق!)  → اتاق با ۰ سخنران
state: current_speaker_id=None, total_speakers=0, limit_ms=0
```
**تأثیر:** ناسازگاری قانون اعتبارسنجی + امکان ساخت اتاق «خالی» که صفحه پخش آن هیچ محتوایی ندارد؛ `limit_ms=0` هم در play.js باعث `pct=0` و منطق overtime نامعین می‌شود. `edit_room.html` هم `min="0"` دارد در حالی که `new_room.html` `min="1"`.

**راه‌حل:** یک قانون واحد (حداقل ۱ اسلات، یا اجازهٔ ۰ با پیام صریح) در هر دو مسیر + همسان‌سازی `min` در HTML.

## 🟡 BE-06 — همهٔ خطاهای اعتبارسنجی، کاربر را به «صفحهٔ خطای خام» می‌برند و تمام ورودی‌ها از دست می‌رود
**محل:** `main.py:221-243` (exception handlers)، `main.py:371`، `424-425`، `465-476`، `536-543`

**بازتولید واقعی:**
```
edit with global_min=99999 (invalid) -> 400 صفحه «خطا»
   room name after failed save: اتاق به‌روز   ← «نام جدید» که کاربر تایپ کرده بود از دست رفت
   global_min after failed save : 1
upload .html file                  -> 400 صفحه «خطا»  (فرم و فایل‌های انتخاب‌شده پریدند)
POST /profile age=abc              -> 422 «ورودی نامعتبر»
POST /rooms/new capacity=abc       -> 422 «ورودی نامعتبر»
POST /rooms/new بدون csrf          -> 422 (به‌جای 403 با پیام «صفحه را تازه کنید»)
```
**تأثیر:** برای فرم ویرایش اتاق با ۱۰۰ سخنران و چند فایل آپلودی، یک اشتباه کوچک = از دست رفتن **همهٔ** داده‌ها و فایل‌های انتخاب‌شده (مرورگر نمی‌تواند `input[type=file]` را برگرداند). هیچ پیام خطای inline کنار فیلد مربوطه وجود ندارد.

**راه‌حل:** برای هر فرم، در خطا همان template را با `error` + داده‌های کاربر دوباره render کنید (الگویی که در `password_change` هست) یا بهتر: اعتبارسنجی سمت کلاینت + پاسخ JSON و نمایش خطا کنار فیلد.

## 🟡 BE-07 — فیلد خالی در فرم → ۴۲۲ به‌جای پیام فارسی (رفتار FastAPI با `Form(...)`)
**محل:** `main.py:367` (`profile_save`)، `main.py:421` (`new_room_save`)، `main.py:260/314/343`

FastAPI در `_get_multidict_value` مقدار **رشتهٔ خالی** را برای فیلد `Form(...)` اجباری معادل «موجود نیست» می‌گیرد:
```
POST /p data={'account_name':''} → {'type':'missing','loc':['body','account_name'],'msg':'Field required'}
```
**بازتولید واقعی:**
```
POST /profile account_name='' -> 422 «ورودی نامعتبر»   (به‌جای 400 «اطلاعات پروفایل نامعتبر است.»)
POST /rooms/new name=''       -> 422                    (شاخهٔ «نام اتاق الزامی است.» در services.py:36-38 هرگز اجرا نمی‌شود = کد مرده)
```
**راه‌حل:** این فیلدها را `Form("")` (اختیاری) بگیرید و خودتان اعتبارسنجی کنید تا پیام‌های فارسی و ۴۰۰ برگردانده شود.

## 🟡 BE-08 — خطاهای multipart به JSON انگلیسی برمی‌گردد (حتی برای فرم HTML)
**بازتولید واقعی:**
```
POST /rooms/{id}/edit با ۱۲۰ فایل (Accept: text/html) ->
  400 content-type: application/json
  {"detail":"Too many files. Maximum number of files is 100."}
```
**تأثیر:** کاربر فارسی‌زبان در مرورگر یک blob JSON انگلیسی می‌بیند. `MultiPartException` هندلر اختصاصی ندارد.
**راه‌حل:** ثبت `@app.exception_handler(MultiPartException)` (و `StarletteHTTPException`) با render صفحهٔ خطای فارسی بر اساس `Accept`.

## 🟡 BE-09 — ۴۰۴های مسیریابی خام (JSON انگلیسی) + هندلر خطا برای `StarletteHTTPException` ثبت نشده
**محل:** `main.py:221` (`@app.exception_handler(HTTPException)` با کلاس fastapi)

**بازتولید واقعی (هم محلی، هم روی سایت زنده):**
```
GET /nonexistent-page -> 404 application/json {"detail":"Not Found"}
GET /favicon.ico      -> 404 application/json {"detail":"Not Found"}
GET /robots.txt       -> 404 application/json {"detail":"Not Found"}
https://mas-xyrb.onrender.com/nonexistent-page-xyz -> {"detail":"Not Found"}
```
در حالی که ۴۰۴های خود برنامه صفحهٔ زیبای فارسی «پیدا نشد» را نشان می‌دهند. علت: هندلر برای `fastapi.HTTPException` ثبت شده ولی router استارلت `starlette.exceptions.HTTPException` پرتاب می‌کند (کلاس پدر) → هندلر اجرا نمی‌شود.
**تأثیر:** تجربهٔ کاربری ناسازگار، نشتی فناوری (FastAPI/Starlette)، و **نبود favicon** یعنی هر بارگذاری صفحه یک ۴۰۴ JSON اضافه می‌کند (BE-10).
**راه‌حل:** `@app.exception_handler(StarletteHTTPException)` هم ثبت شود + صفحهٔ ۴۰۴ فارسی + `/favicon.ico`.

## 🟡 BE-10 — هیچ favicon / manifest / meta توصیفی وجود ندارد
**بررسی شد:** `grep -c favicon mas_app/templates/*.html` → هیچ. هر page view یک `GET /favicon.ico` = ۴۰۴ JSON. همچنین `<meta name="description">`، Open Graph، `theme-color` و PWA manifest وجود ندارد (برای اپی که قرار است روی پروژکتور/موبایل در مراسم استفاده شود، افزودن به صفحه اصلی ارزشمند است).

## 🟡 BE-11 — `HEAD` روی همهٔ مسیرها ۴۰۵
**بازتولید واقعی:** `HEAD / -> 405` (روش‌های ثبت‌شده فقط `['GET']`).
**تأثیر:** مانیتورهای uptime، خزنده‌ها و برخی پروکسی‌ها که HEAD می‌زنند خطا می‌گیرند؛ `/health` با HEAD هم ۴۰۵ است.
**راه‌حل:** `@app.api_route(..., methods=["GET","HEAD"])` یا افزودن خودکار HEAD.

## 🟠 BE-12 — عدد بسیار بزرگ در path/query → ۵۰۰ (`OverflowError`)
**بازتولید واقعی:**
```
/recordings?room_id=99999999999999999999 -> 500
/files/99999999999999999999              -> 500
لاگ: OverflowError: Python int too large to convert to SQLite INTEGER
```
روی PostgreSQL هم psycopg خطای مشابه می‌دهد → ۵۰۰.
**تأثیر:** هر کاربر لاگین‌کرده می‌تواند بی‌نهایت ۵۰۰ تولید کند (لاگ پرهزینه، آلارم بی‌مورد).
**راه‌حل:** محدودکردن نوع با `Path(..., gt=0, le=2**31-1)` / `Query(..., gt=0)` یا گرفتن `str` و تبدیل با try/except.

## 🟠 BE-13 — هیچ سقفی برای تعداد اتاق‌ها و مجموع فضای هر کاربر وجود ندارد
**بازتولید واقعی:**
```
created 25 rooms in 0.24s   (بدون هیچ محدودیت)
```
`max_room_storage_bytes` پیش‌فرض **۱۰۰۰ مگابایت برای هر اتاق** است (`config.py:84`) و تعداد اتاق نامحدود → یک کاربر می‌تواند ۱۰۰ اتاق × ۱GB = **۱۰۰GB** روی دیسک ۵۱۲MB موقت Render بنویسد.
**تأثیر:** پر شدن دیسک → `/health` = ۵۰۳ (`main.py:872-885`) → Render سرویس را restart می‌کند → حلقهٔ خرابی برای همهٔ کاربران.
**راه‌حل:** سهمیهٔ **هر کاربر** (نه هر اتاق)، سقف تعداد اتاق، و rate limit روی endpointهای آپلود.

## 🟠 BE-14 — endpointهای آپلود و تایمر `async def` هستند ولی IO همگام/بلاک‌کننده انجام می‌دهند
**محل:** `main.py:453` (`async def edit_room_save`)، `main.py:692` (`async def save_recording`)؛ `storage.py:87-102` (`out.write` + `os.fsync` همگام)

داخل این توابع، SQLAlchemy همگام، `os.fsync`، `unlink` و ... مستقیم روی **event loop** اجرا می‌شوند. بقیهٔ routeها `def` هستند (در threadpool) ولی این دو نه.
**اندازه‌گیری واقعی (لوکال، دیسک سریع):**
```
upload 20MB ضبط: 200 در 0.22s | latency همزمان /health: median=3.0ms p95=16.1ms max=19.9ms
baseline /health: median=1.4ms max=3.0ms
```
روی دیسک کانتینر Render + fsync، این بلاک‌شدن می‌تواند صدها ms تا چند ثانیه باشد و در آن مدت **polling صفحه پخش همهٔ کاربران و /health متوقف می‌شود**.
**راه‌حل:** یا این routeها را `def` (threadpool) کنید، یا کارهای بلاک‌کننده را با `anyio.to_thread.run_sync` / `run_in_executor` انجام دهید.

## 🟡 BE-15 — N+1 و تکرار lookup احراز هویت در هر درخواست
**اندازه‌گیری واقعی با شمارش SQL:**
```
GET  /                        SELECTs= 6   bytes= 2420
GET  /rooms                   SELECTs= 5
GET  /rooms/1                 SELECTs=10
GET  /rooms/1/edit            SELECTs=11
GET  /rooms/1/play            SELECTs=14   bytes= 6114
GET  /api/rooms/1/state       SELECTs= 7   bytes= 624   ← هر ۱.۵ ثانیه برای هر تب باز
POST /api/rooms/1/start       SELECTs=10  writes=2
```
علت: `owned_room()` یک session می‌زند، `page_context()` دوباره `get_auth_context` را صدا می‌کند، و در `edit_room`/`play` یک بار **سوم** `get_auth_context(...).csrf_token` صدا زده می‌شود (`main.py:450`, `660`). به‌علاوه `state_snapshot` → `current.files` lazy-load (یک SELECT اضافه در هر poll).
**راه‌حل:** یک dependency واحد (`Depends(get_ctx)`) که یک بار session/کاربر/csrf را بگیرد و در کل درخواست استفاده شود؛ `selectinload(Speaker.files)` در snapshot.

## 🟡 BE-16 — payload poll صفحه پخش با تعداد سخنران بزرگ می‌شود و هیچ caching/ETag ندارد
**اندازه‌گیری واقعی (اتاق ۱۰۰ نفره):**
```
state poll: 7.8 KB در 6ms با 7 SELECT   (هر ۱.۵ ثانیه، برای هر تب)
play page : 149 KB / edit page: 124 KB با ۶۱۱ کنترل فرم
```
`speakers` کامل (همهٔ ۱۰۰ نفر) در هر poll ارسال می‌شود در حالی که کلاینت فقط `id/name/is_finished` را لازم دارد و تقریباً هرگز تغییر نمی‌کند.
**راه‌حل:** ETag/`If-None-Match` → ۳۰۴؛ جداکردن «لیست سخنران‌ها» (کش‌شده) از «وضعیت تایمر»؛ یا WebSocket/SSE به‌جای polling.

## 🟡 BE-17 — تشخیص تداخل همزمان (optimistic locking) عملاً کار نمی‌کند؛ ذخیرهٔ همزمان = last-write-wins
**محل:** `models.py:151-152` (`version_id_col`) و `main.py:598-608` (هندلر ۴۰۹)

**بازتولید واقعی (دو تب همزمان):**
```
concurrent room edits -> [('تب یک', 303), ('تب دو', 303)]   ← هر دو «موفق»، بدون هیچ ۴۰۹
```
چون هر درخواست اتاق را **دوباره** از DB می‌خواند (`select ... with_for_update`)، نسخهٔ کهنه‌ای در session نمی‌ماند و `StaleDataError` رخ نمی‌دهد → هندلر ۴۰۹ عملاً کد مرده است. تب دوم با فرم قدیمی خود، تغییرات تب اول را بی‌صدا برمی‌گرداند.
همچنین در SQLite `with_for_update()` هیچ اثری ندارد (FOR UPDATE پشتیبانی نمی‌شود) و `skip_locked` در `process_cleanup_queue` (`services.py:397`) هم بی‌اثر است.
**راه‌حل:** فرم ویرایش باید `version` اتاق را به‌صورت hidden field بفرستد و سرور آن را با مقدار فعلی مقایسه کند (`If-Match`) → در صورت اختلاف ۴۰۹ با پیام «صفحه را تازه کنید».

## 🟡 BE-18 — تغییر نام سخنران، تایمر و فریز نفر قبلی را به ارث می‌گذارد
**بازتولید واقعی:**
```
علی elapsed_ms: 2020  →  after rename -> speaker: بابک elapsed_ms: 2020 remaining_ms: 57980
```
**راه‌حل:** در `edit_room_save`، اگر `name` تغییر کرد → `SpeakerTimerState` آن اسلات صفر و `is_finished` پاک شود (یا اسلات جدید ساخته شود).

## 🟡 BE-19 — در حالت «زمان همگانی»، فیلد زمان هر سخنران editable است ولی نادیده گرفته می‌شود
**بازتولید واقعی:**
```
limit_seconds for everyone: 420   (global_min=7)
per-speaker time inputs still rendered: [('59','1'), ('60','2'), ('61','3')]
```
`timer_limit_ms` (`services.py:106-108`) در حالت global فقط `room.global_seconds` را می‌بیند. UI هیچ غیرفعال/پنهانی نمی‌کند و توضیحی نمی‌دهد → کاربر فکر می‌کند زمان اختصاصی ست شده.
عکسش هم درست است: وقتی `global_min` عوض می‌شود، `speaking_seconds` سخنران‌های موجود به‌روز نمی‌شود؛ بنابراین سوییچ از global به individual بعداً زمان‌های قدیمی را برمی‌گرداند.
**راه‌حل:** در حالت global فیلد زمان را `disabled` کنید (یا مقدارش را از global پر کنید) و در سوییچ حالت، زمان‌ها را همگام‌سازی کنید.

## 🟡 BE-20 — افزودن سخنران جدید فقط با افزایش ظرفیت و با زمان `global_min` (بدون UI مجزا)
**محل:** `main.py:504-511` — `speaking_seconds=global_min*60` برای اسلات‌های جدید. هیچ دکمهٔ «افزودن سخنران» وجود ندارد و اگر `global_min` در همان فرم عوض شود، اسلات‌های جدید زمان جدید می‌گیرند ولی قدیمی‌ها نه (ناسازگاری داده).

## 🟡 BE-21 — `state_snapshot` در یک endpoint «خواندنی» وضعیت ORM را تغییر می‌دهد ولی commit نمی‌شود
**محل:** `services.py:159-200` (`ensure_current_speaker` داخل snapshot) + `main.py:674-682` (`api_state`)
`ensure_current_speaker` می‌تواند `state.current_speaker_id/current_index/running/started_at_ms` را عوض کند؛ چون session بدون commit بسته می‌شود، **پاسخ API چیزی را گزارش می‌کند که در DB ذخیره نشده** (و دفعهٔ بعد دوباره محاسبه می‌شود). این یعنی DB و API می‌توانند موقتاً ناسازگار باشند و اصلاحات «ترمیمی» هرگز persist نمی‌شوند.
**راه‌حل:** snapshot را read-only کنید (بدون mutate) یا در یک transaction صریح با commit انجامش دهید.

## 🔵 BE-22 — `get_auth_context(..., api: bool)` — پارامتر `api` هرگز استفاده نمی‌شود
**محل:** `auth.py:153` — در بدنهٔ تابع هیچ ارجاعی به `api` نیست. یعنی تمایز page/api فقط توسط `is_api(request)` در هندلر خطا انجام می‌شود و `owned_room(api=True)` صرفاً چک پروفایل را رد می‌کند. کد گمراه‌کننده.

## 🔵 BE-23 — چند session همزمان و نامحدود برای هر کاربر؛ انقضای مطلق ۱۴ روزه بدون تمدید
**بازتولید واقعی:**
```
created_at=... expires_at=... (+14 days) last_seen_at=...
sessions rows in DB: 37   (یک ردیف برای هر ورود، تا ۱۴ روز نگه داشته می‌شوند)
```
`expires_at` هرگز جلو نمی‌رود → کاربر فعال **وسط جلسه** بعد از ۱۴ روز لاگ‌اوت می‌شود و در صفحه پخش فقط پیام «نشست شما منقضی شده است» را می‌بیند (play.js:228) و همهٔ دکمه‌ها disabled می‌مانند (FE-08). هیچ هشدار قبلی و هیچ `?next=` برای بازگشت وجود ندارد (BE-24).

## 🟠 BE-24 — بعد از انقضای نشست، کاربر به صفحهٔ قبلی برنمی‌گردد
**بازتولید واقعی:**
```
while logged in : GET /rooms/48/play -> 200
after session dies: 303 location=/login     (بدون ?next=)
login page has a 'next/return-to' field? False
after logging back in -> /    (اتاق/صفحه پخش گم شد)
```
**تأثیر:** برای کاربری که وسط مراسم نشستش منقضی می‌شود، بازگشت به صفحه پخش چند کلیک طول می‌کشد (و اگر cold start هم بخورد، دقیقه‌ها).
**راه‌حل:** `RedirectResponse(f"/login?next={quote(path)}")` و رعایت آن بعد از ورود (با allowlist مسیرهای داخلی برای جلوگیری از open redirect).

## 🔵 BE-25 — `logging.basicConfig(level=INFO)` در زمان import
**محل:** `main.py:81` — پیکربندی root logger در import، تداخل با لاگ uvicorn، نبود structured logging / request id / سطح قابل تنظیم با env، و نبود هرگونه error reporting (Sentry). خطاهای ۵۰۰ فقط با `logger.exception` ثبت می‌شوند.

## 🔵 BE-26 — `env_int` مقدار نامعتبر را بی‌صدا می‌بلعد
**محل:** `config.py:17-27` — اگر `MAS_MAX_UPLOAD_MB=abc` باشد، بدون هیچ warning از default استفاده می‌شود. یک typo در env production می‌تواند محدودیت‌ها را بی‌صدا عوض کند. همچنین `max_password_length`, `min_password_length`, `max_room_capacity` و ... در dataclass hardcoded هستند و از env قابل تنظیم نیستند (ناسازگاری با بقیهٔ تنظیمات).

## 🔵 BE-27 — `duration_seconds` ضبط صوت کاملاً از سمت کلاینت اعتماد می‌شود
**محل:** `main.py:699-704` — فقط range چک می‌شود؛ یک فایل ۱۰ ثانیه‌ای می‌تواند `duration_seconds=10800` ثبت شود. (فعلاً جایی نمایش داده نمی‌شود، ولی در DB ذخیره می‌شود = دادهٔ نادرست.)

## 🔵 BE-28 — `CSRF token` به‌صورت plaintext در DB و بدون rotation
**محل:** `models.py:123` (`csrf_token` در مقابل `token_hash` که HMAC است) — اگر DB لو برود، توکن CSRF مستقیماً قابل استفاده است (هرچند بدون کوکی session بی‌فایده است). همچنین توکن در کل عمر session ثابت است و هیچ rotation/Double-submit با `__Host-` prefix ندارد.

## 🔵 BE-29 — نبود مکانیزم «فراموشی رمز»، تأیید ایمیل، حذف حساب، نقش مدیر، یا هر گونه moderation
ثبت‌نام کاملاً باز است (بدون ایمیل/CAPTCHA) و با BE-01 می‌توان rate limit را دور زد → ساخت بی‌نهایت حساب و پر کردن دیسک (BE-13). هیچ پنل ادمین یا راهی برای ban/حذف کاربر وجود ندارد. اگر کاربر رمز را فراموش کند، **هیچ** راه بازیابی نیست (چون ایمیلی وجود ندارد).

## 🔵 BE-30 — `content_disposition` فقط `filename*` می‌فرستد (بدون fallback `filename="..."`)
**محل:** `storage.py:123-125`
```
content-disposition: attachment; filename*=UTF-8''%DA%AF%D8%B2%D8%A7%D8%B1%D8%B4...pdf
```
کلاینت‌های قدیمی/برخی download managerها که RFC 5987 را پشتیبانی نمی‌کنند، فایل را بدون نام ذخیره می‌کنند.
**راه‌حل:** هر دو: `attachment; filename="report.pdf"; filename*=UTF-8''...` (fallback ASCII).

---

# ۳) باگ‌های Frontend (HTML / CSS / JS / UX / دسترس‌پذیری)

## 🟠 FE-01 — کلاس‌های CSS استفاده‌شده در JS ولی **تعریف‌نشده** در `app.css`
**بررسی واقعی (تطبیق کلاس‌های template/JS با app.css):**
```
.status-online   css:0   play.js:63
.status-offline  css:0   play.js:63
.dragging        css:0   room_editor.js:24
.drop-target     css:0   room_editor.js:43
```
**تأثیر:**
- وضعیت اتصال صفحه پخش («همگام‌سازی فعال است» / «ارتباط با سرور قطع شده») **هیچ تفاوت ظاهری** ندارد (بدون رنگ سبز/قرمز) → کاربر وسط مراسم نمی‌فهمد تایمر sync است یا نه.
- Drag & drop مرتب‌سازی سخنران‌ها **هیچ بازخورد بصری** ندارد (نه کارت کشیده‌شده علامت‌دار می‌شود، نه محل رهاشدن).

## 🟠 FE-02 — اعلان پایان زمان فقط وقتی تب **باز/فعال** است کار می‌کند
**محل:** `play.js:122-150` (`renderTimer` فقط با `requestAnimationFrame` اجرا می‌شود) و `play.js:144-147`
`requestAnimationFrame` در تب مخفی/پنجرهٔ مینیمایز **اجرا نمی‌شود**؛ `schedulePoll` هم در حالت `document.hidden` متوقف است (`play.js:237`). پس:
- اگر مجری به تب دیگری برود (که در عمل همیشه اتفاق می‌افتد)، در لحظهٔ پایان زمان **هیچ modal و هیچ Notification** نمایش داده نمی‌شود؛ فقط وقتی برگشت modal را می‌بیند.
- README ادعا می‌کند «اعلان داخل سایت در پایان زمان مجاز» — در سناریوی واقعی نقض می‌شود.
**راه‌حل:** تشخیص پایان زمان با `setTimeout`/`setInterval` مستقل از rAF، یا (بهتر) push سمت سرور/SSE + Web Worker timer + پخش صدا.

## 🟠 FE-03 — لیست سخنران‌ها در صفحه پخش هر ۱.۵ ثانیه **کاملاً بازسازی** می‌شود
**محل:** `play.js:188` (`renderSpeakerList()` در انتهای `updateState`) و `play.js:82-107`
```js
list.innerHTML = "";  items.forEach(... document.createElement("button") ...)
```
**تأثیر:**
- فوکوس کیبورد از دست می‌رود (کاربر کیبورد/صفحه‌خوان عملاً نمی‌تواند لیست را پیمایش کند).
- hover/scroll/انیمیشن هر ۱.۵ ثانیه ریست می‌شود؛ اگر کاربر در حال کلیک روی سخنران باشد، المان زیر دستش عوض می‌شود.
- همچنین `renderFiles(DATA.common...)` و `renderRecordings()` در هر poll دوباره رندر می‌شوند (DOM churn بیهوده).
**راه‌حل:** diff/patch (یا به‌روزرسانی فقط کلاس `current`/`finished`) و رندر فایل‌ها فقط وقتی داده عوض شد.

## 🟠 FE-04 — حلقهٔ `requestAnimationFrame` هرگز متوقف نمی‌شود و هر فریم DOM را می‌نویسد
**محل:** `play.js:122-150` (حتی در شاخهٔ early-return، خط ۱۲۵ دوباره rAF ثبت می‌شود)، `play.js:341`
تایمر فقط **ثانیه** نمایش می‌دهد ولی حلقه ۶۰ فریم بر ثانیه `timer.textContent`، `overtime.textContent` و `bar.style.width` را می‌نویسد → repaint/layout دائم، مصرف CPU/باتری برای ساعت‌ها (یک جلسهٔ ۳ ساعته روی لپ‌تاپ پروژکتور). `raf` هیچ‌گاه `cancelAnimationFrame` نمی‌شود.
**راه‌حل:** `setInterval(…, 100)` یا rAF با gate روی تغییر مقدار (`if (text !== lastText)`)، و توقف حلقه وقتی تایمر متوقف است.

## 🟠 FE-05 — بعد از ۴۰۱ (انقضای نشست) همهٔ دکمه‌ها **برای همیشه disabled** می‌مانند
**محل:** `play.js:203-207` + `play.js:194-196`
```js
[...].forEach(b => b.disabled = true);
try { const state = await api(action); if (state) updateState(state); }   // state===null در 401
```
`api()` در ۴۰۱ مقدار `null` برمی‌گرداند → `updateState` صدا زده نمی‌شود → هیچ دکمه‌ای دوباره فعال نمی‌شود و `syncOnce()` هم به‌خاطر `sessionExpired` زود return می‌کند. همین‌طور `updateState` در خط ۱۶۸ `if (!speaker) return;` دارد که **قبل از فعال‌کردن دکمه‌ها** خارج می‌شود (اگر سخنران در تب دیگری حذف شده باشد، UI قفل می‌شود).
**راه‌حل:** `finally { enableControls() }` + در ۴۰۱ یک بنر «نشست تمام شد — ورود مجدد» با لینک `/login?next=...`.

## 🟠 FE-06 — حذف فایل در صفحهٔ ویرایش = `location.reload()` و از دست رفتن همهٔ تغییرات ذخیره‌نشده
**محل:** `room_editor.js:56-68`
```js
if (!response.ok) throw ...; location.reload();
```
کاربر ۲۰ سخنران را ویرایش کرده، یک فایل را حذف می‌کند → صفحه reload می‌شود و **همهٔ ویرایش‌ها و فایل‌های انتخاب‌شده از بین می‌روند**.
**راه‌حل:** حذف فقط همان ردیف از DOM + همگام‌سازی `manual_order`، بدون reload.

## 🟠 FE-07 — اعداد فارسی/لاتین قاطی می‌شوند
**بازتولید واقعی:**
```html
<div class="speaker-count" id="speaker-count">۰ / ۰</div>   <!-- play.html:12 -->
```
```js
speakerCount.textContent = `${state.current_index + 1} / ${state.total_speakers}`;   // play.js:172 → "1 / 3"
speakerTotal.textContent = String(items.length);                                     // play.js:87
```
**تأثیر:** در اولین بارگذاری «۰ / ۰» و یک لحظه بعد «1 / 3» — سبک ارقام وسط صفحه عوض می‌شود. همین در `public_room.js` و آمار `home.html` هم هست.
**راه‌حل:** یک تابع `toFa(n)` (یا `Intl.NumberFormat('fa-IR')`) برای همهٔ اعداد UI، یا یکدست‌سازی روی لاتین.

## 🟡 FE-08 — صفحهٔ اتاق، همهٔ اسلات‌های خالی را به‌عنوان کارت «بدون نام» نشان می‌دهد
**بازتولید واقعی (اتاق ۱۰ نفره با ۲ سخنران):**
```
speaker cards rendered: 10
card titles: ['علی','رضا','بدون نام' ×8]
header says: 10 ظرفیت · 2 سخنران ثبت‌شده     ← خودش هم می‌داند ۲ نفرند!
```
برای اتاق ۱۰۰ نفره → ۹۸ کارت بی‌مصرف، هر کدام با لینک «مشاهده در صفحه پخش».
**راه‌حل:** فیلتر `speakers` با نام (مثل کاری که `play()` در `main.py:655` می‌کند) یا نمایش خلاصهٔ «۸ اسلات خالی».

## 🟡 FE-09 — فرم ورود/ثبت‌نام بعد از خطا، نام کاربری تایپ‌شده را نگه نمی‌دارد
**بازتولید واقعی:**
```
POST /login (رمز اشتباه) → «نام کاربری یا رمز عبور اشتباه است.»
username re-rendered in the field? False
input tag: name="username" ... (بدون value)
```
همین در `register.html` و `new_room.html`. کاربر باید دوباره نام کاربری را تایپ کند.

## 🟡 FE-10 — مودال «پایان زمان مجاز» دسترس‌پذیر نیست
**محل:** `play.html:26`, `play.js:251-259`
`hidden` برداشته می‌شود ولی: فوکوس به مودال منتقل نمی‌شود، focus trap ندارد، با `Escape` بسته نمی‌شود، و المان‌های پشت مودال هنوز با Tab قابل دسترسی‌اند. `role="dialog"`/`aria-modal` هست ولی بی‌اثر بدون مدیریت فوکوس.

## 🟡 FE-11 — دسترس‌پذیری (a11y) ضعیف در کل برنامه
**بررسی واقعی:** در کل templates فقط **۵** ویژگی aria وجود دارد:
```
base.html: aria-label="ناوبری اصلی"
edit_room.html: aria-label="انتقال بالا" / "انتقال بالا"
play.html: aria-labelledby="overtime-title" / aria-modal="true"
```
- تایمر و «سخنران فعلی» هیچ `aria-live` ندارند → صفحه‌خوان تغییرات را اعلام نمی‌کند.
- دکمه‌های کنترل فقط ایموجی دارند (`▶ شروع`، `⏸ توقف`) بدون `aria-label`.
- `.play-speaker .mini-status{font-size:10px}` — متن زیر حداقل اندازهٔ خوانا.
- هیچ skip-link، هیچ `:focus-visible` سفارشی، و کنتراست `.muted` روی برخی پس‌زمینه‌ها لب مرز است.
- نبود `@media print` → چاپ لیست سخنران‌ها به‌هم ریخته.
- نبود `prefers-reduced-motion` (با وجود `transition` و `scroll-behavior:smooth`).

## 🟡 FE-12 — فونت فارسی مناسب وجود ندارد
**محل:** `app.css` → `font-family:Tahoma,Arial,sans-serif` و `grep -c "@font-face"` = **۰**.
Tahoma روی اندروید/لینوکس/بسیاری دستگاه‌های پروژکتوری وجود ندارد → متن فارسی با فونت fallback دلخواه (و metric متفاوت) رندر می‌شود. تایمر هم به `ui-monospace, Consolas` تکیه دارد که در لینوکس معادل دقیقی ندارد → پرش عرض ارقام.
**راه‌حل:** وب‌فونت فارسی self-host (وزیرمتن/ایران‌سنس) با `font-display: swap` و `font-variant-numeric: tabular-nums` برای تایمر.

## 🟡 FE-13 — نبود cache-busting برای assetها + نبود `Cache-Control` روی `/static`
**بازتولید واقعی هدرها:**
```
GET /static/app.css → 200, etag + last-modified, بدون cache-control
```
میان‌افزار (`main.py:96-97`) عمداً `/static` را از `no-store` مستثنا می‌کند ولی هیچ سیاست کشی هم ست نمی‌کند → مرورگر از heuristic caching استفاده می‌کند. `base.html:8` هم `/static/app.css` را **بدون** نسخه می‌آورد، در حالی که templateهای مرده از `?v={{ asset_version }}` استفاده می‌کنند (که هیچ‌وقت مقداردهی نمی‌شود!).
**تأثیر:** بعد از هر deploy ممکن است CSS/JS قدیمی برای بعضی کاربران سرو شود و UI نیمه‌شکسته نشان داده شود.
**راه‌حل:** hash در نام فایل یا `?v={{ build_id }}` واقعی + `Cache-Control: public,max-age=31536000,immutable` برای static.

## 🟡 FE-14 — موبایل/لمس: drag & drop کار نمی‌کند و safe-area رعایت نشده
`room_editor.js` فقط از HTML5 Drag and Drop استفاده می‌کند که **روی دستگاه لمسی کار نمی‌کند** (دکمه‌های ↑/↓ تنها راه‌اند، که خوب است) ولی `draggable="true"` روی کارتی که داخلش input است، در برخی مرورگرها انتخاب متن/اسکرول را مختل می‌کند. `viewport-fit=cover` در `base.html:5` هست ولی `grep -c safe-area app.css` = **۰** → در گوشی‌های notch‌دار، هدر sticky و `sticky-actions` ممکن است زیر نوار سیستم بروند.

## 🔵 FE-15 — کد مردهٔ Frontend که به‌صورت عمومی سرو می‌شود
| فایل | وضعیت |
|---|---|
| `templates/public_room.html` | هیچ route آن را render نمی‌کند؛ `public_token`/`live_files`/`asset_version` تعریف‌نشده‌اند؛ endpointهای `/public-api/rooms/{token}/state` و `/public-files/{token}/{id}` **وجود ندارند** |
| `static/public_room.js` | `GET /static/public_room.js → 200 (3096B)` — فراخوانی APIهای ناموجود |
| `templates/auth.html` | استفاده نمی‌شود؛ `asset_version` تعریف‌نشده؛ کلاس‌های `.auth-page/.brand/.error-box` در CSS نیستند |
| `static/rooms.js` | `GET → 200 (249B)` — سلکتور `.delete-room-form` در هیچ template نیست |
| کلاس‌های `.public-*`, `.live-badge`, `.head`, `.section` | در CSS تعریف نشده‌اند (۳۹ کلاس استفاده‌شده ولی تعریف‌نشده در بررسی خودکار) |

**نتیجه:** قابلیت «نمایش زنده برای تماشاگران» (که template و JS دارد) **اصلاً پیاده‌سازی نشده** — نه route، نه `public_token` در مدل، نه endpoint فایل عمومی. یا باید کامل شود یا حذف.

## 🔵 FE-16 — جای «خروج از حساب» در پایین همهٔ صفحه‌ها و بدون تأیید
`base.html:29-33` — فرم logout در `footer-actions` است؛ در صفحه پخش، یک کلیک اشتباه وسط مراسم = خروج (و چون `?next=` نیست، بازگشت به صفحه پخش چند مرحله دارد). نام کاربر لاگین‌کرده هم هیچ‌جا در header نمایش داده نمی‌شود (فقط در `home` و `profile`).

## 🔵 FE-17 — فایل‌های مشترک در صفحه پخش بدون توجه به کلید «نمایش فایل زنده» نشان داده می‌شوند
`play.js:177-179`: `speakerFilesSection.hidden = !DATA.live_files` ولی `renderFiles(DATA.common || [], commonFiles)` **همیشه** اجرا می‌شود؛ در حالی که `room.html:24` به کاربر می‌گوید «فایل‌های مشترک … در صورت فعال بودن فایل زنده، هنگام پخش نمایش داده می‌شوند». تناقض متن راهنما با رفتار واقعی.
همچنین `DATA.live_files`/`DATA.common` فقط هنگام بارگذاری صفحه خوانده می‌شوند → اگر در تب دیگری فایل جدیدی آپلود شود، صفحه پخش تا reload نمی‌فهمد.

## 🔵 FE-18 — نبود میان‌بر کیبورد/حالت پروژکتور/هشدار صوتی
برای ابزار اجرای زنده: Space برای start/pause، N/P برای بعدی/قبلی، F برای تمام‌کردن، حالت تمام‌صفحهٔ تایمر، و بوق/صدا در پایان زمان — هیچ‌کدام وجود ندارد.

## 🔵 FE-19 — نشتی حافظهٔ جزئی در ضبط صوت
`play.js:298, 313` — `URL.createObjectURL(blob)` ساخته می‌شود ولی هرگز `revokeObjectURL` نمی‌شود؛ با چند ضبط ناموفق، blobهای چند ده مگابایتی در حافظهٔ تب می‌مانند.

## 🔵 FE-20 — نبود نمایش پیشرفت/حجم هنگام آپلود و نبود پخش‌کنندهٔ صوت در آرشیو
- آپلود فایل در `edit_room_save` یک submit معمولی فرم است → هیچ progress bar، هیچ نمایش حجم، و در خطا کل صفحه به «خطا» می‌رود.
- صفحهٔ ضبط‌ها (`recordings.html`) فقط لینک «پخش» (باز شدن در تب جدید) دارد؛ `<audio controls>`، مدت زمان (`duration_seconds` که در DB ذخیره شده ولی هرگز نمایش داده نمی‌شود)، جست‌وجو، مرتب‌سازی و صفحه‌بندی ندارد.
- اندازهٔ فایل ضبط‌شده فقط **پایان** کار بررسی می‌شود (`blobTooLarge` در `play.js:297`) → کاربر ۳ ساعت ضبط می‌کند و تازه می‌فهمد از سقف رد شده.

---

# ۴) باگ‌های دیتابیس / لایهٔ داده

## 🟠 DB-01 — ۱۰ ایندکس تکراری که در **هر** startup ساخته می‌شوند (حتی روی DB کاملاً نو)
**بازتولید واقعی (dump از SQLite نوساخت):**
```
auth_sessions   ix_auth_sessions_expires_at      +  ix_sessions_expiry                     (تکراری)
auth_sessions   ix_auth_sessions_token_hash (UQ) +  uq_auth_session_token_legacy     (UQ)  (تکراری)
rooms           ix_rooms_owner_id                +  ix_room_owner                          (تکراری)
speech_files    ix_speech_files_room_id          +  ix_files_room                          (تکراری)
users           ix_users_username           (UQ) +  uq_users_username_legacy         (UQ)  (تکراری)
room_states     sqlite_autoindex_room_states_1   +  uq_room_state_room_legacy        (UQ)  (تکراری)
speakers        autoindex uq_speaker_room_order  +  uq_speaker_room_order_legacy     (UQ)  (تکراری)
speaker_timer_states autoindex uq_timer_...      +  uq_timer_room_speaker_legacy     (UQ)  (تکراری)
speech_files    autoindex storage_name      (UQ) +  uq_speech_file_storage_name_legacy(UQ) (تکراری)
file_cleanup_queue ix_...storage_name       (UQ) +  uq_cleanup_storage_name_legacy   (UQ)  (تکراری)
```
**محل:** `db.py:224-246`. اینها با عنوان «legacy» نوشته شده‌اند ولی **بدون هیچ شرطی** اجرا می‌شوند.
**تأثیر:** روی PostgreSQL هر UNIQUE INDEX اضافه = هزینهٔ نوشتن روی هر INSERT/UPDATE + فضای دیسک + زمان بیشتر برای migration آنلاین.
**راه‌حل:** قبل از ساخت، با `inspect(engine)` بررسی کنید که آیا constraint/index معادل وجود دارد؛ یا کل این بخش را داخل Alembic با نسخه‌بندی ببرید.

## 🟠 DB-02 — هیچ ابزار migration واقعی نیست؛ repairها در هر boot روی **کل** داده اجرا می‌شوند
**محل:** `db.py:14` (`SCHEMA_VERSION = 4`) و `db.py:249-295`
`SchemaInfo.version` نوشته می‌شود ولی **هرگز خوانده نمی‌شود** تا تصمیم بگیرد کدام repair لازم است. نتیجه: در هر startup:
- `_repair_speaker_order` → همهٔ اتاق‌ها و همهٔ سخنران‌ها load می‌شوند و `order_index` هر ردیف **دو بار** UPDATE می‌شود.
- `_dedupe_timer_states` / `_dedupe_room_states` / `_dedupe_storage_records` → `select(...).all()` روی **کل جدول** در حافظه.
- `_backfill_timer_precision` → همهٔ تایمرها و همهٔ room_stateها.
- `_backfill_room_storage_and_profile_flags` → یک `SUM()` به‌ازای هر اتاق + scan همهٔ کاربران.
- `_add_column_if_missing` → ۲۰ بار `inspect(engine)`.

**اندازه‌گیری واقعی (۱۲۰ اتاق × ۱۰۰ سخنران = ۱۲٬۰۰۰ ردیف):**
```
seeded in 0.89s
initialize_database() on startup: 1.16s
initialize_database() again     : 0.83s   ← در هر boot/restart تکرار می‌شود
```
روی PostgreSQL با latency شبکه، ۲۴٬۰۰۰ UPDATE در `_repair_speaker_order` می‌تواند **دقیقه‌ها** طول بکشد → cold start طولانی‌تر، و حتی شکست health check هنگام deploy. همچنین `.all()` روی جدول‌های بزرگ = خطر OOM در instance با ۵۱۲MB RAM.
**راه‌حل:** (۱) Alembic؛ (۲) gate کردن repairها با `SchemaInfo.version`؛ (۳) پردازش دسته‌ای/SQL-side به‌جای ORM در حافظه.

## 🟠 DB-03 — در دیتابیس legacy، کلید خارجی `speaker_timer_states` ساخته نمی‌شود → ردیف‌های یتیم برای همیشه
**بازتولید واقعی** (با همان اسکیمای legacy که تست‌های خود مخزن می‌سازند):
```
FKs declared on speaker_timer_states after migration: []
FKs declared on room_states.current_speaker_id     : []
ORPHAN speaker_timer_states rows after deleting the speaker: 1
DANGLING room_states.current_speaker_id references: 1
```
`initialize_database` فقط **ستون** اضافه می‌کند؛ هیچ FK/قیدی را بازسازی نمی‌کند (که در SQLite نیاز به rebuild جدول دارد). مدل ORM هم رابطه‌ای از `Speaker` به `SpeakerTimerState` ندارد (`models.py:163-180`)، پس cascade سمت ORM هم وجود ندارد.
**تأثیر:** روی دیتابیس مهاجرت‌شدهٔ production، با هر حذف سخنران یک ردیف تایمر یتیم می‌ماند؛ هیچ repair هم آن‌ها را پاک نمی‌کند → رشد نامحدود جدول و گزارش‌های نادرست.
**راه‌حل:** افزودن یک repair صریح (`DELETE FROM speaker_timer_states WHERE speaker_id NOT IN (SELECT id FROM speakers)`) در startup و/یا rebuild جدول با FK درست.

## 🟠 DB-04 — `room_states.current_speaker_id` اصلاً کلید خارجی ندارد (حتی در اسکیمای جدید)
**محل:** `models.py:213`
```python
current_speaker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
```
در مقابل بقیهٔ FKها که `ForeignKey(..., ondelete="CASCADE")` دارند. **بازتولید:** در تست DB-03 دیده شد که بعد از حذف سخنران، `current_speaker_id` روی id حذف‌شده باقی می‌ماند (dangling).
**تأثیر:** ارجاع معلق؛ `ensure_current_speaker` در زمان خواندن fallback می‌کند، ولی یک بار دیگر این مقدار در `_migrate_legacy_room_state`/`state_snapshot` مصرف می‌شود و می‌تواند سخنران اشتباهی را انتخاب کند؛ یکپارچگی داده در سطح DB تضمین نمی‌شود.
**راه‌حل:** `ForeignKey("speakers.id", ondelete="SET NULL")` + repair برای مقادیر معلق.

## 🟡 DB-05 — نبود قیدهای سطح DB (CHECK) و نبود enum واقعی
`capacity >= 0`، `global_seconds >= 60`، `speaking_seconds`، `age BETWEEN 1 AND 120`، `timing_mode IN ('global','individual')`، `order_mode IN (...)`، `gender IN ('','مرد','زن')`، `upload_type IN ('common','speaker','recording')` — همه فقط در کد پایتون اعتبارسنجی می‌شوند. هر نوشتن مستقیم/اسکریپت/باگ می‌تواند دادهٔ نامعتبر بسازد (مثلاً `timing_mode='hacked'` ذخیره شود و `timer_limit_ms` رفتار نامعین داشته باشد).
**راه‌حل:** `CheckConstraint` + (روی PostgreSQL) `ENUM` یا حداقل CHECK.

## 🟡 DB-06 — نبود ایندکس برای کوئری‌های پرتکرار
- `speech_files.upload_type` (کوئری `/recordings` و شمارش home) → بدون ایندکس، scan کامل.
- `speech_files.created_at` (مرتب‌سازی `ORDER BY id DESC` استفاده شده، ولی اگر مرتب‌سازی زمانی بخواهد) → نبود ایندکس.
- `speech_files (room_id, upload_type)` ترکیبی → برای `collect_room_storage`/play.
- `rooms (owner_id, id DESC)` → لیست اتاق‌ها.
- `speakers (room_id, name)` → `named_only=True` در هر poll.

## 🟡 DB-07 — `created_at` با `default=0` و نبود `updated_at`
`models.py:113, 124, 150, 194, 243` — `default=0` یعنی اگر جایی `now()` پاس نشود، رکورد با timestamp = ۰ ذخیره می‌شود و در `/recordings` به‌صورت «1970-01-01» نمایش داده می‌شود. هیچ `updated_at` برای `rooms`/`speakers` وجود ندارد (نه برای audit، نه برای تشخیص تغییر در BE-17).

## 🟡 DB-08 — timestamps همه به‌صورت epoch ثانیه/میلی‌ثانیهٔ UTC ذخیره می‌شوند ولی **هرگز** به منطقهٔ زمانی کاربر تبدیل نمی‌شوند
**محل نمایش:** `main.py:826-828`
```python
def human_time(ts): return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
```
**بازتولید واقعی:**
```
recordings rows: 'r2.webm', 'اتاق: ... · 2026-09-21 21:31'
server UTC now: 2026-09-21 21:31   |  Tehran now: 2026-09-22 01:01
```
روی Render، `time.localtime()` = UTC → کاربر ایرانی زمانی را می‌بیند که **۳.۵ ساعت** عقب است، بدون هیچ برچسب منطقهٔ زمانی، و با تقویم میلادی (در یک UI کاملاً فارسی).
**راه‌حل:** `Asia/Tehran` (یا TZ انتخابی کاربر) + تقویم شمسی (مثلاً `jdatetime`) + نمایش برچسب زمان.

## 🟡 DB-09 — سهمیهٔ `storage_used_bytes` می‌تواند برای همیشه نشت کند
در C-06 دیده شد که بعد از حذف فیزیکی فایل، `storage_used_bytes` همچنان ۱۰۰8 باقی ماند. تنها جایی که مقدار دقیق بازمحاسبه می‌شود، `_backfill_room_storage_and_profile_flags` در startup است (`db.py:183-193`) → یعنی تا restart بعدی، سهمیهٔ نشت‌شده کاربر را از آپلود محروم می‌کند (`reserve_room_storage` → ۴۰۰ «سهمیهٔ فضای این اتاق پر می‌شود»).

## 🔵 DB-10 — `started_at_ms` بر پایهٔ ساعت دیواری (`time.time_ns`) است
**محل:** `services.py:27-28` — تنظیم NTP یا تغییر ساعت سرور، تایمر را جابه‌جا می‌کند (مثلاً ۱ ثانیه عقب‌گرد NTP = پرش تایمر). برای تایمر یک مراسم، `time.monotonic()` مناسب‌تر است (با یک anchor دیواری برای persist).

## 🔵 DB-11 — جزئیات دیگر
- `String(20)` برای `timing_mode/order_mode/gender/upload_type` بدون مستندسازی مقادیر مجاز در DB.
- نبود `unique` روی `(owner_id, name)` برای اتاق‌ها → چند اتاق با نام یکسان (ممکن است عمدی باشد، ولی در UI گیج‌کننده است چون لیست فقط «اتاق #id» را نشان می‌دهد).
- نبود soft delete / سطل بازیافت برای اتاق، سخنران و فایل → هر حذفی قطعی است (ترکیب با C-04/C-07 خطرناک می‌شود).
- `sqlite` با `QueuePool` + `check_same_thread=False` و threadpool چهل‌نفرهٔ FastAPI → در production اگر SQLite استفاده شود (C-09)، قفل‌شدن و `database is locked` تا `busy_timeout=30s` محتمل است.

---

# ۵) امنیت (وضعیت فعلی و شکاف‌ها)

**مواردی که درست کار می‌کنند (تأیید شد):**
- کنترل دسترسی مالک اتاق کامل است: همهٔ ۱۴ مسیر تست‌شده برای کاربر دیگر **۴۰۴** برگرداندند (نه ۴۰۳ که نشتی اطلاعات باشد):
```
GET/POST /rooms/{id}, /edit, /play, /delete, /api/.../state, /start, /goto, /speakers/{id}/delete,
/api/.../recording, /files/{id}, /files/{id}/download, /files/{id}/delete  → همه 404
```
- CSRF درست اعمال می‌شود: توکن اشتباه → ۴۰۳؛ توکن کاربر دیگر → ۴۰۳؛ فیلد غایب → ۴۲۲.
- XSS: Jinja autoescape + `|tojson` → payload `<script>` به `&lt;script&gt;` تبدیل شد (تست مخزن هم تأیید می‌کند).
- Path traversal / نام فایل: `safe_storage_path` و `safe_filename` درست کار کردند؛ آپلود `.exe .svg .zip .js .sh .php .py .html .htm .docm .apk .msi .pdf.exe` → همه ۴۰۰؛ `.TXT` و `.txt ` پذیرفته شدند (case-insensitive و strip — درست).
- هدرهای امنیتی روی همهٔ پاسخ‌ها (تأیید واقعی):
```
x-content-type-options: nosniff / x-frame-options: DENY / referrer-policy: strict-origin-when-cross-origin
permissions-policy: microphone=(self) / cache-control: no-store (غیر static)
content-security-policy: default-src 'self'; script-src 'self'; ... frame-ancestors 'none'; form-action 'self'
```
- رمز با PBKDF2-SHA256/310k + salt تصادفی، `compare_digest` در verify، و rehash خودکار در صورت rounds کمتر؛ dummy hash برای یکنواخت‌سازی زمان پاسخ کاربر ناموجود.
- کوکی session: `HttpOnly`, `SameSite=lax`, `Secure` در production، و توکن به‌صورت HMAC در DB.

**شکاف‌ها:**
| ID | مشکل | محل |
|---|---|---|
| SEC-01 | دور زدن rate limit با `X-Forwarded-For` (BE-01) | `render.yaml:6` |
| SEC-02 | Lockout حساب با IP جعلی (BE-02) | `main.py:271-278` |
| SEC-03 | نبود rate limit روی همهٔ endpointهای API (تایمر، آپلود، حذف) → سوءاستفاده از منابع | `main.py:674-760` |
| SEC-04 | `HSTS` فقط وقتی `MAS_ENV=production`؛ اگر این متغیر ست نشود، کوکی `Secure` هم خاموش می‌شود و هیچ هشدار boot-time وجود ندارد | `main.py:103-104`, `config.py:79` |
| SEC-05 | نبود `Cross-Origin-Resource-Policy`/`Cross-Origin-Opener-Policy`؛ نبود `upgrade-insecure-requests` در CSP | `main.py:98-102` |
| SEC-06 | هدر `server: uvicorn` → نشتی جزئی فناوری | پیش‌فرض uvicorn |
| SEC-07 | کوکی `mas_guest_csrf` با `HttpOnly=False` (خط ۲۵۶) و بدون prefix `__Host-`؛ در حالی که مقدارش در hidden field است و نیازی به خواندن توسط JS ندارد | `main.py:256` |
| SEC-08 | نبود CAPTCHA/ایمیل روی ثبت‌نام باز + نبود سقف منابع هر کاربر (BE-13/BE-29) | — |
| SEC-09 | PBKDF2 با ۳۱۰هزار round زیر OWASP فعلی (۶۰۰هزار برای SHA256) و بدون ارتقای خودکار؛ از طرفی همین هزینه روی instance کوچک = بردار DoS وقتی SEC-01 وجود دارد | `auth.py:17` |
| SEC-10 | نبود لاگ امنیتی (ورود موفق/ناموفق، تغییر رمز، حذف اتاق) با قابلیت audit؛ فقط access log خام uvicorn | `main.py:81-82` |

---

# ۶) استقرار / DevOps

## 🟠 OPS-01 — سایت زنده عملاً «خواب» می‌شود و صفحهٔ Render را برمی‌گرداند (مشاهدهٔ مستقیم)
**مشاهدهٔ واقعی در زمان بررسی:**
```
~21:0x  GET /health  → 200 {"ok":true,"db":true,"storage":true}
~21:0x  GET /        → 303 /login   (صفحه ورود درست رندر شد)
~21:2x  GET /static/rooms.js → صفحهٔ «Render - Application loading»
~21:2x  GET /health          → صفحهٔ «Render - Application loading»
~21:3x  GET /login  → دوباره 200 (بازیابی شد)
```
**تأثیر:** برای ابزاری که قرار است **در لحظهٔ اجرای مراسم** کار کند، این یعنی در بدترین زمان ممکن سایت در دسترس نیست. صفحهٔ پخش در این حالت پاسخ HTML به‌جای JSON می‌گیرد → `play.js` فقط «ارتباط با سرور قطع شده؛ تلاش مجدد…» نشان می‌دهد.
**علت‌های تشدیدکننده در همین کد:** cold start با `initialize_database` که O(کل داده) است (DB-02)، PBKDF2 سنگین، و تک‌worker بودن.
**راه‌حل:** پلن غیررایگان/keep-warm (cron ping به `/health`)، سبک‌کردن startup، و پیام UI مناسب برای «سرور در حال بیدارشدن».

## 🟠 OPS-02 — `render.yaml` ناقص/ناسازگار با `Dockerfile`
```yaml
buildCommand: pip install -r requirements.txt
startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
healthCheckPath: /health
envVars: PYTHON_VERSION, MAS_ENV, MAS_COOKIE_SECURE, MAS_SECRET_KEY, DATABASE_URL(sync:false)
```
- `MAS_STORAGE_DIR` **نیست** → فایل‌ها روی دیسک موقت (C-09).
- `MAS_MAX_UPLOAD_MB` / `MAS_MAX_ROOM_STORAGE_MB` / `MAS_MAX_RECORDING_MINUTES` نیستند → با مقادیر پیش‌فرض ۵۰MB/۱۰۰۰MB/۱۸۰min که با دیسک ۵۱۲MB Render ناسازگارند (BE-13).
- `DATABASE_URL: sync:false` بدون مقدار و بدون guard (C-09).
- `Dockerfile:17` = `uvicorn mas_app.main:app ... --proxy-headers` (بدون `--forwarded-allow-ips`)، entry point متفاوت از render.yaml → دو مسیر استقرار با رفتار متفاوت (BE-01).
- `Dockerfile` از `python:3.12-slim` بدون pin کردن minor، در حالی که render.yaml `3.12.10` می‌خواهد.
- `Dockerfile` با `COPY . .` همه‌چیز (از جمله `.git` اگر باشد، `tests/`، `mas.db` اگر commit شده باشد) را داخل image می‌برد؛ `.dockerignore` **وجود ندارد**.
- هیچ `USER` غیر root تعریف نشده → کانتینر به‌عنوان root اجرا می‌شود.
- تک‌worker بدون `--workers`/gunicorn؛ `maintenance_worker` در هر worker تکرار می‌شود.

## 🟡 OPS-03 — `/health` در هر فراخوانی روی دیسک فایل می‌نویسد
**محل:** `main.py:872-885` — هر health check (هر چند ثانیه توسط Render + هر مانیتور خارجی) یک `write_bytes` + `unlink` انجام می‌دهد. علاوه بر IO بیهوده، اگر دیسک پر/فقط‌خواندنی شود → ۵۰۳ → Render سرویس را restart می‌کند → چون دیسک هنوز پر است، **حلقهٔ crash**. همچنین اگر DB قطع شود، `db.execute(select(1))` → ۵۰۰ (HTML!) نه ۵۰۳ JSON.
**راه‌حل:** تفکیک liveness (بدون IO) از readiness (بررسی DB/دیسک با throttle)، و پاسخ JSON با کد مناسب.

## 🟡 OPS-04 — `reconcile_orphans` می‌تواند دادهٔ سالم را پاک کند
**محل:** `main.py:132-141` (در startup) و `storage.py:139-158`
هر فایل فیزیکی که در `speech_files` مرجع نداشته باشد و قدیمی‌تر از ۱۵ دقیقه باشد **حذف می‌شود**. اگر DB (مثلاً SQLite موقت) از دست برود ولی دیسک پایدار بماند، یا دو محیط یک دیسک را share کنند، یا یک رکورد به‌دلیل باگ C-06 از DB بیفتد → حذف گستردهٔ فایل‌های معتبر. هیچ dry-run/لاگ «چه چیزی حذف شد» با نام فایل وجود ندارد (فقط شمارش برگردانده می‌شود و حتی لاگ نمی‌شود).

## 🟡 OPS-05 — نبود CI/CD، نبود LICENSE، نبود ابزار توسعه
```
$ ls .github  → no .github directory (no CI/CD, no issue templates)
$ ls LICENSE* → NO LICENSE file
```
- هیچ GitHub Actions برای اجرای `pytest` روی PR وجود ندارد (۲۰ تست فقط دستی اجرا می‌شوند).
- نبود LICENSE یعنی مخزن عمومی ولی «همهٔ حقوق محفوظ» — برای همکاری دیگران مانع قانونی است.
- `REPLACE_GITHUB.md` فرآیند استقرار را «بازکردن ZIP و جایگزینی فایل‌ها» توصیف می‌کند (بدون review/branch/PR) → همان چیزی که باعث شده تاریخچهٔ git به یک commit «Add files via upload» ختم شود.
- `.gitignore` ناقص است: `.venv/`, `.pytest_cache/`, `*.db-wal`, `*.db-shm`, `.DS_Store`, `.ruff_cache/` ندارد (در همین بررسی `.venv/` به‌عنوان untracked دیده شد).
- نبود pre-commit/linter/formatter config (pyflakes در این بررسی ۸ import بلااستفاده در کد برنامه و ۵ مورد در تست‌ها پیدا کرد).

## 🔵 OPS-06 — نبود observability
هیچ metric، structured log، request id، tracing یا error reporting وجود ندارد. `logger.exception` تنها مکانیزم است؛ برای تشخیص مشکلات production (مثل OPS-01) هیچ داده‌ای در دسترس نیست.

## 🔵 OPS-07 — نبود backup/restore
README فقط می‌گوید «قبل از deploy backup بگیر»؛ هیچ اسکریپت/داکیومنت dump و restore، و هیچ نسخه‌گیری از `uploads/` وجود ندارد. با توجه به C-04/C-07/C-09 این یک شکاف جدی است.

---

# ۷) تست و کیفیت کد

| ID | مورد | جزئیات |
|---|---|---|
| QA-01 | ۲۰ تست موجود پاس می‌شوند (`20 passed in 5.32s`) ولی **هیچ‌کدام** باگ‌های بالا را پوشش نمی‌دهند | هیچ تستی برای: حذف سخنران وقتی اسلات خالی قبل از آن است (C-01)، رمز غیر ASCII (C-02)، `global_min` نامعتبر (C-03)، کوچک‌کردن ظرفیت با سخنران نام‌دار (C-04)، خطای بعد از commit (C-06)، همزمانی واقعی، PostgreSQL واقعی، یا frontend نیست |
| QA-02 | تست‌ها به `follow_redirects` پیش‌فرض TestClient تکیه دارند | `assert r.status_code == 200` بعد از `POST /register` (که ۳۰۳ است) → اگر روزی پیش‌فرض عوض شود همه می‌شکنند؛ بهتر است `follow_redirects=False` و بررسی `303 + Location` |
| QA-03 | همهٔ تست‌ها روی **یک** app سراسری و یک DB مشترک (`tempfile.mkdtemp` در import) اجرا می‌شوند | `tests/test_app.py:8-19` در زمان import env را ست می‌کند → ایزوله نیست؛ ترتیب تست‌ها روی داده اثر می‌گذارد (usernameهای یکتا با پسوند `_1` مدیریت شده‌اند) |
| QA-04 | نبود تست integration برای PostgreSQL | خود README هم اعتراف می‌کند: «تست PostgreSQL واقعی … اجرا نشده است». با توجه به `with_for_update`, `skip_locked`, `CASE/GREATEST`, `ALTER TABLE ADD COLUMN NOT NULL DEFAULT` و unique indexها، ریسک واقعی است |
| QA-05 | کد مرده در کد برنامه | `storage.cleanup_storage_temp_files()` هرگز صدا زده نمی‌شود (lifespan همان منطق را inline دارد)؛ `services.RoomSnapshot` استفاده نمی‌شود؛ پارامتر `api` در `get_auth_context` بی‌استفاده (BE-22)؛ import‌های بلااستفاده: `db.py:4,7,8`، `main.py:10,42,43,66`، `services.py:8` |
| QA-06 | pyflakes روی تست‌ها | `tests/test_app.py:21,22` import بلااستفاده؛ `:187` و `:409` متغیر بلااستفاده |
| QA-07 | تابع در انتهای ماژول تعریف شده و در وسط فایل استفاده می‌شود | `hmac_compare` در `main.py:890` تعریف و در `main.py:397` استفاده شده (کار می‌کند ولی خوانایی/لینتر بد؛ و `import hmac` داخل تابع) |
| QA-08 | `from .services import persist_running_elapsed` **داخل** بدنهٔ تابع (دو بار) | `main.py:491`, `main.py:766` — در حالی که بقیهٔ services در بالای فایل import شده‌اند |
| QA-09 | مستندات ناسازگار با واقعیت | README/CHANGELOG: «اعلان داخل سایت در پایان زمان مجاز» (FE-02)، «حذف سخنران در حالت پخش + انتخاب خودکار سخنران بعدی» (C-01 → در حالت رایج ۵۰۰ می‌شود)، «Rate Limit پایدار در DB» (BE-01)؛ دستور اجرای محلی فقط برای ویندوز (`.venv\Scripts\activate`) نوشته شده و معادل Linux/macOS ندارد |
| QA-10 | `main.py` ۸۹۵ خط در یک فایل با همهٔ routeها به‌صورت تو در تو داخل `create_app` | نبود router تفکیک‌شده (auth/rooms/files/api)، تست‌پذیری و نگهداری سخت |

---

# ۸) جمع‌بندی سریع: ۱۰ مورد اولی که باید همین امروز اصلاح شوند

1. **C-01** — شماره‌گذاری مجدد همهٔ اسلات‌ها در `delete_speaker` (وگرنه «حذف سخنران» در حالت رایج ۵۰۰ است).
2. **C-02** — حذف `hmac_compare` برای مقایسهٔ رمز (`new_password == current_password`).
3. **C-07 + C-04** — تأییدیه برای حذف اتاق و برای کوچک‌کردن ظرفیت (جلوگیری از حذف دائم داده).
4. **C-05** — افزودن «رفع فریز» / «بازنشانی همه» + صفرکردن تایمر هنگام تغییر نام.
5. **C-06** — بیرون بردن cleanup از بلوک `try` (یا پرچم `committed`).
6. **C-03** — try/except روی `global_min` و `manual_order` (+ پیام فارسی).
7. **C-09 + OPS-02** — guard برای SQLite در production، افزودن `MAS_STORAGE_DIR`/Persistent Disk و مقادیر `MAS_MAX_*` به `render.yaml`.
8. **C-08 + DB-01/DB-02** — dedupe برای `users.username`/`auth_sessions.token_hash`، gate کردن repairها با `SchemaInfo.version`، و مهاجرت به Alembic.
9. **BE-01/BE-02** — اصلاح `--forwarded-allow-ips` و طراحی مجدد rate limit/lockout.
10. **FE-01/FE-02/FE-03** — افزودن کلاس‌های CSS گم‌شده، مستقل‌کردن اعلان پایان زمان از `requestAnimationFrame`، و جلوگیری از بازسازی کامل لیست سخنران‌ها در هر poll.

---

## پیوست الف — خروجی خام تست‌های کلیدی (برای ارجاع)

```text
# C-01
POST /api/rooms/{rid}/speakers/{id}/delete → 500 {"detail":"خطای داخلی سرور."}
sqlite3.IntegrityError: UNIQUE constraint failed: speakers.room_id, speakers.order_index
[SQL: UPDATE speakers SET order_index=? WHERE speakers.id = ?] [parameters: (0, 6)]

# C-02
POST /profile/password (new_password=رمزعبور۱۲۳) → 500
TypeError: comparing strings with non-ASCII characters is not supported  (main.py:397 → 892)

# C-03
POST /rooms/{id}/edit global_min=''    → 500
POST /rooms/{id}/edit global_min='5.5' → 500
POST /rooms/{id}/edit manual_order='²' → 500

# C-04
shrink to capacity=1 → 303 ; remaining speakers: [('12','علی')] ; files: ['shared.txt'] (maryam-note.txt حذف شد)

# C-06
DB rows still committed: [(1,'ok.webm',...), (2,'lost.webm',...)]
files on disk now: ['...ok.webm']        (lost.webm حذف شد)
room.storage_used_bytes: 1008            (سهمیه آزاد نشد)
GET /files/2 → 404 «فایل روی سرور وجود ندارد»

# BE-01
12 failed logins, no XFF      : [401×10, 429, 429]
12 failed logins, spoofed XFF : [401×12]

# BE-04 (random)
['پ','الف','ت','ب'] → ['الف','ب','ت','پ'] → ['پ','ت','الف','ب'] → ['الف','ت','ب','پ']

# BE-12
/recordings?room_id=99999999999999999999 → 500  (OverflowError)
/files/99999999999999999999             → 500

# BE-16/BE-15
GET /api/rooms/1/state → 7 SELECT، 624 B (۳ سخنران) | 7.8 KB (۱۰۰ سخنران)، هر ۱.۵ ثانیه
GET /rooms/1/play      → 14 SELECT | edit page ۱۰۰ نفره = 124 KB و ۶۱۱ کنترل فرم

# DB-01/DB-03
۱۰ ایندکس تکراری در DB نوساخت
legacy DB: FKs on speaker_timer_states = [] → ORPHAN rows = 1 ؛ dangling current_speaker_id = 1

# DB-02
۱۲۰ اتاق × ۱۰۰ سخنران → initialize_database() هر boot: 0.83–1.16s (۲۴٬۰۰۰ UPDATE)

# C-08
CREATE UNIQUE INDEX uq_users_username_legacy → IntegrityError: UNIQUE constraint failed: users.username (boot شکست خورد)

# FE-08
۱۰ کارت سخنران برای ۲ سخنران واقعی: ['علی','رضا','بدون نام'×8]

# DB-08
recordings: '2026-09-21 21:31' در حالی که تهران '2026-09-22 01:01'

# OPS-01
https://mas-xyrb.onrender.com/health → «Render - Application loading» (و بعد از ~۱ دقیقه دوباره 200)

# BE-09 (روی سایت زنده)
https://mas-xyrb.onrender.com/nonexistent-page-xyz → {"detail":"Not Found"}
https://mas-xyrb.onrender.com/api/rooms/1/state   → {"detail":"وارد حساب کاربری شوید."}
```

## پیوست ب — محیط/ابزار بررسی
- Python 3.11.2، `fastapi==0.128.2`, `starlette==0.50.0`, `SQLAlchemy==2.0.50`, `python-multipart==0.0.29` (دقیقاً همان `requirements.txt`).
- سرور: `uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"` (همان start command در `render.yaml`).
- کلاینت تست: `httpx` (بدون و با `follow_redirects`)، `TestClient`، `curl`، و multipart خام با هدر UTF-8 دقیقاً مثل مرورگر (نام فایل فارسی درست منتقل شد — این بخش سالم است).
