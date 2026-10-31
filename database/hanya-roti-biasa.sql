-- Hanya Roti Biasa: skema MySQL 8.4 / Alembic 0007 dan data contoh sintetis.
-- Impor HANYA ke database kosong; tidak ada perintah penghapusan atau reset.
-- Skema dibaca dari database tes lokal terpasang; BUKAN backup database live.
-- Akun penjual dibuat terpisah melalui seed lokal.

CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `email` varchar(254) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `password_hash` varchar(255) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `role` varchar(10) COLLATE utf8mb4_0900_as_cs NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_email` (`email`),
  CONSTRAINT `ck_users_role` CHECK ((`role` in (_utf8mb4'buyer',_utf8mb4'seller')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE `sessions` (
  `token_digest` varchar(64) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `csrf_token` varchar(64) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `user_id` int DEFAULT NULL,
  `expires_at` datetime(6) NOT NULL,
  PRIMARY KEY (`token_digest`),
  KEY `user_id` (`user_id`),
  KEY `ix_sessions_expires_at` (`expires_at`),
  CONSTRAINT `sessions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE `products` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(80) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `selling_unit` varchar(40) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `price_rupiah` int NOT NULL,
  `description` varchar(400) COLLATE utf8mb4_0900_as_cs NOT NULL DEFAULT '',
  `is_demo` tinyint(1) NOT NULL DEFAULT '1',
  `archived_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  CONSTRAINT `ck_products_name_length` CHECK ((char_length(`name`) between 2 and 80)),
  CONSTRAINT `ck_products_price_rupiah` CHECK ((`price_rupiah` between 1000 and 1000000)),
  CONSTRAINT `ck_products_unit_length` CHECK ((char_length(`selling_unit`) between 2 and 40))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE `schedules` (
  `id` int NOT NULL AUTO_INCREMENT,
  `pickup_at` datetime(6) NOT NULL,
  `order_cutoff_at` datetime(6) NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `archived_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `ck_schedules_cutoff_before_pickup` CHECK ((`order_cutoff_at` < `pickup_at`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE `schedule_offers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `schedule_id` int NOT NULL,
  `product_id` int NOT NULL,
  `product_name` varchar(80) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `selling_unit` varchar(40) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `price_rupiah` int NOT NULL,
  `quota` int NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_schedule_offers_schedule_product` (`schedule_id`,`product_id`),
  KEY `product_id` (`product_id`),
  CONSTRAINT `schedule_offers_ibfk_1` FOREIGN KEY (`schedule_id`) REFERENCES `schedules` (`id`) ON DELETE CASCADE,
  CONSTRAINT `schedule_offers_ibfk_2` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_schedule_offers_price_rupiah` CHECK ((`price_rupiah` between 1000 and 1000000)),
  CONSTRAINT `ck_schedule_offers_quota` CHECK ((`quota` between 1 and 999)),
  CONSTRAINT `ck_schedule_offers_unit_length` CHECK ((char_length(`selling_unit`) between 2 and 40))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE `orders` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `schedule_id` int NOT NULL,
  `order_number` varchar(32) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `checkout_key` varchar(64) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `checkout_fingerprint` varchar(64) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `status` varchar(24) COLLATE utf8mb4_0900_as_cs NOT NULL DEFAULT 'menunggu_pembayaran',
  `total_rupiah` bigint NOT NULL,
  `pickup_at` datetime(6) NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `transfer_note` varchar(200) COLLATE utf8mb4_0900_as_cs DEFAULT NULL,
  `transfer_reported_at` datetime(6) DEFAULT NULL,
  `transfer_reported_by_id` int DEFAULT NULL,
  `verified_at` datetime(6) DEFAULT NULL,
  `verified_by_id` int DEFAULT NULL,
  `payment_received_rupiah` bigint DEFAULT NULL,
  `cancelled_at` datetime(6) DEFAULT NULL,
  `cancelled_by_id` int DEFAULT NULL,
  `cancellation_reason` varchar(300) COLLATE utf8mb4_0900_as_cs DEFAULT NULL,
  `refund_outcome` varchar(24) COLLATE utf8mb4_0900_as_cs DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_orders_user_checkout_key` (`user_id`,`checkout_key`),
  UNIQUE KEY `order_number` (`order_number`),
  KEY `ix_orders_schedule_id` (`schedule_id`),
  KEY `fk_orders_transfer_reported_by` (`transfer_reported_by_id`),
  KEY `fk_orders_verified_by` (`verified_by_id`),
  KEY `fk_orders_cancelled_by` (`cancelled_by_id`),
  CONSTRAINT `fk_orders_cancelled_by` FOREIGN KEY (`cancelled_by_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_orders_transfer_reported_by` FOREIGN KEY (`transfer_reported_by_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_orders_verified_by` FOREIGN KEY (`verified_by_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `orders_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `orders_ibfk_2` FOREIGN KEY (`schedule_id`) REFERENCES `schedules` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_orders_cancellation_complete` CHECK ((((`cancelled_at` is null) and (`cancelled_by_id` is null) and (`cancellation_reason` is null)) or ((`cancelled_at` is not null) and (`cancelled_by_id` is not null) and (`cancellation_reason` is not null)))),
  CONSTRAINT `ck_orders_cancellation_reason_length` CHECK (((`cancellation_reason` is null) or (char_length(`cancellation_reason`) between 3 and 300))),
  CONSTRAINT `ck_orders_cancelled_status` CHECK ((((`status` = _utf8mb4'batal') and (`cancelled_at` is not null)) or ((`status` <> _utf8mb4'batal') and (`cancelled_at` is null)))),
  CONSTRAINT `ck_orders_checkout_key_length` CHECK ((char_length(`checkout_key`) between 8 and 64)),
  CONSTRAINT `ck_orders_refund_outcome` CHECK (((`refund_outcome` is null) or (`refund_outcome` in (_utf8mb4'refunded_manually',_utf8mb4'no_funds_received')))),
  CONSTRAINT `ck_orders_status` CHECK ((`status` in (_utf8mb4'menunggu_pembayaran',_utf8mb4'menunggu_pemeriksaan',_utf8mb4'terkonfirmasi',_utf8mb4'siap_diambil',_utf8mb4'selesai',_utf8mb4'batal'))),
  CONSTRAINT `ck_orders_total_rupiah` CHECK ((`total_rupiah` between 1000 and 49950000000)),
  CONSTRAINT `ck_orders_transfer_note_length` CHECK (((`transfer_note` is null) or (char_length(`transfer_note`) between 3 and 200))),
  CONSTRAINT `ck_orders_transfer_report_complete` CHECK ((((`transfer_note` is null) and (`transfer_reported_at` is null) and (`transfer_reported_by_id` is null)) or ((`transfer_note` is not null) and (`transfer_reported_at` is not null) and (`transfer_reported_by_id` is not null)))),
  CONSTRAINT `ck_orders_verification_complete` CHECK ((((`verified_at` is null) and (`verified_by_id` is null) and (`payment_received_rupiah` is null)) or ((`verified_at` is not null) and (`verified_by_id` is not null) and (`payment_received_rupiah` = `total_rupiah`) and (`payment_received_rupiah` between 1000 and 49950000000)))),
  CONSTRAINT `ck_orders_verified_amount_present` CHECK (((`verified_at` is null) or (`payment_received_rupiah` is not null)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE `order_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` int NOT NULL,
  `offer_id` int NOT NULL,
  `product_id` int NOT NULL,
  `product_name` varchar(80) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `selling_unit` varchar(40) COLLATE utf8mb4_0900_as_cs NOT NULL,
  `unit_price_rupiah` int NOT NULL,
  `quantity` int NOT NULL,
  `line_total_rupiah` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_order_items_order_offer` (`order_id`,`offer_id`),
  KEY `product_id` (`product_id`),
  KEY `ix_order_items_offer_id` (`offer_id`),
  CONSTRAINT `order_items_ibfk_1` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE CASCADE,
  CONSTRAINT `order_items_ibfk_2` FOREIGN KEY (`offer_id`) REFERENCES `schedule_offers` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `order_items_ibfk_3` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_order_items_line_total` CHECK ((`line_total_rupiah` = (`unit_price_rupiah` * `quantity`))),
  CONSTRAINT `ck_order_items_quantity` CHECK ((`quantity` between 1 and 999)),
  CONSTRAINT `ck_order_items_unit_price` CHECK ((`unit_price_rupiah` between 1000 and 1000000))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE `alembic_version` (
  `version_num` varchar(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Data contoh sintetis untuk pengumpulan UAS, bukan ekspor transaksi produksi.
-- Waktu DATETIME di bawah ditulis dalam UTC. Tanggal pembuatan adalah nilai contoh.
-- Tidak ada baris akun, password hash, session, atau riwayat pesanan.
-- Setelah batas PO lewat, buat jadwal baru melalui UI penjual.

INSERT INTO `products`
 (`id`, `name`, `selling_unit`, `price_rupiah`, `description`, `is_demo`, `archived_at`, `created_at`)
VALUES
 (1, 'Roti Sourdough Klasik', '1 loaf 500 gram', 65000, '', 1, NULL, '2026-10-31 00:00:00.000000'),
 (2, 'Roti Gandum Utuh', '1 loaf 650 gram', 72000, '', 1, NULL, '2026-10-31 00:00:00.000000');

INSERT INTO `schedules`
 (`id`, `pickup_at`, `order_cutoff_at`, `archived_at`, `created_at`)
VALUES
 (1, '2026-11-06 02:00:00.000000', '2026-11-04 13:00:00.000000', NULL, '2026-10-31 00:00:00.000000');

INSERT INTO `schedule_offers`
 (`id`, `schedule_id`, `product_id`, `product_name`, `selling_unit`, `price_rupiah`, `quota`, `created_at`)
VALUES
 (1, 1, 1, 'Roti Sourdough Klasik', '1 loaf 500 gram', 65000, 8, '2026-10-31 00:00:00.000000'),
 (2, 1, 2, 'Roti Gandum Utuh', '1 loaf 650 gram', 72000, 6, '2026-10-31 00:00:00.000000');

INSERT INTO `alembic_version` (`version_num`) VALUES ('0007');
