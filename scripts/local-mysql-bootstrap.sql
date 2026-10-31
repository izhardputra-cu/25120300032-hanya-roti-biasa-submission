-- Template setup database lokal untuk Hanya Roti Biasa.
--
-- Ini BUKAN installer otomatis dan tidak boleh dijalankan apa adanya.
-- File ini tidak memuat perintah DROP, RESET, impor, atau FOREIGN_KEY_CHECKS=0.
-- Semua pembuatan memakai bentuk tanpa IF NOT EXISTS, sehingga nama database
-- atau user yang sudah ada menghasilkan error dan tidak ditimpa.
--
-- Langkah aman:
--   1. Cek dulu secara read-only bahwa nama masih bebas:
--        SELECT SCHEMA_NAME FROM information_schema.SCHEMATA
--         WHERE SCHEMA_NAME IN ('wad05_dev', 'wad05_test');
--        SELECT User, Host FROM mysql.user
--         WHERE User IN ('wad05_dev', 'wad05_test');
--   2. Salin file ini ke luar repository, mis. .local/bootstrap-lokal.sql
--   3. Ganti __GANTI_PASSWORD_DEV__ dan __GANTI_PASSWORD_TEST__ dengan literal
--      string berisi password lokal pilihanmu, contoh: 'password-lokal-dev'
--   4. Hapus baris guard "__TEMPLATE_GUARD__" di bawah pada salinan itu.
--   5. chmod 600 salinan tersebut dan jalankan dengan akun admin MySQL lokal:
--        mysql -h 127.0.0.1 -P 3307 -u ADMIN_LOKAL -p < .local/bootstrap-lokal.sql
--   6. Jika satu perintah gagal, berhenti dan periksa objek yang sudah
--      terbentuk. File ini tidak menyediakan perintah hapus.
--
-- Password diminta interaktif oleh client mysql, jadi tidak masuk argv.
-- Jangan commit salinan yang sudah berisi password.

-- Guard: baris ini sengaja gagal selama template belum disiapkan.
SELECT * FROM __TEMPLATE_GUARD__;

-- User dibuat lebih dulu agar nama user yang sudah ada menggagalkan script
-- sebelum database baru terbentuk. Host dibatasi ke loopback saja.
CREATE USER 'wad05_dev'@'127.0.0.1' IDENTIFIED BY __GANTI_PASSWORD_DEV__;
CREATE USER 'wad05_test'@'127.0.0.1' IDENTIFIED BY __GANTI_PASSWORD_TEST__;

CREATE DATABASE wad05_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;
CREATE DATABASE wad05_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;

-- Hak akses hanya pada database milik masing-masing, tanpa GRANT OPTION.
GRANT ALL PRIVILEGES ON wad05_dev.* TO 'wad05_dev'@'127.0.0.1';
GRANT ALL PRIVILEGES ON wad05_test.* TO 'wad05_test'@'127.0.0.1';
