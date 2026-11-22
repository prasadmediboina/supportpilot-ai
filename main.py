import os, re, io, secrets, datetime as dt
from urllib.parse import quote
import bcrypt, jwt, httpx
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session

E = os.getenv
DB = E("DATABASE_URL", "sqlite:///./supportpilot.db").replace("postgres://", "postgresql://")
SECRET = E("JWT_SECRET", "change-me")
ADMINS = {x.strip().lower() for x in E("ADMIN_EMAILS", "").split(",") if x.strip()}
PLANS = {"free": (1, 0), "starter": (1, 2000), "growth": (5, 5000), "business": (20, 10000)}  # (agents, INR/month)

engine = create_engine(DB, connect_args={"check_same_thread": False} if DB.startswith("sqlite") else {})
Session_ = sessionmaker(bind=engine)
Base = declarative_base()
now = lambda: dt.datetime.utcnow()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True); email = Column(String, unique=True, index=True)
    pw = Column(String); biz = Column(String); plan = Column(String, default="free")
    plan_until = Column(DateTime, nullable=True)
    reset = Column(String, nullable=True); reset_exp = Column(DateTime, nullable=True)
class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True); owner = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String); tone = Column(String, default="")
class Doc(Base):
    __tablename__ = "docs"
    id = Column(Integer, primary_key=True); owner = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String); text = Column(Text)
class Convo(Base):
    __tablename__ = "convos"
    id = Column(Integer, primary_key=True); owner = Column(Integer, index=True); agent = Column(Integer)
    q = Column(Text); a = Column(Text); ok = Column(Boolean); t = Column(DateTime, default=now)
class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True); owner = Column(Integer, index=True); plan = Column(String)
    amount = Column(Integer); utr = Column(String, unique=True); status = Column(String, default="pending")
    t = Column(DateTime, default=now)
Base.metadata.create_all(engine)

app = FastAPI(title="SupportPilot AI API")
app.add_middleware(CORSMiddleware, allow_origins=[E("FRONTEND_ORIGIN", "*")], allow_methods=["*"], allow_headers=["*"])
bearer = HTTPBearer(auto_error=False)

def db():
    s = Session_()
    try: yield s
    finally: s.close()

def user(c: HTTPAuthorizationCredentials = Depends(bearer), s: Session = Depends(db)) -> User:
    try:
        u = s.get(User, int(jwt.decode(c.credentials, SECRET, algorithms=["HS256"])["sub"]))
    except Exception:
        u = None
    if not u: raise HTTPException(401, "Please log in again.")
    return u

def admin(u: User = Depends(user)):
    if u.email not in ADMINS: raise HTTPException(403, "Admins only.")
    return u

def token(u): return jwt.encode({"sub": str(u.id), "exp": now() + dt.timedelta(days=7)}, SECRET, "HS256")
def pub(u): return {"email": u.email, "biz": u.biz, "plan": active_plan(u), "plan_until": (u.plan_until.isoformat() + "Z") if u.plan_until else None, "is_admin": u.email in ADMINS}
def active_plan(u):  # drop to free when a paid month has lapsed
    return u.plan if u.plan == "free" or (u.plan_until and u.plan_until > now()) else "free"

class Reg(BaseModel): biz: str; email: str; password: str
class Login(BaseModel): email: str; password: str
class Forgot(BaseModel): email: str
class Reset(BaseModel): token: str; password: str
class AgentIn(BaseModel): name: str; tone: str = ""
class Chat(BaseModel): agent_id: int; q: str
class Pay(BaseModel): plan: str; utr: str

# ---------- auth ----------
@app.post("/auth/register")
def register(b: Reg, s: Session = Depends(db)):
    em = b.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em): raise HTTPException(422, "Enter a valid email.")
    if len(b.password) < 8: raise HTTPException(422, "Password needs at least 8 characters.")
    if s.query(User).filter_by(email=em).first(): raise HTTPException(409, "An account with this email already exists.")
    u = User(email=em, biz=b.biz.strip(), pw=bcrypt.hashpw(b.password.encode(), bcrypt.gensalt()).decode())
    s.add(u); s.commit()
    return {"token": token(u), "user": pub(u)}

@app.post("/auth/login")
def login(b: Login, s: Session = Depends(db)):
    u = s.query(User).filter_by(email=b.email.strip().lower()).first()
    if not u or not bcrypt.checkpw(b.password.encode(), u.pw.encode()): raise HTTPException(401, "Email or password is incorrect.")
    return {"token": token(u), "user": pub(u)}

