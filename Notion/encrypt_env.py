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

# ---- updated decrypt_env: passes env to subprocess explicitly ----
def decrypt_env(password: str):
    """
    Decrypt ENC_PATH (read-only), load variables into a temporary env,
    then run SCRIPT_TO_RUN with those env vars passed explicitly.
    """
    import tempfile, subprocess, sys

    if not os.path.exists(ENC_PATH):
        raise FileNotFoundError(f"{ENC_PATH} missing")

    key = derive_key(password)
    fernet = Fernet(key)

    # read encrypted file (never overwrite)
    with open(ENC_PATH, "rb") as f_enc:
        encrypted = f_enc.read()

    # decrypt into memory - raise a clear error if wrong password
    try:
        decrypted = fernet.decrypt(encrypted)
    except Exception as e:
        raise RuntimeError("Decryption failed — wrong password or corrupted .env.enc") from e

    # write to a temporary file (deleted later)
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        tmp.write(decrypted)
        tmp.flush()
        tmp.close()

        # load the vars (do not print values)
        config = dotenv_values(tmp.name)
        loaded_keys = [k for k, v in (config.items()) if v is not None]
        print("[env] Loaded keys:", ", ".join(loaded_keys) if loaded_keys else "(none)")

        # prepare child env: copy current plus loaded keys (safe)
        child_env = os.environ.copy()
        for k, v in config.items():
            if v is not None:
                child_env[k] = v

        # run the target script using the same Python executable
        if not os.path.exists(SCRIPT_TO_RUN):
            raise FileNotFoundError(f"{SCRIPT_TO_RUN} not found")

        print(f"[run] Executing: {SCRIPT_TO_RUN}")
        subprocess.run([sys.executable, SCRIPT_TO_RUN], check=True, env=child_env)
    finally:
        # cleanup temp file
        try:
            os.remove(tmp.name)
        except Exception:
            pass

if __name__ == "__main__":
    mode = input("Mode (encrypt/decrypt): ").strip().lower()
    password = input("Enter password: ").strip()

    if mode == "encrypt":
        encrypt_env(password)
    elif mode == "decrypt":
        decrypt_env(password)
    else:
        print("Invalid mode — use 'encrypt' or 'decrypt'")