# Rekomendasi Teknis: Transisi Telemetri dari SNMP Polling ke Flow-Based Export (NetFlow/sFlow/IPFIX)

Dokumen ini menganalisis kelayakan, arsitektur, skema basis data, dan estimasi dampak perubahan untuk meningkatkan akurasi pemantauan bandwidth di level backbone/WAN NetMon dengan menerapkan teknologi berbasis Flow.

---

## 1. Analisis Dukungan Protokol Flow per Vendor Perangkat
Berdasarkan `README.md` (bagian SNMP Setup), berikut adalah analisis protokol flow-export yang didukung oleh masing-masing tipe perangkat:

| Merek / Tipe Device | Protokol yang Didukung | Keterangan Teknis |
|---------------------|------------------------|-------------------|
| **MikroTik RouterOS** | NetFlow v5, v9, IPFIX | Built-in fitur **Traffic Flow**. Sangat stabil dan mudah diaktifkan langsung via WinBox/CLI. |
| **Cisco IOS / IOS-XE** | NetFlow v5, v9, Flexible NetFlow (FNF), IPFIX | Cisco FNF mendukung kustomisasi parameter pencatatan data secara detail dan efisien. |
| **Generic Linux (net-snmp)** | NetFlow v5/v9/IPFIX, sFlow | Linux kernel tidak mengekspor flow secara langsung dari net-snmp, namun dapat dikonfigurasi menggunakan agent daemon ringan seperti **softflowd** atau **fprobe** untuk menangkap paket raw dan mengekspornya ke collector. |
| **UniFi Devices** | NetFlow v9 | USG (UniFi Security Gateway) dan UDM (UniFi Dream Machine) mendukung NetFlow v9 yang dapat diaktifkan melalui opsi penyesuaian controller (*Site Settings*). |

---

## 2. Opsi Solusi yang Direkomendasikan
Untuk campuran perangkat di atas, protokol **NetFlow v9 / IPFIX (NetFlow v10)** adalah pilihan paling ideal karena merupakan standar industri de-facto yang didukung secara universal oleh MikroTik, Cisco, dan UniFi.

### Pilihan Arsitektur Collector:
* **Opsi A (Built-in Python Collector - Direkomendasikan untuk NetMon)**
  * Menjalankan UDP Server sederhana berbasis Python thread (`socketserver` atau `asyncio`) yang mendengarkan port UDP 2055 secara asinkron di dalam proses Flask.
  * **Kelebihan**: Sangat portabel, tidak ada dependensi biner pihak ketiga, satu siklus instalasi/update yang bersih (sesuai filosofi NetMon).
  * **Kekurangan**: Overhead pemrosesan di interpreter Python untuk traffic yang sangat padat (>50k flows/detik).
* **Opsi B (External Sidecar Collector - goflow2 / nfcapd)**
  * Menjalankan daemon pihak ketiga seperti **goflow2** (Go) atau **nfcapd** (C) sebagai service pendamping (systemd unit baru), yang mengumpulkan flow dan meneruskannya ke NetMon via HTTP POST JSON.
  * **Kelebihan**: Performa sangat tinggi, mampu menangani throughput jaringan skala enterprise/ISP.
  * **Kekurangan**: Menambah dependensi biner baru, membutuhkan konfigurasi port forwarding/HTTP listener tambahan, serta mempersulit script `update.sh`.

---

## 3. Skema Basis Data Baru (SQLite)
Untuk menampung catatan aliran traffic (flow records) secara efisien tanpa membebani disk IO SQLite, kita **TIDAK boleh menyimpan raw flow records secara langsung** karena jumlahnya bisa mencapai jutaan baris per jam.
Rekomendasi terbaik adalah menerapkan **agregasi berkala di memori (in-memory buffer)** sebelum ditulis ke SQLite setiap 1 atau 5 menit.

Berikut usulan skema tabel baru di `database.py`:

```sql
-- Menyimpan top talkers teragregasi per interval waktu (misal per 5 menit)
CREATE TABLE IF NOT EXISTS flow_traffic_aggr (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    src_ip TEXT NOT NULL,
    dst_ip TEXT NOT NULL,
    protocol INTEGER,          -- Protocol number (6=TCP, 17=UDP, 1=ICMP, dll)
    bytes INTEGER DEFAULT 0,
    packets INTEGER DEFAULT 0,
    timestamp TEXT NOT NULL,   -- Format: YYYY-MM-DD HH:MM:00 (di-bucket per 5m)
    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_flow_aggr_query ON flow_traffic_aggr(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_flow_aggr_ips ON flow_traffic_aggr(src_ip, dst_ip);
```

---

## 4. Perkiraan Besar Perubahan Kode (Estimasi Dampak)
* **File Baru (1 file)**:
  * `flow_collector.py`: Parser paket biner NetFlow v9/IPFIX dan UDP receiver yang menyimpan data sementara ke in-memory buffer sebelum dibackup ke database SQLite secara berkala.
* **File Lama Terpengaruh (3 file)**:
  * `database.py`: Menambahkan migrasi tabel `flow_traffic_aggr` dan menulis fungsi database untuk query agregat Top Talkers berdasarkan data flow.
  * `app.py`: Menjalankan thread `flow_collector` saat Flask startup, serta merombak route `/api/metrics/traffic` (dan query Top Talkers) agar mengambil data dari tabel agregat flow alih-alih SNMP.
  * `templates/dashboard.html` / `static/js/main.js`: Menyesuaikan visualisasi Top Talkers dan bandwidth chart agar menampilkan relasi IP Source -> IP Destination secara dinamis.

---

## 5. Analisis Trade-Off & Konsekuensi
1. **Konfigurasi Akses Device**: Flow-export mengharuskan user memiliki hak akses administratif untuk mengkonfigurasi perangkat (misalnya memasukkan IP collector dan mengaktifkan Traffic Flow di MikroTik). Di beberapa lingkungan korporat yang ketat, hal ini mungkin memerlukan izin khusus.
2. **Port Firewall Baru**: Port UDP `2055` (atau port kustom lainnya) harus dibuka di firewall server (perlu penyesuaian di `install.sh` / `update.sh` jika diimplementasikan).
3. **Peningkatan Penggunaan Disk IO**: SQLite sangat sensitif terhadap frekuensi penulisan (*write transaction*). Menulis data flow tanpa agregasi memori akan menyebabkan disk bottleneck dan dashboard menjadi lambat (*database is locked*). Penggunaan agregasi in-memory buffer 5 menit adalah harga mutlak yang harus dibayar demi menjaga performa aplikasi.
