import os
import sys

# config.py import vaqtida majburiy env'lar kerak — testda soxta qiymatlar
for k, v in {"BOT_TOKEN": "123456:TEST", "SUPERADMIN_ID": "1", "DB_GROUP_ID": "-100999",
             "ENCRYPTION_KEY": "x" * 44}.items():
    os.environ.setdefault(k, v)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