@app.post("/auth/forgot")
def forgot(b: Forgot, s: Session = Depends(db)):
    u = s.query(User).filter_by(email=b.email.strip().lower()).first()
    if u:
        u.reset, u.reset_exp = secrets.token_urlsafe(32), now() + dt.timedelta(hours=1); s.commit()
        print(f"[RESET LINK for {u.email}] {E('SITE_URL','http://localhost:8000')}/#reset?token={u.reset}")  # replace with SMTP email
    return {"ok": True}  # same reply whether or not the account exists

@app.post("/auth/reset")
def reset(b: Reset, s: Session = Depends(db)):
    u = s.query(User).filter_by(reset=b.token).first()
    if not u or u.reset_exp < now() or len(b.password) < 8: raise HTTPException(400, "This reset link is invalid or has expired.")
    u.pw, u.reset = bcrypt.hashpw(b.password.encode(), bcrypt.gensalt()).decode(), None; s.commit()
    return {"ok": True}

@app.get("/me")
def me(u: User = Depends(user)): return pub(u) | {"effective_plan": active_plan(u)}

# ---------- agents & knowledge ----------
@app.get("/agents")
def agents(u: User = Depends(user), s: Session = Depends(db)):
    return [{"id": a.id, "name": a.name, "tone": a.tone} for a in s.query(Agent).filter_by(owner=u.id)]

@app.post("/agents")
def new_agent(b: AgentIn, u: User = Depends(user), s: Session = Depends(db)):
    limit = PLANS[active_plan(u)][0]
    if s.query(Agent).filter_by(owner=u.id).count() >= limit:
        raise HTTPException(402, f"Your plan allows {limit} agent(s). Upgrade to add more.")
    a = Agent(owner=u.id, name=b.name, tone=b.tone); s.add(a); s.commit()
    return {"id": a.id, "name": a.name, "tone": a.tone}

@app.delete("/agents/{i}")
def del_agent(i: int, u: User = Depends(user), s: Session = Depends(db)):
    s.query(Agent).filter_by(id=i, owner=u.id).delete(); s.commit(); return {"ok": True}

@app.get("/docs-list")
def docs(u: User = Depends(user), s: Session = Depends(db)):
    return [{"id": d.id, "name": d.name, "chars": len(d.text)} for d in s.query(Doc).filter_by(owner=u.id)]

@app.post("/docs")
async def upload(f: UploadFile = File(...), u: User = Depends(user), s: Session = Depends(db)):
    raw, n = await f.read(), f.filename.lower()
    if len(raw) > 5_000_000: raise HTTPException(413, "File is larger than 5 MB.")
    if n.endswith(".pdf"):
        from pypdf import PdfReader; text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
    elif n.endswith(".docx"):
        import docx; text = "\n".join(p.text for p in docx.Document(io.BytesIO(raw)).paragraphs)
    elif n.endswith((".txt", ".md", ".csv")): text = raw.decode("utf-8", "ignore")
    else: raise HTTPException(415, "Upload a PDF, DOCX or TXT file.")
    if not text.strip(): raise HTTPException(422, "No readable text found in this file.")
    d = Doc(owner=u.id, name=f.filename, text=text); s.add(d); s.commit()
    return {"id": d.id, "name": d.name}

@app.delete("/docs/{i}")
def del_doc(i: int, u: User = Depends(user), s: Session = Depends(db)):
    s.query(Doc).filter_by(id=i, owner=u.id).delete(); s.commit(); return {"ok": True}

# ---------- answering ----------
STOP = set("the a an is are what do you i to of for and in on at can how my your it me we with does when".split())
tk = lambda t: [w for w in re.findall(r"[a-z0-9₹]+", t.lower()) if w not in STOP]

def retrieve(q, docs, k=3):
    qt, hits = set(tk(q)), []
    for d in docs:
        for c in re.split(r"(?<=[.!?])\s+|\n+", d.text):
            sc = sum(w in qt for w in tk(c))
            if sc and c.strip(): hits.append((sc, c.strip()))
    return [c for _, c in sorted(hits, reverse=True)[:k]]

def respond(s, a: Agent, q: str):
    ctx = retrieve(q, s.query(Doc).filter_by(owner=a.owner).all())
    if not ctx: ans, ok = "I'm not sure about that, so I've passed it to our team.", False
    else:
        ok, ans, key = True, " ".join(ctx[:1]), E("GROQ_API_KEY")
        if key:  # optional: let an LLM phrase the answer, strictly from the retrieved text
            try:
                r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": "Bearer " + key}, timeout=20,
                    json={"model": E("GROQ_MODEL", "llama-3.1-8b-instant"), "messages": [
                        {"role": "system", "content": f"You are a customer support agent. Tone: {a.tone or 'friendly'}. Answer ONLY from the context. If the answer is missing, say you will pass it to the team.\n\nContext:\n" + "\n".join(ctx)},
                        {"role": "user", "content": q}]})
                ans = r.json()["choices"][0]["message"]["content"]
            except Exception: pass
    s.add(Convo(owner=a.owner, agent=a.id, q=q[:2000], a=ans, ok=ok)); s.commit()
    return {"answer": ans, "answered": ok}

