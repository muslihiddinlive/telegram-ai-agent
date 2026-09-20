import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPERADMIN_ID = int(os.environ["SUPERADMIN_ID"])
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
DB_GROUP_ID = int(os.environ["DB_GROUP_ID"])
PORT = int(os.environ.get("PORT", 8080))

def _split_keys(env_name: str) -> list[str]:
    raw = os.environ.get(env_name, "")
    return [k.strip() for k in raw.split(",") if k.strip()]

GROQ_API_KEYS = _split_keys("GROQ_API_KEYS")
OPENAI_API_KEYS = _split_keys("OPENAI_API_KEYS")
ANTHROPIC_API_KEYS = _split_keys("ANTHROPIC_API_KEYS")
DEEPSEEK_API_KEYS = _split_keys("DEEPSEEK_API_KEYS")

ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"]  # Fernet.generate_key() bilan yarating
