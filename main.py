from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from pydantic import BaseModel
import socketio
import os
import time

from database import (
    get_db, User, TicketType, Guiche, Setting, CallRecord, Tenant, Plan,
    init_db, engine, SessionLocal, Base
)

# ── Configuração ────────────────────────────────────────────────────────────
SECRET_KEY = "sistema-senhas-secret-key-2024-saas"
ALGORITHM  = "HS256"
TOKEN_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security    = HTTPBearer(auto_error=False)

app = FastAPI(title="SwiftQ", version="5.0")
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)

# ── Estado em memória (Multitenant) ──────────────────────────────────────────
tenants_queues   = {} 
tenants_counters = {} 
tenants_history  = {} 
tenants_dates    = {} # {tenant_id: "YYYY-MM-DD"}
active_guiches   = {} # {(tenant_id, name): {"user_id": int, "user_name": str}}

def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        init_db(db)
        # Inicializa filas de todos os tenants ativos
        all_tenants = db.query(Tenant).filter(Tenant.active == True).all()
        for t in all_tenants:
            tenants_queues[t.id]   = {}
            tenants_counters[t.id] = {}
            tenants_history[t.id]  = []
            tenants_dates[t.id]    = datetime.now().strftime("%Y-%m-%d")
            
            types = db.query(TicketType).filter(TicketType.tenant_id == t.id, TicketType.active == True).all()
            for tt in types:
                tenants_queues[t.id][tt.code]   = []
                tenants_counters[t.id][tt.code] = 1
    finally:
        db.close()

startup()

# ── Auth ─────────────────────────────────────────────────────────────────────
def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security), db: Session = Depends(get_db)) -> User:
    if not creds: raise HTTPException(401, "Não autenticado")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError: raise HTTPException(401, "Token inválido/expirado")
    user = db.query(User).filter(User.id == int(payload["sub"]), User.active == True).first()
    if not user: raise HTTPException(401, "Usuário não encontrado")
    if user.tenant_id and not user.tenant.active:
        raise HTTPException(401, "Unidade inativa. Entre em contato com o suporte.")
    return user

def require_admin(user: User = Depends(get_current_user)):
    if user.role not in ["admin", "superadmin"]: raise HTTPException(403, "Acesso restrito")
    return user

def require_superadmin(user: User = Depends(get_current_user)):
    if user.role != "superadmin": raise HTTPException(403, "Acesso restrito ao SUPERADMIN")
    return user