@app.post("/chat")
def chat(b: Chat, u: User = Depends(user), s: Session = Depends(db)):
    a = s.query(Agent).filter_by(id=b.agent_id, owner=u.id).first()
    if not a: raise HTTPException(404, "Agent not found.")
    return respond(s, a, b.q)

@app.post("/public/chat")  # used by the website widget; no login, add rate limiting before launch
def public_chat(b: Chat, s: Session = Depends(db)):
    a = s.get(Agent, b.agent_id)
    if not a: raise HTTPException(404, "Agent not found.")
    return respond(s, a, b.q)

@app.get("/conversations")
def convos(u: User = Depends(user), s: Session = Depends(db)):
    return [{"t": c.t, "agent": c.agent, "q": c.q, "a": c.a, "ok": c.ok} for c in s.query(Convo).filter_by(owner=u.id).order_by(Convo.id.desc()).limit(200)]

@app.get("/stats")
def stats(u: User = Depends(user), s: Session = Depends(db)):
    cs = s.query(Convo).filter_by(owner=u.id).all()
    return {"conversations": len(cs), "answered_pct": round(100 * sum(c.ok for c in cs) / len(cs)) if cs else 0,
            "agents": s.query(Agent).filter_by(owner=u.id).count(), "docs": s.query(Doc).filter_by(owner=u.id).count()}

# ---------- billing (UPI QR to your own account) ----------
@app.get("/billing/upi")
def upi(plan: str, u: User = Depends(user)):
    if plan not in PLANS or plan == "free": raise HTTPException(422, "Unknown plan.")
    amt = PLANS[plan][1]
    if not E("UPI_ID"): raise HTTPException(503, "Payments are not set up yet. The owner needs to set UPI_ID.")
    link = f"upi://pay?pa={E('UPI_ID','')}&pn={quote(E('PAYEE_NAME','SupportPilot AI'))}&am={amt}&cu=INR&tn={quote('SupportPilot ' + plan)}"
    return {"upi_link": link, "amount": amt, "payee": E("PAYEE_NAME", "SupportPilot AI")}  # render upi_link as a QR code in the frontend

@app.post("/billing/submit")
def submit(b: Pay, u: User = Depends(user), s: Session = Depends(db)):
    if b.plan not in PLANS or b.plan == "free": raise HTTPException(422, "Unknown plan.")
    if not re.fullmatch(r"\d{12}", b.utr.strip()): raise HTTPException(422, "Enter the 12-digit UPI reference (UTR) from your payment app.")
    if s.query(Payment).filter_by(utr=b.utr.strip()).first(): raise HTTPException(409, "This reference was already submitted.")
    s.add(Payment(owner=u.id, plan=b.plan, amount=PLANS[b.plan][1], utr=b.utr.strip())); s.commit()
    return {"status": "pending", "message": "We'll confirm your payment and activate your plan."}

@app.get("/admin/payments")
def pending(a: User = Depends(admin), s: Session = Depends(db)):
    return [{"id": p.id, "email": getattr(s.get(User, p.owner), "email", "?"), "owner": p.owner, "plan": p.plan, "amount": p.amount, "utr": p.utr, "status": p.status, "t": p.t} for p in s.query(Payment).order_by(Payment.id.desc())]

@app.post("/admin/payments/{pid}/approve")  # check the UTR and amount in your bank app first
def approve(pid: int, a: User = Depends(admin), s: Session = Depends(db)):
    p = s.get(Payment, pid)
    if not p or p.status != "pending": raise HTTPException(404, "No pending payment with this id.")
    u = s.get(User, p.owner); p.status, u.plan = "approved", p.plan
    u.plan_until = max(u.plan_until or now(), now()) + dt.timedelta(days=30); s.commit()
    return {"ok": True}

@app.post("/admin/payments/{pid}/reject")
def reject(pid: int, a: User = Depends(admin), s: Session = Depends(db)):
    p = s.get(Payment, pid)
    if p: p.status = "rejected"; s.commit()
    return {"ok": True}

@app.get("/admin/users")
def users(a: User = Depends(admin), s: Session = Depends(db)):
    return [pub(u) | {"id": u.id} for u in s.query(User).all()]

@app.get("/billing/mine")
def mine(u: User = Depends(user), s: Session = Depends(db)):
    return [{"plan": p.plan, "amount": p.amount, "utr": p.utr, "status": p.status} for p in s.query(Payment).filter_by(owner=u.id).order_by(Payment.id.desc())]

@app.get("/health")
def health(): return {"ok": True}

# serves the website and widget from the same service (keep this last)
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="site")
