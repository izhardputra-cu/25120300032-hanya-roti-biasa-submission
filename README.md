# Hanya Roti Biasa

Aplikasi pre-order sourdough untuk satu penjual rumahan. Repository ini disiapkan
sebagai bahan pengumpulan UAS Web Application Development.

- Nama: Izhar Rahman Dwiputra
- NIM: 25120300032
- Stack: Vue 3 (JavaScript) + Vite, FastAPI + SQLAlchemy, MySQL 8.4

Usaha roti ini masih berupa rencana; aplikasi belum dipakai untuk penjualan
nyata dan repository ini tidak memuat data pelanggan.

## Snapshot source

Source aplikasi diambil dari snapshot commit
`027953336d9d4830dbd85b5ca359576f0d635a5b`, revisi skema `0007`. Riwayat Git
pengembangan tidak disertakan. Karena itu hash tersebut adalah penanda sumber,
bukan perintah `git checkout` yang bisa dijalankan di repository ini.

## Fitur

- Katalog publik; penjual dapat menambah, mengubah, mengarsipkan, memulihkan,
  dan menghapus produk.
- Jadwal panggang dengan penawaran produk, kuota, harga snapshot, satu batas
  pre-order, serta status buka/tutup dari jam server (ditampilkan dalam WIB).
- Keranjang untuk satu jadwal, checkout atomik di MySQL, nomor pesanan, riwayat
  dan detail pesanan milik pembeli.
- Konfirmasi transfer oleh pembeli, verifikasi nominal manual oleh penjual,
  pembatalan pembeli/penjual dengan alasan dan pernyataan refund manual.
- Rekap produksi per jadwal, penandaan `siap_diambil`, lalu `selesai`.
- Akun pembeli (registrasi publik), login/logout, session cookie server-side,
  token CSRF + pemeriksaan Origin pada setiap mutasi, password Argon2.

Peran akun di database adalah `buyer` dan `seller`; tidak ada registrasi penjual
publik. Penjual dibuat lewat perintah seed yang dijalankan manual.

## Prasyarat

- Python 3.12 dan `uv`
- Node.js 22 dan `npm`
- MySQL 8.4 pada `127.0.0.1:3307`
- Port pengembangan: API `127.0.0.1:8010`, frontend `127.0.0.1:5173`

Jalankan setiap blok perintah dari **root repository**, kecuali perpindahan folder
tertulis di dalam blok tersebut. Kembali ke root atau buka terminal baru sebelum
mengikuti blok berikutnya.

## 1. Menyiapkan database lokal

Aplikasi memakai dua database terpisah:

- `wad05_dev` dengan user `wad05_dev` untuk menjalankan aplikasi.
- `wad05_test` dengan user `wad05_test` khusus tes. Fixture pytest dan server
  E2E menolak berjalan jika `TEST_DATABASE_URL` bukan `127.0.0.1:3307`, database
  `wad05_test`, dan user `wad05_test`.

`scripts/local-mysql-bootstrap.sql` adalah template kecil untuk membuat kedua
database dan user tersebut. Template ini bukan installer otomatis: tidak ada
`DROP`, `RESET`, impor, atau `FOREIGN_KEY_CHECKS=0` di dalamnya, dan semua
perintah pembuatan memakai bentuk tanpa `IF NOT EXISTS`. Nama database atau user
yang sudah ada akan menghasilkan error, bukan ditimpa.

Cara pakai:

1. Periksa dulu secara read-only apakah nama sudah dipakai:

   ```sql
   SELECT SCHEMA_NAME FROM information_schema.SCHEMATA
    WHERE SCHEMA_NAME IN ('wad05_dev', 'wad05_test');
   SELECT User, Host FROM mysql.user
    WHERE User IN ('wad05_dev', 'wad05_test');
   ```

2. Salin template ke luar repository (misalnya `.local/bootstrap-lokal.sql`),
   isi semua placeholder, hapus baris guard yang sengaja gagal, lalu
   `chmod 600` salinan itu. Jangan commit salinan yang sudah berisi password.
3. Jalankan salinan privat itu dengan akun admin MySQL lokal milikmu; password
   diminta interaktif sehingga tidak masuk argv:

   ```sh
   mysql -h 127.0.0.1 -P 3307 -u ADMIN_LOKAL -p < .local/bootstrap-lokal.sql
   ```

Jika satu perintah gagal, berhenti. Periksa objek apa yang sudah terbentuk
sebelum melakukan apa pun; file template tidak menyediakan perintah hapus.

