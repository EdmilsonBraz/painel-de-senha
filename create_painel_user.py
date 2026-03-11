from database import SessionLocal, User, Tenant, Plan
from passlib.context import CryptContext

db = SessionLocal()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Tenant (get matrix or create test)
tenant = db.query(Tenant).filter(Tenant.slug == "matriz").first()
if not tenant:
    tenant = db.query(Tenant).first()

if not tenant:
    print("ERRO: Nenhum tenant encontrado para associar o usuário.")
else:
    # Painel User
    user = db.query(User).filter(User.username == "painel").first()
    if not user:
        user = User(
            username="painel",
            password_hash=pwd_context.hash("123"),
            name="Painel de Chamada",
            role="painel",
            tenant_id=tenant.id
        )
        db.add(user)
        db.commit()
        print(f"Usuário 'painel' criado com senha '123' na unidade '{tenant.name}'")
    else:
        print("Usuário 'painel' já existe")

db.close()
