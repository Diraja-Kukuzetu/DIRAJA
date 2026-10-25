# Dira AI Analytics Schema

Semantic control layer for natural-language → SQL.
Database: MariaDB 10.4.32
Tables: 74 | Explicit foreign keys: 16

---

## 0. MANDATORY RULES — you MUST follow these

These rules override everything else in this document. If a rule requires a JOIN, include that JOIN. If a rule forbids a column, do NOT use that column.

### M1. Item identity
- Use `stock_item` as the product/item master.
- Join `sold_items.item_id = stock_item.id` to enrich a sale line with product metadata.

### M2. Money — total sales, revenue, amount paid (KSh)
- MUST join `sales_payment_methods` on `sales_payment_methods.sale_id = sales.sales_id`.
- MUST sum `sales_payment_methods.amount_paid` for money totals.
- MUST NOT use `sold_items.total_price` or `sold_items.unit_price` for money totals.
- Reason: `total_price` is a stored line value that does not reflect what the customer actually paid.

### M3. Quantity sold
- Use `sold_items.quantity` and `sold_items.metric`.
- If `stock_item.pack_quantity` exists, convert packs → pieces using `pack_quantity`.
  Example: Egg (Grade), `pack_quantity=30`, `quantity=2.5` → 2 trays + 15 pieces.
- If `sold_items.metric` says the stored unit is already pieces, do NOT convert.

### M4. Eggs display unit
- If `stock_item.item_name` is `Egg (Grade)` or contains `egg` (case-insensitive), display pack-level quantity as **trays**, not packs.
- Underlying calculation is unchanged — only the label changes.

### M5. Selling price (per line, not totals)
- Use `sold_items.unit_price`.

### M6. Cost of sale
- Join `cost_of_sale_ledger.sales_id = sales.sales_id`.
- The ledger is double-entry: the same transaction appears as a debit AND a credit.
- MUST NOT sum both sides. Count the amount once per `sales_id`.
- When aggregating across sales, deduplicate by `sales_id`.

### M7. Payment-method analysis
- Join `sales_payment_methods` to `sales`.

### M8. Inventory — V2 vs legacy
- V2 (preferred for current work): `inventoryV2`, `shop_stock_v2`.
- Legacy: `inventory`, `shop_stock`.
- Do NOT silently merge V2 and legacy tables.
- Do NOT combine `stock`, `shop_stock`, `shop_stock_v2`, `LiveStock` unless the question explicitly asks for reconciliation.

### M9. Expenses
- Totals → `expenses`.
- Accounting/GL postings → `expenses_ledger`.

### M10. Accounting
- Use `chart_of_accounts` + accounting ledgers for GL questions.
- Do NOT reconstruct balances from operational tables.

### M11. eTIMS
- eTIMS questions → `etims_sales`, `etims_sale_items`.
- Local operational sales → `sales`, `sold_items`.
- Do not mix unless the question explicitly asks about eTIMS.

### M12. Mabanda (legacy)
- `mabanda*` tables are a separate legacy family.
- Do NOT mix with main sales/inventory unless the user asks.

### M13. Never use in analytics
- `users.password`, `users.two_factor_secret`, `users.backup_codes`
- `two_factor_auth.code`, `two_factor_auth.secret`
- `push_subscription.endpoint`, `.p256dh`, `.auth`
- `employees.national_id_number`, `.personal_email`, `.bank_account_number`, `.kra_pin`, `.date_of_birth`

### M14. Query safety
- Only `SELECT` (or `WITH ... SELECT`) allowed.
- No DDL, no DML.
- No comments (`--`, `/*`, `#`).
- Single statement only.
- Prefer aggregates; enforce `LIMIT` on detail queries.

---

## 1. Domain → Tables map

