"""Telegram diagnostic — finds why sendMessage returns 400."""
import sys, os, requests, json

# Load .env via secrets_loader (Sprint 2 migration — secrets live in .env, not env.bat)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    import secrets_loader
    secrets_loader.load_env()
except ImportError:
    pass  # fallback: env vars already set by caller

token   = os.environ.get("TELEGRAM_TOKEN", "").strip()
chat_id = os.environ.get("CHAT_ID", "").strip()

print(f"TELEGRAM_TOKEN set: {bool(token)} (len={len(token)})")
print(f"CHAT_ID set       : {bool(chat_id)} (value={chat_id!r})")

if not token:
    print("\n[FAIL] TELEGRAM_TOKEN missing. Add it to .env (e.g. TELEGRAM_TOKEN=123456:ABC...)")
    raise SystemExit(1)
if not chat_id:
    print("\n[FAIL] CHAT_ID missing. Add it to .env (e.g. CHAT_ID=-1001234567890)")
    raise SystemExit(1)

# 1) Verify the bot itself
print("\n[1] Verifying bot via getMe ...")
r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
print(f"    HTTP {r.status_code}")
try:
    j = r.json()
    print(f"    body: {json.dumps(j, indent=2)[:400]}")
except Exception:
    print(f"    raw: {r.text[:300]}")
if r.status_code != 200:
    print("\n[FAIL] Bot token is invalid. Re-issue via BotFather (/revoke or /token).")
    raise SystemExit(1)

# 2) Try the actual send
print("\n[2] Attempting sendMessage ...")
r2 = requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    json={"chat_id": chat_id, "text": "TradeAI diagnostic ping (plain text, no markdown)"},
    timeout=10,
)
print(f"    HTTP {r2.status_code}")
try:
    print(f"    body: {json.dumps(r2.json(), indent=2)[:400]}")
except Exception:
    print(f"    raw: {r2.text[:300]}")

if r2.status_code == 200:
    print("\n[OK] Telegram is reachable. The startup-message 400 is markdown-related —")
    print("     likely the em-dash or pipes in the welcome message.")
    raise SystemExit(0)

# 3) Diagnose the 400
print("\n[FAIL] sendMessage failed. Reading body for the cause ...")
body = r2.text.lower()
if "chat not found" in body:
    print("  → Cause: chat_id does not exist for THIS bot.")
    print("  → Fix: Send /start to the bot in DM, OR add the bot to the group,")
    print("         then re-fetch CHAT_ID from https://api.telegram.org/bot<token>/getUpdates")
elif "bot was blocked" in body:
    print("  → Cause: the user has blocked this bot. Unblock it in Telegram.")
elif "can't parse entities" in body or "parse" in body:
    print("  → Cause: Markdown parse error in startup message.")
elif "chat_id is empty" in body:
    print("  → Cause: CHAT_ID env var is empty or whitespace.")
else:
    print(f"  → Unknown 400. Full body above.")

# 4) Show what getUpdates says — helps find the correct chat_id
print("\n[3] Recent updates (so you can see the real chat_id) ...")
r3 = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
try:
    upd = r3.json().get("result", [])
    if not upd:
        print("    (no updates — send /start to the bot in Telegram first, then re-run)")
    for u in upd[-3:]:
        msg = u.get("message") or u.get("channel_post") or {}
        ch  = msg.get("chat", {})
        print(f"    chat_id={ch.get('id')!r}  type={ch.get('type')!r}  title={ch.get('title') or ch.get('username') or ch.get('first_name')!r}")
except Exception as e:
    print(f"    getUpdates parse error: {e}")