## 2. Konfigurasi privat

```sh
test -f .env || cp .env.example .env
chmod 600 .env
```

Ganti `GANTI_PASSWORD_DEV` dan `GANTI_PASSWORD_TEST` di `.env` dengan password
lokal yang kamu buat sendiri. Jika password mengandung karakter khusus URL,
percent-encode dulu. Jangan commit `.env` dan jangan menaruh kredensial nyata di
README, log, atau screenshot.

`TEST_DATABASE_URL` harus tetap menunjuk target tes lokal yang dijaga
(`127.0.0.1:3307`, `wad05_test`, user `wad05_test`). Jangan pernah mengarahkannya
ke database pengembangan atau database cloud.

## 3. Mengisi database — pilih salah satu

### Opsi A: database kosong, lalu migrasi

```sh
cd backend
uv sync --frozen --group dev
uv run --frozen --env-file ../.env alembic upgrade head
```

Migrasi `0001`–`0007` membuat skema lengkap. Katalog dan jadwal awal dibuat
lewat UI penjual setelah akun penjual di-seed.

### Opsi B: database kosong, lalu impor sample SQL

`database/hanya-roti-biasa.sql` berisi skema lengkap dari database tes lokal
revisi `0007` dan data contoh sintetis yang disusun terpisah, **bukan backup
transaksi produksi**. Impor hanya ke database kosong (password diminta interaktif):

```sh
mysql -h 127.0.0.1 -P 3307 -u wad05_dev -p wad05_dev < database/hanya-roti-biasa.sql
```

File itu sudah berisi skema revisi `0007` beserta produk, jadwal, penawaran, dan
versi migrasi. Setelah impor, jalankan
`cd backend && uv run --frozen --env-file ../.env alembic upgrade head` untuk
memastikan tidak ada revisi yang diterapkan (sudah di head). File tersebut tidak
berisi baris data pada `users`, `sessions`, `orders`, atau `order_items`, jadi akun penjual tetap dibuat
lewat seed pada langkah berikut. Tanggal jadwal di file adalah snapshot; jika
batas pre-order-nya sudah lewat, buat jadwal baru yang tanggalnya di masa depan
lewat UI penjual.

### Seed akun penjual (setelah Opsi A atau B)

```sh
cd backend
uv run --frozen --env-file ../.env python -m app.seed
```

Seed membuat akun dengan nama **Penjual Hanya Roti Biasa**, email
`seller@example.com`, dan peran `seller`. Password default
`Demo-seller-2026!` adalah **fixture pengembangan lokal** yang tertulis di
`backend/app/seed.py`; ini bukan kredensial akun cloud/privat siapa pun dan
tidak boleh dipakai di luar database lokal. Untuk password lain pada pembuatan
pertama, isi `SEED_SELLER_PASSWORD` pada environment privat; jangan menulis
password pada argumen command line atau shell history. Mengulang seed
tidak mengganti password akun yang sudah ada, dan seed menolak mempromosikan
akun pembeli.

Snapshot ini tidak memuat password akun cloud/privat mana pun. Jangan
menambahkan kredensial seperti itu ke repository, README, commit, atau log.

## 4. Menjalankan aplikasi (mode pengembangan)

Backend:

```sh
cd backend
uv run --frozen --env-file ../.env uvicorn app.main:create_app --factory \
  --host 127.0.0.1 --port 8010
```

Frontend di terminal lain:

```sh
cd frontend
npm ci
npm run dev
```

Buka <http://127.0.0.1:5173>. Vite meneruskan `/api` ke `127.0.0.1:8010`.
Startup API tidak menjalankan migrasi, seed, atau pembersihan data; semua langkah
itu eksplisit.

## 5. Build frontend dan layanan same-origin

Build statis lalu layani oleh FastAPI pada satu origin, seperti bentuk image
produksi tanpa Docker:

```sh
cd frontend
npm ci
npm run build

cd ../backend
FRONTEND_DIR="$PWD/../frontend/dist" ENVIRONMENT=test \
  ALLOWED_ORIGINS='["http://127.0.0.1:8080"]' \
  uv run --frozen --env-file ../.env uvicorn app.main:create_app --factory \
  --host 127.0.0.1 --port 8080
```

Buka <http://127.0.0.1:8080>. Pada mode ini `/api` dan aset statis berasal dari
proses yang sama, dan deep link SPA jatuh ke `index.html`; path API atau aset
yang hilang tetap `404` JSON.

