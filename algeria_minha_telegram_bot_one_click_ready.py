# AlgeriaMinha Telegram Bot - One-Click Deploy (Railway)
# -----------------------------------------------------
# Project structure (single-file minimal deploy):
# - main.py         -> bot + monitor + language detection + simple AI placeholder
# - requirements.txt
# - README.md       -> deployment & configuration instructions
# - Procfile        -> for Railway

# ---------------- main.py ----------------
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import os
import time
import requests
from datetime import datetime

# --- minimal multilingual detection (no external libs) ---
# We'll use a tiny heuristic: presence of Arabic letters, French words, or fallback to English.
ARABIC_LETTERS = set("ابتثجحخدذرزسشصضطظعغفقكلمنهويىءئة")
FRENCH_KEYWORDS = ("ministère", "demande", "inscription", "offre", "emploi", "bonjour", "merci")


def detect_language(text: str) -> str:
    t = text.lower()
    if any(ch in ARABIC_LETTERS for ch in t):
        return "ar"
    if any(k in t for k in FRENCH_KEYWORDS):
        return "fr"
    return "en"


# --- Telegram bot using long polling (no external bot framework required) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Please set TELEGRAM_TOKEN environment variable")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Basic send message
def send_message(chat_id, text):
    payload = {"chat_id": chat_id, "text": text}
    requests.post(f"{API_URL}/sendMessage", data=payload)


# Welcome message per language
WELCOME = {
    "ar": "مرحباً! هذا بوت تنبيهات منحة البطالة. اكتب /minha للحصول على آخر الأخبار.",
    "fr": "Bienvenue! Ceci est le bot d'alerte Minha. Tapez /minha pour les dernières infos.",
    "en": "Welcome! This is the Minha alerts bot. Type /minha for latest updates.",
}

# Simple AI placeholder response generator (free)
def ai_reply(user_text, lang):
    # Very simple rule-based assistant for common Minha questions.
    t = user_text.lower()
    if any(x in t for x in ("متى", "وقت", "متى يفتح", "مفتوح")):
        if lang == "ar":
            return "الموقع لا يملك وقت ثابت، سنرسل لك إشعاراً أول ما يفتح."
        if lang == "fr":
            return "Le site n'a pas d'horaire fixe. Nous vous enverrons une alerte dès qu'il ouvre."
        return "The site has no fixed opening time. You'll get notified when it opens."
    if any(x in t for x in ("كيف", "واش لازم", "documents", "وثائق")):
        if lang == "ar":
            return "الوثائق المطلوبة عادة: بطاقة وطنية، شهادة الحالة،... (تحقق محلياً من الوكالة)."
        if lang == "fr":
            return "Documents typiques: carte d'identité, justificatif de situation, etc. Vérifiez localement."
        return "Typical docs: ID card, proof of status, etc. Check locally with ANEM."
    # fallback short reply
    if lang == "ar":
        return "أستطيع تنبيهك عند فتح الموقع أو الإجابة عن أسئلة بسيطة حول المنحة. اكتب /minha للتسجيل في التنبيهات."
    if lang == "fr":
        return "Je peux vous alerter quand le site ouvre ou répondre à des questions simples. Tapez /minha."
    return "I can alert you when the site opens or answer simple questions. Type /minha."


# --- Monitor logic: polls the Minha URL and notifies subscribers on change ---
MINHA_URL = os.getenv("MINHA_URL", "https://minha.anem.dz/pre_inscription")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))

# Subscribers stored in-memory (for production, use a DB or persistent store)
SUBSCRIBERS = set()  # chat_id integers
LAST_CONTENT = None


def monitor_loop():
    global LAST_CONTENT
    print(f"[monitor] starting. Monitoring {MINHA_URL} every {CHECK_INTERVAL}s")
    while True:
        try:
            r = requests.get(MINHA_URL, timeout=15)
            content = r.text
            # simple change detection: if 'inscription' or 'ouvrir' or 'فتح' appears newly
            trigger = False
            if LAST_CONTENT is None:
                LAST_CONTENT = content
            else:
                if content != LAST_CONTENT:
                    trigger = True
                    LAST_CONTENT = content
            if trigger:
                print("[monitor] change detected, notifying subscribers...")
                notify_all_subscribers()
        except Exception as e:
            print("[monitor] error:", e)
        time.sleep(CHECK_INTERVAL)


def notify_all_subscribers():
    msg_ar = "تنبيه: تم تحديث صفحة التسجيل لمنحة البطالة. ادخل الآن: " + MINHA_URL
    msg_fr = "Alerte: la page de pré-inscription a été mise à jour. Vérifiez: " + MINHA_URL
    msg_en = "Alert: Minha pre-inscription page updated. Check: " + MINHA_URL
    for chat in list(SUBSCRIBERS):
        try:
            # default send in Arabic first; better: store language per user (not implemented)
            send_message(chat, msg_ar)
        except Exception as e:
            print("[notify] failed to send to", chat, e)


# --- Simple webhook-like polling for incoming updates ---
OFFSET = None


