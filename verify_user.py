from database import SessionLocal, User
db = SessionLocal()
u = db.query(User).filter(User.username == "totem").first()
if u:
    print(f"User: {u.username}, Role: {u.role}")
else:
    print("User not found")
db.close()
