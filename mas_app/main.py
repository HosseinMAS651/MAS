from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
from qrcode.image.svg import SvgImage
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import AUTH_FORM_COOKIE, DUMMY_PASSWORD_HASH, client_key, cleanup_expired_sessions, clear_rate_limit, create_session, get_auth_context, hash_password, invalidate_session, issue_auth_form_token, normalize_username, password_needs_rehash, rate_limit_allow, require_auth_form, require_csrf, token_digest, verify_password, _bucket_hash
from .config import Settings, load_settings
from .db import configure_sqlite, initialize_database, make_engine, session_factory
from .models import FileCleanupQueue, Room, RoomState, Speaker, SpeechFile, User
from .services import GENDERS, ORDER_MODES, TIMING_MODES, apply_timer_action, collect_room_storage, enqueue_cleanup, limit_for, now, ordered_speakers, process_cleanup_queue, release_room_storage, reserve_room_storage, room_speakers, state_snapshot, timer_for, validate_capacity, validate_room_name, validate_speaker_name, ensure_room_state
from .storage import content_disposition, safe_storage_path, store_upload

BASE_DIR=Path(__file__).resolve().parent.parent
logging.basicConfig(level=logging.INFO)
TEMPLATES_DIR=BASE_DIR/"mas_app"/"templates"; STATIC_DIR=BASE_DIR/"mas_app"/"static"
ASSET_VERSION="4.0.0"
logger=logging.getLogger("mas")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self,app,settings):super().__init__(app);self.settings=settings
    async def dispatch(self,request,call_next):
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff";response.headers["X-Frame-Options"]="SAMEORIGIN";response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]="microphone=(self)"
        if not request.url.path.startswith("/static/"):response.headers["Cache-Control"]="no-store"
        if request.url.path.startswith("/p/") or request.url.path.startswith("/public-api/") or request.url.path.startswith("/public-files/"):
            response.headers["X-Robots-Tag"]="noindex, nofollow, noarchive"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        if self.settings.env=="production":response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
        return response

