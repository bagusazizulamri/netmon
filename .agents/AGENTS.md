# Project Rules for NetMon

## Rule for update.sh Synchronization
Setiap kali terdapat penambahan dependensi baru (di `requirements.txt`), penambahan file baru, atau perubahan sistem konfigurasi pada project NetMon, pastikan script `update.sh` diperiksa dan diperbarui agar semua perubahan tersebut dapat di-update secara otomatis di server tanpa perlu melakukan manual add atau reinstall secara penuh. Pastikan proses update tetap aman dan menjaga agar file database `netmon.db` tidak tertimpa atau hilang.
