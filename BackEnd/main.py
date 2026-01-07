import uuid
import time
import shutil
import os
import json
import logging
import traceback
from datetime import datetime, timedelta
from typing import Optional
from pydantic import Field
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Request, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from logging.handlers import RotatingFileHandler

# Import local modules
from auth import get_password_hash, verify_password, create_access_token, get_current_user
from mailer import send_contact_info_email, send_verification_code_email, get_email_config, save_email_config, reload_email_config
from models import FarmerCreate, BuyerCreate
import random

# ==========================================
# 1. Core Configuration and Logging
# ==========================================
# Key fix: Explicitly define all data file paths (fixed to root directory)
BASE_DIR = os.getcwd()
DB_USERS = os.path.join(BASE_DIR, "users.json")
DB_FARMERS = os.path.join(BASE_DIR, "farmers.json")
DB_BUYERS = os.path.join(BASE_DIR, "buyers.json")
DB_PROPOSALS = os.path.join(BASE_DIR, "proposals.json")
DB_NOTIFS = os.path.join(BASE_DIR, "notifications.json")
DB_REFS = os.path.join(BASE_DIR, "references.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

# Logging configuration
logger = logging.getLogger("cattle_app")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler("app.log", maxBytes=1024*1024, backupCount=1)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

ACCESS_TOKEN_EXPIRE_MINUTES = 60
app = FastAPI(title="Cattle Match System (Fixed Paths)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        error_msg = f"❌ Error: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        print(error_msg)
        return JSONResponse(status_code=500, content={"detail": "Server Error"})

# ==========================================
# 2. Unified Data Read/Write Utilities (Helper)
# ==========================================
# Completely replace db.py to prevent path confusion
def load_json(filepath):
    if not os.path.exists(filepath): return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except: return []

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def append_record(filepath, record):
    data = load_json(filepath)
    data.append(record)
    save_json(filepath, data)

# Notification helper
def save_notification(user_id, title, details=None):
    notif = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "message": title,
        "details": details or {},
        "timestamp": time.time(),
        "read": False
    }
    append_record(DB_NOTIFS, notif)

# Simple matching logic (replaces matcher.py to prevent path issues)
def simple_match(new_record, target_file, is_farmer):
    targets = load_json(target_file)
    count = 0
    for t in targets:
        # Simple matching: same breed + status open
        if t.get('race') == new_record.get('race') and t.get('status', 'OPEN') == 'OPEN':
            count += 1
            # Send notification to the other party
            target_user = t.get('owner_id')
            if target_user:
                role = "Farmer" if is_farmer else "Buyer"
                save_notification(target_user, f"New Match: {role} posted {new_record.get('race')}", new_record)
    return count

# ==========================================
# 3. Two-Factor Authentication Storage (In-memory storage with expiration)
# ==========================================
verification_codes = {}  # {username: {"code": "123456", "expires_at": timestamp}}
verified_users = {}  # {username: {"verified_at": timestamp}} - 5 minutes grace period

def generate_verification_code():
    """Generate 6-digit verification code"""
    return str(random.randint(100000, 999999))

def store_verification_code(username: str, code: str):
    """Store verification code, expires in 10 minutes"""
    expires_at = time.time() + 600  # Expires in 10 minutes
    verification_codes[username] = {
        "code": code,
        "expires_at": expires_at
    }

def verify_code(username: str, code: str) -> bool:
    """Verify verification code"""
    if username not in verification_codes:
        return False
    
    stored = verification_codes[username]
    
    # Check if expired
    if time.time() > stored["expires_at"]:
        del verification_codes[username]
        return False
    
    # Verify code match
    if stored["code"] == code:
        # Delete verification code after successful verification (one-time use)
        del verification_codes[username]
        # Store verification timestamp for 5-minute grace period
        verified_users[username] = {"verified_at": time.time()}
        return True
    
    return False

def is_recently_verified(username: str) -> bool:
    """Check if user was verified within the last 5 minutes"""
    if username not in verified_users:
        return False
    
    verified_at = verified_users[username]["verified_at"]
    # 5 minutes = 300 seconds
    if time.time() - verified_at < 300:
        return True
    
    # Expired, remove from cache
    del verified_users[username]
    return False

# ==========================================
# 4. Dependencies and Models
# ==========================================
def get_current_admin(current_user: str = Depends(get_current_user)):
    users = load_json(DB_USERS)
    user = next((u for u in users if u['username'] == current_user), None)
    if not user or user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin required")
    return user

class UserRegister(BaseModel):
    username: str
    password: str
    email: str
    first_name: str
    last_name: str
    phone: str
    address: str
    tax_id: Optional[str] = None
    ie: Optional[str] = None
    role: Optional[str] = "user"

class Proposal(BaseModel):
    supply_id: str
    price_offer: float
    message: Optional[str] = ""
    # New fields for enhanced proposals
    loading_date: Optional[str] = None  # ISO date string
    conditions: Optional[str] = None    # Specific conditions for the purchase
    price_per_unit: Optional[float] = None  # Price per arroba (@) for live weight transactions

class CustomCity(BaseModel):
    state: str
    name: str

# ==========================================
# 5. Auth Endpoints
# ==========================================
@app.post("/auth/register")
def register(user: UserRegister):
    users = load_json(DB_USERS)
    if any(u['username'] == user.username for u in users):
        raise HTTPException(status_code=400, detail="Username taken")

    new_user = user.dict()
    new_user['password'] = get_password_hash(user.password)
    new_user['created_at'] = time.time()
    new_user['is_active'] = True

    append_record(DB_USERS, new_user)
    return {"msg": "Created"}

@app.post("/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    users = load_json(DB_USERS)
    user = next((u for u in users if u['username'] == form_data.username), None)

    if not user or not verify_password(form_data.password, user['password']):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status_code=400, detail="Account disabled")

    token = create_access_token(data={"sub": user['username']}, expires_delta=timedelta(minutes=60))
    return {"access_token": token, "token_type": "bearer", "role": user.get("role", "user"), "username": user['username']}

# ==========================================
# 6. File and Basic Endpoints
# ==========================================
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), user: str = Depends(get_current_user)):
    ext = file.filename.split(".")[-1]
    name = f"{uuid.uuid4()}.{ext}"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as b:
        shutil.copyfileobj(file.file, b)
    return {"filename": name}