def create_app(settings:Settings|None=None)->FastAPI:
    cfg=settings or load_settings();engine=make_engine(cfg);configure_sqlite(engine);SessionLocal=session_factory(engine);templates=Jinja2Templates(directory=str(TEMPLATES_DIR))
    async def cleanup_worker():
        while True:
            await asyncio.sleep(300)
            try:
                cleanup_expired_sessions(SessionLocal)
                best_effort_cleanup(200)
                for path in cfg.storage_dir.glob(".upload-*.tmp"):
                    try:path.unlink(missing_ok=True)
                    except OSError:pass
            except Exception: logger.exception("cleanup worker failed")
    @asynccontextmanager
    async def lifespan(app):
        initialize_database(engine);cleanup_expired_sessions(SessionLocal)
        task=asyncio.create_task(cleanup_worker())
        try:yield
        finally:task.cancel();
        try: await task
        except asyncio.CancelledError: pass
        engine.dispose()
    app=FastAPI(title="ماس | مدیریت اتاق سخنرانی",lifespan=lifespan)
    app.state.settings=cfg;app.state.engine=engine;app.state.SessionLocal=SessionLocal;app.state.templates=templates
    app.add_middleware(SecurityHeadersMiddleware,settings=cfg);app.mount("/static",StaticFiles(directory=str(STATIC_DIR)),name="static")
    def render(request,name,context,status_code=200):return templates.TemplateResponse(request=request,name=name,context={**context,"asset_version":ASSET_VERSION},status_code=status_code)
    def require_page_user(request,require_profile=True):
        ctx=get_auth_context(request,SessionLocal,cfg,api=False)
        if require_profile and not ctx.user.profile_completed and request.url.path!="/profile":raise HTTPException(303,headers={"Location":"/profile?first=1"})
        return ctx.user
    def page_context(request,user,active="",flash=""):
        ctx=get_auth_context(request,SessionLocal,cfg,api=False);return {"request":request,"user":ctx.user,"csrf":ctx.csrf_token,"active":active,"flash":flash}
    def owned_room(request,room_id,api=False):
        ctx=get_auth_context(request,SessionLocal,cfg,api=api)
        if not ctx.user.profile_completed and not api:raise HTTPException(303,headers={"Location":"/profile?first=1"})
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.id==room_id,Room.owner_id==ctx.user.id))
            if not room:raise HTTPException(404,"اتاق پیدا نشد.")
            db.expunge(room);return ctx.user,room
    def cookie(response,raw):
        response.set_cookie("mas_session",raw,max_age=cfg.session_seconds,httponly=True,secure=cfg.cookie_secure,samesite="lax",path="/")
    def validate_username(v):
        v=normalize_username(v)
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}",v):raise HTTPException(400,"نام کاربری باید فقط شامل حروف انگلیسی، عدد و _ و بین ۳ تا ۳۲ کاراکتر باشد.")
        return v
    def validate_password(v):
        if not cfg.min_password_length<=len(v)<=cfg.max_password_length:raise HTTPException(400,f"رمز عبور باید بین {cfg.min_password_length} تا {cfg.max_password_length} کاراکتر باشد.")
        return v
    def public_base_url(request: Request) -> str:
        configured = getattr(cfg, "public_base_url", "")
        if configured:
            return str(configured).rstrip("/")
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        scheme = forwarded_proto or request.url.scheme
        host = request.headers.get("x-forwarded-host", "").split(",")[0].strip() or request.headers.get("host", "") or request.url.netloc
        return f"{scheme}://{host}".rstrip("/")

    def preflight(request,limit):
        raw=request.headers.get("content-length")
        if raw:
            try:n=int(raw)
            except ValueError:raise HTTPException(400,"اندازه درخواست نامعتبر است.")
            if n>limit+5*1024*1024:raise HTTPException(413,"حجم درخواست بیش از حد مجاز است.")
    def best_effort_cleanup(limit=100):
        try:
            with SessionLocal() as db:
                process_cleanup_queue(db,cfg,limit)
        except Exception:
            logger.exception("background cleanup could not be completed")
    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        if exc.status_code==303:return RedirectResponse(exc.headers.get("Location","/login"),303)
        if request.url.path.startswith("/api/") or request.url.path.startswith("/public-api/") or request.headers.get("Accept","").find("application/json")>=0:return JSONResponse(content={"detail":exc.detail},status_code=exc.status_code)
        if exc.status_code==401:return RedirectResponse("/login",303)
        title={404:"پیدا نشد",403:"دسترسی غیرمجاز",429:"تعداد درخواست زیاد است"}.get(exc.status_code,"خطا")
        return render(request,"error.html",{"request":request,"title":title,"status_code":exc.status_code,"message":str(exc.detail)},exc.status_code)
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        if request.url.path.startswith("/api/"):return JSONResponse(content={"detail":"ورودی نامعتبر است.","errors":exc.errors()},status_code=422)
        return render(request,"error.html",{"request":request,"title":"ورودی نامعتبر","status_code":422,"message":"یکی از اطلاعات ارسالی معتبر نیست."},422)
    @app.exception_handler(Exception)
    async def internal_error(request,exc):
        logger.exception("Unhandled error %s %s",request.method,request.url.path)
        if request.url.path.startswith("/api/") or request.url.path.startswith("/public-api/"):return JSONResponse(content={"detail":"خطای داخلی سرور."},status_code=500)
        return render(request,"error.html",{"request":request,"title":"خطای داخلی","status_code":500,"message":"خطای داخلی رخ داد. دوباره تلاش کنید."},500)

    @app.get("/login",response_class=HTMLResponse)
    def login_page(request:Request):
        if request.cookies.get("mas_session"):
            try:
                ctx=get_auth_context(request,SessionLocal,cfg,api=False);return RedirectResponse("/" if ctx.user.profile_completed else "/profile?first=1",303)
            except HTTPException:pass
        temp=Response(); token=issue_auth_form_token(temp,cfg)
        rendered=render(request,"login.html",{"title":"ورود به حساب کاربری","subtitle":"ورود به مدیریت اتاق سخنرانی","error":"","auth_form_token":token})
        rendered.set_cookie(AUTH_FORM_COOKIE,token,max_age=3600,httponly=False,secure=cfg.cookie_secure,samesite="lax",path="/");return rendered
    @app.post("/login")
    def login(request:Request,username:str=Form(...),password:str=Form(...),auth_token:str=Form(...)):
        require_auth_form(request,auth_token);username=normalize_username(username)
        try:username=validate_username(username);password=validate_password(password)
        except HTTPException as exc:return render(request,"login.html",{"title":"ورود به حساب کاربری","subtitle":"ورود به مدیریت اتاق سخنرانی","error":str(exc.detail),"auth_form_token":auth_token},exc.status_code)
        ipk=_bucket_hash("login-ip",client_key(request));ck=_bucket_hash("login-combo",client_key(request),username)
        if not rate_limit_allow(SessionLocal,key=ipk,max_count=cfg.login_max_failures*4,window_seconds=cfg.login_window_seconds) or not rate_limit_allow(SessionLocal,key=ck,max_count=cfg.login_max_failures,window_seconds=cfg.login_window_seconds):
            return render(request,"login.html",{"title":"ورود به حساب کاربری","subtitle":"ورود به مدیریت اتاق سخنرانی","error":"تعداد تلاش‌های ورود زیاد است. بعداً دوباره تلاش کنید.","auth_form_token":auth_token},429)
        with SessionLocal() as db:
            user=db.scalar(select(User).where(User.username==username));ph=user.password_hash if user else DUMMY_PASSWORD_HASH
            valid,rounds=verify_password(password,ph)
            if not valid or not user:return render(request,"login.html",{"title":"ورود به حساب کاربری","subtitle":"ورود به مدیریت اتاق سخنرانی","error":"نام کاربری یا رمز عبور اشتباه است.","auth_form_token":auth_token},401)
            if password_needs_rehash(rounds):user.password_hash=hash_password(password);db.commit()
            uid=user.id;profile=user.profile_completed
        clear_rate_limit(SessionLocal,ck);raw,_,_=create_session(uid,SessionLocal,cfg);response=RedirectResponse("/" if profile else "/profile?first=1",303);cookie(response,raw);return response
    @app.get("/register",response_class=HTMLResponse)
    def register_page(request:Request):
        token=__import__('secrets').token_urlsafe(32);response=render(request,"register.html",{"title":"ایجاد حساب کاربری","subtitle":"مرحله اول: ساخت نام کاربری و رمز عبور","error":"","auth_form_token":token});response.set_cookie(AUTH_FORM_COOKIE,token,max_age=3600,httponly=False,secure=cfg.cookie_secure,samesite="lax",path="/");return response
    @app.post("/register")
    def register(request:Request,username:str=Form(...),password:str=Form(...),password2:str=Form(...),auth_token:str=Form(...)):
        require_auth_form(request,auth_token);username=validate_username(username);password=validate_password(password);validate_password(password2)
        if password!=password2:raise HTTPException(400,"رمزها یکسان نیستند.")
        key=_bucket_hash("register",client_key(request))
        if not rate_limit_allow(SessionLocal,key=key,max_count=cfg.register_max_attempts,window_seconds=cfg.register_window_seconds):raise HTTPException(429,"تعداد تلاش‌های ثبت‌نام زیاد است. بعداً دوباره تلاش کنید.")
        try:
            with SessionLocal() as db:
                user=User(username=username,password_hash=hash_password(password),created_at=now(),profile_completed=False);db.add(user);db.commit();db.refresh(user);uid=user.id
        except IntegrityError:raise HTTPException(409,"این نام کاربری قبلاً ثبت شده است.")
        raw,_,_=create_session(uid,SessionLocal,cfg);response=RedirectResponse("/profile?first=1",303);cookie(response,raw);return response
    @app.post("/logout")
    def logout(request:Request,csrf:str=Form(...)):require_csrf(request,csrf,SessionLocal,cfg);invalidate_session(request,SessionLocal,cfg);response=RedirectResponse("/login",303);response.delete_cookie("mas_session",path="/");return response
    @app.get("/",response_class=HTMLResponse)
    def home(request:Request):
        user=require_page_user(request)
        with SessionLocal() as db:
            rooms=db.scalars(select(Room).where(Room.owner_id==user.id).order_by(Room.id.desc()).limit(50)).all();count=db.scalar(select(func.count(SpeechFile.id)).join(Room).where(Room.owner_id==user.id,SpeechFile.upload_type=="recording")) or 0
        return render(request,"home.html",{**page_context(request,user,"home"),"title":"ماس | خانه","rooms":rooms,"total_capacity":sum(r.capacity for r in rooms),"recordings_count":count})
    @app.get("/profile",response_class=HTMLResponse)
    def profile(request:Request):
        ctx=get_auth_context(request,SessionLocal,cfg,api=False);first=request.query_params.get("first")=="1" or not ctx.user.profile_completed
        return render(request,"profile.html",{**page_context(request,ctx.user,"profile"),"title":"ماس | پروفایل","first":first})
    @app.post("/profile")
    def profile_save(request:Request,csrf:str=Form(...),account_name:str=Form(...),age:int=Form(...),job:str=Form(...)):
        require_csrf(request,csrf,SessionLocal,cfg);account_name=account_name.strip();job=job.strip()
        if not account_name or len(account_name)>120 or not job or len(job)>120 or not 1<=age<=120:raise HTTPException(400,"اطلاعات پروفایل نامعتبر است.")
        ctx=get_auth_context(request,SessionLocal,cfg,api=False)
        with SessionLocal() as db:
            user=db.get(User,ctx.user.id);user.account_name=account_name;user.age=age;user.job=job;user.profile_completed=True;db.commit()
        return RedirectResponse("/",303)
    @app.get("/rooms",response_class=HTMLResponse)
    def rooms(request:Request):
        user=require_page_user(request)
        with SessionLocal() as db:room_list=db.scalars(select(Room).where(Room.owner_id==user.id).order_by(Room.id.desc())).all()
        return render(request,"rooms.html",{**page_context(request,user,"rooms"),"title":"ماس | اتاق‌ها","rooms":room_list})
    @app.get("/rooms/new",response_class=HTMLResponse)
    def new_room(request:Request):
        user=require_page_user(request);return render(request,"new_room.html",{**page_context(request,user,"rooms"),"title":"ماس | ایجاد اتاق"})
    @app.post("/rooms/new")
    def new_room_save(request:Request,csrf:str=Form(...),name:str=Form(...),capacity:int=Form(...)):
        require_csrf(request,csrf,SessionLocal,cfg);user=require_page_user(request);name=validate_room_name(name);validate_capacity(capacity,1,cfg.max_room_capacity)
        with SessionLocal() as db:
            token=__import__('secrets').token_urlsafe(32);room=Room(owner_id=user.id,name=name,capacity=capacity,recording_enabled=False,live_files_enabled=False,timing_mode="global",global_seconds=300,order_mode="manual",version=1,created_at=now(),public_token=token);db.add(room);db.flush()
            for i in range(capacity):db.add(Speaker(room_id=room.id,name="",order_index=i,speaking_seconds=300))
            db.add(RoomState(room_id=room.id,updated_at=now(),version=1,overtime_allowed=False,completed=False));db.commit();rid=room.id
        return RedirectResponse(f"/rooms/{rid}",303)
    @app.get("/rooms/{room_id}",response_class=HTMLResponse)
    def room_page(request:Request,room_id:int):
        user,_=owned_room(request,room_id)
        with SessionLocal() as db:
            room=db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files),selectinload(Room.files)).where(Room.id==room_id,Room.owner_id==user.id))
            if not room:raise HTTPException(404,"اتاق پیدا نشد.")
            speakers=sorted(room.speakers,key=lambda s:(s.order_index,s.id));common=[f for f in room.files if f.upload_type=="common"]
        public_url=public_base_url(request)+f"/p/{room.public_token}"
        return render(request,"room.html",{**page_context(request,user,"room"),"title":f"ماس | {room.name}","room":room,"speakers":speakers,"common_files":common,"public_url":public_url})
    @app.get("/rooms/{room_id}/edit",response_class=HTMLResponse)
    def room_edit(request:Request,room_id:int):
        user,room=owned_room(request,room_id);return render(request,"edit_room.html",{**page_context(request,user,"rooms"),"title":"ماس | ویرایش اتاق","room":room})
    @app.post("/rooms/{room_id}/edit")
    def room_edit_save(request:Request,room_id:int,csrf:str=Form(...),name:str=Form(...),capacity:int=Form(...)):
        require_csrf(request,csrf,SessionLocal,cfg);user,_=owned_room(request,room_id);name=validate_room_name(name);validate_capacity(capacity,1,cfg.max_room_capacity)
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.id==room_id,Room.owner_id==user.id));old=room.capacity
            if not room: raise HTTPException(404,"اتاق پیدا نشد.")
            state=ensure_room_state(db,room_id)
            if capacity<old:
                doomed=db.scalars(select(Speaker).where(Speaker.room_id==room_id,Speaker.order_index>=capacity)).all()
                if state.running: raise HTTPException(409,"هنگام اجرای تایمر، ابتدا سخنرانی را متوقف کنید.")
                for sp in doomed:
                    for f in list(sp.files):
                        release_room_storage(db,room.id,f.size_bytes)
                        db.add(FileCleanupQueue(storage_name=f.storage_name,attempts=0,next_attempt_at=now(),created_at=now()))
                        db.delete(f)
                    if state.current_speaker_id==sp.id: state.current_speaker_id=None
                    db.delete(sp)
            elif capacity>old:
                for i in range(old,capacity):db.add(Speaker(room_id=room.id,name="",order_index=i,speaking_seconds=room.global_seconds))
            room.name=name;room.capacity=capacity;room.version+=1
            remaining_named=room_speakers(db,room.id,named_only=True)
            if state.current_speaker_id not in {s.id for s in remaining_named}:
                state.current_speaker_id=remaining_named[0].id if remaining_named else None
                state.current_index=0
                state.running=False
                state.started_at=None
                state.elapsed_seconds=0
                state.overtime_seconds=0
                state.overtime_allowed=False
                state.completed=not bool(remaining_named)
            db.commit()
        best_effort_cleanup(100)
        return RedirectResponse(f"/rooms/{room_id}",303)
    @app.post("/rooms/{room_id}/delete")
    def delete_room(request:Request,room_id:int,csrf:str=Form(...)):
        require_csrf(request,csrf,SessionLocal,cfg);user,_=owned_room(request,room_id)
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.id==room_id,Room.owner_id==user.id));files=collect_room_storage(db,room.id);enqueue_cleanup(db,files);db.delete(room);db.commit()
        best_effort_cleanup(200)
        return RedirectResponse("/rooms",303)
    @app.post("/rooms/{room_id}/save")
    async def save_room(request:Request,room_id:int):
        ctx=get_auth_context(request,SessionLocal,cfg,api=False)
        preflight(request,cfg.max_total_upload_bytes)
        staged=[]
        try:
            async with request.form(max_files=cfg.max_files_per_request,max_fields=max(800,cfg.max_room_capacity*8+60),max_part_size=cfg.max_upload_bytes) as form:
                require_csrf(request,str(form.get("csrf","")),SessionLocal,cfg)
                mode=str(form.get("timing_mode","global"));order=str(form.get("order_mode","manual"));room_name=validate_room_name(str(form.get("room_name","")))
                gm_raw=str(form.get("global_min","5"))
                if mode not in TIMING_MODES or order not in ORDER_MODES or not gm_raw.isdigit() or not 1<=int(gm_raw)<=1440:
                    raise HTTPException(400,"تنظیمات اتاق نامعتبر است.")
                global_seconds=int(gm_raw)*60
                # Read/validate current room data before expensive filesystem work.
                with SessionLocal() as db:
                    room=db.scalar(select(Room).options(selectinload(Room.speakers)).where(Room.id==room_id,Room.owner_id==ctx.user.id))
                    if not room:raise HTTPException(404,"اتاق پیدا نشد.")
                    state=ensure_room_state(db,room.id)
                    if state.running:raise HTTPException(409,"هنگام اجرای تایمر تنظیمات اتاق را ذخیره نکنید.")
                    speakers=sorted(room.speakers,key=lambda s:(s.order_index,s.id))
                    speaker_specs={}
                    for sp in speakers:
                        g=str(form.get(f"gender_{sp.id}",""));rawage=str(form.get(f"age_{sp.id}","")).strip();rawtime=str(form.get(f"time_{sp.id}","" )).strip()
                        if rawtime and (not rawtime.isdigit() or not 1<=int(rawtime)<=1440):raise HTTPException(400,"زمان اختصاصی سخنران نامعتبر است.")
                        age=int(rawage) if rawage.isdigit() and 1<=int(rawage)<=120 else None
                        speaker_specs[sp.id]={"name":validate_speaker_name(str(form.get(f"name_{sp.id}",""))),"gender":g if g in GENDERS else "","age":age,"description":str(form.get(f"desc_{sp.id}",""))[:1000],"speaking_seconds":int(rawtime)*60 if rawtime else (sp.speaking_seconds or global_seconds)}
                    old_order_mode=room.order_mode;oldid=state.current_speaker_id
                    room_version=room.version
                    current_order=[sp.id for sp in speakers]
                    room_capacity=room.capacity
                uploads=[]
                for sp in speakers:
                    for item in form.getlist(f"file_{sp.id}"):
                        if isinstance(item,StarletteUploadFile) and item.filename:uploads.append((item,sp.id,"speaker"))
                for item in form.getlist("common_files"):
                    if isinstance(item,StarletteUploadFile) and item.filename:uploads.append((item,None,"common"))
                if len(uploads)>cfg.max_files_per_request:raise HTTPException(400,"تعداد فایل‌ها بیش از حد مجاز است.")
                used=0
                for upload,sid,utype in uploads:
                    st=await store_upload(upload,cfg,request_bytes_used=used)
                    staged.append(st);used+=st.size_bytes
                manual_ids=[];ids=set(current_order);rawmanual=str(form.get("manual_order",""))
                for raw in rawmanual.split(","):
                    if raw.strip().isdigit() and int(raw.strip()) in ids:manual_ids.append(int(raw.strip()))
                with SessionLocal() as db:
                    room=db.scalar(select(Room).options(selectinload(Room.speakers)).where(Room.id==room_id,Room.owner_id==ctx.user.id).with_for_update())
                    if not room:raise HTTPException(404,"اتاق پیدا نشد.")
                    if room.version!=room_version:raise HTTPException(409,"تنظیمات اتاق همزمان تغییر کرده است. صفحه را دوباره باز کنید.")
                    state=ensure_room_state(db,room.id)
                    if state.running:raise HTTPException(409,"هنگام اجرای تایمر تنظیمات اتاق را ذخیره نکنید.")
                    speakers=sorted(room.speakers,key=lambda s:(s.order_index,s.id));sp_map={s.id:s for s in speakers}
                    for sid,spec in speaker_specs.items():
                        sp=sp_map[sid];sp.name=spec["name"];sp.gender=spec["gender"];sp.age=spec["age"];sp.description=spec["description"];sp.speaking_seconds=spec["speaking_seconds"]
                    room.name=room_name;room.recording_enabled=bool(form.get("recording"));room.live_files_enabled=bool(form.get("live_files"));room.timing_mode=mode;room.global_seconds=global_seconds;room.order_mode=order
                    ordered=(list(speakers) if order=="random" and old_order_mode=="random" else ordered_speakers(speakers,order,manual_ids))
                    for i,sp in enumerate(speakers):sp.order_index=-(i+1)
                    db.flush()
                    for i,sp in enumerate(ordered):sp.order_index=i
                    db.flush()
                    for (upload,sid,utype),st in zip(uploads,staged):
                        speaker=sp_map.get(sid) if sid else None
                        reserve_room_storage(db,room.id,st.size_bytes,cfg.max_room_storage_bytes)
                        db.add(SpeechFile(room_id=room.id,speaker_id=sid,filename=st.original_name,storage_name=st.storage_name,content_type=st.content_type,size_bytes=st.size_bytes,upload_type=utype,created_at=now(),speaker_name_snapshot=speaker.name if speaker else "",room_name_snapshot=room.name))
                    named=[sp for sp in ordered if sp.name]
                    if oldid in {sp.id for sp in named}:
                        state.current_speaker_id=oldid;state.current_index=next(i for i,sp in enumerate(named) if sp.id==oldid)
                    else:
                        state.current_speaker_id=named[0].id if named else None;state.current_index=0;state.completed=not bool(named);state.elapsed_seconds=0;state.overtime_seconds=0;state.running=False;state.started_at=None;state.overtime_allowed=False
                    state.updated_at=now();room.version+=1
                    db.commit()
            staged.clear()
            return RedirectResponse(f"/rooms/{room_id}",303)
        except Exception:
            for st in staged:
                try:safe_storage_path(cfg,st.storage_name).unlink(missing_ok=True)
                except OSError:pass
            raise
    @app.post("/api/rooms/{room_id}/speakers/{speaker_id}/delete")
    async def delete_speaker(request:Request,room_id:int,speaker_id:int):
        ctx=get_auth_context(request,SessionLocal,cfg,api=True);preflight(request,cfg.max_upload_bytes)
        async with request.form(max_files=2,max_fields=8,max_part_size=cfg.max_upload_bytes) as form:
            require_csrf(request,str(form.get("csrf","")),SessionLocal,cfg);save=str(form.get("save_recording","0"))=="1";uploaded=None;newly=[]
            if save:
                item=form.get("recording")
                if isinstance(item,StarletteUploadFile) and item.filename:
                    rawdur=str(form.get("duration_seconds","0")).strip()
                    duration=int(rawdur) if rawdur.isdigit() else 0
                    if duration < 0 or duration > cfg.max_recording_seconds:
                        raise HTTPException(400,"مدت ضبط نامعتبر است.")
                    uploaded=await store_upload(item,cfg)
                    newly.append(uploaded.storage_name)
            try:
                with SessionLocal() as db:
                    room=db.scalar(select(Room).where(Room.id==room_id,Room.owner_id==ctx.user.id).with_for_update());sp=db.scalar(select(Speaker).where(Speaker.id==speaker_id,Speaker.room_id==room_id).with_for_update())
                    if not room or not sp:raise HTTPException(404,"سخنران پیدا نشد.")
                    state=ensure_room_state(db,room_id);speakers=room_speakers(db,room_id,named_only=True);idx=speakers.index(sp) if sp in speakers else -1
                    if uploaded:
                        if not room.recording_enabled:
                            raise HTTPException(403,"ضبط برای این اتاق فعال نیست.")
                        suffix=Path(uploaded.original_name).suffix.lower()
                        recording_type={".webm":"audio/webm",".ogg":"audio/ogg",".mp4":"audio/mp4"}.get(suffix,uploaded.content_type)
                        reserve_room_storage(db,room.id,uploaded.size_bytes,cfg.max_room_storage_bytes)
                        db.add(SpeechFile(room_id=room.id,speaker_id=None,filename=uploaded.original_name,storage_name=uploaded.storage_name,content_type=recording_type,size_bytes=uploaded.size_bytes,upload_type="recording",duration_seconds=duration,created_at=now(),speaker_name_snapshot=sp.name,room_name_snapshot=room.name))
                    for f in list(sp.files):
                        if f.upload_type=="recording":
                            if save:
                                f.speaker_name_snapshot=f.speaker_name_snapshot or sp.name
                                f.room_name_snapshot=f.room_name_snapshot or room.name
                                f.speaker_id=None
                            else:
                                release_room_storage(db,room.id,f.size_bytes)
                                db.add(FileCleanupQueue(storage_name=f.storage_name,attempts=0,next_attempt_at=now(),created_at=now()))
                                db.delete(f)
                        else:
                            release_room_storage(db,room.id,f.size_bytes)
                            db.add(FileCleanupQueue(storage_name=f.storage_name,attempts=0,next_attempt_at=now(),created_at=now()))
                            db.delete(f)
                    was_current=state.current_speaker_id==speaker_id;db.delete(sp);room.capacity=max(0,room.capacity-1);room.version+=1
                    db.flush()
                    remaining=room_speakers(db,room_id,named_only=True)
                    if was_current:
                        target=remaining[min(max(idx,0),len(remaining)-1)] if remaining else None
                        state.current_speaker_id=target.id if target else None;state.current_index=remaining.index(target) if target else 0;state.elapsed_seconds=0;state.overtime_seconds=0;state.running=False;state.started_at=None;state.overtime_allowed=False;state.completed=not bool(target)
                    else:
                        current_id=state.current_speaker_id
                        if current_id in {s.id for s in remaining}:
                            state.current_index=next(i for i,s in enumerate(remaining) if s.id==current_id)
                        else:
                            target=remaining[0] if remaining else None;state.current_speaker_id=target.id if target else None;state.current_index=0;state.completed=not bool(target);state.running=False;state.started_at=None;state.overtime_allowed=False
                    db.commit()
                best_effort_cleanup(100)
                return JSONResponse({"ok":True})
            except Exception:
                for n in newly:
                    try:safe_storage_path(cfg,n).unlink(missing_ok=True)
                    except OSError:pass
                if uploaded and uploaded.storage_name not in newly:
                    pass
                raise
    @app.get("/rooms/{room_id}/play",response_class=HTMLResponse)
    def play(request:Request,room_id:int):
        user,_=owned_room(request,room_id)
        with SessionLocal() as db:
            room=db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files),selectinload(Room.files)).where(Room.id==room_id,Room.owner_id==user.id))
            if not room:raise HTTPException(404,"اتاق پیدا نشد.")
            speakers=[s for s in sorted(room.speakers,key=lambda s:(s.order_index,s.id)) if s.name];common=[f for f in room.files if f.upload_type=="common"]
        pd={"room_id":room.id,"room":room.name,"live_files":room.live_files_enabled,"recording":room.recording_enabled,"max_recording_seconds":cfg.max_recording_seconds,"csrf":get_auth_context(request,SessionLocal,cfg,api=False).csrf_token,"public_url":public_base_url(request)+f"/p/{room.public_token}","speakers":[{"id":s.id,"name":s.name,"seconds":limit_for(room,s),"gender":s.gender,"age":s.age,"description":s.description,"files":[{"id":f.id,"name":f.filename,"content_type":f.content_type} for f in s.files if f.upload_type!="recording"]} for s in speakers],"common":[{"id":f.id,"name":f.filename,"content_type":f.content_type} for f in common]}
        return render(request,"play.html",{**page_context(request,user,"play"),"title":f"ماس | پخش {room.name}","room":room,"page_data":pd})
    @app.get("/api/rooms/{room_id}/state")
    def api_state(request:Request,room_id:int):
        ctx=get_auth_context(request,SessionLocal,cfg,api=True)
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.id==room_id,Room.owner_id==ctx.user.id));
            if not room:raise HTTPException(404,"اتاق پیدا نشد.")
            return JSONResponse(state_snapshot(db,room,auto_expire=True))
    @app.post("/api/rooms/{room_id}/recording")
    async def save_recording(request:Request,room_id:int):
        ctx=get_auth_context(request,SessionLocal,cfg,api=True);preflight(request,cfg.max_upload_bytes)
        async with request.form(max_files=2,max_fields=10,max_part_size=cfg.max_upload_bytes) as form:
            require_csrf(request,str(form.get("csrf","")),SessionLocal,cfg)
            rawdur=str(form.get("duration_seconds","0")).strip()
            duration=int(rawdur) if rawdur.isdigit() else 0
            if duration < 0 or duration > cfg.max_recording_seconds:
                raise HTTPException(400,"مدت ضبط نامعتبر است.")
            sid=int(str(form.get("speaker_id","0"))) if str(form.get("speaker_id","0")).isdigit() else 0
            item=form.get("file")
            if not isinstance(item,StarletteUploadFile) or not item.filename:raise HTTPException(400,"فایل ضبط ارسال نشده است.")
            stored=await store_upload(item,cfg)
            try:
                with SessionLocal() as db:
                    room=db.scalar(select(Room).where(Room.id==room_id,Room.owner_id==ctx.user.id).with_for_update());speaker=db.scalar(select(Speaker).where(Speaker.id==sid,Speaker.room_id==room_id)) if sid else None
                    if not room or not room.recording_enabled:raise HTTPException(403,"ضبط برای این اتاق فعال نیست.")
                    if speaker is None:
                        raise HTTPException(400,"سخنران ضبط مشخص نیست.")
                    suffix=Path(stored.original_name).suffix.lower()
                    recording_type={".webm":"audio/webm",".ogg":"audio/ogg",".mp4":"audio/mp4"}.get(suffix,stored.content_type)
                    reserve_room_storage(db,room.id,stored.size_bytes,cfg.max_room_storage_bytes)
                    db.add(SpeechFile(room_id=room.id,speaker_id=speaker.id,filename=stored.original_name,storage_name=stored.storage_name,content_type=recording_type,size_bytes=stored.size_bytes,upload_type="recording",duration_seconds=duration,created_at=now(),speaker_name_snapshot=speaker.name,room_name_snapshot=room.name))
                    room.version += 1
                    db.commit()
                return JSONResponse({"ok":True})
            except Exception:
                safe_storage_path(cfg,stored.storage_name).unlink(missing_ok=True);raise
    @app.post("/api/rooms/{room_id}/{action}")
    def playback_control(request:Request,room_id:int,action:str,csrf:str=Form(...)):
        ctx=get_auth_context(request,SessionLocal,cfg,api=True);require_csrf(request,csrf,SessionLocal,cfg)
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.id==room_id,Room.owner_id==ctx.user.id).with_for_update());
            if not room:raise HTTPException(404,"اتاق پیدا نشد.")
            return JSONResponse(apply_timer_action(db,room,action))
    @app.get("/recordings",response_class=HTMLResponse)
    def recordings(request:Request,room_id:int|None=None):
        user=require_page_user(request)
        with SessionLocal() as db:
            stmt=select(SpeechFile).join(Room).where(Room.owner_id==user.id,SpeechFile.upload_type=="recording").order_by(SpeechFile.id.desc())
            if room_id is not None:stmt=stmt.where(SpeechFile.room_id==room_id)
            rows=db.scalars(stmt.limit(500)).all()
        def human_size(n):
            for base,label in [(1024**3,"GB"),(1024**2,"MB"),(1024,"KB")]:
                if n>=base:return f"{n/base:.1f} {label}"
            return f"{n} B"
        items=[{"id":f.id,"speaker_name":f.speaker_name_snapshot or "بدون نام","room_name":f.room_name_snapshot or "اتاق","filename":f.filename,"size_label":human_size(f.size_bytes),"created_label":time.strftime("%Y-%m-%d %H:%M",time.localtime(f.created_at))} for f in rows]
        return render(request,"recordings.html",{**page_context(request,user,"recordings"),"title":"ماس | فایل‌های ضبط‌شده","recordings":items})
    @app.post("/files/{file_id}/delete")
    def delete_file(request:Request,file_id:int,csrf:str=Form(...)):
        ctx=get_auth_context(request,SessionLocal,cfg,api=True);require_csrf(request,csrf,SessionLocal,cfg)
        with SessionLocal() as db:
            f=db.scalar(select(SpeechFile).join(Room).where(SpeechFile.id==file_id,Room.owner_id==ctx.user.id));
            if not f:raise HTTPException(404,"فایل پیدا نشد.")
            room=f.room
            release_room_storage(db,f.room_id,f.size_bytes)
            db.add(FileCleanupQueue(storage_name=f.storage_name,attempts=0,next_attempt_at=now(),created_at=now()))
            db.delete(f)
            room.version += 1
            db.commit()
        best_effort_cleanup(20)
        return JSONResponse({"ok":True})
    def private_file(request:Request,file_id:int,download:bool):
        ctx=get_auth_context(request,SessionLocal,cfg,api=False)
        with SessionLocal() as db:
            f=db.scalar(select(SpeechFile).join(Room).where(SpeechFile.id==file_id,Room.owner_id==ctx.user.id))
            if not f:raise HTTPException(404,"فایل پیدا نشد.")
            path=safe_storage_path(cfg,f.storage_name)
            if not path.is_file():raise HTTPException(404,"فایل روی سرور وجود ندارد.")
            return FileResponse(path,media_type=f.content_type,headers={"Content-Disposition":content_disposition(f.filename,"attachment" if download else "inline"),"X-Content-Type-Options":"nosniff"})
    @app.get("/files/{file_id}")
    def get_file(request:Request,file_id:int):return private_file(request,file_id,False)
    @app.get("/files/{file_id}/download")
    def download_file(request:Request,file_id:int):return private_file(request,file_id,True)
    @app.get("/p/{token}",response_class=HTMLResponse)
    def public_room(request:Request,token:str):
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.public_token==token))
            if not room:raise HTTPException(404,"لینک عمومی پیدا نشد.")
            return render(request,"public_room.html",{"request":request,"title":f"تماشای زنده | {room.name}","room":room,"public_token":token,"live_files":room.live_files_enabled})
    @app.get("/public-api/rooms/{token}/state")
    def public_state(token:str,request:Request):
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.public_token==token));
            if not room:raise HTTPException(404,"اتاق پیدا نشد.")
            state=state_snapshot(db,room,auto_expire=True);speakers=room_speakers(db,room.id,named_only=True);files=[]
            common=db.scalars(select(SpeechFile).where(SpeechFile.room_id==room.id,SpeechFile.upload_type=="common").order_by(SpeechFile.id)).all();files.extend([{"id":f.id,"name":f.filename,"content_type":f.content_type,"scope":"common"} for f in common])
            if room.live_files_enabled and state.get("current_speaker_id"):
                spfiles=db.scalars(select(SpeechFile).where(SpeechFile.room_id==room.id,SpeechFile.speaker_id==state["current_speaker_id"],SpeechFile.upload_type=="speaker").order_by(SpeechFile.id)).all();files.extend([{"id":f.id,"name":f.filename,"content_type":f.content_type,"scope":"speaker"} for f in spfiles])
            state["files"]=files;state["room_version"]=room.version;state["server_time"]=now();return JSONResponse(state)
    @app.get("/public-files/{token}/{file_id}")
    def public_file(token:str,file_id:int):
        with SessionLocal() as db:
            room=db.scalar(select(Room).where(Room.public_token==token));
            if not room:raise HTTPException(404,"اتاق پیدا نشد.")
            f=db.scalar(select(SpeechFile).where(SpeechFile.id==file_id,SpeechFile.room_id==room.id))
            if not f or f.upload_type=="recording" or (f.upload_type=="speaker" and not room.live_files_enabled):raise HTTPException(404,"فایل برای نمایش عمومی در دسترس نیست.")
            path=safe_storage_path(cfg,f.storage_name)
            if not path.is_file():raise HTTPException(404,"فایل روی سرور وجود ندارد.")
            return FileResponse(path,media_type=f.content_type,headers={"Content-Disposition":content_disposition(f.filename,"inline"),"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
    @app.get("/p/{token}/qr.svg")
    def public_qr(token:str,request:Request):
        with SessionLocal() as db:
            if not db.scalar(select(Room.id).where(Room.public_token==token)):raise HTTPException(404,"لینک عمومی پیدا نشد.")
        url=public_base_url(request)+f"/p/{token}";qr=qrcode.QRCode(box_size=8,border=2);qr.add_data(url);qr.make(fit=True);buf=__import__('io').BytesIO();img=qr.make_image(image_factory=SvgImage);img.save(buf);return Response(content=buf.getvalue(),media_type="image/svg+xml",headers={"Cache-Control":"no-store"})
    @app.get("/health")
    def health():
        with SessionLocal() as db:db.execute(select(1))
        probe=cfg.storage_dir/f".health-{time.time_ns()}"
        try:probe.write_bytes(b"ok");probe.unlink(missing_ok=True);return {"status":"ok","database":"ok","storage_writable":True}
        except OSError:return JSONResponse(content={"status":"degraded","database":"ok","storage_writable":False},status_code=503)
    return app

app=create_app()
