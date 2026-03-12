from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from passlib.context import CryptContext

import os
if not os.path.exists("./data"): os.makedirs("./data", exist_ok=True)
DATABASE_URL = "sqlite:///./data/painel.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Plan(Base):
    __tablename__ = "plans"
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(50), unique=True, nullable=False)
    max_guiches = Column(Integer, default=5)
    max_users   = Column(Integer, default=10)
    max_types   = Column(Integer, default=4)
    active      = Column(Boolean, default=True)

    tenants = relationship("Tenant", back_populates="plan")


class Tenant(Base):
    __tablename__ = "tenants"
    id          = Column(Integer, primary_key=True, index=True)
    plan_id     = Column(Integer, ForeignKey("plans.id"), nullable=True)
    name        = Column(String(100), unique=True, nullable=False)
    slug        = Column(String(50), unique=True, nullable=False, index=True)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.now)

    # Cache de limites do plano (Opcional, mas vamos usar o relacionamento)
    primary_color   = Column(String(20), default="#3b82f6")
    secondary_color = Column(String(20), default="#00d1ff")
    bg_color        = Column(String(20), default="#0c0f16")
    logo_url        = Column(String(500), nullable=True)
    
    plan         = relationship("Plan", back_populates="tenants")
    users        = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    ticket_types = relationship("TicketType", back_populates="tenant", cascade="all, delete-orphan")
    guiches      = relationship("Guiche", back_populates="tenant", cascade="all, delete-orphan")
    settings     = relationship("Setting", back_populates="tenant", cascade="all, delete-orphan")
    calls        = relationship("CallRecord", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, index=True)
    tenant_id     = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    username      = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    name          = Column(String(100), nullable=False)
    role          = Column(String(20), default="operator")   # superadmin | admin | operator | kiosk | painel
    active        = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.now)

    tenant = relationship("Tenant", back_populates="users")


class TicketType(Base):
    __tablename__ = "ticket_types"
    id        = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    code      = Column(String(20), nullable=False)
    name      = Column(String(100), nullable=False)
    color     = Column(String(20), default="#4f6ef7")
    icon      = Column(String(50), default="fa-ticket")
    priority  = Column(Integer, default=0)
    priority_guiches = Column(String(200), nullable=True) # Lista de nomes de guichês separados por vírgula
    active    = Column(Boolean, default=True)

    tenant = relationship("Tenant", back_populates="ticket_types")


class Guiche(Base):
    __tablename__ = "guiches"
    id        = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name      = Column(String(100), nullable=False)
    active    = Column(Boolean, default=True)

    tenant = relationship("Tenant", back_populates="guiches")


class Setting(Base):
    __tablename__ = "settings"
    tenant_id = Column(Integer, ForeignKey("tenants.id"), primary_key=True)
    key       = Column(String(50), primary_key=True)
    value     = Column(String(500), default="")

    tenant = relationship("Tenant", back_populates="settings")


class CallRecord(Base):
    __tablename__ = "calls"
    id               = Column(Integer, primary_key=True, index=True)
    tenant_id        = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    password         = Column(String(10), nullable=False)
    ticket_type_code = Column(String(20), nullable=False)
    ticket_type_name = Column(String(100), nullable=False)
    guiche_name      = Column(String(100), nullable=False)
    user_name        = Column(String(100), nullable=False)
    called_at        = Column(DateTime, default=datetime.now, index=True)
    date_key         = Column(String(10), nullable=False, index=True)

    tenant = relationship("Tenant", back_populates="calls")


def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()


def init_db(db):
    Base.metadata.create_all(bind=engine)
    
    # Planos Iniciais
    if not db.query(Plan).first():
        p1 = Plan(name="Básico", max_guiches=2, max_users=3, max_types=2)
        p2 = Plan(name="Pro", max_guiches=10, max_users=20, max_types=8)
        p3 = Plan(name="Unlimited", max_guiches=999, max_users=999, max_types=99)
        db.add_all([p1, p2, p3])
        db.commit()

    # Superadmin global
    if not db.query(User).filter(User.role == "superadmin").first():
        db.add(User(
            username="superadmin",
            password_hash=pwd_context.hash("super123"),
            name="Super Administrador",
            role="superadmin",
            tenant_id=None
        ))
        db.commit()

    # Tenant Padrão
    if not db.query(Tenant).first():
        basic_plan = db.query(Plan).filter(Plan.name == "Básico").first()
        default_tenant = Tenant(name="Matriz", slug="matriz", plan_id=basic_plan.id)
        db.add(default_tenant)
        db.commit()
        db.refresh(default_tenant)

        db.add(User(
            username="admin", password_hash=pwd_context.hash("admin123"),
            name="Admin Matriz", role="admin", tenant_id=default_tenant.id
        ))
        db.add_all([
            TicketType(tenant_id=default_tenant.id, code="P", name="Preferencial", color="#00b87f", icon="fa-person-walking-with-cane", priority=10),
            TicketType(tenant_id=default_tenant.id, code="N", name="Normal", color="#4f6ef7", icon="fa-user", priority=5),
        ])
        db.add(Guiche(tenant_id=default_tenant.id, name="Guichê 01"))
        db.add_all([
            Setting(tenant_id=default_tenant.id, key="system_name", value="Atendimento Matriz"),
            Setting(tenant_id=default_tenant.id, key="system_subtitle", value="Seja bem-vindo"),
        ])
        db.commit()
