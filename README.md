# ☁️ Alibaba Cloud Farm — Master GUI Architecture

Proyek ini adalah sebuah **Farm Automation Manager** tersentralisasi yang berfungsi mengendalikan, memanen, dan mengelola ratusan/ribuan akun Node AI dan komputasi awan. Seluruh antarmukanya dibangun menggunakan grafis visual dinamis berbasi Python (`Tkinter`/`ttk`) yang diatur ulang menggunakan Arsitektur Modular (Core Registry).

## 🧩 Arsitektur GUI Modular (`core.registry`)
Dibuat untuk menghilangkan struktur hard-code/kaku, GUI ini memuat setiap aplikasinya secara dinamis menggunakan `FarmRegistry.auto_discover()`.
- **`gui/app.py`**: Merupakan fondasi (Jendela Utama / *Master Window*) yang meluncurkan aplikasi layar penuh.
- **`gui/tabs.py` & `gui/tabs/`**: Tempat seluruh kelas layout tiap penyedia platform (Provider/Farm) ditulis, diturunkan dari `BaseFarmTab`.
- **`core/registry.py`**: Mengatur urutan penempatan (order) dan icon yang akan muncul pada menu bar Tab.

Jika suatu saat Anda butuh menambahkan platform baru, cukup buat *Class* Tab di dalam folder `gui` dan daftarkan di direktori _TAB_META pada class pendaftar.

---

## 🗂️ Direktori Tab & Ekosistem
Aplikasi ini melayani pengelolaan platform-platform multi-node paralel berikut:

1. 📱 **Xiaomi MiMo Farm**
   Kendali kluster pengelolaan perolehan resource MiMo (Xiaomi). Mengotomasi perolehan token/sesi spesifik dari platform yang terhubung.
2. 📧 **Email Farm**
   Modul peternakan dan penampungan SMTP/Imap massif yang di-generate massal untuk operasional klon/akun.
3. ☁️ **Alibaba Cloud Farm** *(Core)*
   Sentral kendali instance dan pengelolaan token *Cloud-Resource* Alibaba yang melengkapi fondasi project ini.
4. 🌐 **Qwen Cloud Farm**
   Pengelola alokasi model/API *Qwen*, mengawasi node farm dalam memproses AI.
5. 🎯 **Mistral AI Farm**
   Pengelola resource provider AI dari sisi Mistral API/token farm.
6. 🤖 **SiliconFlow Farm**
   Menangani otomasi pembuatan dan pencatatan Key dari infrastruktur SiliconFlow model hosting.
7. 🌊 **WaveSpeed Farm**
   Subsistem otomatisasi bagi layanan komputasi instan dari WaveSpeed.
8. ✨ **Genspark Farm**
   Injeksi API dan farming model text/generation dari platform Genspark.
9. 🔑 **Kiro Harvester Desktop** *(Add-on Standalone)*
   Modul pencegat Token (Interceptor). Bergerak secara *background daemon* memanen (Harvest) Access Token OAuth2 milik Kiro IDE (Entra ID) sebelum API Kiro berhasil melancarkan *Self-Destruct*. Menambahkan update token secara atomik ke dalam `kiro_database_farm.json`.

---

## ⚙️ Kiro Token Harvester (Mekanisme Bypass)
Khusus pada tab **Kiro Harvester**, ia beroperasi di balik layar (*headless interceptor*):
- Berjalan dengan interval observasi mikro (50 milisecond).
- Secanggih memata-matai cache di `C:\Users\...\.aws\sso\cache\kiro-auth-token.json`.
- Mengekstrak JWT Token menggunakan dekripsi Base64, dan mengatur datanya secara *Crash-Safe Upsert* (menggunakan temp file dan `os.replace` atomik) agar baris konfigurasi tidak dobel melainkan di-*update*.

## 🚀 Instalasi & Menjalankan
1. Pastikan Anda punya Python versi `3.13` atau ke atas dengan pustaka terkait seperti *playwright*.
2. Meluncurkan Aplikasi Utama (Rekomendasi Utama):
   ```bash
   run_farm_gui.bat
   ```
3. Meluncurkan dari GUI lama (Opsional / Legacy):
   ```bash
   run_qwen_gui.bat
   ```

*Semua kunci kredensial atau output dari tab-tab ini diawasi aman oleh `.gitignore` berlapis (tidak akan terkirim ke riwayat Github).*