`Dockerfile` membangun aset Vue pada stage Node lalu menjalankan satu proses
FastAPI non-root yang melayani `/api` dan `FRONTEND_DIR`. Entrypoint
`scripts/container-entrypoint.sh` menjalankan uvicorn pada `$PORT`; argumen
tambahan menggantikan perintah default, sehingga migrasi/seed dapat dijalankan
dengan image yang sama. Image tidak memuat database. Konfigurasi kontainer
memakai komponen `DB_USER`, `DB_PASSWORD`, `DB_NAME`, dan
`CLOUDSQL_CONNECTION_NAME`; password diberikan saat runtime, bukan dari file
yang di-commit. Snapshot ini tidak menyatakan bahwa image sudah dibangun atau
diuji ulang.

## Tes

Tes backend memakai MySQL tes nyata dan menghapus baris di database itu. Pastikan
`TEST_DATABASE_URL` menunjuk target tes lokal yang dijaga, lalu:

```sh
cd backend
uv sync --frozen --group dev
uv run --frozen --env-file ../.env pytest -q
uv run --frozen --group dev ruff check .
uv run --frozen --group dev mypy
```

Tes end-to-end lokal menjalankan API dan Vite sendiri, memakai database tes yang
sama. Pastikan dependensi backend sudah disinkronkan lebih dulu
(`uv sync --frozen --group dev` di `backend/`), karena Playwright menjalankan
server API dari direktori itu:

```sh
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

Tes terhadap build statis yang dilayani FastAPI (port `8020`):

```sh
cd frontend
npm ci
npm run build
npm run test:e2e:production
```

Peringatan keselamatan:

- Jangan menunjuk tes ke database pengembangan atau cloud. Jangan memakai skrip
  reset ad hoc, menonaktifkan foreign key, atau menghapus database di luar
  fixture/serve/cleanup tes yang sudah menjaga target `wad05_test`.
- Jalankan tes backend dan E2E bergantian, bukan bersamaan, karena keduanya
  memakai database tes yang sama.
- Artefak Playwright ditulis ke `.local/`, yang diabaikan Git.

Pengumpulan tes (`pytest --collect-only` atau `playwright test --list`) hanya
memeriksa daftar tes, bukan menjalankan skenarionya. Suite backend/MySQL dan E2E
tetap memerlukan database tes terpisah dan harus dijalankan secara berurutan.

## Tes cloud (opsional, bukan default)

`frontend/e2e-cloud/` dan `frontend/e2e-containment/` disertakan sebagai source
tes opsional. Keduanya bukan bagian dari verifikasi default: dibutuhkan layanan
HTTPS yang sedang berjalan dan password penjual dari lingkungan operator, yang
tidak boleh ditulis ke repository atau log. Beberapa helper yang disebut
komentar konfigurasi (`scripts/check-e2e-artifacts.sh`, `scripts/cloud_smoke.py`,
dan skrip persistensi cloud) tidak disertakan dalam snapshot ini, sehingga alur
tersebut tidak turnkey dan harus disiapkan operator.

## Struktur

```text
backend/
  app/              API akun, katalog, jadwal, pesanan, pembayaran, pemenuhan
  migrations/       migrasi Alembic 0001-0007
  tests/            tes API MySQL, migrasi, seed, server dan cleanup E2E
frontend/
  src/              App, router, session, keranjang, API client, tampilan
  src/assets/       ilustrasi hero CC0 dan provenance lisensi
  e2e/              Playwright lokal dengan backend dan MySQL tes
  e2e-production/   Playwright terhadap build nyata pada satu origin
  e2e-cloud/        tes cloud opsional
  e2e-containment/  harness kontainmen kredensial opsional
scripts/
  container-entrypoint.sh
  local-mysql-bootstrap.sql   template setup database lokal (isi placeholder)
database/
  hanya-roti-biasa.sql        skema 0007 dan data contoh sintetis
licenses/
  plus-jakarta-sans-OFL.txt
```

## Lisensi dan atribusi

- Font Plus Jakarta Sans (`@fontsource-variable/plus-jakarta-sans` 5.3.0)
  memakai SIL Open Font License 1.1; teks lisensinya ada di
  `licenses/plus-jakarta-sans-OFL.txt`.
- Foto hero `frontend/src/assets/bread-hero.jpg` berasal dari Wikimedia Commons
  dengan lisensi CC0 1.0. Provenance dan checksum ada di
  `frontend/src/assets/ATTRIBUTION.md`.

Repository ini tidak menambahkan lisensi proyek tingkat atas baru.