@app.get("/api/files/{filename}")
def get_file(filename: str):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path): raise HTTPException(404)
    return FileResponse(path)

@app.get("/api/market")
def get_market():
    # Market only shows Supply (Farmers)
    farmers = load_json(DB_FARMERS)
    active = [f for f in farmers if f.get('status', 'OPEN') == 'OPEN']
    active.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    return {"supply": active}

# ==========================================
# 7. User Business Endpoints (Listings)
# ==========================================
@app.post("/api/farmer")
def create_farmer(data: FarmerCreate, user: str = Depends(get_current_user)):
    rec = data.dict()
    rec.update({"id": str(uuid.uuid4()), "timestamp": time.time(), "owner_id": user, "status": "OPEN"})
    append_record(DB_FARMERS, rec)
    # Simple match notification
    count = simple_match(rec, DB_BUYERS, True)
    return {"id": rec['id'], "matches": count}

@app.post("/api/buyer")
def create_buyer(data: BuyerCreate, user: str = Depends(get_current_user)):
    rec = data.dict()
    rec.update({"id": str(uuid.uuid4()), "timestamp": time.time(), "owner_id": user})
    append_record(DB_BUYERS, rec)
    count = simple_match(rec, DB_FARMERS, False)
    return {"id": rec['id'], "matches": count}

@app.get("/api/my-listings")
def get_my_listings(user: str = Depends(get_current_user)):
    farmers = load_json(DB_FARMERS)
    buyers = load_json(DB_BUYERS)
    return {
        "supply": sorted([f for f in farmers if f.get('owner_id') == user], key=lambda x: x.get('timestamp', 0), reverse=True),
        "demand": sorted([b for b in buyers if b.get('owner_id') == user], key=lambda x: x.get('timestamp', 0), reverse=True)
    }

@app.get("/api/notifications")
def get_notifs(user: str = Depends(get_current_user)):
    notifs = load_json(DB_NOTIFS)
    return sorted([n for n in notifs if n['user_id'] == user], key=lambda x: x.get('timestamp', 0), reverse=True)

# ==========================================
# 8. Proposals and Transactions (Proposals) - Key Fixes
# ==========================================
@app.post("/api/proposals")
def create_proposal(prop: Proposal, user: str = Depends(get_current_user)):
    # Check Supply
    farmers = load_json(DB_FARMERS)
    supply = next((f for f in farmers if f['id'] == prop.supply_id), None)

    if not supply: raise HTTPException(404, "Supply not found")
    if supply.get('status') != 'OPEN': raise HTTPException(400, "Listing not open")

    # Check user role
    users = load_json(DB_USERS)
    u_data = next((u for u in users if u['username'] == user), {})
    if u_data.get('role') == 'farmer': raise HTTPException(400, "Farmers cannot buy")

    new_prop = {
        "id": str(uuid.uuid4()),
        "supply_id": prop.supply_id,
        "buyer_id": user,
        "buyer_contact": u_data.get('phone', 'Unknown'),
        "price_offer": prop.price_offer,
        "message": prop.message,
        "loading_date": prop.loading_date,
        "conditions": prop.conditions,
        "price_per_unit": prop.price_per_unit,
        "status": "PENDING",
        "timestamp": time.time()
    }

    append_record(DB_PROPOSALS, new_prop)

    # Send notification to Farmer
    save_notification(supply['owner_id'], f"New Offer: R$ {prop.price_offer}", new_prop)

    return {"msg": "Sent", "id": new_prop['id']}

@app.get("/api/my-proposals")
def get_received_proposals(user: str = Depends(get_current_user)):
    # I am Farmer, view proposals sent to me
    farmers = load_json(DB_FARMERS)
    proposals = load_json(DB_PROPOSALS)

    my_supply_ids = [f['id'] for f in farmers if f.get('owner_id') == user]
    received = [p for p in proposals if p['supply_id'] in my_supply_ids]

    # Fill supply details (consistent with sent proposals)
    for p in received:
        supply = next((f for f in farmers if f['id'] == p['supply_id']), None)
        if supply:
            p['supply_detail'] = {
                "race": supply.get('race'),
                "qty": supply.get('quantity'),
                "quantity": supply.get('quantity'),
                "location": f"{supply.get('city')}, {supply.get('state')}",
                "city": supply.get('city'),
                "state": supply.get('state'),
                "photo": supply.get('cattle_photo'),
                "age": supply.get('age'),
                "weight": supply.get('estimated_weight'),
                "weight_type": supply.get('weight_type', 'live'),
                "category": supply.get('category')
            }

    return sorted(received, key=lambda x: x.get('timestamp', 0), reverse=True)

