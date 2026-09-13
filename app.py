"""
🚀 Nexus Extractor Engine - Industrial Web Dashboard & API Gateway
"""
import os
import json
import secrets
import threading
import time
from datetime import datetime
from io import BytesIO
from flask import Flask, render_template, jsonify, request, send_file, session, redirect, url_for

app = Flask(__name__)
app.secret_key = secrets.token_hex(24)

# ================= Configurations =================
REDIS_URL = os.environ.get("REDIS_URL", "redis://default:fuHrGqESMbVVRciLtcxCzsKaeUdGnrOU@interchange.proxy.rlwy.net:58097")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://your-domain.com").rstrip('/')
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
APP_SECRET_HEADER = "JetApp-Secure-Client"

# اتصال امن به ردیس با فالبک درون‌حافظه‌ای
redis_client = None
try:
    import redis
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3)
    redis_client.ping()
    print("✅ Connected to Redis successfully.")
except Exception as e:
    print(f"⚠️ Redis unavailable ({e}). Running in Local In-Memory Fallback mode.")
    redis_client = None

# حافظه موقت در صورت نبود ردیس
in_memory_db = {
    "status": "Standby",
    "alerts": [
        f"[{datetime.now().strftime('%H:%M:%S')}] سیستم با موفقیت راه‌اندازی شد. موتور Nexus در حالت آماده‌باش قرار دارد."
    ],
    "accounts": {
        "09121112233": {
            "phone": "09121112233",
            "name": "محمدرضا ",
            "token": secrets.token_urlsafe(14),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },
        "09354445566": {
            "phone": "09354445566",
            "name": "علیرضا حسینی",
            "token": secrets.token_urlsafe(14),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    }
}

# ================= Background Token Worker =================
def token_worker():
    while True:
        try:
            if redis_client:
                raw = redis_client.lpop("bot:new_accounts")
                if raw:
                    acc = json.loads(raw)
                    token = secrets.token_urlsafe(14)
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    redis_client.setex(f"jet_session:{token}", 30 * 24 * 3600, json.dumps(acc["data"], ensure_ascii=False))
                    
                    record = {
                        "phone": acc["phone"],
                        "name": acc["name"],
                        "token": token,
                        "created_at": now_str
                    }
                    redis_client.hset("jet:bulk_accounts", acc["phone"], json.dumps(record, ensure_ascii=False))
        except Exception:
            pass
        time.sleep(1)

threading.Thread(target=token_worker, daemon=True).start()

# ================= Routes & Views =================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    if redis_client:
        total = redis_client.hlen("jet:bulk_accounts")
        last_cmd = redis_client.lindex("bot:admin_commands", -1)
        status = "Processing" if last_cmd == "START_BULK" else "Standby"
    else:
        total = len(in_memory_db["accounts"])
        status = in_memory_db["status"]

    return jsonify({
        "total_accounts": total,
        "success_rate": 98.4 if total > 0 else 100.0,
        "active_proxies": 30,
        "system_status": status
    })

@app.route('/api/logs')
def get_logs():
    logs_list = []
    if redis_client:
        raw_alerts = redis_client.lrange("bot:admin_alerts", -30, -1)
        for r in raw_alerts:
            logs_list.append({
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "message": r.replace("\n", " | ")
            })
    else:
        for m in in_memory_db["alerts"][-30:]:
            logs_list.append({
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "message": m
            })
            
    if not logs_list:
        logs_list.append({"timestamp": datetime.now().strftime("%H:%M:%S"), "message": "سیستم آماده اجرای دستورات است."})
        
    return jsonify({"logs": logs_list})

@app.route('/api/accounts')
def get_accounts():
    accounts_list = []
    if redis_client:
        records = redis_client.hgetall("jet:bulk_accounts")
        for phone, val in records.items():
            item = json.loads(val)
            accounts_list.append({
                "phone": item.get("phone", phone),
                "name": item.get("name", "کاربر جت"),
                "created_at": item.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "status": "Active",
                "link": f"{WEBHOOK_URL}/auth/{item.get('token', '')}"
            })
    else:
        for phone, item in in_memory_db["accounts"].items():
            accounts_list.append({
                "phone": item["phone"],
                "name": item["name"],
                "created_at": item["created_at"],
                "status": "Active",
                "link": f"{WEBHOOK_URL}/auth/{item['token']}"
            })

    return jsonify({"data": accounts_list})

@app.route('/api/action/<action>', methods=['POST'])
def handle_action(action):
    if action == 'start':
        if redis_client:
            redis_client.delete("bot:admin_commands")
            redis_client.rpush("bot:admin_commands", "START_BULK")
        else:
            in_memory_db["status"] = "Processing"
            in_memory_db["alerts"].append(f"[{datetime.now().strftime('%H:%M:%S')}] پردازش همزمان آغاز شد.")
        return jsonify({"status": "ok", "message": "فرمان استارت ارسال شد."})

    elif action == 'stop':
        if redis_client:
            redis_client.rpush("bot:admin_commands", "STOP_BULK")
        else:
            in_memory_db["status"] = "Standby"
            in_memory_db["alerts"].append(f"[{datetime.now().strftime('%H:%M:%S')}] پردازش متوقف گردید.")
        return jsonify({"status": "ok", "message": "فرمان توقف اضطراری اعمال شد."})

    elif action == 'clean':
        if redis_client:
            redis_client.delete("jet:processed_phones")
            redis_client.delete("jet:bulk_accounts")
            redis_client.delete("bot:admin_alerts")
        else:
            in_memory_db["accounts"].clear()
            in_memory_db["alerts"] = [f"[{datetime.now().strftime('%H:%M:%S')}] دیتابیس پاکسازی شد."]
        return jsonify({"status": "ok", "message": "دیتابیس به صورت کامل فلش شد."})

    return jsonify({"status": "error", "message": "دستور نامعتبر است."}), 400

@app.route('/api/action/delete_account', methods=['POST'])
def delete_account():
    data = request.json or {}
    phone = data.get("phone")
    if not phone:
        return jsonify({"status": "error", "message": "شماره نامعتبر است."}), 400

    if redis_client:
        record = redis_client.hget("jet:bulk_accounts", phone)
        if record:
            acc = json.loads(record)
            redis_client.delete(f"jet_session:{acc.get('token')}")
            redis_client.hdel("jet:bulk_accounts", phone)
            redis_client.srem("jet:processed_phones", phone)
    else:
        in_memory_db["accounts"].pop(phone, None)

    return jsonify({"status": "ok", "message": f"اکانت شماره {phone} با موفقیت حذف شد."})

@app.route('/auth/<token>')
def secure_gateway(token):
    session_str = None
    if redis_client:
        session_str = redis_client.get(f"jet_session:{token}")
    else:
        for acc in in_memory_db["accounts"].values():
            if acc["token"] == token:
                session_str = json.dumps({"token": token, "phone": acc["phone"]})
                break

    if not session_str:
        return '<html dir="rtl"><body style="background:#0f172a;color:#f43f5e;font-family:Tahoma;text-align:center;padding-top:100px;"><h2>لینک نامعتبر یا منقضی شده است.</h2></body></html>', 404

    u_agent = request.headers.get("User-Agent", "")
    app_hdr = request.headers.get("X-Client-App", "")
    if app_hdr == APP_SECRET_HEADER or "JetAppClient" in u_agent:
        return jsonify({"status": "success", "session": json.loads(session_str)})

    return '<html dir="rtl"><body style="background:#0f172a;color:#f43f5e;font-family:Tahoma;text-align:center;padding-top:100px;"><h2>دسترسی مسدود است</h2><p>این پیوند امن صرفاً از داخل نرم‌افزار موبایل قابل فراخوانی است.</p></body></html>'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=True)
