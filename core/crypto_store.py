"""
Session/API-key shifrlash — userbot-ai/crypto_store.py patternidan.
Fernet (symmetric) shifrlash ishlatiladi. ENCRYPTION_KEY .env'da saqlanadi
(kodda yoki DB'da hech qachon plaintext holda saqlanmaydi).

Kalit yaratish:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet
import config

_fernet = Fernet(config.ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
