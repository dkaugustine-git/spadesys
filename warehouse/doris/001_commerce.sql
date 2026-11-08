-- Spadesys warehouse: hybrid commerce model for Apache Doris 3.0
-- (Design sketch. Not wired into the pipeline yet.)
--
-- Idea: one wide row per customer carries their orders and line items as
-- nested ARRAY<STRUCT>, so "everything about a customer" is a single-row read
-- with no joins. Item details (name, category, ...) stay in a small lookup
-- table joined by item_id, so catalog changes don't rewrite every customer row.
--
-- Run against the FE's MySQL port:  mysql -h 127.0.0.1 -P 9030 -u root

CREATE DATABASE IF NOT EXISTS spadesys;
USE spadesys;

-- Lookup / dimension: small, frequently joined, updated in place.
CREATE TABLE IF NOT EXISTS dim_item (
    item_id      BIGINT        NOT NULL,
    sku          VARCHAR(64),
    name         VARCHAR(255),
    category     VARCHAR(64),
    unit_price   DECIMAL(12, 2),
    _row_hash    VARCHAR(64)
)
UNIQUE KEY (item_id)
DISTRIBUTED BY HASH (item_id) BUCKETS 1
PROPERTIES ("replication_num" = "1", "enable_unique_key_merge_on_write" = "true");

-- Nested fact: customer -> orders -> items.
CREATE TABLE IF NOT EXISTS customer_orders (
    customer_id  BIGINT        NOT NULL,
    email        VARCHAR(255),
    first_name   VARCHAR(100),
    last_name    VARCHAR(100),
    state        VARCHAR(8),
    signup_date  DATE,
    orders ARRAY<STRUCT<
        order_id:    BIGINT,
        ordered_at:  DATETIME,
        status:      VARCHAR(16),
        order_total: DECIMAL(12, 2),
        items: ARRAY<STRUCT<
            item_id:    BIGINT,
            quantity:   INT,
            unit_price: DECIMAL(12, 2)
        >>
    >>,
    _row_hash    VARCHAR(64),
    _loaded_at   DATETIME
)
UNIQUE KEY (customer_id)
DISTRIBUTED BY HASH (customer_id) BUCKETS 4
PROPERTIES ("replication_num" = "1", "enable_unique_key_merge_on_write" = "true");

-- Example: revenue by category, flattening the nested arrays and joining the lookup.
-- SELECT d.category, SUM(i.quantity * i.unit_price) AS revenue
-- FROM customer_orders c
-- LATERAL VIEW EXPLODE(c.orders) o_tbl AS o
-- LATERAL VIEW EXPLODE(STRUCT_ELEMENT(o, 'items')) i_tbl AS i
-- JOIN dim_item d ON d.item_id = STRUCT_ELEMENT(i, 'item_id')
-- GROUP BY d.category ORDER BY revenue DESC;
