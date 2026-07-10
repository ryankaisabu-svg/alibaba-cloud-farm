# Kiro Token Harvester & Standalone DB Farm

Sistem ini adalah modul interceptor kredensial yang beroperasi sepenuhnya secara headless/background. Sistem ini dirancang untuk "membajak" OAuth Token Entra ID langsung dari memori sistem sesaat setelah user berhasil login melalui **Kiro IDE**.

Metode ini 100% melompati penggunaan web browser automation (Playwright/Puppeteer) untuk skrip farm.

## Alur Kerja (Arsitektur Polling & Upsert)
1. **Interceptor (`kiro_harvester_standalone.py`)** berjalan sebagai daemon background memantau file cache AWS SSO (`C:\Users\Dhipa\.aws\sso\cache\kiro-auth-token.json`).
2. Proses polling dilakukan dengan interval secepat **50 miliseconds** untuk memenangkan balapan (menghadang) fitur penghapusan diri (Self-Destruct) dari Kiro IDE.
3. Kredensial JWT yang diserap segera diparse untuk mendapatkan profil Target Email.
4. Kredensial di-push secara atomic ke sebuah master file database JSON.

## Crash-Safe & Append (Upsert)
Data yang tertangkap dimasukkan ke dalam:
`E:\WEB\alibaba-cloud-farm\kiro_database_farm.json`

Sistem tidak akan mencetak baris yang double/tumpang tindih jika mendapatkan email yang sama keesokan harinya.
- Akun baru = Menambahkan baris (Append di akhir).
- Akun lama = Kredensial JWT-nya disuntik ulang / ditimpa dengan nilai terbaru.

## Cara Penggunaan
Aktifkan script secara manual dari terminal jika belum aktif di background:
```bash
python E:/WEB/alibaba-cloud-farm/kiro_harvester_standalone.py
```
Setelah skrip berjalan, silakan terus lakukan **Login Berantai (multi-akun)** di dalam aplikasi GUI Kiro IDE tanpa perlu menghiraukan skrip Python ini. Ia akan mengatur penampungan JWT-nya secara otomatis.
