"""
Nexus Extractor Engine - Cloud Master Panel
"""
import os, json, secrets, threading, time
from datetime import datetime
from flask import Flask, render_template_string, render_template, jsonify, request, session, redirect, url_for
import redis

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", secrets.token_hex(24))

# Configuration
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://your-domain.com").rstrip('/')
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
APP_SECRET_HEADER = "JetApp-Secure-Client"

# Redis Connection
try:
    db = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    db.ping()
    print("✅ Connected to Redis successfully.")
except Exception as e:
    print(f"⚠️ Redis Connection Error: {e}")
    db = None

# ================= Background Token Worker =================
def token_worker():
    while True:
        if db:
            try:
                raw_data = db.lpop("bot:new_accounts")
                if raw_data:
                    acc = json.loads(raw_data)
                    token = secrets.token_urlsafe(14)
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # ذخیره نشست برای اپلیکیشن
                    db.setex(f"jet_session:{token}", 30 * 24 * 3600, json.dumps(acc.get("data", {}), ensure_ascii=False))
                    
                    # ذخیره اطلاعات برای نمایش در جدول و خروجی‌ها
                    record = {
                        "phone": acc.get("phone", ""),
                        "name": acc.get("name", ""),
                        "token": token,
                        "created_at": now_str
                    }
                    db.hset("jet:bulk_accounts", acc.get("phone", ""), json.dumps(record, ensure_ascii=False))
            except Exception:
                pass
        time.sleep(1)

threading.Thread(target=token_worker, daemon=True).start()

# ================= Login Template =================
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ورود به پنل سازمانی | Nexus</title>
    <link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.0.0/Vazirmatn-font-face.css" rel="stylesheet" />
    <script src="https://cdn.tailwindcss.com"></script>
    <style>body { font-family: 'Vazirmatn', sans-serif; background-color: #f8fafc; }</style>
</head>
<body class="min-h-screen flex items-center justify-center p-4">
    <div class="bg-white p-8 rounded-2xl border border-slate-200 shadow-xl w-full max-w-md">
        <div class="flex justify-center mb-6"><div class="h-12 w-12 bg-indigo-600 rounded-xl shadow-lg flex items-center justify-center"><svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg></div></div>
        <h2 class="text-2xl font-bold text-slate-800 text-center mb-6">NEXUS WORKSPACE</h2>
        <form method="POST" action="/login" class="flex flex-col gap-4">
            <input type="password" name="password" placeholder="کلمه عبور سیستم..." required class="bg-slate-50 border border-slate-300 text-slate-800 rounded-xl p-3 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all text-center" dir="ltr">
            <button type="submit" class="bg-indigo-600 text-white font-bold py-3 rounded-xl hover:bg-indigo-700 transition-colors shadow-md">ورود ایمن</button>
        </form>
    </div>
</body>
</html>
"""

# ================= Routes =================
@app.route('/')
def index():
    if not session.get('logged_in'): return render_template_string(LOGIN_HTML)
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('password') == ADMIN_PASS:
        session['logged_in'] = True
        return redirect(url_for('index'))
    return "پسورد اشتباه است.", 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/stats')
def get_stats():
    if not session.get('logged_in') or not db: return jsonify({"total_accounts":0, "success_rate":100, "active_proxies":0, "system_status":"Offline"})
    total = db.hlen("jet:bulk_accounts")
    last_cmd = db.lindex("bot:admin_commands", -1)
    status = "Processing" if last_cmd == "START_BULK" else "Standby"
    return jsonify({"total_accounts": total, "success_rate": 100.0 if total else 0.0, "active_proxies": 25, "system_status": status})

@app.route('/api/logs')
def get_logs():
    if not session.get('logged_in') or not db: return jsonify({"logs": []})
    raw_logs = db.lrange("bot:admin_alerts", -40, -1)
    logs_fmt = [{"timestamp": datetime.now().strftime("%H:%M:%S"), "message": l.replace('\n', ' - ')} for l in raw_logs]
    if not logs_fmt: logs_fmt.append({"timestamp": datetime.now().strftime("%H:%M:%S"), "message": "سیستم منتظر دستور..."})
    return jsonify({"logs": logs_fmt})

@app.route('/api/accounts')
def get_accounts():
    if not session.get('logged_in') or not db: return jsonify({"data": []})
    records = db.hgetall("jet:bulk_accounts")
    data = []
    for phone, val in records.items():
        acc = json.loads(val)
        data.append({
            "phone": acc.get("phone", phone),
            "name": acc.get("name", ""),
            "created_at": acc.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "status": "Active",
            "link": f"{WEBHOOK_URL}/auth/{acc.get('token', '')}"
        })
    return jsonify({"data": data})

@app.route('/api/action/<cmd>', methods=['POST'])
def handle_action(cmd):
    if not session.get('logged_in') or not db: return jsonify({"error": "Unauthorized"}), 401
    
    if cmd == 'start':
        db.delete("bot:admin_commands")
        db.rpush("bot:admin_commands", "START_BULK")
        return jsonify({"status": "ok", "message": "پردازش موازی آغاز شد."})
    elif cmd == 'stop':
        db.rpush("bot:admin_commands", "STOP_EMERGENCY")
        return jsonify({"status": "ok", "message": "فرمان توقف صادر شد."})
    elif cmd == 'clean':
        req = request.json or {}
        if req.get('code') != 'NEXUS-WIPE-ALL': return jsonify({"status": "error", "message": "کد تایید اشتباه است."})
        db.delete("jet:processed_phones", "jet:bulk_accounts", "bot:admin_alerts", "bot:new_accounts")
        for key in db.keys("jet_session:*"): db.delete(key)
        return jsonify({"status": "ok", "message": "دیتابیس کاملاً فلش شد."})
    
    return jsonify({"status": "error"})

@app.route('/api/action/delete_account', methods=['POST'])
def delete_account():
    if not session.get('logged_in') or not db: return jsonify({"status": "error"})
    phone = request.json.get('phone')
    rec = db.hget("jet:bulk_accounts", phone)
    if rec:
        acc = json.loads(rec)
        db.delete(f"jet_session:{acc.get('token')}")
        db.hdel("jet:bulk_accounts", phone)
        db.srem("jet:processed_phones", phone)
    return jsonify({"status": "ok"})

@app.route('/auth/<token>')
def secure_gateway(token):
    if not db: return "Server Error", 500
    session_str = db.get(f"jet_session:{token}")
    if not session_str: return '<html dir="rtl"><body style="background:#f8fafc;color:#e11d48;font-family:Tahoma;text-align:center;padding:50px;"><h2>لینک نامعتبر یا منقضی شده است.</h2></body></html>', 404
    
    u_agent, app_hdr = request.headers.get("User-Agent", ""), request.headers.get("X-Client-App", "")
    if app_hdr == APP_SECRET_HEADER or "JetAppClient" in u_agent:
        return jsonify({"status": "success", "session": json.loads(session_str)})
    return '<html dir="rtl"><body style="background:#f8fafc;color:#e11d48;font-family:Tahoma;text-align:center;padding:50px;"><h2>دسترسی مسدود است</h2><p>این پیوند فقط از داخل اپلیکیشن موبایل قابل بازگشایی است.</p></body></html>'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

