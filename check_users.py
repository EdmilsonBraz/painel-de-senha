from database import SessionLocal, User
db = SessionLocal()
users = db.query(User).all()
for u in users:
    print(f"Username: {u.username}, Role: {u.role}")
db.close()