| Domain | Tables |
|---|---|
| sales | sales, sold_items, sales_payment_methods, sales_ledger, credit_sales_ledger, sales_department, customers, loyalty_transactions, bank |
| inventory | stock_item, stock, inventory, inventoryV2, shop_stock, shop_stock_v2, LiveStock, transfers, transfers_v2, system_stock_transfer, shoptoshop_transfer, shoptransfers, stock_returnv2, stock_reconciliation, spoilt, spoilt_stock_ledger, broken_eggs_loging, cooked_items, distribution_ledger |
| purchasing / suppliers | suppliers, supplier_history, purchase_ledger_inventory, inventory_payments |
| expenses / creditors | expenses, expenses_ledger, expense_category, expense_items, expense_creditors, expense_distributions, credit_payments, creditors |
| accounting / banking | chart_of_accounts, bank_account, banking_transaction, bank_transfers_ledger, manual_ledger, transaction, cash_deposits, cost_of_sale_ledger |
| employees / security | users, employees, employeesLoan, permission, two_factor_auth, merit_points, merit_ledger |
| shops / operations | shops, shop_targets, clerk_reports, stock_reports, notifications, push_subscription |
| etims | etims_items, etims_sales, etims_sale_items |
| tasks | task_manager, task_comments, task_evaluations, task_category |
| mabanda (legacy) | mabandastock, mabandapurchase, mabandasale, mabandaexpense |
| system | alembic_version |

---

## 2. Join cheat-sheet

Use these joins. Do not invent joins.

```
sales.sales_id              → sold_items.sales_id
sales.sales_id              → sales_payment_methods.sale_id
sales.sales_id              → cost_of_sale_ledger.sales_id
sales.sales_id              → sales_ledger.sales_id
sales.sales_id              → credit_sales_ledger.sales_id
sales.sales_id              → bank.sales_id
sales.shop_id               → shops.shops_id
sales.user_id               → users.users_id

sold_items.item_id          → stock_item.id
sold_items.stockv2_id       → shop_stock_v2.stockv2_id

inventoryV2.inventoryV2_id  → shop_stock_v2.inventoryv2_id
inventoryV2.inventoryV2_id  → inventory_payments.inventory_id

shop_stock_v2.shop_id       → shops.shops_id

loyalty_transactions.customer_id → customers.customer_id

expenses.creditor_id        → expense_creditors.creditor_id
expense_creditors.user_id   → users.users_id
expense_items.category_id   → expense_category.id
expense_distributions.original_expense_id → expenses.expense_id
expense_distributions.distributed_to_shop_id → shops.shops_id
expense_distributions.distributed_by → users.users_id

credit_payments.expense_id  → expenses.expense_id
credit_payments.created_by  → users.users_id

etims_items.local_item_id   → stock_item.id
etims_sale_items.etims_sale_id → etims_sales.id

bank_account.chart_account_id → chart_of_accounts.id
banking_transaction.account_id → bank_account.id

notifications.user_id       → users.users_id
two_factor_auth.user_id     → users.users_id
task_manager.parent_task_id → task_manager.task_id
```

---

## 3. Sales domain

### sales
- **Purpose:** Sale header/transaction record.
- **Use for:** sale counts, sale dates, shop-level headers, customer attached to sale, sale status, outstanding balance.
- **Primary key:** `sales_id`
- **Key columns:**
  - `sales_id` [ID]
  - `shop_id` → shops.shops_id
  - `user_id` → users.users_id
  - `customer_name`, `customer_number`
  - `status`
  - `created_at` [TIME]
  - `balance` [MONEY]
  - `delivery` (bool)

### sold_items
- **Purpose:** Line items on a sale.
- **Use for:** items sold, quantity, unit price, line totals, cost of sale, sales by product.
- **Primary key:** `id`
- **Key columns:**
  - `id` [ID]
  - `sales_id` → sales.sales_id
  - `item_id` → stock_item.id
  - `item_name`
  - `quantity` [QTY]
  - `metric` [QTY]
  - `unit_price` [MONEY] — per-line selling price
  - `total_price` [MONEY] — stored line total (do NOT use for money totals — see M2)
  - `Cost_of_sale` [MONEY]
  - `stockv2_id` → shop_stock_v2.stockv2_id
  - `BatchNumber`
  - `is_service`

### sales_payment_methods
- **Purpose:** Payment records attached to a sale.
- **Use for:** sales by payment method, amount paid, discounts, transaction codes, SasaPay status.
- **Primary key:** `id`
- **Key columns:**
  - `id` [ID]
  - `sale_id` → sales.sales_id
  - `payment_method`
  - `amount_paid` [MONEY] ← authoritative "amount paid" (see M2)
  - `balance` [MONEY]
  - `discount` [MONEY]
  - `payment_status`, `transaction_code`

