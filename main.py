import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, selectinload

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE / 'mas.db'}")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
SECRET_KEY = os.getenv("MAS_SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    # Development fallback only. Production README requires a real secret in the environment.
    SECRET_KEY = hashlib.sha256(f"dev-{BASE}".encode()).hexdigest()

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

SESSION_COOKIE = "mas_session"
SESSION_TTL = 60 * 60 * 24 * 14
MAX_UPLOAD_BYTES = int(os.getenv("MAS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".txt", ".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".webm", ".png", ".jpg", ".jpeg"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    account_name: Mapped[str] = mapped_column(String(120), default="")
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    job: Mapped[str] = mapped_column(String(120), default="")
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer)
    rooms: Mapped[list["Room"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
    user: Mapped[User] = relationship(back_populates="sessions")


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    capacity: Mapped[int] = mapped_column(Integer)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    live_files_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timing_mode: Mapped[str] = mapped_column(String(20), default="global")
    global_seconds: Mapped[int] = mapped_column(Integer, default=300)
    order_mode: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[int] = mapped_column(Integer)
    owner: Mapped[User] = relationship(back_populates="rooms")
    speakers: Mapped[list["Speaker"]] = relationship(back_populates="room", cascade="all, delete-orphan", order_by="Speaker.order_index")
    files: Mapped[list["SpeechFile"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    state: Mapped[Optional["RoomState"]] = relationship(back_populates="room", uselist=False, cascade="all, delete-orphan")


class Speaker(Base):
    __tablename__ = "speakers"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    gender: Mapped[str] = mapped_column(String(20), default="")
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    speaking_seconds: Mapped[int] = mapped_column(Integer, default=300)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    room: Mapped[Room] = relationship(back_populates="speakers")
    files: Mapped[list["SpeechFile"]] = relationship(back_populates="speaker", cascade="all, delete-orphan")


class SpeechFile(Base):
    __tablename__ = "speech_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    speaker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("speakers.id", ondelete="CASCADE"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_name: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    upload_type: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[int] = mapped_column(Integer)
    room: Mapped[Room] = relationship(back_populates="files")
    speaker: Mapped[Optional[Speaker]] = relationship(back_populates="files")


class RoomState(Base):
    __tablename__ = "room_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), unique=True)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0)
    overtime_seconds: Mapped[int] = mapped_column(Integer, default=0)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer)
    room: Mapped[Room] = relationship(back_populates="state")


Base.metadata.create_all(engine)
app = FastAPI(title="ماس | مدیریت اتاق سخنرانی")


# ------------------------------ Security helpers ------------------------------
def pbkdf2_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds_s, salt_hex, digest_hex = encoded.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds_s)).hex()
        return hmac.compare_digest(candidate, digest_hex)
    except Exception:
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_session(user_id: int, response: RedirectResponse):
    raw = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    now = int(time.time())
    with Session(engine) as db:
        db.add(AuthSession(user_id=user_id, token_hash=sha256(raw), csrf_token=csrf, created_at=now, expires_at=now + SESSION_TTL))
        db.commit()
    response.set_cookie(SESSION_COOKIE, raw, max_age=SESSION_TTL, httponly=True, secure=os.getenv("MAS_COOKIE_SECURE", "0") == "1", samesite="lax")


def get_session(request: Request) -> AuthSession:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(303, headers={"Location": "/login"})
    with Session(engine) as db:
        s = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256(raw)))
        if not s or s.expires_at < int(time.time()):
            raise HTTPException(303, headers={"Location": "/login"})
        db.expunge(s)
        return s


def current_user(request: Request) -> User:
    s = get_session(request)
    with Session(engine) as db:
        u = db.get(User, s.user_id)
        if not u:
            raise HTTPException(303, headers={"Location": "/login"})
        db.expunge(u)
        return u


def require_csrf(request: Request, csrf: str):
    s = get_session(request)
    if not hmac.compare_digest(s.csrf_token, csrf or ""):
        raise HTTPException(403, "درخواست نامعتبر است.")


def owned_room(request: Request, room_id: int) -> Room:
    u = current_user(request)
    with Session(engine) as db:
        r = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == u.id))
        if not r:
            raise HTTPException(404, "اتاق پیدا نشد.")
        db.expunge(r)
        return r


def validate_capacity(capacity: int):
    if capacity < 1 or capacity > 100:
        raise ValueError("ظرفیت باید بین ۱ تا ۱۰۰ باشد.")


def safe_filename(name: str) -> str:
    name = Path(name).name.replace("\x00", "").strip()
    if not name:
        raise ValueError("نام فایل نامعتبر است.")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("این نوع فایل مجاز نیست.")
    return name


