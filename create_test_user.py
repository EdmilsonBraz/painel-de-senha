from database import SessionLocal, User, Tenant, Plan, TicketType
from passlib.context import CryptContext

db = SessionLocal()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Plan
plan = db.query(Plan).first()
if not plan:
    plan = Plan(name="Basic", max_guiches=5, max_users=5, max_types=5)
    db.add(plan)
    db.commit()

# Tenant
tenant = db.query(Tenant).filter(Tenant.slug == "test").first()
if not tenant:
    tenant = Tenant(name="Test Unit", slug="test", plan_id=plan.id)
    db.add(tenant)
    db.commit()

# Kiosk User
user = db.query(User).filter(User.username == "totem").first()
if not user:
    user = User(
        username="totem",
        password_hash=pwd_context.hash("123"),
        name="Totem User",
        role="kiosk",
        tenant_id=tenant.id
    )
    db.add(user)
    db.commit()
    print("User 'totem' created with password '123'")
else:
    print("User 'totem' already exists")

db.close()