### sales_ledger, credit_sales_ledger, sales_department
- **sales_ledger:** GL postings for a sale.
- **credit_sales_ledger:** credit-sale side ledger entries.
- **sales_department:** JSON-based departmental sale record; rarely needed for analytics.

### customers
- **Purpose:** Customer master + loyalty summary.
- **Key columns:** `customer_id`, `customer_name`, `customer_number`, `shop_id`, `total_spent`, `loyalty_points`, `loyalty_tier`, `payment_method`, `last_purchase_date`.

### loyalty_transactions
- **Purpose:** Points earned/redeemed history.
- **Join:** `loyalty_transactions.customer_id = customers.customer_id`

### bank
- **Purpose:** Legacy simple bank record attached to a sale.
- **Join:** `bank.sales_id = sales.sales_id`

---

## 4. Inventory domain

### stock_item
- **Purpose:** Canonical item master.
- **Use for:** product metadata, categories, pack config, eTIMS item info, unit prices.
- **Primary key:** `id`
- **Key columns:**
  - `id` [ID]
  - `item_name`
  - `item_code`
  - `unit_price` [MONEY] — reference list price
  - `pack_price` [MONEY]
  - `pack_quantity` [QTY] ← pieces per pack (see M3)
  - `category` (eggs / chicken / farmers choice / others)
  - `stock_item_type`

### inventoryV2 (preferred)
- **Purpose:** Current inventory purchase/receipt.
- **Use for:** purchases, receipts, supplier amounts, batches, cost, payment status, VAT.
- **Primary key:** `inventoryV2_id`
- **Key columns:** `inventoryV2_id`, `itemname`, `quantity`, `metric`, `unitCost`, `totalCost`, `amountPaid`, `BatchNumber`, `Suppliername`, `created_at`, `payment_status`, `credits_amount`, `vat`.

### shop_stock_v2 (preferred)
- **Purpose:** Shop-level V2 stock.
- **Primary key:** `stockv2_id`
- **Key columns:** `stockv2_id`, `shop_id`, `inventoryv2_id`, `itemname`, `quantity`, `metric`, `BatchNumber`, `unitPrice`, `total_cost`.
- **Join:** `shop_stock_v2.inventoryv2_id = inventoryV2.inventoryV2_id`

### inventory (legacy)
- **Purpose:** Original inventory table.
- **Avoid** when V2 applies.

### shop_stock (legacy)
- **Purpose:** Original shop-level stock.
- **Avoid** when shop_stock_v2 applies.

### stock
- **Purpose:** Shop stock snapshot.
- **Warning:** Do NOT auto-join with `shop_stock` / `shop_stock_v2` — separate storage models.

### LiveStock
- **Purpose:** Live shop stock with clock-in / clock-out quantities.
- **Key columns:** `shop_id`, `item_name`, `metric`, `clock_in_quantity`, `added_stock`, `current_quantity`, `clock_out_quantity`, `mismatch_quantity`.

### Transfers & adjustments
- `transfers` (legacy), `transfers_v2` (current), `system_stock_transfer`, `shoptoshop_transfer`, `shoptransfers`
- `stock_returnv2` — V2 returns
- `stock_reconciliation` — shop reconciliation records
- `spoilt`, `spoilt_stock_ledger` — spoilage
- `broken_eggs_loging` — egg reclassification
- `cooked_items` — raw → prepared conversions
- `distribution_ledger` — GL entries for transfers

---

## 5. Purchasing / suppliers

### suppliers
- **Purpose:** Supplier master.
- **Key columns:** `supplier_id`, `supplier_name`, `supplier_location`, `phone_number`, `credit_amount`, `total_amount_received`, `kra_pin`.

### supplier_history
- **Purpose:** Supplier transaction history.
- **Use for:** supplier purchases, payment status, credit transactions.

### inventory_payments
- **Purpose:** Payments against inventory.
- **Join:** `inventory_payments.inventory_id = inventoryV2.inventoryV2_id`

### purchase_ledger_inventory
- **Purpose:** GL postings for inventory purchases.

---

## 6. Expenses / creditors

### expenses
- **Purpose:** Expense header.
- **Use for:** expense totals, counts, by-shop, payment status, creditors.
- **Key columns:** `expense_id`, `shop_id`, `user_id`, `item`, `category`, `quantity`, `totalPrice` [MONEY], `amountPaid` [MONEY], `payment_status`, `creditor_id`, `distribution_status`, `created_at`.