async def store_upload(up: UploadFile) -> tuple[str, str, int, str]:
    original = safe_filename(up.filename or "")
    ext = Path(original).suffix.lower()
    storage = f"{uuid.uuid4().hex}{ext}"
    path = UPLOADS / storage
    total = 0
    with path.open("wb") as out:
        while True:
            chunk = await up.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                out.close()
                path.unlink(missing_ok=True)
                raise ValueError(f"حجم هر فایل حداکثر {MAX_UPLOAD_BYTES // 1024 // 1024} مگابایت است.")
            out.write(chunk)
    return original, storage, total, (up.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream")


def html_escape(s) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def session_csrf(request: Request) -> str:
    return get_session(request).csrf_token


# ------------------------------ Views ------------------------------
CSS = r"""
*{box-sizing:border-box}body{margin:0;background:#f4f7fb;color:#172536;font-family:Tahoma,Arial,sans-serif}a{text-decoration:none;color:inherit}
header{background:#fff;border-bottom:1px solid #e3e9ef;position:sticky;top:0;z-index:20}.top{max-width:1150px;margin:auto;padding:15px 18px;display:flex;justify-content:space-between;align-items:center}.logo{font-weight:900;font-size:24px;color:#0a527f}.logo small{display:block;font-size:10px;color:#758394;font-weight:500}.add,.primary{background:#0c5d91;color:#fff;border:0;border-radius:12px;padding:11px 16px;font-weight:800;cursor:pointer}.danger{background:#d33d4a;color:#fff;border:0;border-radius:10px;padding:10px 14px}.secondary{border:1px solid #ccd7e1;background:#fff;border-radius:10px;padding:10px 14px;cursor:pointer}nav{max-width:1150px;margin:auto;display:flex;gap:5px;padding:0 12px 10px;overflow:auto}nav a{padding:10px 14px;border-radius:10px;white-space:nowrap;color:#687687}.on{background:#e7f3fa;color:#075887!important;font-weight:800}.disabled{opacity:.45;pointer-events:none}main{max-width:1150px;margin:auto;padding:28px 16px 80px}h1,h2,h3{margin-top:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}.card,.form{background:#fff;border:1px solid #e0e7ee;border-radius:18px;padding:20px;box-shadow:0 6px 22px #173b530b}.muted{color:#778494}.stat{font-size:32px;color:#0c5d91;font-weight:900}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px}.room{position:relative;cursor:pointer;transition:.15s}.room:hover{box-shadow:0 10px 28px #173b5318;transform:translateY(-1px)}.dots{position:absolute;left:12px;top:12px;border:0;background:#edf2f6;border-radius:10px;font-size:20px}.pop{display:none;position:absolute;left:10px;top:48px;background:#fff;border:1px solid #dfe6ed;border-radius:10px;box-shadow:0 10px 25px #0002;z-index:5;overflow:hidden}.pop button{display:block;border:0;background:#fff;padding:10px 15px;width:130px;text-align:right;cursor:pointer}.pop button:hover{background:#f2f6f9}label{display:block;font-weight:700;font-size:14px;margin:12px 0}input,select,textarea{width:100%;padding:12px;border:1px solid #d5dee7;border-radius:11px;margin-top:7px;background:#fff}input:focus,select:focus,textarea:focus{outline:0;border-color:#0c6b9f;box-shadow:0 0 0 3px #0c6b9f19}.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.section{margin:22px 0}.speaker{background:#fff;border:1px solid #e0e7ee;border-radius:16px;padding:18px;margin-bottom:14px}.switches{display:flex;gap:20px;flex-wrap:wrap}.switches label{font-weight:600}.switches input{width:auto}.file{border:2px dashed #cad8e4;border-radius:13px;padding:14px;margin-top:10px}.empty{text-align:center;padding:45px;color:#7b8795}.float{position:fixed;bottom:25px;left:25px;width:64px;height:64px;border-radius:50%;border:0;background:#0c5d91;color:#fff;font-size:24px;box-shadow:0 12px 30px #0c5d9140;cursor:pointer}.timer{font-size:72px;text-align:center;font-weight:900;direction:ltr}.overtime{text-align:center;color:#c52e40;font-size:21px;font-weight:800;min-height:30px}.bar{height:9px;background:#e5ebf0;border-radius:20px;overflow:hidden}.bar i{display:block;height:100%;background:#0c5d91}.auth{min-height:100vh;display:grid;place-items:center;background:linear-gradient(145deg,#092a4b,#0e5e91);padding:20px}.auth .form{width:min(430px,100%);text-align:center;padding:32px}.brand{font-size:44px;color:#0b5d91;font-weight:900}.auth .brand{color:#0c5d91}.error{color:#c52e40}.success{color:#17804d}.inline-form{display:inline}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #edf1f4;text-align:right}.grip{cursor:grab;font-size:20px;color:#8795a5}.flash{padding:12px 16px;border-radius:11px;background:#edf7ff;margin-bottom:14px}.danger-text{color:#c52e40}@media(max-width:650px){.two{grid-template-columns:1fr}.timer{font-size:50px}.top{padding:12px}.add{padding:9px 11px;font-size:13px}}
"""
JS = r"""
function toast(t){let x=document.getElementById('toast');x.textContent=t;x.style.display='block';setTimeout(()=>x.style.display='none',2200)}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
"""


def page(title: str, body: str, request: Optional[Request] = None, active: str = "home") -> str:
    csrf = html_escape(session_csrf(request)) if request else ""
    nav = f'''<header><div class="top"><a class="logo" href="/">مــاس <small>مدیریت اتاق سخنرانی</small></a><a class="add" href="/rooms/new">＋ افزودن اتاق</a></div>
<nav><a class="{'on' if active=='home' else ''}" href="/">خانه</a><a class="{'on' if active=='profile' else ''}" href="/profile">پروفایل کاربری</a><a class="{'on' if active in ['rooms','room','play'] else ''}" href="/rooms">اتاق‌های سخنرانی</a><a class="disabled" href="#">فایل‌های ضبط شده</a></nav></header>'''
    logout = f'''<form class="inline-form" method="post" action="/logout"><input type="hidden" name="csrf" value="{csrf}"><button style="border:0;background:none;color:#c52e40;font-weight:bold;cursor:pointer">خروج از حساب</button></form>'''
    return f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html_escape(title)}</title><style>{CSS}</style></head><body>{nav}<main>{body}<div style="margin-top:30px">{logout}</div></main><div id="toast" style="display:none;position:fixed;right:20px;bottom:20px;background:#182a3a;color:white;padding:13px 18px;border-radius:12px;z-index:50"></div><script>{JS}</script></body></html>'''


def auth_page(kind: str, msg: str = "") -> str:
    if kind == "login":
        body = f'''<div class="auth"><div class="form"><div class="brand">مــاس</div><h1>مدیریت اتاق سخنرانی</h1><p class="muted">ورود به حساب کاربری</p><form method="post" action="/login"><label>نام کاربری<input name="username" autocomplete="username" required></label><label>رمز عبور<input name="password" type="password" autocomplete="current-password" required></label><button class="primary" style="width:100%">ورود</button></form><p><a href="/register" style="color:#0c5d91;font-weight:bold">ایجاد حساب کاربری</a></p><p class="error">{html_escape(msg)}</p></div></div>'''
    else:
        body = f'''<div class="auth"><div class="form"><div class="brand">مــاس</div><h1>ایجاد حساب کاربری</h1><p class="muted">مرحله اول: نام کاربری و رمز عبور</p><form method="post" action="/register"><label>نام کاربری انگلیسی<input name="username" pattern="[A-Za-z0-9_]+" minlength="3" maxlength="32" autocomplete="username" required placeholder="hossein_20"></label><label>رمز عبور<input name="password" type="password" minlength="8" autocomplete="new-password" required></label><label>تکرار رمز عبور<input name="password2" type="password" minlength="8" autocomplete="new-password" required></label><button class="primary" style="width:100%">ایجاد حساب</button></form><p><a href="/login" style="color:#0c5d91;font-weight:bold">بازگشت به ورود</a></p><p class="error">{html_escape(msg)}</p></div></div>'''
    return f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ماس</title><style>{CSS}</style></head><body>{body}</body></html>'''


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.cookies.get(SESSION_COOKIE):
        try:
            current_user(request)
            return RedirectResponse("/", 303)
        except HTTPException:
            pass
    return auth_page("login")