def process_update(update):
    # update is a dict from Telegram getUpdates
    if 'message' not in update:
        return
    msg = update['message']
    text = msg.get('text','')
    chat_id = msg['chat']['id']
    # detect language
    lang = detect_language(text)
    if text.startswith('/'):
        # command handling
        cmd = text.split()[0].lower()
        if cmd == '/start':
            send_message(chat_id, WELCOME.get(lang, WELCOME['en']))
        elif cmd == '/minha':
            # subscribe user
            SUBSCRIBERS.add(chat_id)
            if lang == 'ar':
                send_message(chat_id, "تم تفعيل التنبيه: ستحصل على إشعار عند فتح التسجيل.")
            elif lang == 'fr':
                send_message(chat_id, "Abonnement activé: vous recevrez une alerte.")
            else:
                send_message(chat_id, "Subscription activated: you'll receive alerts.")
        elif cmd == '/stop' or cmd == '/unsubscribe':
            if chat_id in SUBSCRIBERS:
                SUBSCRIBERS.discard(chat_id)
                send_message(chat_id, "تم إلغاء الاشتراك. يمكنك إعادة الاشتراك بإرسال /minha")
            else:
                send_message(chat_id, "You are not subscribed.")
        elif cmd == '/help' or cmd == '/aide':
            help_text = {
                'ar': "/minha - تفعيل التنبيه\n/stop - إلغاء الاشتراك\n/help - المساعدة",
                'fr': "/minha - Activer l'alerte\n/stop - Se désabonner\n/help - Aide",
                'en': "/minha - Activate alert\n/stop - Unsubscribe\n/help - Help",
            }
            send_message(chat_id, help_text.get(lang, help_text['en']))
        else:
            # unknown command -> fallback to AI
            reply = ai_reply(text, lang)
            send_message(chat_id, reply)
    else:
        # normal text -> AI reply
        reply = ai_reply(text, lang)
        send_message(chat_id, reply)


def updates_loop():
    global OFFSET
    print("[updates] starting long-polling getUpdates")
    while True:
        try:
            params = { 'timeout': 30 }
            if OFFSET:
                params['offset'] = OFFSET
            r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
            data = r.json()
            if not data.get('ok'):
                time.sleep(2)
                continue
            for upd in data.get('result',[]):
                OFFSET = upd['update_id'] + 1
                process_update(upd)
        except Exception as e:
            print('[updates] error', e)
            time.sleep(2)


# --- small web server so Railway shows the service is up ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type','text/plain')
        self.end_headers()
        self.wfile.write(b'AlgeriaMinha bot running')


def run_web_server():
    port = int(os.getenv('PORT', '8000'))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"[web] starting web server on port {port}")
    server.serve_forever()


if __name__ == '__main__':
    # start web server thread
    t = threading.Thread(target=run_web_server, daemon=True)
    t.start()
    # start monitor thread
    m = threading.Thread(target=monitor_loop, daemon=True)
    m.start()
    # start updates loop (blocking)
    updates_loop()


# ---------------- requirements.txt ----------------
# requests is enough for this minimal example
# add any other libs if you extend the bot (e.g., python-telegram-bot, transformers...)

# content of requirements.txt:
# requests>=2.25.1


# ---------------- Procfile ----------------
# web: python main.py


# ---------------- README.md ----------------
# AlgeriaMinha Telegram Bot - One-Click Deploy (Railway)

README = '''
# AlgeriaMinha Telegram Bot (One-Click for Railway)

This project is a minimal Telegram bot that monitors the ANEM Minha page and notifies subscribers when the page changes.
It includes simple multilingual detection and a small rule-based AI fallback (so you can run without a paid API).

## Files
- `main.py` - main application (bot + monitor + health webserver)
- `requirements.txt` - Python dependencies
- `Procfile` - for Railway

## Setup & Deploy on Railway (one-click style)
1. Create a GitHub repository and push these files (main.py, requirements.txt, Procfile, README.md).
2. Sign up / login to Railway (https://railway.app).
3. Create a new project -> Deploy from GitHub -> select your repo.
4. Go to Settings -> Environment Variables and add:
   - `TELEGRAM_TOKEN` = your bot token (from BotFather)
   - `MINHA_URL` = https://minha.anem.dz/pre_inscription
   - (optional) `CHECK_INTERVAL_SECONDS` = 60
5. Deploy. Railway will build and launch the service.
6. To get your `chat_id` for admin/test: send `/start` to your bot, then check Railway logs to see updates from `getUpdates` or temporarily include a print in code.

## Usage
- Send `/start` to the bot. It will greet you in the language it detects.
- Send `/minha` to subscribe to alerts.
- Send `/stop` to unsubscribe.

## Next steps (recommended)
- Persist subscribers in a database (Postgres) instead of in-memory.
- Add a paid subscription flow (Stripe / DmP) or integrate with Djezzy/algérie telecom payment gateways.
- Replace the rule-based AI with an actual LLM (OpenAI/HuggingFace) if you want richer answers.

''' 
