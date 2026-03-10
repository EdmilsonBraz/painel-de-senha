from database import SessionLocal, User
from passlib.context import CryptContext

db = SessionLocal()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

user = db.query(User).filter(User.username == "totem").first()
if user:
    user.password_hash = pwd_context.hash("totem")
    user.role = "kiosk" # Ensure role is correct
    db.commit()
    print("User 'totem' updated with password 'totem' and role 'kiosk'")
else:
    print("User 'totem' not found")

db.close()