LOGIN_ATTEMPTS: dict[str, list[int]] = {}

def allow_login(username: str) -> bool:
    now = int(time.time())
    arr = [t for t in LOGIN_ATTEMPTS.get(username, []) if now - t < 600]
    LOGIN_ATTEMPTS[username] = arr
    return len(arr) < 10


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if not allow_login(username):
        return HTMLResponse(auth_page("login", "تلاش‌های ورود زیاد است؛ چند دقیقه بعد دوباره امتحان کنید."), status_code=429)
    with Session(engine) as db:
        u = db.scalar(select(User).where(User.username == username))
        valid = bool(u and verify_password(password, u.password_hash))
        if valid:
            LOGIN_ATTEMPTS.pop(username, None)
            response = RedirectResponse("/", 303)
            create_session(u.id, response)
            return response
    LOGIN_ATTEMPTS.setdefault(username, []).append(int(time.time()))
    return HTMLResponse(auth_page("login", "نام کاربری یا رمز عبور اشتباه است."), status_code=401)


@app.get("/register", response_class=HTMLResponse)
def register_page():
    return auth_page("register")


@app.post("/register")
def register(username: str = Form(...), password: str = Form(...), password2: str = Form(...)):
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        return HTMLResponse(auth_page("register", "نام کاربری باید فقط شامل حروف انگلیسی، عدد و _ و بین ۳ تا ۳۲ کاراکتر باشد."), status_code=400)
    if len(password) < 8:
        return HTMLResponse(auth_page("register", "رمز عبور باید حداقل ۸ کاراکتر باشد."), status_code=400)
    if password != password2:
        return HTMLResponse(auth_page("register", "رمزها یکسان نیستند."), status_code=400)
    with Session(engine) as db:
        if db.scalar(select(User).where(User.username == username)):
            return HTMLResponse(auth_page("register", "این نام کاربری قبلاً ثبت شده است."), status_code=409)
        u = User(username=username, password_hash=pbkdf2_hash(password), created_at=int(time.time()))
        db.add(u); db.commit(); db.refresh(u)
        response = RedirectResponse("/profile?first=1", 303)
        create_session(u.id, response)
        return response


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    require_csrf(request, csrf)
    raw = request.cookies.get(SESSION_COOKIE)
    with Session(engine) as db:
        s = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256(raw or "")))
        if s:
            db.delete(s); db.commit()
    response = RedirectResponse("/login", 303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = current_user(request)
    with Session(engine) as db:
        rooms = db.scalars(select(Room).where(Room.owner_id == u.id).order_by(Room.id.desc())).all()
    cards = "".join(f'''<div class="card room" onclick="location.href='/rooms/{r.id}'"><button class="dots" onclick="event.stopPropagation();this.nextElementSibling.style.display=this.nextElementSibling.style.display==='block'?'none':'block'">⋮</button><div class="pop"><button onclick="location.href='/rooms/{r.id}/edit'">ویرایش</button><form method="post" action="/rooms/{r.id}/delete" onclick="event.stopPropagation()"><input type="hidden" name="csrf" value="{html_escape(session_csrf(request))}"><button class="danger-text" type="submit" onclick="return confirm('حذف شود؟')">حذف</button></form></div><h3>{html_escape(r.name)}</h3><p class="muted">ظرفیت: {r.capacity} سخنران</p></div>''' for r in rooms)
    body = f'''<div class="head"><div><h2>خانه</h2><p class="muted">سلام {html_escape(u.account_name or u.username)} 👋</p></div><a class="primary" href="/rooms/new">＋ افزودن اتاق</a></div><div class="grid"><div class="card"><div class="stat">{len(rooms)}</div>اتاق ساخته شده</div><div class="card"><div class="stat">{sum(r.capacity for r in rooms)}</div>ظرفیت کل</div></div><div class="section"><h3>اتاق‌های شما</h3><div class="grid">{cards or '<div class="card empty">هنوز اتاقی ساخته نشده است.</div>'}</div></div>'''
    return page("ماس | خانه", body, request)


@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    u = current_user(request); first = request.query_params.get("first") == "1"
    body = f'''<div class="head"><h2>{'تکمیل پروفایل' if first else 'پروفایل کاربری'}</h2></div><div class="form"><form method="post" action="/profile"><input type="hidden" name="csrf" value="{html_escape(session_csrf(request))}"><div class="two"><label>نام حساب<input name="account_name" maxlength="120" required value="{html_escape(u.account_name)}"></label><label>سن<input name="age" type="number" min="1" max="120" required value="{u.age or ''}"></label></div><label>شغل<input name="job" maxlength="120" required value="{html_escape(u.job)}"></label><label>نام کاربری<input disabled value="{html_escape(u.username)}"></label><button class="primary">ذخیره اطلاعات</button></form></div>'''
    return page("ماس | پروفایل", body, request, "profile")


@app.post("/profile")
def profile_save(request: Request, csrf: str = Form(...), account_name: str = Form(...), age: int = Form(...), job: str = Form(...)):
    require_csrf(request, csrf)
    if not 1 <= age <= 120 or not account_name.strip() or not job.strip():
        raise HTTPException(400, "اطلاعات پروفایل نامعتبر است.")
    u = current_user(request)
    with Session(engine) as db:
        d = db.get(User, u.id); d.account_name = account_name.strip(); d.age = age; d.job = job.strip(); d.profile_completed = True; db.commit()
    return RedirectResponse("/", 303)


@app.get("/rooms", response_class=HTMLResponse)
def rooms(request: Request):
    u = current_user(request)
    with Session(engine) as db:
        rs = db.scalars(select(Room).where(Room.owner_id == u.id).order_by(Room.id.desc())).all()
    cards = "".join(f'''<div class="card room" onclick="location.href='/rooms/{r.id}'"><button class="dots" onclick="event.stopPropagation();this.nextElementSibling.style.display=this.nextElementSibling.style.display==='block'?'none':'block'">⋮</button><div class="pop"><button onclick="location.href='/rooms/{r.id}/edit'">ویرایش</button><form method="post" action="/rooms/{r.id}/delete" onclick="event.stopPropagation()"><input type="hidden" name="csrf" value="{html_escape(session_csrf(request))}"><button class="danger-text" type="submit" onclick="return confirm('حذف شود؟')">حذف</button></form></div><h3>{html_escape(r.name)}</h3><p class="muted">ظرفیت: {r.capacity} سخنران</p></div>''' for r in rs)
    return page("ماس | اتاق‌ها", f'''<div class="head"><h2>اتاق‌های سخنرانی</h2><a class="primary" href="/rooms/new">＋ ایجاد اتاق</a></div><div class="grid">{cards or '<div class="card empty">اتاقی وجود ندارد.</div>'}</div>''', request, "rooms")


@app.get("/rooms/new", response_class=HTMLResponse)
def new_room(request: Request):
    current_user(request)
    body = f'''<div class="head"><h2>ایجاد اتاق سخنرانی</h2></div><div class="form"><form method="post" action="/rooms/new"><input type="hidden" name="csrf" value="{html_escape(session_csrf(request))}"><label>نام اتاق سخنرانی<input name="name" maxlength="160" required></label><label>تعداد سخنرانان<input name="capacity" type="number" min="1" max="100" value="5" required></label><button class="primary">ایجاد</button></form></div>'''
    return page("ایجاد اتاق", body, request, "rooms")


@app.post("/rooms/new")
def new_room_save(request: Request, csrf: str = Form(...), name: str = Form(...), capacity: int = Form(...)):
    require_csrf(request, csrf); validate_capacity(capacity)
    if not name.strip(): raise HTTPException(400, "نام اتاق الزامی است.")
    u = current_user(request)
    with Session(engine) as db:
        r = Room(owner_id=u.id, name=name.strip(), capacity=capacity, created_at=int(time.time()))
        db.add(r); db.flush()
        for i in range(capacity): db.add(Speaker(room_id=r.id, name="", order_index=i))
        db.add(RoomState(room_id=r.id, updated_at=int(time.time())))
        db.commit(); rid = r.id
    return RedirectResponse(f"/rooms/{rid}", 303)


@app.get("/rooms/{room_id}/edit", response_class=HTMLResponse)
def edit_room(request: Request, room_id: int):
    r = owned_room(request, room_id)
    return page("ویرایش اتاق", f'''<div class="head"><h2>ویرایش اتاق</h2></div><div class="form"><form method="post"><input type="hidden" name="csrf" value="{html_escape(session_csrf(request))}"><label>نام اتاق<input name="name" maxlength="160" value="{html_escape(r.name)}" required></label><label>ظرفیت<input name="capacity" type="number" min="1" max="100" value="{r.capacity}" required></label><p class="muted">کاهش ظرفیت، سخنرانان اضافی و فایل‌های وابسته به آن‌ها را حذف می‌کند.</p><button class="primary">ذخیره</button></form></div>''', request, "rooms")


@app.post("/rooms/{room_id}/edit")
def edit_room_save(request: Request, room_id: int, csrf: str = Form(...), name: str = Form(...), capacity: int = Form(...)):
    require_csrf(request, csrf); validate_capacity(capacity)
    r = owned_room(request, room_id)
    with Session(engine) as db:
        room = db.get(Room, r.id); old = room.capacity; room.name = name.strip(); room.capacity = capacity
        if capacity > old:
            for i in range(old, capacity): db.add(Speaker(room_id=room.id, name="", order_index=i))
        elif capacity < old:
            extra = db.scalars(select(Speaker).where(Speaker.room_id == room.id, Speaker.order_index >= capacity)).all()
            for s in extra: db.delete(s)
        db.commit()
    return RedirectResponse(f"/rooms/{room_id}", 303)


@app.post("/rooms/{room_id}/delete")
def delete_room(request: Request, room_id: int, csrf: str = Form(...)):
    require_csrf(request, csrf); r = owned_room(request, room_id)
    files = []
    with Session(engine) as db:
        room = db.get(Room, r.id)
        files = [f.storage_name for f in room.files]
        db.delete(room); db.commit()
    for storage in files: (UPLOADS / storage).unlink(missing_ok=True)
    return RedirectResponse("/rooms", 303)


@app.get("/rooms/{room_id}", response_class=HTMLResponse)
def room_page(request: Request, room_id: int):
    r = owned_room(request, room_id)
    with Session(engine) as db:
        room = db.get(Room, r.id)
        speakers = db.scalars(select(Speaker).options(selectinload(Speaker.files)).where(Speaker.room_id == room.id).order_by(Speaker.order_index, Speaker.id)).all()
        common = db.scalars(select(SpeechFile).where(SpeechFile.room_id == room.id, SpeechFile.upload_type == "common")).all()
    csrf = html_escape(session_csrf(request))
    speaker_html = ""
    for i, s in enumerate(speakers):
        fs = [f for f in s.files]
        filehtml = "".join(f'''<div>📄 <a href="/files/{f.id}">{html_escape(f.filename)}</a> <button type="button" class="secondary" onclick="deleteFile({f.id})">حذف</button></div>''' for f in fs) or '<span class="muted">فایلی ثبت نشده</span>'
        speaker_html += f'''<div class="speaker" draggable="true" data-id="{s.id}"><div class="head" style="margin-bottom:8px"><h3>سخنران {i+1}</h3><span class="grip">☷</span></div><input type="hidden" name="sid" value="{s.id}"><div class="two"><label>نام<input maxlength="120" name="name_{s.id}" value="{html_escape(s.name)}"></label><label>جنسیت<select name="gender_{s.id}"><option value="" {'selected' if not s.gender else ''}>انتخاب</option><option value="مرد" {'selected' if s.gender=='مرد' else ''}>مرد</option><option value="زن" {'selected' if s.gender=='زن' else ''}>زن</option></select></label></div><div class="two"><label>سن<input name="age_{s.id}" type="number" min="1" max="120" value="{s.age or ''}"></label><label>زمان اختصاصی (دقیقه)<input name="time_{s.id}" type="number" min="1" max="1440" value="{max(1, int((s.speaking_seconds or 300)/60))}"></label></div><label>توضیحات<textarea name="desc_{s.id}" rows="2" maxlength="1000">{html_escape(s.description)}</textarea></label><div class="file"><b>آپلود برای این سخنران</b><input type="file" name="file_{s.id}" multiple accept=".pdf,.ppt,.pptx,.doc,.docx,.txt,.mp3,.wav,.m4a,.ogg,.mp4,.webm,.png,.jpg,.jpeg"><div>{filehtml}</div></div></div>'''
    commonhtml = "".join(f'''<div>📎 <a href="/files/{f.id}">{html_escape(f.filename)}</a> <button type="button" class="secondary" onclick="deleteFile({f.id})">حذف</button></div>''' for f in common) or '<span class="muted">فایل همگانی ثبت نشده</span>'
    body = f'''<div class="head"><div><h2>تنظیمات اتاق: {html_escape(room.name)}</h2><p class="muted">ظرفیت {room.capacity} سخنران</p></div><a class="primary" href="/rooms/{room.id}/play">▶ پخش اتاق</a></div><form class="form" action="/rooms/{room.id}/save" method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{csrf}"><div class="section"><h3>تنظیمات عمومی</h3><label>نام اتاق<input name="room_name" maxlength="160" value="{html_escape(room.name)}" required></label><div class="switches"><label><input type="checkbox" name="recording" {'checked' if room.recording_enabled else ''}> ضبط اتاق</label><label><input type="checkbox" name="live_files" {'checked' if room.live_files_enabled else ''}> نمایش زنده فایل سخنران</label></div></div><div class="section"><h3>زمان سخنرانی</h3><div class="switches"><label><input type="radio" name="timing_mode" value="global" {'checked' if room.timing_mode=='global' else ''}> همگانی</label><label><input type="radio" name="timing_mode" value="individual" {'checked' if room.timing_mode=='individual' else ''}> برای هر سخنران</label></div><label>زمان همگانی (دقیقه)<input name="global_min" type="number" min="1" max="1440" value="{max(1,int(room.global_seconds/60))}"></label></div><div class="section"><h3>فایل همگانی</h3><div class="file"><input type="file" name="common_files" multiple accept=".pdf,.ppt,.pptx,.doc,.docx,.txt,.mp3,.wav,.m4a,.ogg,.mp4,.webm,.png,.jpg,.jpeg"><div>{commonhtml}</div></div></div><div class="section"><h3>سخنرانان</h3><p class="muted">برای «ترتیب دستی» کارت‌ها را با ماوس جابه‌جا کنید.</p>{speaker_html}</div><div class="section"><h3>ترتیب سخنرانی</h3><div class="switches"><label><input type="radio" name="order_mode" value="age" {'checked' if room.order_mode=='age' else ''}> بر اساس سن</label><label><input type="radio" name="order_mode" value="alpha" {'checked' if room.order_mode=='alpha' else ''}> بر اساس حروف الفبا</label><label><input type="radio" name="order_mode" value="random" {'checked' if room.order_mode=='random' else ''}> تصادفی</label><label><input type="radio" name="order_mode" value="manual" {'checked' if room.order_mode=='manual' else ''}> دستی</label></div><input type="hidden" name="manual_order" id="manual_order"></div><button class="primary">ذخیره همه تنظیمات</button></form><button class="float" onclick="location.href='/rooms/{room.id}/play'">▶</button><script>document.querySelectorAll('.speaker').forEach(el=>{{el.addEventListener('dragstart',e=>e.dataTransfer.setData('text/plain',el.dataset.id));el.addEventListener('dragover',e=>e.preventDefault());el.addEventListener('drop',e=>{{e.preventDefault();let id=e.dataTransfer.getData('text/plain'),src=document.querySelector('[data-id="'+id+'"]');if(src!==el)el.parentNode.insertBefore(src,el);writeOrder()}})}});function writeOrder(){{document.getElementById('manual_order').value=[...document.querySelectorAll('.speaker')].map(x=>x.dataset.id).join(',')}}writeOrder();async function deleteFile(id){{if(!confirm('فایل حذف شود؟'))return;let fd=new FormData();fd.append('csrf','{csrf}');let r=await fetch('/files/'+id+'/delete',{{method:'POST',body:fd}});if(r.ok)location.reload();else toast('حذف فایل ناموفق بود');}}</script>'''
    return page("ماس | اتاق", body, request, "room")


@app.post("/rooms/{room_id}/save")
async def save_room(request: Request, room_id: int):
    form = await request.form(); require_csrf(request, str(form.get("csrf", "")))
    r = owned_room(request, room_id)
    try:
        mode = str(form.get("timing_mode", "global")); g = max(60, min(86400, int(form.get("global_min", 5)) * 60))
    except Exception: raise HTTPException(400, "زمان نامعتبر است.")
    with Session(engine) as db:
        room = db.get(Room, r.id); room.name = str(form.get("room_name", room.name)).strip() or room.name; room.recording_enabled = bool(form.get("recording")); room.live_files_enabled = bool(form.get("live_files")); room.timing_mode = mode if mode in {"global","individual"} else "global"; room.global_seconds = g; room.order_mode = str(form.get("order_mode", "manual"))
        speaker_ids = [int(x) for x in form.getlist("sid")]
        for sid in speaker_ids:
            s = db.get(Speaker, sid)
            if not s or s.room_id != room.id: continue
            s.name = str(form.get(f"name_{sid}", "")).strip()
            gender = str(form.get(f"gender_{sid}", "")); s.gender = gender if gender in {"", "مرد", "زن"} else ""
            age_raw = form.get(f"age_{sid}") or None
            s.age = int(age_raw) if age_raw and str(age_raw).isdigit() and 1 <= int(age_raw) <= 120 else None
            s.description = str(form.get(f"desc_{sid}", ""))[:1000]
            raw_min = str(form.get(f"time_{sid}", "5"))
            sec = max(60, min(86400, int(raw_min) * 60)) if raw_min.isdigit() else 300
            s.speaking_seconds = g if room.timing_mode == "global" else sec
            for up in form.getlist(f"file_{sid}"):
                if isinstance(up, UploadFile) and up.filename:
                    try: filename, storage, size, ctype = await store_upload(up)
                    except ValueError as e: raise HTTPException(400, str(e))
                    db.add(SpeechFile(room_id=room.id, speaker_id=s.id, filename=filename, storage_name=storage, content_type=ctype, size_bytes=size, upload_type="speaker", created_at=int(time.time())))
        for up in form.getlist("common_files"):
            if isinstance(up, UploadFile) and up.filename:
                try: filename, storage, size, ctype = await store_upload(up)
                except ValueError as e: raise HTTPException(400, str(e))
                candidates = sorted(UPLOADS.glob(f"*{Path(filename).suffix}"), key=lambda p:p.stat().st_mtime, reverse=True)
                storage = candidates[0].name
                db.add(SpeechFile(room_id=room.id, speaker_id=None, filename=filename, storage_name=storage, content_type=ctype, size_bytes=size, upload_type="common", created_at=int(time.time())))
        order_mode = room.order_mode
        speakers = db.scalars(select(Speaker).options(selectinload(Speaker.files)).where(Speaker.room_id == room.id).order_by(Speaker.order_index, Speaker.id)).all()
        if order_mode == "age": speakers = sorted(speakers, key=lambda x: (x.age is None, x.age or 0, x.id))
        elif order_mode == "alpha": speakers = sorted(speakers, key=lambda x: (x.name or "").casefold())
        elif order_mode == "random": secrets.SystemRandom().shuffle(speakers)
        elif order_mode == "manual":
            requested = [int(x) for x in str(form.get("manual_order", "")).split(",") if x.strip().isdigit()]
            mapping = {s.id:s for s in speakers}; speakers = [mapping[i] for i in requested if i in mapping] + [s for s in speakers if s.id not in requested]
        for i, s in enumerate(speakers): s.order_index = i
        db.commit()
    return RedirectResponse(f"/rooms/{room_id}", 303)


# ------------------------------ Real playback state ------------------------------
def state_snapshot(db: Session, room: Room) -> dict:
    state = room.state
    speakers = db.scalars(select(Speaker).options(selectinload(Speaker.files)).where(Speaker.room_id == room.id, Speaker.name != "").order_by(Speaker.order_index, Speaker.id)).all()
    if state is None:
        state = RoomState(room_id=room.id, updated_at=int(time.time())); db.add(state); db.commit(); db.refresh(state)
    current_elapsed = state.elapsed_seconds
    overtime = state.overtime_seconds
    if state.running and state.started_at:
        delta = max(0, int(time.time()) - state.started_at)
        current_total = state.elapsed_seconds + delta
        current_elapsed = min(current_total, speakers[state.current_index].speaking_seconds) if speakers and state.current_index < len(speakers) else current_total
        overtime = max(0, current_total - (speakers[state.current_index].speaking_seconds if speakers and state.current_index < len(speakers) else 0))
    return {"running": state.running, "current_index": state.current_index, "elapsed_seconds": current_elapsed, "overtime_seconds": overtime, "total_speakers": len(speakers), "server_time": int(time.time())}


def persist_elapsed(state: RoomState, speaker_seconds: int):
    if state.running and state.started_at:
        delta = max(0, int(time.time()) - state.started_at)
        state.elapsed_seconds += delta
        state.started_at = int(time.time())
        state.overtime_seconds = max(0, state.elapsed_seconds - speaker_seconds)


@app.get("/rooms/{room_id}/play", response_class=HTMLResponse)
def play(request: Request, room_id: int):
    r = owned_room(request, room_id)
    with Session(engine) as db:
        room = db.get(Room, r.id)
        speakers = db.scalars(select(Speaker).options(selectinload(Speaker.files)).where(Speaker.room_id == room.id, Speaker.name != "").order_by(Speaker.order_index, Speaker.id)).all()
        common = db.scalars(select(SpeechFile).where(SpeechFile.room_id == room.id, SpeechFile.upload_type == "common")).all()
        data=[]
        for s in speakers:
            data.append({"id":s.id,"name":s.name,"seconds":s.speaking_seconds,"gender":s.gender,"age":s.age,"description":s.description,"files":[{"id":f.id,"name":f.filename} for f in s.files]})
        common_data=[{"id":f.id,"name":f.filename} for f in common]
    payload=json.dumps({"room":room.name,"speakers":data,"common":common_data,"live_files":room.live_files_enabled,"recording":room.recording_enabled}, ensure_ascii=False)
    csrf=html_escape(session_csrf(request))
    body=f'''<div id="play"></div><script>const DATA={payload};const CSRF='{csrf}';let idx=0,interval=null;function fmt(s){{s=Math.max(0,Math.floor(s));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}}async function api(path,method='POST',extra={{}}){{let fd=new FormData();fd.append('csrf',CSRF);for(const [k,v] of Object.entries(extra))fd.append(k,v);let r=await fetch(path,{{method,body:fd}});if(!r.ok)throw new Error('request');return r.json()}}async function sync(){{try{{let s=await fetch('/api/rooms/{room_id}/state').then(x=>x.json());idx=s.current_index;render(s)}}catch(e){{}}}}function render(st){{let s=DATA.speakers[idx];if(!s){{document.getElementById('play').innerHTML='<div class="card empty">سخنرانی برای پخش وجود ندارد.</div>';return}}let own=s.files.map(f=>'<div>📄 <a href="/files/'+f.id+'">'+esc(f.name)+'</a></div>').join('')||'<span class="muted">فایلی نیست</span>';let common=DATA.common.map(f=>'<div>📎 <a href="/files/'+f.id+'">'+esc(f.name)+'</a></div>').join('')||'<span class="muted">فایل همگانی نیست</span>';let remaining=Math.max(0,s.seconds-st.elapsed_seconds),over=st.overtime_seconds;document.getElementById('play').innerHTML=`<div class="head"><div><h2>پخش اتاق: ${{esc(DATA.room)}}</h2><p class="muted">سخنران ${{idx+1}} از ${{DATA.speakers.length}}</p></div><a class="secondary" href="/rooms/{room_id}">بازگشت</a></div><div class="card"><h2 style="text-align:center">${{esc(s.name)}}</h2><p style="text-align:center" class="muted">${{esc(s.gender)}} ${{s.age?'· سن '+s.age:''}}</p><div class="timer" id="timer">${{fmt(remaining)}}</div><div class="overtime" id="over">${{over?'زمان اضافه: +'+fmt(over):''}}</div><div class="bar"><i style="width:${{Math.max(0,Math.min(100,remaining/(s.seconds||1)*100))}}%"></i></div><div class="row" style="justify-content:center;margin:20px"><button class="primary" onclick="start()">▶ شروع</button><button class="secondary" onclick="pause()">⏸ توقف</button><button class="secondary" onclick="resetTimer()">↻ بازیابی</button></div><div class="section"><h3>فایل‌های سخنران</h3><div class="file">${{own}}</div></div><div class="section"><h3>فایل‌های همگانی</h3><div class="file">${{common}}</div></div><div class="row" style="justify-content:space-between"><button class="secondary" onclick="prev()">← سخنران قبلی</button><button class="primary" onclick="next()">سخنران بعدی →</button></div>${{DATA.recording?'<div class="section"><h3>ضبط اتاق</h3><button class="primary" id="recBtn" onclick="toggleRec()">● شروع ضبط</button><span id="recStatus" class="muted" style="margin-right:10px"></span></div>':''}}</div>`}}async function start(){{await api('/api/rooms/{room_id}/start');await sync()}}async function pause(){{await api('/api/rooms/{room_id}/pause');await sync()}}async function resetTimer(){{await api('/api/rooms/{room_id}/reset');await sync()}}async function next(){{await api('/api/rooms/{room_id}/next');await sync()}}async function prev(){{await api('/api/rooms/{room_id}/prev');await sync()}}async function tick(){{if(!DATA.speakers.length)return;let r=await fetch('/api/rooms/{room_id}/state');if(r.ok)render(await r.json())}}setInterval(tick,1000);sync();let rec=null,chunks=[];async function toggleRec(){{let b=document.getElementById('recBtn');if(!b)return;if(rec&&rec.state==='recording'){{rec.stop();b.textContent='● شروع ضبط';return}}try{{let stream=await navigator.mediaDevices.getUserMedia({{audio:true}});rec=new MediaRecorder(stream);chunks=[];rec.ondataavailable=e=>e.data.size&&chunks.push(e.data);rec.onstop=async()=>{{stream.getTracks().forEach(t=>t.stop());let blob=new Blob(chunks,{{type:'audio/webm'}});let fd=new FormData();fd.append('csrf',CSRF);fd.append('file',blob,'recording-'+Date.now()+'.webm');let r=await fetch('/api/rooms/{room_id}/recording',{{method:'POST',body:fd}});document.getElementById('recStatus').textContent=r.ok?'ضبط ذخیره شد':'ذخیره ضبط ناموفق بود'}};rec.start();b.textContent='■ توقف ضبط'}}catch(e){{document.getElementById('recStatus').textContent='دسترسی میکروفون ممکن نیست'}}}}</script>'''
    return page("ماس | پخش اتاق", body, request, "play")


# ------------------------------ Playback API ------------------------------
def room_and_speakers(request: Request, room_id: int):
    r = owned_room(request, room_id)
    with Session(engine) as db:
        room=db.get(Room,r.id); speakers=db.scalars(select(Speaker).where(Speaker.room_id==r.id, Speaker.name!="").order_by(Speaker.order_index,Speaker.id)).all(); state=room.state
        if state is None: state=RoomState(room_id=r.id,updated_at=int(time.time()));db.add(state);db.commit();db.refresh(state)
        db.expunge_all(); return room,speakers,state


@app.get("/api/rooms/{room_id}/state")
def api_state(request: Request, room_id: int):
    r=owned_room(request,room_id)
    with Session(engine) as db:
        room=db.get(Room,r.id); speakers=db.scalars(select(Speaker).where(Speaker.room_id==r.id, Speaker.name!="").order_by(Speaker.order_index,Speaker.id)).all(); state=room.state
        if not state: state=RoomState(room_id=r.id,updated_at=int(time.time()),current_index=0);db.add(state);db.commit();db.refresh(state)
        snap=state_snapshot(db,room); snap["current_speaker_id"]=speakers[state.current_index].id if speakers and state.current_index < len(speakers) else None
        snap["total_speakers"]=len(speakers); return JSONResponse(snap)


def _apply_control(request: Request, room_id: int, csrf: str, action: str):
    require_csrf(request,csrf); r=owned_room(request,room_id)
    with Session(engine) as db:
        room=db.get(Room,r.id); speakers=db.scalars(select(Speaker).where(Speaker.room_id==r.id, Speaker.name!="").order_by(Speaker.order_index,Speaker.id)).all(); state=room.state
        if not state: state=RoomState(room_id=r.id,updated_at=int(time.time()),current_index=0);db.add(state);db.flush()
        current_sec=speakers[state.current_index].speaking_seconds if speakers and state.current_index < len(speakers) else room.global_seconds
        if action in {"pause","next","prev","reset"}: persist_elapsed(state,current_sec)
        if action=="start" and speakers:
            state.running=True;state.started_at=int(time.time())
        elif action=="pause": state.running=False;state.started_at=None
        elif action=="reset" and speakers: state.elapsed_seconds=0;state.overtime_seconds=0;state.running=False;state.started_at=None
        elif action=="next" and state.current_index < max(0,len(speakers)-1): state.current_index += 1;state.elapsed_seconds=0;state.overtime_seconds=0;state.running=False;state.started_at=None
        elif action=="prev" and state.current_index > 0: state.current_index -= 1;state.elapsed_seconds=0;state.overtime_seconds=0;state.running=False;state.started_at=None
        state.updated_at=int(time.time());db.commit();return state_snapshot(db,room)


@app.post("/api/rooms/{room_id}/{action}")
def playback_control(request: Request, room_id: int, action: str, csrf: str = Form(...)):
    if action not in {"start","pause","reset","next","prev"}: raise HTTPException(404)
    return _apply_control(request,room_id,csrf,action)


@app.post("/api/rooms/{room_id}/recording")
async def save_recording(request: Request, room_id: int, csrf: str = Form(...), file: UploadFile = File(...)):
    require_csrf(request,csrf); r=owned_room(request,room_id)
    with Session(engine) as db:
        room=db.get(Room,r.id)
        if not room.recording_enabled: raise HTTPException(403,"ضبط برای این اتاق فعال نیست.")
        try: filename,size,ctype=await store_upload(file)
        except ValueError as e: raise HTTPException(400,str(e))
        db.add(SpeechFile(room_id=room.id,filename=filename,storage_name=storage,content_type=ctype,size_bytes=size,upload_type="recording",created_at=int(time.time())));db.commit()
    return {"ok":True}


@app.post("/files/{file_id}/delete")
def delete_file(request: Request,file_id:int,csrf:str=Form(...)):
    require_csrf(request,csrf); u=current_user(request)
    with Session(engine) as db:
        f=db.scalar(select(SpeechFile).join(Room).where(SpeechFile.id==file_id,Room.owner_id==u.id))
        if not f: raise HTTPException(404,"فایل پیدا نشد")
        storage=f.storage_name;db.delete(f);db.commit()
    (UPLOADS/storage).unlink(missing_ok=True);return {"ok":True}


@app.get("/files/{file_id}")
def get_file(request:Request,file_id:int):
    u=current_user(request)
    with Session(engine) as db:
        f=db.scalar(select(SpeechFile).join(Room).where(SpeechFile.id==file_id,Room.owner_id==u.id))
        if not f: raise HTTPException(404,"فایل پیدا نشد")
        path=UPLOADS/f.storage_name
        if not path.exists(): raise HTTPException(404,"فایل روی سرور وجود ندارد")
        return FileResponse(path,filename=f.filename,media_type=f.content_type)



@app.get("/health")
def health():
    with Session(engine) as db:
        db.execute(select(User).limit(1))
    return {"status":"ok"}
