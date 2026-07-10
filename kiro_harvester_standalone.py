import os
import time
import json
import base64
from datetime import datetime

# Konfigurasi Path
FARM_DIR = r"E:\WEB\alibaba-cloud-farm"
CACHE_PATH = r"C:\Users\Dhipa\.aws\sso\cache\kiro-auth-token.json"
OUTPUT_JSON = os.path.join(FARM_DIR, "kiro_database_farm.json")

# Ensure Farm Dir exists
os.makedirs(FARM_DIR, exist_ok=True)

def decode_jwt(token):
    """Mengekstrak informasi dari dalam JWT token"""
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return json.loads(base64.b64decode(payload).decode('utf-8'))
    except Exception:
        return {}

def append_to_farm(email, token_data):
    """Menambah data tanpa menghapus yang lama (Upsert logic). Crash-safe!"""
    farm_data = []
    
    # 1. Baca data lama (jika ada)
    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, 'r', encoding='utf-8') as f:
                farm_data = json.load(f)
        except json.JSONDecodeError:
            farm_data = []
            
    # 2. Update jika akun sudah ada, Append jika ini akun baru
    updated = False
    for account in farm_data:
        if account.get('email') == email:
            account['accessToken'] = token_data.get('accessToken')
            account['refreshToken'] = token_data.get('refreshToken')
            account['expiresAt'] = token_data.get('expiresAt')
            account['updatedAt'] = datetime.now().isoformat()
            updated = True
            break
            
    if not updated:
        # Akun baru, tambahkan ke dictionary paling bawah
        new_account = {
            "email": email,
            "accessToken": token_data.get('accessToken'),
            "refreshToken": token_data.get('refreshToken'),
            "expiresAt": token_data.get('expiresAt'),
            "addedAt": datetime.now().isoformat(),
            "updatedAt": datetime.now().isoformat()
        }
        farm_data.append(new_account)
        
    # 3. Secure / Atomic Write
    tmp_file = OUTPUT_JSON + ".tmp"
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(farm_data, f, indent=4)
    os.replace(tmp_file, OUTPUT_JSON)
    
    return updated

def main():
    print("=" * 60)
    print("KIRO TOKEN HARVESTER (STANDALONE FARM)")
    print("=" * 60)
    print(f"[*] Target Simpan : {OUTPUT_JSON}")
    print("[*] Status        : AKTIF & MENUNGGU SESI LOGIN...")
    print("[*] (Anda bisa membiarkan tab ini terbuka dan lanjut login bergantian di Kiro IDE)\n")
    
    last_processed_token = ""
    
    while True:
        if os.path.exists(CACHE_PATH):
            try:
                # Sedot secara agresif untuk mengalahkan Self-Destruct Kiro
                with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                access_token = data.get('accessToken')
                
                # Pastikan token yang masuk valid dan bukan token yang sama dengan milisecond sebelumnya
                if access_token and access_token != last_processed_token:
                    # Parse Kredensial
                    jwt_data = decode_jwt(access_token)
                    email = jwt_data.get('preferred_username', f"unknown_{int(time.time())}@kirolocal")
                    
                    # Simpan ke Farm
                    is_update = append_to_farm(email, data)
                    status_text = "UPDATE" if is_update else "NEW"
                    
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{timestamp}] [+] {status_text} SLOT : {email}")
                    print(f"           - Kredensial diamankan di form DB Farm.")
                    
                    last_processed_token = access_token
                    
            except json.JSONDecodeError:
                # File sedang di-write oleh sistem, jangan crash, coba di iterasi msec berikutnya
                pass
            except Exception as e:
                pass
                
        # Polling rate: 50 milisecond (Sangat ringan tidak membebani CPU, tapi cukup cepat mendahului penghapusan)
        time.sleep(0.05)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Harvester dihentikan oleh pengguna. Sampai jumpa!")