@app.get("/api/my-sent-proposals")
def get_sent_proposals(user: str = Depends(get_current_user)):
    # I am Buyer, view proposals I sent
    proposals = load_json(DB_PROPOSALS)
    farmers = load_json(DB_FARMERS)

    sent = [p for p in proposals if p['buyer_id'] == user]

    # Fill details
    for p in sent:
        supply = next((f for f in farmers if f['id'] == p['supply_id']), None)
        if supply:
            p['supply_detail'] = {
                "race": supply.get('race'),
                "qty": supply.get('quantity'),
                "quantity": supply.get('quantity'),
                "location": f"{supply.get('city')}, {supply.get('state')}",
                "city": supply.get('city'),
                "state": supply.get('state'),
                "photo": supply.get('cattle_photo'),
                "age": supply.get('age'),
                "weight": supply.get('estimated_weight'),
                "weight_type": supply.get('weight_type', 'live'),
                "category": supply.get('category'),
                "nfe_file": supply.get('nfe_file'),
                "gta_file": supply.get('gta_file')
            }

    return sorted(sent, key=lambda x: x.get('timestamp', 0), reverse=True)

@app.post("/api/proposals/{pid}/{action}")
def handle_proposal(pid: str, action: str, user: str = Depends(get_current_user)):
    proposals = load_json(DB_PROPOSALS)
    prop = next((p for p in proposals if p['id'] == pid), None)
    if not prop: raise HTTPException(404, "Not found")

    # Verify permission: only seller can accept/reject proposals
    farmers = load_json(DB_FARMERS)
    supply = next((f for f in farmers if f['id'] == prop['supply_id']), None)
    if not supply:
        raise HTTPException(404, "Supply not found")
    
    # Only seller (supply owner) can accept or reject
    if supply.get('owner_id') != user:
        raise HTTPException(403, "Only the seller can accept or reject proposals")

    if action == 'reject':
        prop['status'] = 'REJECTED'
    elif action == 'accept':
        # Check if proposal has already been accepted
        if prop.get('status') != 'PENDING':
            raise HTTPException(400, "Proposal is not in PENDING status")
        
        prop['status'] = 'ACCEPTED'
        # Lock Supply
        supply['status'] = 'AWAITING_PAYMENT'
        supply['buyer_id'] = prop['buyer_id']
        save_json(DB_FARMERS, farmers) # Save status

        # 通知买家
        save_notification(prop['buyer_id'], "Offer Accepted! Pay reservation deposit to lock the deal.", prop)

    save_json(DB_PROPOSALS, proposals)
    return {"msg": "Updated"}

@app.post("/api/pay-reservation/{pid}")
def pay_fee(pid: str, user: str = Depends(get_current_user)):
    """Simulated reservation deposit payment"""
    proposals = load_json(DB_PROPOSALS)
    prop = next((p for p in proposals if p['id'] == pid), None)

    if not prop or prop['buyer_id'] != user: raise HTTPException(403)
    if prop.get('status') != 'ACCEPTED': raise HTTPException(400, "Proposal must be accepted first")

    farmers = load_json(DB_FARMERS)
    supply = next((f for f in farmers if f['id'] == prop['supply_id']), None)

    if not supply: raise HTTPException(404)

    # Status transition
    supply['status'] = 'RESERVED'  # Changed from 'SOLD' to 'RESERVED'
    prop['status'] = 'PAID'
    prop['deposit_paid_at'] = time.time()
    prop['deposit_amount'] = 100.0  # Simulated deposit amount

    save_json(DB_FARMERS, farmers)
    save_json(DB_PROPOSALS, proposals)

    # 通知卖家
    save_notification(supply['owner_id'], "Reservation deposit received! You can now start weighing.", {
        "listing_id": prop['supply_id'],
        "proposal_id": pid,
        "next_action": "Start weighing"
    })

    return {
        "msg": "Deposit paid", 
        "deposit_amount": 100.0, 
        "status": "RESERVED",
        "listing_id": prop['supply_id']
    }

# ==========================================
# 9. Admin & System
# ==========================================
def get_refs():
    if not os.path.exists(DB_REFS):
        save_json(DB_REFS, {"breeds": ["Nelore", "Angus"], "custom_cities": []})
    return load_json(DB_REFS)

@app.get("/api/system/references")
def sys_refs(): return get_refs()

@app.post("/api/admin/breed")
def add_breed(name: str, admin: dict = Depends(get_current_admin)):
    refs = get_refs()
    if name not in refs["breeds"]:
        refs["breeds"].append(name)
        refs["breeds"].sort()
        save_json(DB_REFS, refs)
    return {"msg": "Added"}