### expenses_ledger
- **Purpose:** Accounting postings for expenses.
- **Join:** `expenses_ledger.expense_id = expenses.expense_id`

### expense_creditors, creditors
- Two creditor master tables.
  - `expense_creditors` (newer, richer).
  - `creditors` (simpler, older).
- `expenses.creditor_id → expense_creditors.creditor_id`

### expense_category, expense_items
- Master lists for expense categorization.

### expense_distributions
- Records where an expense was split across shops.
- **Join:** `expense_distributions.original_expense_id = expenses.expense_id`

### credit_payments
- **Purpose:** Payments against expense creditors.
- **Join:** `credit_payments.expense_id = expenses.expense_id`

---

## 7. Accounting / banking

### chart_of_accounts
- **Primary key:** `id`
- **Key columns:** `code`, `name`, `type`, `statement_type`, `transaction_type`

### bank_account
- **Purpose:** Bank account master with stored balance.
- **Join:** `bank_account.chart_account_id = chart_of_accounts.id`

### banking_transaction
- **Purpose:** Bank credit/debit transactions.
- **Join:** `banking_transaction.account_id = bank_account.id`
- **Key columns:** `Transaction_type_credit`, `Transaction_type_debit`

### bank_transfers_ledger, manual_ledger, transaction, cash_deposits
- GL / cash movement tables. Use `chart_of_accounts` to resolve account IDs.

### cost_of_sale_ledger
- **Purpose:** GL entries for cost of sale.
- **Join:** `cost_of_sale_ledger.sales_id = sales.sales_id`
- **Warning:** double-entry — deduplicate by `sales_id` (see M6).

---

## 8. Employees / security

### users
- **Primary key:** `users_id`
- **Safe columns:** `users_id`, `username`, `email`, `role`, `employee_id`, `status`
- **Restricted (never return):** `password`, `two_factor_secret`, `backup_codes`

### employees
- **Primary key:** `employee_id`
- **Safe columns:** `employee_id`, `first_name`, `middle_name`, `surname`, `designation`, `role`, `department`, `account_status`, `shop_id`, `starting_date`
- **Restricted:** `national_id_number`, `kra_pin`, `personal_email`, `bank_account_number`, `date_of_birth`, `monthly_gross_salary`

### employeesLoan
- `loan_id`, `employee_id`, `loan`, `wallet_ballance`

### two_factor_auth
- **Restricted entirely.** Never query.

### permission
- Feature flags per user.

### merit_points, merit_ledger
- Employee merit/points system.

---

## 9. Shops / operations

### shops
- **Primary key:** `shops_id`
- **Key columns:** `shopname`, `location`, `shopstatus`, `report_status`

### shop_targets
- Per-shop sales targets.
- **Key columns:** `shop_id`, `target_type` (daily/weekly/monthly), `target_amount`, `current_sales`, `status`, `start_date`, `end_date`.

### clerk_reports, stock_reports
- Daily clerk and stock report submissions.

### notifications, push_subscription
- **push_subscription** is restricted for analytics.

---

## 10. eTIMS

### etims_items
- Mirror of `stock_item` for eTIMS.
- **Join:** `etims_items.local_item_id = stock_item.id`

### etims_sales
- eTIMS representation of a local sale.
- **Join (application-level):** `etims_sales.local_sale_id = sales.sales_id` — verify before relying on it.

### etims_sale_items
- Line items for eTIMS invoices.
- **Join:** `etims_sale_items.etims_sale_id = etims_sales.id`

---

## 11. Tasks

- `task_manager` — task records, assignees, status, priority, recurrence.
- `task_comments`, `task_evaluations`, `task_category`.

---

## 12. Mabanda (legacy — do not mix)

- `mabandastock`, `mabandapurchase`, `mabandasale`, `mabandaexpense`
- Separate legacy family. Only use when the question explicitly refers to Mabanda.

---

## 13. System

- `alembic_version` — migration version. Not for analytics.

---

## Appendix A — Verified foreign keys (DB-enforced)

