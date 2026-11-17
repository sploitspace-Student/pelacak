"""Pelacak HP sederhana untuk Termux (Android).

Fitur:
  - /lokasi  : bot mengirim lokasi HP saat ini (GPS, cadangan jaringan)
  - /baterai : bot mengirim persentase baterai
  - Peringatan otomatis berisi lokasi saat baterai rendah
  - Kirim lokasi berkala (opsional, lewat INTERVAL_MENIT di .env)

Hanya pesan dari CHAT_ID milikmu yang dilayani.
Hanya memakai library bawaan Python, jadi tidak perlu pip install.
"""

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def muat_env(nama_file=".env"):
    """Baca file .env sederhana (KUNCI=nilai) ke environment."""
    path = os.path.join(BASE_DIR, nama_file)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for baris in f:
            baris = baris.strip()
            if not baris or baris.startswith("#") or "=" not in baris:
                continue
            kunci, nilai = baris.split("=", 1)
            os.environ.setdefault(kunci.strip(), nilai.strip().strip('"').strip("'"))


muat_env()
TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
INTERVAL_MENIT = int(os.environ.get("INTERVAL_MENIT", "0"))  # 0 = nonaktif
BATERAI_RENDAH = int(os.environ.get("BATERAI_RENDAH", "10"))  # persen


# ---------- Bagian HP (Termux:API) ----------

def jalankan_termux(perintah, timeout):
    """Jalankan perintah termux-api dan kembalikan hasil JSON-nya (atau None)."""
    try:
        hasil = subprocess.run(
            perintah, capture_output=True, text=True, timeout=timeout
        )
        if hasil.stdout.strip():
            return json.loads(hasil.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return None


def ambil_lokasi():
    """Coba GPS dulu, kalau gagal pakai jaringan sebagai cadangan."""
    for provider, batas in (("gps", 25), ("network", 20)):
        data = jalankan_termux(["termux-location", "-p", provider], batas)
        if data and "latitude" in data:
            return data
    return None


def ambil_baterai():
    return jalankan_termux(["termux-battery-status"], 10)


# ---------- Bagian Telegram ----------

def api(metode, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{metode}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(url, data=data, timeout=45) as resp:
        return json.loads(resp.read().decode())


def kirim(teks):
    api("sendMessage", chat_id=CHAT_ID, text=teks, disable_web_page_preview="true")


def teks_lokasi(judul="Lokasi HP"):
    data = ambil_lokasi()
    baterai = ambil_baterai()
    if not data:
        return f"{judul}: lokasi belum didapat. Coba lagi sebentar."
    lat, lon = data["latitude"], data["longitude"]
    baris = [
        judul,
        f"Koordinat: {lat}, {lon}",
        f"Akurasi: {data.get('accuracy', '?')} m ({data.get('provider', '?')})",
    ]
    if baterai:
        baris.append(f"Baterai: {baterai.get('percentage', '?')}%")
    baris.append(f"Peta: https://maps.google.com/?q={lat},{lon}")
    return "\n".join(baris)


def tangani_pesan(pesan):
    if not pesan or str(pesan.get("chat", {}).get("id")) != str(CHAT_ID):
        return  # abaikan siapa pun selain pemilik
    teks = (pesan.get("text") or "").strip().lower()
    if teks in ("/start", "/bantuan"):
        kirim("Perintah:\n/lokasi - kirim lokasi HP\n/baterai - cek baterai")
    elif teks == "/lokasi":
        kirim(teks_lokasi())
    elif teks == "/baterai":
        b = ambil_baterai()
        kirim(f"Baterai: {b.get('percentage')}% ({b.get('status')})" if b else "Gagal membaca baterai.")


# ---------- Program utama ----------

def main():
    if not TOKEN or not CHAT_ID:
        print("BOT_TOKEN dan CHAT_ID belum diisi. Salin .env.example menjadi .env lalu isi.")
        return

    try:
        subprocess.run(["termux-wake-lock"], timeout=10)
    except Exception:
        pass

    # Lewati pesan lama agar perintah lama tidak dijalankan ulang.
    offset = None
    try:
        lama = api("getUpdates", offset=-1).get("result", [])
        if lama:
            offset = lama[-1]["update_id"] + 1
    except Exception as e:
        print("Peringatan:", e)

    kirim("Pelacak aktif. Ketik /lokasi untuk meminta lokasi HP.")
    terakhir_berkala = time.time()
    peringatan_terkirim = False

    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            for update in api("getUpdates", **params).get("result", []):
                offset = update["update_id"] + 1
                tangani_pesan(update.get("message"))

            # Peringatan baterai rendah: kirim lokasi terakhir sebelum HP mati.
            b = ambil_baterai()
            if b:
                persen = b.get("percentage", 100)
                mengisi = b.get("status") == "CHARGING"
                if persen <= BATERAI_RENDAH and not mengisi and not peringatan_terkirim:
                    kirim(teks_lokasi("PERINGATAN: baterai rendah"))
                    peringatan_terkirim = True
                elif persen > BATERAI_RENDAH + 5:
                    peringatan_terkirim = False

            # Kirim lokasi berkala (opsional).
            if INTERVAL_MENIT and time.time() - terakhir_berkala >= INTERVAL_MENIT * 60:
                kirim(teks_lokasi("Lokasi berkala"))
                terakhir_berkala = time.time()
        except Exception as e:
            print("Error:", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