@app.delete("/api/admin/breed/{name}")
def del_breed(name: str, admin: dict = Depends(get_current_admin)):
    refs = get_refs()
    refs["breeds"] = [b for b in refs["breeds"] if b != name]
    save_json(DB_REFS, refs)
    return {"msg": "Deleted"}

@app.post("/api/admin/location/city")
def add_city(city: CustomCity, admin: dict = Depends(get_current_admin)):
    refs = get_refs()
    refs['custom_cities'].append(city.dict())
    save_json(DB_REFS, refs)
    return {"msg": "Added"}

@app.delete("/api/admin/location/city/{s}/{n}")
def del_city(s: str, n: str, admin: dict = Depends(get_current_admin)):
    refs = get_refs()
    refs['custom_cities'] = [c for c in refs['custom_cities'] if not (c['state'] == s and c['name'] == n)]
    save_json(DB_REFS, refs)
    return {"msg": "Deleted"}

@app.get("/api/admin/stats")
def admin_stats(admin: dict = Depends(get_current_admin)):
    return {
        "total_users": len(load_json(DB_USERS)),
        "total_supply": len(load_json(DB_FARMERS)),
        "total_demand": len(load_json(DB_BUYERS)),
        "recent_activity": [] # Simplified
    }

@app.get("/api/admin/users")
def admin_users(admin: dict = Depends(get_current_admin)):
    return [{k:v for k,v in u.items() if k!='password'} for u in load_json(DB_USERS)]

@app.patch("/api/admin/user/{username}/toggle-status")
def toggle_status(username: str, admin: dict = Depends(get_current_admin)):
    users = load_json(DB_USERS)
    for u in users:
        if u['username'] == username:
            u['is_active'] = not u.get('is_active', True)
            save_json(DB_USERS, users)
            return {"msg": "Toggled"}
    raise HTTPException(404)

@app.delete("/api/admin/user/{username}")
def del_user(username: str, admin: dict = Depends(get_current_admin)):
    users = load_json(DB_USERS)
    users = [u for u in users if u['username'] != username]
    save_json(DB_USERS, users)
    return {"msg": "Deleted"}

@app.get("/api/admin/listings")
def admin_list(admin: dict = Depends(get_current_admin)):
    return {"supply": load_json(DB_FARMERS), "demand": load_json(DB_BUYERS)}

@app.delete("/api/admin/listing/{ltype}/{lid}")
def del_listing(ltype: str, lid: str, admin: dict = Depends(get_current_admin)):
    fname = DB_FARMERS if ltype == 'supply' else DB_BUYERS
    data = load_json(fname)
    data = [i for i in data if i['id'] != lid]
    save_json(fname, data)
    return {"msg": "Deleted"}

@app.get("/api/admin/logs")
def admin_logs(admin: dict = Depends(get_current_admin)):
    if os.path.exists("app.log"):
        with open("app.log", "r") as f: return {"logs": f.readlines()[-100:]}
    return {"logs": []}

@app.delete("/api/admin/logs")
def clear_logs(admin: dict = Depends(get_current_admin)):
    open("app.log", "w").close()
    return {"msg": "Cleared"}

# ==========================================
# Two-Factor Authentication Endpoints
# ==========================================

class VerifyCodeRequest(BaseModel):
    code: str

@app.post("/api/2fa/send-code")
def send_2fa_code(current_user: str = Depends(get_current_user)):
    """
    Send two-factor authentication code to user's email
    """
    users = load_json(DB_USERS)
    user = next((u for u in users if u['username'] == current_user), None)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    email = user.get('email')
    if not email:
        raise HTTPException(status_code=400, detail="User email not found")
    
    # Generate verification code
    code = generate_verification_code()
    
    # Store verification code
    store_verification_code(current_user, code)
    
    # Send email
    success = send_verification_code_email(email, code)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send verification code")
    
    return {"status": "success", "msg": "Verification code sent to your email"}

@app.post("/api/2fa/verify-code")
def verify_2fa_code(req: VerifyCodeRequest, current_user: str = Depends(get_current_user)):
    """
    Verify two-factor authentication code
    """
    if verify_code(current_user, req.code):
        return {"status": "success", "verified": True, "grace_period": 300}
    else:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

# ==========================================
# Email Configuration Management (Admin)
# ==========================================

class EmailConfigUpdate(BaseModel):
    smtp_server: str
    smtp_port: int
    smtp_login: str
    smtp_password: str
    sender_name: str

@app.get("/api/admin/email-config")
def get_email_config_api(admin: dict = Depends(get_current_admin)):
    """Get email configuration"""
    return get_email_config()

@app.post("/api/admin/email-config")
def update_email_config(config: EmailConfigUpdate, admin: dict = Depends(get_current_admin)):
    """Update email configuration"""
    # Validate port range
    if not (1 <= config.smtp_port <= 65535):
        raise HTTPException(status_code=400, detail="SMTP port must be between 1 and 65535")
    
    # Validate required fields
    if not config.smtp_server or not config.smtp_login:
        raise HTTPException(status_code=400, detail="SMTP server and login are required")
    
    # Save configuration
    config_dict = {
        "smtp_server": config.smtp_server,
        "smtp_port": config.smtp_port,
        "smtp_login": config.smtp_login,
        "smtp_password": config.smtp_password,
        "sender_name": config.sender_name
    }
    
    if save_email_config(config_dict):
        # Reload configuration
        reload_email_config()
        return {"status": "success", "msg": "Email configuration updated successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to save email configuration")

