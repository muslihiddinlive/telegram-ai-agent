import os
import sys

# config.py import vaqtida majburiy env'lar kerak — testda soxta qiymatlar
from cryptography.fernet import Fernet  # noqa: E402

# core/crypto_store.py import vaqtida yaroqli Fernet kalit talab qiladi (admin.panel shuni import qiladi)
for k, v in {"BOT_TOKEN": "123456:TEST", "SUPERADMIN_ID": "1", "DB_GROUP_ID": "-100999",
             "ENCRYPTION_KEY": Fernet.generate_key().decode()}.items():
    os.environ.setdefault(k, v)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