# ── Multi-Tenant Helpers ───────────────────────────────────────────────────
def get_tenant_queues(tenant_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    if tenant_id not in tenants_queues or tenants_dates.get(tenant_id) != today:
        print(f"DEBUG: Resetando contadores do tenant {tenant_id} para o dia {today}")
        tenants_queues[tenant_id]   = {}
        tenants_counters[tenant_id] = {}
        tenants_history[tenant_id]  = []
        tenants_dates[tenant_id]    = today
    return tenants_queues[tenant_id], tenants_counters[tenant_id], tenants_history[tenant_id]

def get_tenant_by_slug(slug: str, db: Session):
    tenant = db.query(Tenant).filter(Tenant.slug == slug, Tenant.active == True).first()
    if not tenant: raise HTTPException(404, "Unidade não encontrada")
    return tenant

# ── Schemas ──────────────────────────────────────────────────────────────────
class LoginReq(BaseModel): username: str; password: str
class PlanCreate(BaseModel): name: str; max_guiches: int; max_users: int; max_types: int
class PlanUpdate(BaseModel): name: Optional[str] = None; max_guiches: Optional[int] = None; max_users: Optional[int] = None; max_types: Optional[int] = None; active: Optional[bool] = None
class TenantCreate(BaseModel): name: str; slug: str; plan_id: int
class TenantUpdate(BaseModel): name: Optional[str] = None; plan_id: Optional[int] = None; active: Optional[bool] = None
class UserSuperUpdate(BaseModel): name: Optional[str] = None; username: Optional[str] = None; password: Optional[str] = None; role: Optional[str] = None; active: Optional[bool] = None
class UserCreate(BaseModel): name: str; username: str; password: str; role: str; tenant_id: Optional[int] = None; active: bool = True
class AppearanceUpdate(BaseModel): primary_color: str; secondary_color: str; bg_color: str; logo_url: Optional[str] = None
class TypeUpdate(BaseModel): name: str; code: str; color: str; icon: str; priority: int; active: bool; priority_guiches: Optional[str] = None

# ── Public Routes (Tenant-Specific) ──────────────────────────────────────────
@app.get("/api/{slug}/status")
async def get_tenant_status(slug: str, db: Session = Depends(get_db)):
    t = get_tenant_by_slug(slug, db)
    q_map, _, history = get_tenant_queues(t.id)
    types = db.query(TicketType).filter(TicketType.tenant_id == t.id, TicketType.active == True).order_by(TicketType.priority.desc()).all()
    cfg   = {s.key: s.value for s in db.query(Setting).filter(Setting.tenant_id == t.id).all()}
    return {
        "tenant": {"id": t.id, "name": t.name, "primary": t.primary_color, "secondary": t.secondary_color, "bg": t.bg_color, "logo": t.logo_url},
        "queues": {k: len(v) for k, v in q_map.items()},
        "types": [{"code": tt.code, "name": tt.name, "color": tt.color, "icon": tt.icon} for tt in types],
        "history": history[:8],
        "last_called": history[0] if history else None,
        "system_name": cfg.get("system_name", t.name),
        "system_subtitle": cfg.get("system_subtitle", ""),
        "config": cfg
    }

@app.post("/api/{slug}/generate/{ticket_type}")
async def generate_password(slug: str, ticket_type: str, db: Session = Depends(get_db)):
    t = get_tenant_by_slug(slug, db)
    code = ticket_type.upper()
    tt = db.query(TicketType).filter(TicketType.tenant_id == t.id, TicketType.code == code).first()
    if not tt: raise HTTPException(400, "Tipo inválido")
    
    q_map, c_map, _ = get_tenant_queues(t.id)
    if code not in q_map:
        q_map[code] = []; c_map[code] = 1
    
    password = f"{code}{c_map[code]:03d}"
    c_map[code] += 1
    q_map[code].append({"p": password, "t": time.time()})
    await sio.emit(f"new_password_{t.id}", {"type": code, "count": len(q_map[code])})
    
    cfg = {s.key: s.value for s in db.query(Setting).filter(Setting.tenant_id == t.id).all()}
    system_name = cfg.get("system_name", t.name)
    system_subtitle = cfg.get("system_subtitle", "")
    now = datetime.now()

    return {
        "password": password, 
        "queue_size": len(q_map[code]),
        "tenant_name": system_name,
        "system_subtitle": system_subtitle,
        "type_name": tt.name,
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M:%S")
    }

# ── Auth ─────────────────────────────────────────────────────────────────────
@app.post("/api/auth/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username, User.active == True).first()
    if not user or not pwd_context.verify(req.password, user.password_hash): raise HTTPException(401, "Usuário ou senha incorretos")
    if user.tenant_id and not user.tenant.active:
        raise HTTPException(401, "Unidade inativa. Entre em contato com o suporte.")
    tenant_info = {"id": user.tenant.id, "name": user.tenant.name, "slug": user.tenant.slug} if user.tenant else None
    return {"token": create_token(user.id), "user": {"id": user.id, "name": user.name, "username": user.username, "role": user.role, "tenant": tenant_info}}

@app.get("/api/status")
def get_my_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.tenant_id: raise HTTPException(403)
    t = user.tenant
    q_map, _, history = get_tenant_queues(t.id)
    types = db.query(TicketType).filter(TicketType.tenant_id == t.id, TicketType.active == True).order_by(TicketType.priority.desc()).all()
    cfg   = {s.key: s.value for s in db.query(Setting).filter(Setting.tenant_id == t.id).all()}
    print(f"DEBUG: Status para Tenant {t.id} - system_name no DB: {cfg.get('system_name')}")
    return {
        "tenant": {"id": t.id, "name": t.name, "primary": t.primary_color, "secondary": t.secondary_color, "bg": t.bg_color, "logo": t.logo_url},
        "queues": {k: len(v) for k, v in q_map.items()},
        "types": [{"code": tt.code, "name": tt.name, "color": tt.color, "icon": tt.icon} for tt in types],
        "history": history[:8],
        "last_called": history[0] if history else None,
        "system_name": cfg.get("system_name", t.name),
        "system_subtitle": cfg.get("system_subtitle", ""),
        "config": cfg
    }

@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)): return {"id": user.id, "name": user.name, "role": user.role}