@app.post("/api/admin/email-config/test")
def test_email_config(config: EmailConfigUpdate, admin: dict = Depends(get_current_admin)):
    """Test email configuration (send test email)"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Get admin email
        users = load_json(DB_USERS)
        admin_user = next((u for u in users if u['username'] == admin['username']), None)
        
        if not admin_user or not admin_user.get('email'):
            raise HTTPException(status_code=400, detail="Admin email not found")
        
        test_email = admin_user['email']
        
        # Build test email
        msg = MIMEMultipart()
        msg['From'] = f"{config.sender_name} <{config.smtp_login}>"
        msg['To'] = test_email
        msg['Subject'] = "Test Email - Cattle Match System"
        
        html_content = f"""
        <html>
        <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
        <div style="background: #2c3e50; color: white; padding: 20px; text-align: center;">
        <h2 style="margin: 0;">Email Configuration Test</h2>
        </div>
        <div style="padding: 30px;">
        <p>Hello,</p>
        <p>This is a test email to verify your email configuration is working correctly.</p>
        <p style="font-size: 0.9em; color: #666;">
        If you received this email, your SMTP settings are configured properly.
        </p>
        </div>
        </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to server
        if config.smtp_port == 465:
            server = smtplib.SMTP_SSL(config.smtp_server, config.smtp_port)
        else:
            server = smtplib.SMTP(config.smtp_server, config.smtp_port)
            server.starttls()
        
        server.login(config.smtp_login, config.smtp_password)
        server.sendmail(config.smtp_login, test_email, msg.as_string())
        server.quit()
        
        return {"status": "success", "msg": "Test email sent successfully. Please check your inbox."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")

# ==========================================
# Add the following new features at the end of your existing main.py file
# ==========================================

# New: Weight entry model
class WeightEntry(BaseModel):
    batch_number: int
    quantity: int
    total_weight: float
    timestamp: Optional[str] = None

class InternalWeightRequest(BaseModel):
    perform_weighing: bool = False
    batch_number: Optional[int] = None
    quantity: Optional[int] = None
    total_weight: Optional[float] = None

class SlaughterhouseWeightData(BaseModel):
    final_weight: float
    yield_rate: Optional[float] = 0.52
    price_per_unit: float

class FinalPayment(BaseModel):
    nfe_document: Optional[str] = None  # Can be file name or document number
    gta_document: Optional[str] = None  # Can be file name or document number
    nfe_file: Optional[str] = None  # Uploaded file name
    gta_file: Optional[str] = None  # Uploaded file name
    transport_fee: Optional[float] = 0
    funrural_tax: Optional[float] = 0
    yield_rate: float = Field(ge=0.48, le=0.55, default=0.52)

# ==========================================
# Weight Management API (Live Weight Mode)
# ==========================================

@app.post("/api/listings/{listing_id}/weights")
def add_weight_entry(listing_id: str, weight: WeightEntry, user: str = Depends(get_current_user)):
    """Add weight entry (live weight mode)"""
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == listing_id), None)

    if not listing:
        raise HTTPException(404, "Listing not found")

    if listing.get('owner_id') != user:
        raise HTTPException(403, "Not authorized")

    # Check if it's live weight mode
    weight_type = listing.get('weight_type', 'live')
    if weight_type != 'live':
        raise HTTPException(400, "This listing is for dead weight. Use internal weight endpoint for reference only.")

    # Ensure listing supports weighing (proposal accepted and deposit paid)
    if listing.get('status') not in ['RESERVED', 'SOLD', 'AWAITING_PAYMENT']:
        raise HTTPException(400, "Listing must be reserved first")

    # Create weights data file path
    DB_WEIGHTS = os.path.join(BASE_DIR, "weights.json")
    weights = load_json(DB_WEIGHTS)

    # Add weight entry
    weight_data = weight.dict()
    weight_data['listing_id'] = listing_id
    if not weight_data.get('timestamp'):
        weight_data['timestamp'] = datetime.now().isoformat()

    weights.append(weight_data)
    save_json(DB_WEIGHTS, weights)

    # Check if all weighing is completed
    listing_weights = [w for w in weights if w['listing_id'] == listing_id]
    total_quantity = sum(w['quantity'] for w in listing_weights)

    if total_quantity >= listing.get('quantity', 0):
        # Notify farmer that weighing is completed
        save_notification(user, f"Weighing completed for listing #{listing_id}", {
            "listing_id": listing_id,
            "total_weighed": total_quantity
        })

    return {
        "message": "Weight entry added",
        "total_weighed": total_quantity,
        "remaining": listing.get('quantity', 0) - total_quantity
    }

@app.get("/api/listings/{listing_id}/weights")
def get_weights(listing_id: str, user: str = Depends(get_current_user)):
    """Get weight entries"""
    DB_WEIGHTS = os.path.join(BASE_DIR, "weights.json")
    weights = load_json(DB_WEIGHTS)

    listing_weights = [w for w in weights if w['listing_id'] == listing_id]
    total_weight = sum(w['total_weight'] for w in listing_weights)
    total_quantity = sum(w['quantity'] for w in listing_weights)

    return {
        "data": listing_weights,
        "summary": {
            "total_batches": len(listing_weights),
            "total_quantity": total_quantity,
            "total_weight": round(total_weight, 2)
        }
    }

