import os
from cryptography.fernet import Fernet
from dotenv import dotenv_values

# === CONFIG ===
ENV_PATH = "/Users/saidixitnaidu/Python/Notion/.env"
ENC_PATH = "/Users/saidixitnaidu/Python/Notion/.env.enc"
SCRIPT_TO_RUN = "/Users/saidixitnaidu/Python/notion_sync.py"
# ===============

def derive_key(password: str):
    """Convert password into a valid Fernet key."""
    import base64, hashlib
    return base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest())

def encrypt_env(password: str):
    """Encrypt .env → .env.enc"""
    key = derive_key(password)
    f = Fernet(key)
    with open(ENV_PATH, "rb") as f_in:
        data = f_in.read()
    enc = f.encrypt(data)
    with open(ENC_PATH, "wb") as f_out:
        f_out.write(enc)
    print(f"[✓] Encrypted and saved: {ENC_PATH}")
    print("⚠️  Now delete the plain .env before pushing to GitHub!")

def decrypt_env(password: str):
    """Decrypt .env.enc, load into memory, and run main script."""
    import subprocess
    import tempfile

    key = derive_key(password)
    f = Fernet(key)

    with open(ENC_PATH, "rb") as f_in:
        dec = f.decrypt(f_in.read())

    tmp_env = tempfile.NamedTemporaryFile(delete=False)
    tmp_env.write(dec)
    tmp_env.close()

    # Load decrypted vars
    config = dotenv_values(tmp_env.name)
    for k, v in config.items():
        if v is not None:
            os.environ[k] = v
    print(f"[env] Loaded {len(config)} vars")

    # Run your main script
    subprocess.run(["python", SCRIPT_TO_RUN], check=True)

    # Clean up
    os.remove(tmp_env.name)

if __name__ == "__main__":
    mode = input("Mode (encrypt/decrypt): ").strip().lower()
    password = input("Enter password: ").strip()

    if mode == "encrypt":
        encrypt_env(password)
    elif mode == "decrypt":
        decrypt_env(password)
    else:
        print("Invalid mode — use 'encrypt' or 'decrypt'")