```
bank.sales_id                             → sales.sales_id
credit_payments.expense_id                → expenses.expense_id
credit_payments.created_by                → users.users_id
etims_items.local_item_id                 → stock_item.id
etims_sale_items.etims_sale_id            → etims_sales.id
expenses.creditor_id                      → expense_creditors.creditor_id
expense_creditors.user_id                 → users.users_id
expense_distributions.original_expense_id → expenses.expense_id
expense_distributions.distributed_to_shop_id → shops.shops_id
expense_distributions.distributed_by      → users.users_id
expense_items.category_id                 → expense_category.id
inventory_payments.inventory_id           → inventoryV2.inventoryV2_id
loyalty_transactions.customer_id          → customers.customer_id
notifications.user_id                     → users.users_id
task_manager.parent_task_id               → task_manager.task_id
two_factor_auth.user_id                   → users.users_id
```

---

## Appendix B — Full column dumps

Only needed when exact SQL types matter.

### sales
`sales_id` int PK · `user_id` int · `shop_id` int · `customer_name` varchar · `customer_number` varchar · `status` varchar · `created_at` datetime · `balance` float · `note` varchar · `promocode` varchar · `delivery` tinyint · `timestamp` datetime

### sold_items
`id` bigint PK · `sales_id` int · `item_name` varchar · `quantity` float · `metric` varchar · `unit_price` float · `total_price` float · `BatchNumber` varchar · `stock_id` int · `Cost_of_sale` float · `Purchase_account` float · `LivestockDeduction` float · `stockv2_id` int · `round_off` float · `item_id` int · `is_service` tinyint · `etims_item_code` varchar

### sales_payment_methods
`id` int PK · `sale_id` int · `payment_method` varchar · `amount_paid` float · `balance` float · `transaction_code` varchar · `created_at` datetime · `discount` float · `checkout_request_id` varchar · `merchant_code` varchar · `sasapay_transaction_id` varchar · `payment_status` varchar · `result_code` varchar · `result_desc` varchar · `failure_reason` varchar · `callback_received_at` datetime · `callback_data` text

### stock_item
`id` int PK · `item_name` varchar · `item_code` varchar · `unit_price` float · `pack_price` float · `pack_quantity` int · `category` enum · `etims_item_code` varchar · `etims_synced` tinyint · `etims_sync_date` datetime · `org_country_code` varchar · `item_type_code` varchar · `tax_code` varchar · `qty_unit_code` varchar · `pkg_unit_code` varchar · `item_class_code` varchar · `initial_stock` float · `created_at` datetime · `updated_at` datetime · `stock_item_type` varchar

### inventoryV2
`inventoryV2_id` int PK · `itemname` varchar · `initial_quantity` float · `quantity` float · `metric` varchar · `unitCost` float · `totalCost` float · `amountPaid` float · `unitPrice` float · `BatchNumber` varchar · `user_id` int · `Trasnaction_type_credit` float · `Transcation_type_debit` float · `paymentRef` varchar · `Suppliername` varchar · `Supplier_location` varchar · `ballance` float · `note` text · `created_at` datetime · `source` varchar · `timestamp` datetime · `received_timestamp` datetime · `updated_at` datetime · `payment_status` varchar · `credits_amount` float · `vat` float

### shop_stock_v2
`stockv2_id` int PK · `shop_id` int · `transferv2_id` int · `total_cost` float · `itemname` varchar · `metric` varchar · `inventoryv2_id` int · `quantity` float · `BatchNumber` varchar · `unitPrice` float

### expenses
`expense_id` int PK · `user_id` int · `shop_id` int · `item` varchar · `description` varchar · `category` varchar · `quantity` float · `paidTo` varchar · `totalPrice` float · `amountPaid` float · `created_at` datetime · `source` varchar · `comments` text · `paymentRef` varchar · `payment_status` text · `creditor_id` int · `distribution_status` text

### shops
`shops_id` int PK · `shopname` varchar · `location` varchar · `employee` longtext(json) · `shopstatus` varchar · `created_at` datetime · `report_status` tinyint

### customers
`customer_id` int PK · `customer_name` varchar · `customer_number` varchar · `shop_id` int · `sales_id` int · `user_id` int · `item` varchar · `amount_paid` float · `payment_method` varchar · `created_at` datetime · `loyalty_points` int · `total_spent` decimal · `points_earned_total` int · `points_redeemed_total` int · `loyalty_tier` varchar · `last_purchase_date` datetime · `is_loyalty_registered` tinyint · `loyalty_registration_date` datetime