# ==========================================
# Dead Weight Mode - Internal Weighing (Optional)
# ==========================================

@app.post("/api/listings/{listing_id}/internal-weight")
def record_internal_weight(listing_id: str, weight_data: InternalWeightRequest, user: str = Depends(get_current_user)):
    """Dead weight mode - Farmer internal weighing (optional, for reference only)"""
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == listing_id), None)

    if not listing or listing.get('owner_id') != user:
        raise HTTPException(403, "Not authorized")

    weight_type = listing.get('weight_type', 'live')
    if weight_type != 'dead':
        raise HTTPException(400, "Internal weight is only for dead weight transactions")

    # If weight data is provided, record it (for internal tracking)
    if weight_data.perform_weighing:
        if not weight_data.quantity or not weight_data.total_weight:
            raise HTTPException(400, "quantity and total_weight are required when perform_weighing is true")
        
        # Use the same weight format as live weight
        DB_WEIGHTS = os.path.join(BASE_DIR, "weights.json")
        weights = load_json(DB_WEIGHTS)
        
        # Record internal weight (marked as internal use)
        weight_entry = {
            "listing_id": listing_id,
            "batch_number": weight_data.batch_number or 1,
            "quantity": weight_data.quantity,
            "total_weight": weight_data.total_weight,
            "is_internal": True,  # Marked as internal weighing
            "timestamp": datetime.now().isoformat()
        }
        weights.append(weight_entry)
        save_json(DB_WEIGHTS, weights)
        
        listing['internal_weight_recorded'] = True
        listing['internal_weight_recorded_at'] = time.time()
    else:
        # Skip weighing, directly mark as ready for transport
        listing['internal_weight_skipped'] = True
        listing['internal_weight_skipped_at'] = time.time()

    save_json(DB_FARMERS, farmers)

    return {
        "message": "Internal weight process completed",
        "weighed": weight_data.perform_weighing
    }

# ==========================================
# Dead Weight Mode - Request Advance Payment
# ==========================================

@app.post("/api/listings/{listing_id}/request-advance")
def request_advance_payment(listing_id: str, pauta_value: float, user: str = Depends(get_current_user)):
    """Request symbolic advance payment (Pauta Value)"""
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == listing_id), None)

    if not listing or listing.get('owner_id') != user:
        raise HTTPException(403, "Not authorized")

    listing['pauta_value_requested'] = pauta_value
    listing['advance_payment_status'] = 'pending'

    save_json(DB_FARMERS, farmers)

    # 通知买家
    if listing.get('buyer_id'):
        save_notification(listing['buyer_id'], f"Advance payment requested: R$ {pauta_value}", {
            "listing_id": listing_id,
            "amount": pauta_value
        })

    return {"message": "Advance payment requested"}

# ==========================================
# Final Settlement
# ==========================================

@app.post("/api/listings/{listing_id}/finalize")
def finalize_transaction(listing_id: str, payment: FinalPayment, user: str = Depends(get_current_user)):
    """Submit final documents and calculate amount"""
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == listing_id), None)

    if not listing or listing.get('owner_id') != user:
        raise HTTPException(403, "Not authorized")

    # Get accepted proposal
    proposals = load_json(DB_PROPOSALS)
    proposal = next((p for p in proposals if p['supply_id'] == listing_id and p['status'] == 'PAID'), None)

    if not proposal:
        raise HTTPException(400, "No accepted proposal found")

    # Create transaction record
    DB_TRANSACTIONS = os.path.join(BASE_DIR, "transactions.json")
    transactions = load_json(DB_TRANSACTIONS)

    transaction = {
        "id": str(uuid.uuid4()),
        "listing_id": listing_id,
        "proposal_id": proposal['id'],
        "nfe_document": payment.nfe_document or payment.nfe_file,
        "gta_document": payment.gta_document or payment.gta_file,
        "nfe_file": payment.nfe_file,
        "gta_file": payment.gta_file,
        "transport_fee": payment.transport_fee,
        "funrural_tax": payment.funrural_tax,
        "timestamp": time.time()
    }

    # Determine if it's live weight or dead weight mode
    weight_type = listing.get('weight_type', 'live')
    
    # Calculate amount (live weight mode)
    DB_WEIGHTS = os.path.join(BASE_DIR, "weights.json")
    weights = load_json(DB_WEIGHTS)
    listing_weights = [w for w in weights if w['listing_id'] == listing_id]

    if weight_type == 'live' and listing_weights:
        # Live weight mode: calculate based on actual weighing
        total_weight = sum(w['total_weight'] for w in listing_weights)
        at_quantity = total_weight / 15  # Convert to @ (arroba)
        # Use price_per_unit if available, otherwise use price_offer
        price_per_arroba = proposal.get('price_per_unit') or (proposal['price_offer'] / (listing.get('quantity', 1) * listing.get('estimated_weight', 1) / 15))
        final_amount = at_quantity * payment.yield_rate * price_per_arroba

        transaction.update({
            "weight_type": "live",
            "total_weight": total_weight,
            "at_quantity": round(at_quantity, 2),
            "yield_rate": payment.yield_rate,
            "price_per_unit": price_per_arroba,
            "gross_amount": round(final_amount, 2),
            "final_amount": round(final_amount - payment.transport_fee - payment.funrural_tax, 2),
            "status": "awaiting_final_payment"
        })
    elif weight_type == 'dead':
        # Dead weight mode - waiting for slaughterhouse weighing
        transaction.update({
            "weight_type": "dead",
            "status": "awaiting_slaughterhouse_weight",
            "note": "Waiting for slaughterhouse weighing after slaughter"
        })
    else:
        # No weight records but marked as live weight mode
        transaction.update({
            "status": "awaiting_weighing",
            "note": "Waiting for weight confirmation"
        })

    transactions.append(transaction)
    save_json(DB_TRANSACTIONS, transactions)

    # 更新列表状态
    listing['status'] = 'AWAITING_FINAL_PAYMENT'
    listing['transaction_id'] = transaction['id']
    save_json(DB_FARMERS, farmers)

    # Notify buyer to pay final payment
    save_notification(listing.get('buyer_id'), f"Final payment required: R$ {transaction.get('final_amount', 0):.2f}", {
        "transaction_id": transaction['id'],
        "listing_id": listing_id,
        "final_amount": transaction.get('final_amount', 0),
        "gross_amount": transaction.get('gross_amount', 0),
        "action": "pay_final_payment"
    })

    return {
        "message": "Documents submitted. Waiting for final payment.",
        "data": transaction,
        "next_step": "buyer_pay_final"
    }

