import os
import json
import time
import threading
import requests
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------- CONFIG ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Please set TELEGRAM_TOKEN environment variable")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
MINHA_URL = os.getenv("MINHA_URL", "https://minha.anem.dz/pre_inscription")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))

SUBSCRIBERS_FILE = "subscribers.json"

# ---------- LANGUAGE DETECTION ----------
ARABIC_LETTERS = set("ابتثجحخدذرزسشصضطظعغفقكلمنهويىءئة")
FRENCH_KEYWORDS = ("ministère", "demande", "inscription", "offre", "emploi", "bonjour", "merci")

def detect_language(text: str) -> str:
    t = text.lower()
    if any(ch in ARABIC_LETTERS for ch in t):
        return "ar"
    if any(k in t for k in FRENCH_KEYWORDS):
        return "fr"
    return "en"

# ---------- SUBSCRIBERS HANDLING ----------
def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_subscribers():
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(SUBSCRIBERS), f)

SUBSCRIBERS = load_subscribers()

# ---------- TELEGRAM FUNCTIONS ----------
def send_message(chat_id, text):
    try:
        requests.post(f"{API_URL}/sendMessage", data={"chat_id": chat_id, "text": text})
    except Exception as e:
        print(f"[send_message] error {e}")

WELCOME = {
    "ar": "مرحباً! هذا بوت تنبيهات منحة البطالة. اكتب /minha للحصول على آخر الأخبار.",
    "fr": "Bienvenue! Ceci est le bot d'alerte Minha. Tapez /minha pour les dernières infos.",
    "en": "Welcome! This is the Minha alerts bot. Type /minha for latest updates.",
}

def ai_reply(user_text, lang):
    t = user_text.lower()
    if any(x in t for x in ("متى","وقت","مفتوح")):
        return {
            "ar":"الموقع لا يملك وقت ثابت، سنرسل لك إشعاراً أول ما يفتح.",
            "fr":"Le site n'a pas d'horaire fixe. Nous vous enverrons une alerte dès qu'il ouvre.",
            "en":"The site has no fixed opening time. You'll get notified when it opens."
        }[lang]
    if any(x in t for x in ("كيف","وثائق","documents")):
        return {
            "ar":"الوثائق المطلوبة عادة: بطاقة وطنية، شهادة الحالة، تحقق من الوكالة.",
            "fr":"Documents typiques: carte d'identité, justificatif, vérifiez localement.",
            "en":"Typical docs: ID card, proof of status, check locally."
        }[lang]
    return {
        "ar":"أستطيع تنبيهك عند فتح الموقع أو الإجابة عن أسئلة بسيطة. اكتب /minha.",
        "fr":"Je peux vous alerter ou répondre à des questions simples. Tapez /minha.",
        "en":"I can alert you or answer simple questions. Type /minha."
    }[lang]

# ---------- MONITOR ----------
LAST_CONTENT = None

def notify_all_subscribers():
    msg = {
        "ar": f"تنبيه: تم تحديث صفحة التسجيل لمنحة البطالة. ادخل الآن: {MINHA_URL}",
        "fr": f"Alerte: la page de pré-inscription a été mise à jour. Vérifiez: {MINHA_URL}",
        "en": f"Alert: Minha pre-inscription page updated. Check: {MINHA_URL}"
    }
    for chat_id in list(SUBSCRIBERS):
        send_message(chat_id, msg["ar"])  # default Arabic, can extend per-user language

def monitor_loop():
    global LAST_CONTENT
    print(f"[monitor] starting. Monitoring {MINHA_URL} every {CHECK_INTERVAL}s")
    while True:
        try:
            r = requests.get(MINHA_URL, timeout=15)
            content = r.text
            if LAST_CONTENT is None:
                LAST_CONTENT = content
            elif content != LAST_CONTENT:
                print("[monitor] change detected!")
                LAST_CONTENT = content
                notify_all_subscribers()
        except Exception as e:
            print("[monitor] error:", e)
        time.sleep(CHECK_INTERVAL)

# ---------- UPDATES LOOP ----------
OFFSET = None

def process_update(update):
    if 'message' not in update:
        return
    msg = update['message']
    text = msg.get('text','')
    chat_id = msg['chat']['id']
    lang = detect_language(text)

    if text.startswith('/'):
        cmd = text.split()[0].lower()
        if cmd == '/start':
            send_message(chat_id, WELCOME.get(lang, WELCOME['en']))
        elif cmd == '/minha':
            SUBSCRIBERS.add(chat_id)
            save_subscribers()
            send_message(chat_id,{
                "ar":"تم تفعيل التنبيه.",
                "fr":"Abonnement activé.",
                "en":"Subscription activated."
            }[lang])
        elif cmd in ('/stop','/unsubscribe'):
            SUBSCRIBERS.discard(chat_id)
            save_subscribers()
            send_message(chat_id,"تم إلغاء الاشتراك." if lang=="ar" else ("Unsubscribed." if lang=="en" else "Désabonné."))
        elif cmd in ('/help','/aide'):
            send_message(chat_id,{
                "ar":"/minha - تفعيل التنبيه\n/stop - إلغاء الاشتراك\n/help - المساعدة",
                "fr":"/minha - Activer l'alerte\n/stop - Se désabonner\n/help - Aide",
                "en":"/minha - Activate alert\n/stop - Unsubscribe\n/help - Help"
            }[lang])
        else:
            send_message(chat_id, ai_reply(text, lang))
    else:
        send_message(chat_id, ai_reply(text, lang))

def updates_loop():
    global OFFSET
    print("[updates] starting long-polling")
    while True:
        try:
            params = {'timeout':30}
            if OFFSET:
                params['offset'] = OFFSET
            r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
            data = r.json()
            for upd in data.get('result',[]):
                OFFSET = upd['update_id'] + 1
                process_update(upd)
        except Exception as e:
            print("[updates] error", e)
            time.sleep(2)

# ---------- HEALTH SERVER ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type','text/plain')
        self.end_headers()
        self.wfile.write(b'AlgeriaMinha bot running')

def run_web_server():
    port = int(os.getenv('PORT', '8000'))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"[web] running on port {port}")
    server.serve_forever()

# ---------- MAIN ----------
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    updates_loop()