# ── Private / Chamada ───────────────────────────────────────────────────────
@app.post("/api/call")
async def call_next_tenant(terminal: str, type: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.tenant_id: raise HTTPException(403)
    tid = user.tenant_id
    q_map, _, history = get_tenant_queues(tid)
    target = type.upper() if type else None
    
    if not target:
        # 1. Buscar tipos que têm este terminal como prioridade
        priority_types = db.query(TicketType).filter(TicketType.tenant_id == tid, TicketType.active == True, TicketType.priority_guiches.like(f"%{terminal}%")).all()
        candidate_tickets = []
        for pt in priority_types:
            if q_map.get(pt.code):
                candidate_tickets.append({"code": pt.code, "ticket": q_map[pt.code][0]})
        
        # 2. Se houver tickets de prioridade, pegar o mais antigo entre eles (FIFO entre prioridades)
        if candidate_tickets:
            candidate_tickets.sort(key=lambda x: x["ticket"]["t"])
            target = candidate_tickets[0]["code"]
        else:
            # 3. Fallback: Pegar o ticket mais antigo de TODOS os tipos (Global FIFO)
            all_candidates = []
            for code, queue in q_map.items():
                if queue:
                    all_candidates.append({"code": code, "ticket": queue[0]})
            
            if all_candidates:
                all_candidates.sort(key=lambda x: x["ticket"]["t"])
                target = all_candidates[0]["code"]

    if not target or not q_map.get(target): return {"error": "Fila vazia"}
    
    t_obj = q_map[target].pop(0)
    password = t_obj["p"]
    tt_obj = db.query(TicketType).filter(TicketType.tenant_id == tid, TicketType.code == target).first()
    call_data = {"password": password, "terminal": terminal, "user_name": user.name, "type": target, "label": tt_obj.name, "color": tt_obj.color, "time": datetime.now().strftime("%H:%M:%S")}
    history.insert(0, call_data)
    if len(history) > 30: history.pop()
    db.add(CallRecord(tenant_id=tid, password=password, ticket_type_code=target, ticket_type_name=tt_obj.name, guiche_name=terminal, user_name=user.name, date_key=datetime.now().strftime("%Y-%m-%d")))
    db.commit(); await sio.emit(f"password_called_{tid}", call_data)
    return call_data

@app.post("/api/recall")
async def recall_last(user: User = Depends(get_current_user)):
    if not user.tenant_id: raise HTTPException(403)
    _, _, h = get_tenant_queues(user.tenant_id)
    if not h: return {"error": "Nenhuma senha para repetir"}
    last = h[0]
    await sio.emit(f"password_called_{user.tenant_id}", last)
    return last

@app.post("/api/absent")
async def mark_absent(user: User = Depends(get_current_user)):
    if not user.tenant_id: raise HTTPException(403)
    _, _, h = get_tenant_queues(user.tenant_id)
    if not h: return {"error": "Nenhuma senha para marcar como ausente"}
    last = h[0]
    return {"status": "ok", "absent": last["password"]}

# ── Admin da Unidade ────────────────────────────────────────────────────────
@app.put("/api/admin/appearance")
def update_appearance(req: AppearanceUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not user.tenant_id: raise HTTPException(403)
    t = user.tenant
    t.primary_color = req.primary_color; t.secondary_color = req.secondary_color; t.bg_color = req.bg_color; t.logo_url = req.logo_url
    db.commit(); return {"status": "ok"}

@app.get("/api/admin/users")
def admin_list_users(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).filter(User.tenant_id == user.tenant_id).all()

@app.post("/api/admin/users")
def admin_create_user(req: UserCreate, user_id: Optional[int] = None, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = user.tenant
    query = db.query(User).filter(User.tenant_id == t.id)
    if user_id:
        # Se está tentando ativar ou manter ativo, verifica limite
        if req.active:
            others_active = db.query(User).filter(User.tenant_id == t.id, User.active == True, User.id != user_id).count()
            if others_active >= t.plan.max_users: raise HTTPException(400, "Limite do plano atingido (Usuários ativos)")
        # Verificar duplicidade de username ignorando o próprio usuário
        if db.query(User).filter(User.username == req.username, User.id != user_id).first(): raise HTTPException(400, "Username já existe")
        u = db.get(User, user_id)
        if not u: raise HTTPException(404, "Usuário não encontrado")
        u.name = req.name; u.username = req.username; u.role = req.role; u.active = req.active
        if req.password: u.password_hash = pwd_context.hash(req.password)
        db.commit(); return u
    else:
        if req.active:
            active_count = db.query(User).filter(User.tenant_id == t.id, User.active == True).count()
            if active_count >= t.plan.max_users: raise HTTPException(400, "Limite do plano atingido (Usuários ativos)")
        if db.query(User).filter(User.username == req.username).first(): raise HTTPException(400, "Username já existe")
        u = User(username=req.username, password_hash=pwd_context.hash(req.password), name=req.name, role=req.role, tenant_id=t.id, active=req.active)
        db.add(u); db.commit(); db.refresh(u); return u

@app.get("/api/guiches")
def list_guiches(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.tenant_id: return []
    gs = db.query(Guiche).filter(Guiche.tenant_id == user.tenant_id, Guiche.active == True).all()
    res = []
    for g in gs:
        occupant = active_guiches.get((user.tenant_id, g.name))
        res.append({
            "id": g.id,
            "name": g.name,
            "busy": occupant is not None,
            "occupant_name": occupant["user_name"] if occupant else None,
            "occupant_id": occupant["user_id"] if occupant else None
        })
    return res

@app.post("/api/guiches/occupy")
async def occupy_guiche(name: str, user: User = Depends(get_current_user)):
    if not user.tenant_id: raise HTTPException(403)
    # Remove user de outros guiches na mesma unidade
    to_del = [k for k, v in active_guiches.items() if k[0] == user.tenant_id and v["user_id"] == user.id]
    for k in to_del: del active_guiches[k]
    
    # Notificar possível ocupante anterior
    old_occupant = active_guiches.get((user.tenant_id, name))
    if old_occupant and old_occupant["user_id"] != user.id:
        await sio.emit(f"terminal_kick_{user.tenant_id}_{name}", {"new_user": user.name})

    active_guiches[(user.tenant_id, name)] = {"user_id": user.id, "user_name": user.name}
    return {"status": "ok"}

@app.get("/api/admin/guiches")
def admin_list_guiches(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(Guiche).filter(Guiche.tenant_id == user.tenant_id).all()

@app.post("/api/admin/guiches")
def admin_create_guiche(data: dict, guiche_id: Optional[int] = None, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = user.tenant
    query = db.query(Guiche).filter(Guiche.tenant_id == t.id)
    if guiche_id:
        if data.get("active", True):
            others_active = db.query(Guiche).filter(Guiche.tenant_id == t.id, Guiche.active == True, Guiche.id != guiche_id).count()
            if others_active >= t.plan.max_guiches: raise HTTPException(400, "Limite do plano atingido (Guichês ativos)")
        g = db.get(Guiche, guiche_id)
        if not g: raise HTTPException(404, "Guichê não encontrado")
        g.name = data.get("name")
        if "active" in data: g.active = data["active"]
        db.commit(); return g
    else:
        if data.get("active", True):
            active_count = db.query(Guiche).filter(Guiche.tenant_id == t.id, Guiche.active == True).count()
            if active_count >= t.plan.max_guiches: raise HTTPException(400, "Limite do plano atingido (Guichês ativos)")
        new_g = Guiche(name=data.get("name"), tenant_id=t.id, active=data.get("active", True))
        db.add(new_g); db.commit(); db.refresh(new_g); return new_g

@app.get("/api/admin/types")
def admin_list_types(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(TicketType).filter(TicketType.tenant_id == user.tenant_id).all()

@app.post("/api/admin/types")
def admin_create_type(req: TypeUpdate, type_id: Optional[int] = None, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = user.tenant
    query = db.query(TicketType).filter(TicketType.tenant_id == t.id)
    if type_id:
        if req.active:
            others_active = db.query(TicketType).filter(TicketType.tenant_id == t.id, TicketType.active == True, TicketType.id != type_id).count()
            if others_active >= t.plan.max_types: raise HTTPException(400, "Limite do plano atingido (Tipos de Senha ativos)")
        tt = db.get(TicketType, type_id)
        if not tt: raise HTTPException(404, "Tipo não encontrado")
        old_code = tt.code
        new_code = req.code[:1].upper()
        tt.code = new_code; tt.name = req.name; tt.color = req.color; tt.icon = req.icon; tt.priority = req.priority; tt.active = req.active; tt.priority_guiches = req.priority_guiches
        db.commit()
        if old_code != new_code:
            q, c, _ = get_tenant_queues(t.id)
            if new_code not in q: q[new_code] = []; c[new_code] = 1
        return tt
    else:
        if req.active:
            active_count = db.query(TicketType).filter(TicketType.tenant_id == t.id, TicketType.active == True).count()
            if active_count >= t.plan.max_types: raise HTTPException(400, "Limite do plano atingido (Tipos de Senha ativos)")
        new_code = req.code[:1].upper()
        tt = TicketType(tenant_id=t.id, code=new_code, name=req.name, color=req.color, icon=req.icon, priority=req.priority, active=req.active, priority_guiches=req.priority_guiches)
        db.add(tt); db.commit(); db.refresh(tt)
        q, c, _ = get_tenant_queues(t.id); q[new_code] = []; c[new_code] = 1
        return tt

@app.post("/api/admin/settings")
def update_settings(data: Dict[str, Any], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ['admin', 'superadmin', 'kiosk']: raise HTTPException(403)
    tid = user.tenant_id
    if not tid: raise HTTPException(403)
    
    print(f"Salvando configuracoes para Tenant {tid}: {data}")
    for k, v in data.items():
        val = str(v) if v is not None else ""
        s = db.query(Setting).filter(Setting.tenant_id == tid, Setting.key == k).first()
        if s: 
            s.value = val
        else: 
            db.add(Setting(tenant_id=tid, key=k, value=val))
        print(f"Salvo chave {k} com valor {val}")
    db.commit()
    return {"status": "ok"}

@app.delete("/api/reset")
async def reset_queues_all(user: User = Depends(require_admin)):
    if not user.tenant_id: raise HTTPException(403)
    q, c, h = get_tenant_queues(user.tenant_id)
    q.clear(); c.clear(); h.clear(); return {"status": "reset ok"}

# ── Superadmin (Gestão de Planos e Unidades) ────────────────────────────────
@app.get("/api/super/plans")
def list_plans(db: Session = Depends(get_db), _: User = Depends(require_superadmin)): return db.query(Plan).all()

@app.post("/api/super/plans")
def create_plan(req: PlanCreate, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    p = Plan(name=req.name, max_guiches=req.max_guiches, max_users=req.max_users, max_types=req.max_types)
    db.add(p); db.commit(); db.refresh(p); return p

@app.put("/api/super/plans/{pid}")
def update_plan(pid: int, req: PlanUpdate, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    p = db.get(Plan, pid)
    if not p: raise HTTPException(404, "Plano não encontrado")
    if req.name is not None: p.name = req.name
    if req.max_guiches is not None: p.max_guiches = req.max_guiches
    if req.max_users is not None: p.max_users = req.max_users
    if req.max_types is not None: p.max_types = req.max_types
    if req.active is not None: p.active = req.active
    db.commit(); return p

@app.get("/api/super/tenants")
def super_list_tenants(db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    return db.query(Tenant).all()

@app.post("/api/super/tenants")
def super_create_tenant(req: TenantCreate, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    if db.query(Tenant).filter((Tenant.name == req.name) | (Tenant.slug == req.slug)).first(): raise HTTPException(400, "Unidade/Slug já existe")
    t = Tenant(name=req.name, slug=req.slug, plan_id=req.plan_id)
    db.add(t); db.commit(); db.refresh(t)
    
    # Seed tipos padrão para nova unidade
    db.add_all([
        TicketType(tenant_id=t.id, code="P", name="Preferencial", color="#00b87f", icon="fa-person-walking-with-cane", priority=10),
        TicketType(tenant_id=t.id, code="N", name="Normal", color="#4f6ef7", icon="fa-user", priority=5),
    ])
    db.add_all([
        Setting(tenant_id=t.id, key="system_name", value=t.name),
        Setting(tenant_id=t.id, key="system_subtitle", value="Seja bem-vindo"),
    ])
    db.commit()
    
    # Inicializa em memória
    get_tenant_queues(t.id)
    return t

@app.put("/api/super/tenants/{tid}")
def super_update_tenant(tid: int, req: TenantUpdate, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    t = db.get(Tenant, tid)
    if not t: raise HTTPException(404)
    if req.name is not None: t.name = req.name
    if req.plan_id is not None: t.plan_id = req.plan_id
    if req.active is not None: t.active = req.active
    db.commit(); return t

@app.get("/api/super/tenants/{tid}/users")
def super_list_tenant_users(tid: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    return db.query(User).filter(User.tenant_id == tid).all()

@app.put("/api/super/users/{uid}")
def super_update_user(uid: int, req: UserSuperUpdate, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    u = db.get(User, uid)
    if not u: raise HTTPException(404)
    if req.name is not None: u.name = req.name
    if req.username is not None: u.username = req.username
    if req.role is not None: u.role = req.role
    if req.active is not None: u.active = req.active
    if req.password: u.password_hash = pwd_context.hash(req.password)
    db.commit(); return {"id": u.id, "name": u.name, "status": "updated"}

# ── Reports ───────────────────────────────────────────────────────────────────
@app.get("/api/reports/summary")
def get_summary(start: str, end: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not user.tenant_id: raise HTTPException(403)
    tid = user.tenant_id
    calls = db.query(CallRecord).filter(CallRecord.tenant_id == tid, CallRecord.date_key >= start, CallRecord.date_key <= end).all()
    by_type = {}; by_guiche = {}; by_hour = {}; by_attendant = {}; by_weekday = {}
    weekdays = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    
    for c in calls:
        by_type[c.ticket_type_name] = by_type.get(c.ticket_type_name, 0) + 1
        by_guiche[c.guiche_name]   = by_guiche.get(c.guiche_name, 0) + 1
        by_attendant[c.user_name]  = by_attendant.get(c.user_name, 0) + 1
        
        h = str(c.called_at.hour); by_hour[h] = by_hour.get(h, 0) + 1
        wd = weekdays[c.called_at.weekday()]; by_weekday[wd] = by_weekday.get(wd, 0) + 1
        
    return {
        "total": len(calls), 
        "by_type": by_type, 
        "by_guiche": by_guiche, 
        "by_attendant": by_attendant,
        "by_hour": by_hour,
        "by_weekday": by_weekday
    }

@app.get("/api/reports/calls")
def get_calls_report(start: str, end: str, page: int = 1, size: int = 50, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not user.tenant_id: raise HTTPException(403)
    tid = user.tenant_id
    q = db.query(CallRecord).filter(CallRecord.tenant_id == tid, CallRecord.date_key >= start, CallRecord.date_key <= end).order_by(CallRecord.called_at.desc())
    total = q.count()
    items = q.offset((page-1)*size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "pages": (total + size - 1) // size,
        "data": [{"password": c.password, "type": c.ticket_type_name, "guiche": c.guiche_name, "user": c.user_name, "date": c.date_key, "time": c.called_at.strftime("%H:%M:%S")} for c in items]
    }

# ── Static Mappings ──────────────────────────────────────────────────────────
@app.get("/{slug}/panel")
def get_panel_slug(slug: str):
    return HTMLResponse(open("static/panel.html", encoding="utf-8").read())

@app.get("/{slug}/kiosk")
def get_kiosk_slug(slug: str):
    return HTMLResponse(open("static/kiosk.html", encoding="utf-8").read())

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def home(): return HTMLResponse("<script>window.location='/login'</script>")
@app.get("/login")    
def login_page():    return HTMLResponse(open("static/login.html", encoding="utf-8").read())
@app.get("/terminal") 
def terminal_page(): return HTMLResponse(open("static/terminal.html", encoding="utf-8").read())
@app.get("/admin")    
def admin_page():    return HTMLResponse(open("static/admin.html", encoding="utf-8").read())
@app.get("/superadmin")
def super_page():    return HTMLResponse(open("static/superadmin.html", encoding="utf-8").read())
@app.get("/reports")  
def report_page():   return HTMLResponse("<script>window.location='/admin'</script>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=9000)