# ==========================================
# Dead Weight Mode - Slaughterhouse Submit Final Weight
# ==========================================

@app.post("/api/transactions/{transaction_id}/slaughterhouse-weight")
def submit_slaughterhouse_weight(
        transaction_id: str,
        weight_data: SlaughterhouseWeightData,
        user: str = Depends(get_current_user)
):
    """Slaughterhouse submit final weight result (dead weight mode)"""
    DB_TRANSACTIONS = os.path.join(BASE_DIR, "transactions.json")
    transactions = load_json(DB_TRANSACTIONS)

    transaction = next((t for t in transactions if t['id'] == transaction_id), None)
    if not transaction:
        raise HTTPException(404, "Transaction not found")

    # 验证用户是买家
    proposals = load_json(DB_PROPOSALS)
    proposal = next((p for p in proposals if p['id'] == transaction['proposal_id']), None)
    if not proposal or proposal['buyer_id'] != user:
        raise HTTPException(403, "Only the buyer can submit slaughterhouse weight")

    final_weight = weight_data.final_weight
    yield_rate = weight_data.yield_rate or 0.52
    price_per_unit = weight_data.price_per_unit

    # Calculate amount (dead weight: directly use carcass weight)
    at_quantity = final_weight / 15
    final_amount = at_quantity * price_per_unit

    transaction.update({
        "slaughterhouse_weight": final_weight,
        "at_quantity": round(at_quantity, 2),
        "yield_rate": yield_rate,
        "price_per_unit": price_per_unit,
        "gross_amount": round(final_amount, 2),
        "final_amount": round(final_amount - transaction.get('transport_fee', 0) - transaction.get('funrural_tax', 0), 2),
        "status": "completed",
        "completed_at": time.time(),
        "slaughterhouse_user": user
    })

    save_json(DB_TRANSACTIONS, transactions)

    # 更新列表状态
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == transaction['listing_id']), None)
    if listing:
        listing['status'] = 'COMPLETED'
        save_json(DB_FARMERS, farmers)
        
        # Notify farmer
        save_notification(listing['owner_id'], f"Final weighing completed by slaughterhouse", {
            "transaction_id": transaction_id,
            "final_weight": final_weight,
            "final_amount": final_amount
        })

    return {
        "message": "Final weight submitted",
        "calculation": {
            "final_weight": final_weight,
            "at_quantity": round(at_quantity, 2),
            "gross_amount": round(final_amount, 2),
            "final_amount": transaction['final_amount']
        }
    }

# ==========================================
# Get Transaction Details
# ==========================================

@app.get("/api/transactions/by-listing/{listing_id}")
def get_transaction_by_listing(listing_id: str, user: str = Depends(get_current_user)):
    """Get transaction by listing_id (for frontend to navigate based on listing)"""
    DB_TRANSACTIONS = os.path.join(BASE_DIR, "transactions.json")
    transactions = load_json(DB_TRANSACTIONS)

    transaction = next((t for t in transactions if t['listing_id'] == listing_id), None)

    if not transaction:
        raise HTTPException(404, "Transaction not found")

    # Verify user permission (producer or buyer)
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == listing_id), None)
    if listing:
        proposals = load_json(DB_PROPOSALS)
        proposal = next((p for p in proposals if p['id'] == transaction['proposal_id']), None)
        if proposal:
            if listing.get('owner_id') != user and proposal.get('buyer_id') != user:
                raise HTTPException(403, "Not authorized to view this transaction")

    return {"data": transaction}

@app.get("/api/transactions/{transaction_id}")
def get_transaction(transaction_id: str, user: str = Depends(get_current_user)):
    """Get transaction details by transaction ID"""
    DB_TRANSACTIONS = os.path.join(BASE_DIR, "transactions.json")
    transactions = load_json(DB_TRANSACTIONS)

    transaction = next((t for t in transactions if t['id'] == transaction_id), None)

    if not transaction:
        raise HTTPException(404, "Transaction not found")

    return {"data": transaction}

@app.post("/api/transactions/{transaction_id}/pay-final")
def pay_final_payment(transaction_id: str, user: str = Depends(get_current_user)):
    """Buyer pay final payment"""
    DB_TRANSACTIONS = os.path.join(BASE_DIR, "transactions.json")
    transactions = load_json(DB_TRANSACTIONS)

    transaction = next((t for t in transactions if t['id'] == transaction_id), None)
    if not transaction:
        raise HTTPException(404, "Transaction not found")

    # 验证用户是买家
    proposals = load_json(DB_PROPOSALS)
    proposal = next((p for p in proposals if p['id'] == transaction['proposal_id']), None)
    if not proposal or proposal['buyer_id'] != user:
        raise HTTPException(403, "Only the buyer can pay final payment")

    # 检查交易状态
    if transaction.get('status') != 'awaiting_final_payment':
        raise HTTPException(400, f"Transaction is not awaiting final payment. Current status: {transaction.get('status')}")

    # Update transaction status
    transaction['status'] = 'final_payment_paid'
    transaction['final_payment_paid_at'] = time.time()
    transaction['final_payment_paid_by'] = user
    save_json(DB_TRANSACTIONS, transactions)

    # 通知卖家
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == transaction['listing_id']), None)
    if listing:
        listing['status'] = 'FINAL_PAYMENT_PAID'
        save_json(DB_FARMERS, farmers)
        save_notification(listing['owner_id'], f"Final payment received: R$ {transaction.get('final_amount', 0):.2f}. Please confirm receipt.", {
            "transaction_id": transaction_id,
            "listing_id": transaction['listing_id'],
            "final_amount": transaction.get('final_amount', 0),
            "action": "confirm_payment"
        })

    return {
        "message": "Final payment processed",
        "transaction_id": transaction_id,
        "final_amount": transaction.get('final_amount', 0),
        "next_step": "seller_confirm"
    }

@app.post("/api/transactions/{transaction_id}/confirm-payment")
def confirm_payment_receipt(transaction_id: str, user: str = Depends(get_current_user)):
    """Producer confirms payment received, trigger deposit refund"""
    DB_TRANSACTIONS = os.path.join(BASE_DIR, "transactions.json")
    transactions = load_json(DB_TRANSACTIONS)

    transaction = next((t for t in transactions if t['id'] == transaction_id), None)
    if not transaction:
        raise HTTPException(404, "Transaction not found")

    # Verify user is producer
    farmers = load_json(DB_FARMERS)
    listing = next((f for f in farmers if f['id'] == transaction['listing_id']), None)
    if not listing or listing.get('owner_id') != user:
        raise HTTPException(403, "Only the producer can confirm payment receipt")

    # 检查交易状态
    if transaction.get('status') != 'final_payment_paid':
        raise HTTPException(400, f"Final payment must be paid first. Current status: {transaction.get('status')}")

    # Process deposit refund
    proposals = load_json(DB_PROPOSALS)
    proposal = next((p for p in proposals if p['id'] == transaction['proposal_id']), None)
    
    if proposal and proposal.get('deposit_amount') and not proposal.get('deposit_refunded'):
        proposal['deposit_refunded'] = True
        proposal['deposit_refunded_at'] = time.time()
        proposal['payment_confirmed_by'] = user
        proposal['payment_confirmed_at'] = time.time()
        save_json(DB_PROPOSALS, proposals)

        # Notify buyer that deposit has been refunded
        save_notification(proposal['buyer_id'], f"Reservation deposit refunded: R$ {proposal.get('deposit_amount', 0):.2f}", {
            "transaction_id": transaction_id,
            "refund_amount": proposal.get('deposit_amount', 0)
        })

        transaction['payment_confirmed'] = True
        transaction['payment_confirmed_at'] = time.time()
        transaction['status'] = 'completed'
        save_json(DB_TRANSACTIONS, transactions)

        # Update listing status to completed
        farmers = load_json(DB_FARMERS)
        listing = next((f for f in farmers if f['id'] == transaction['listing_id']), None)
        if listing:
            listing['status'] = 'COMPLETED'
            save_json(DB_FARMERS, farmers)

        return {
            "message": "Payment confirmed and deposit refunded",
            "refund_amount": proposal.get('deposit_amount', 0),
            "status": "completed"
        }
    else:
        transaction['payment_confirmed'] = True
        transaction['payment_confirmed_at'] = time.time()
        transaction['status'] = 'completed'
        save_json(DB_TRANSACTIONS, transactions)

        farmers = load_json(DB_FARMERS)
        listing = next((f for f in farmers if f['id'] == transaction['listing_id']), None)
        if listing:
            listing['status'] = 'COMPLETED'
            save_json(DB_FARMERS, farmers)

        return {
            "message": "Payment confirmed (no deposit to refund)",
            "refund_amount": 0,
            "status": "completed"
        }