from app import db
from Server.Models.Accounting.SalesLedger import SalesLedger
from Server.Models.Accounting.CreditSalesLedger import CreditSalesLedger
from Server.Models.ChartOfAccounts import ChartOfAccounts
from Server.Models.Accounting.PurchaseLedger import PurchaseLedgerInventory,DistributionLedger
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.TransferV2 import TransfersV2
from Server.Models.Expenses import Expenses
from Server.Models.ExpenseCategory import ExpenseCategory
from Server.Models.Accounting.ExpensesLedger import ExpensesLedger
from Server.Models.Accounting.SpoiltStockLedger import SpoiltStockLedger
from Server.Models.SpoiltStock import SpoiltStock
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.Accounting.CostOfSalesLedger import CostOfSaleLedger
from Server.Models.Accounting.BankTransferLedger import BankTransfersLedger
from Server.Models.BankAccounts import BankAccount
from datetime import datetime


class JournalService:

    @staticmethod
    def post_sale_journal(
        sale,
        sold_items,
        shop_id,
        creditor_id=None,
        amount_paid=0
    ):
        """
        Posts journal entries for sales using proper double-entry:
        - Paid → Cash DR, Revenue CR
        - Unpaid / Partial → A/R DR, Revenue CR
        - Cost of Goods Sold → Cost of Goods Sold DR, Inventory CR
        """

        # ===== ACCOUNT LOOKUPS =====
        revenue_account = ChartOfAccounts.query.filter_by(type="Revenue").first()
        receivable_account = ChartOfAccounts.query.filter_by(name="Current Asset").first()
        cash_account = ChartOfAccounts.query.filter_by(name="Cash & Bank").first()
        
        # Cost of Goods Sold account lookups
        cogs_account = ChartOfAccounts.query.filter_by(name="Cost of Goods Sold").first()
        inventory_account = ChartOfAccounts.query.filter_by(name="Inventory").first()

        if not revenue_account:
            raise Exception("Revenue account not found")
        if not cogs_account:
            raise Exception("Cost of Goods Sold account not found")
        if not inventory_account:
            raise Exception("Inventory account not found")

        created_at = sale.created_at

        # ==============================
        # POST COST OF GOODS SOLD ENTRIES (Common for all sale types)
        # ==============================
        cogs_entries = []
        cogs_journal_payload = []

        for item in sold_items:
            # Skip if no cost (e.g., livestock deduction with zero cost)
            if float(item.get('Purchase_account', 0)) <= 0:
                continue

            description = f"Cost of Goods Sold - {item['item_name']}"
            cogs_amount = float(item['Purchase_account'])

            # Find inventory_id from the batch or stock
            inventory_id = None
            if item.get('stockv2_id'):
                stock = ShopStockV2.query.filter_by(stockv2_id=item['stockv2_id']).first()
                if stock:
                    inventory_id = stock.inventoryv2_id

            if not inventory_id:
                # For livestock or if inventory not found, skip or use default
                continue

            # DR: Cost of Goods Sold
            debit_entry = CostOfSaleLedger(
                sales_id=sale.sales_id,
                inventory_id=inventory_id,
                description=description,
                debit_account_id=cogs_account.id,
                credit_account_id=None,
                amount=cogs_amount,
                shop_id=shop_id,
                created_at=created_at
            )

            # CR: Inventory
            credit_entry = CostOfSaleLedger(
                sales_id=sale.sales_id,
                inventory_id=inventory_id,
                description=description,
                debit_account_id=None,
                credit_account_id=inventory_account.id,
                amount=cogs_amount,
                shop_id=shop_id,
                created_at=created_at
            )

            cogs_entries.extend([debit_entry, credit_entry])
            
            cogs_journal_payload.append({
                "item": item['item_name'],
                "type": "debit", 
                "account": cogs_account.name, 
                "amount": cogs_amount,
                "inventory_id": inventory_id
            })
            cogs_journal_payload.append({
                "item": item['item_name'],
                "type": "credit", 
                "account": inventory_account.name, 
                "amount": cogs_amount,
                "inventory_id": inventory_id
            })

        # Add cost of goods sold entries to database
        if cogs_entries:
            db.session.add_all(cogs_entries)

        # ==============================
        # PAID SALE
        # ==============================
        if sale.status == "paid":
            if not cash_account:
                raise Exception("Cash & Bank account not found")

            entries = []
            journal_payload_entries = []

            for item in sold_items:
                description = f"Sales - {item['item_name']}"
                item_amount = float(item['total_price'])

                # DR: Cash
                debit_entry = SalesLedger(
                    sales_id=sale.sales_id,
                    description=description,
                    debit_account_id=cash_account.id,
                    credit_account_id=None,
                    amount=item_amount,
                    shop_id=shop_id,
                    created_at=created_at
                )

                # CR: Revenue
                credit_entry = SalesLedger(
                    sales_id=sale.sales_id,
                    description=description,
                    debit_account_id=None,
                    credit_account_id=revenue_account.id,
                    amount=item_amount,
                    shop_id=shop_id,
                    created_at=created_at
                )

                entries.extend([debit_entry, credit_entry])
                
                journal_payload_entries.append({
                    "item": item['item_name'],
                    "type": "debit", 
                    "account": cash_account.name, 
                    "amount": item_amount
                })
                journal_payload_entries.append({
                    "item": item['item_name'],
                    "type": "credit", 
                    "account": revenue_account.name, 
                    "amount": item_amount
                })

            db.session.add_all(entries)

            return {
                "journal_type": "sales",
                "journal_payload": {
                    "sales_id": sale.sales_id,
                    "status": sale.status,
                    "entries": journal_payload_entries
                },
                "cost_of_goods_sold": {
                    "entries": cogs_journal_payload,
                    "total_cogs": sum(float(item['Purchase_account']) for item in sold_items if float(item.get('Purchase_account', 0)) > 0)
                }
            }

        # ==============================
        # CREDIT / PARTIALLY PAID SALE
        # ==============================
        if sale.status in ["unpaid", "partially_paid"]:

            if not creditor_id:
                raise Exception("Creditor ID is required")

            if not receivable_account:
                raise Exception("Accounts Receivable account not found")

            journal_amount = (
                sale.balance
                if sale.status == "partially_paid"
                else sum(float(item['total_price']) for item in sold_items)
            )

            entries = []
            journal_payload_entries = []

            # For credit sales, we need to allocate the journal amount across items
            # This example assumes proportional allocation based on item prices
            total_sale = sum(float(item['total_price']) for item in sold_items)
            
            for item in sold_items:
                description = f"Sales - {item['item_name']}"
                
                # Calculate proportional amount for this item
                item_amount = (float(item['total_price']) / total_sale) * journal_amount
                
                # DR: Accounts Receivable
                debit_entry = CreditSalesLedger(
                    sales_id=sale.sales_id,
                    creditor_id=creditor_id,
                    description=description,
                    debit_account_id=receivable_account.id,
                    credit_account_id=None,
                    amount=item_amount,
                    shop_id=shop_id,
                    created_at=created_at
                )

                # CR: Revenue
                credit_entry = CreditSalesLedger(
                    sales_id=sale.sales_id,
                    creditor_id=creditor_id,
                    description=description,
                    debit_account_id=None,
                    credit_account_id=revenue_account.id,
                    amount=item_amount,
                    shop_id=shop_id,
                    created_at=created_at
                )

                entries.extend([debit_entry, credit_entry])
                
                journal_payload_entries.append({
                    "item": item['item_name'],
                    "type": "debit", 
                    "account": receivable_account.name, 
                    "amount": item_amount
                })
                journal_payload_entries.append({
                    "item": item['item_name'],
                    "type": "credit", 
                    "account": revenue_account.name, 
                    "amount": item_amount
                })

            db.session.add_all(entries)

            return {
                "journal_type": "credit_sales",
                "journal_payload": {
                    "sales_id": sale.sales_id,
                    "status": sale.status,
                    "creditor_id": creditor_id,
                    "entries": journal_payload_entries,
                    "balance": sale.balance
                },
                "cost_of_goods_sold": {
                    "entries": cogs_journal_payload,
                    "total_cogs": sum(float(item['Purchase_account']) for item in sold_items if float(item.get('Purchase_account', 0)) > 0)
                }
            }

        raise Exception(f"Unsupported sale status: {sale.status}")


# Optional: Add a separate method if you want to post cost of goods sold independently
@staticmethod
def post_cost_of_goods_sold(sale, sold_items, shop_id):
    """
    Standalone method to post only cost of goods sold entries
    """
    cogs_account = ChartOfAccounts.query.filter_by(name="Cost of Goods Sold").first()
    inventory_account = ChartOfAccounts.query.filter_by(name="Inventory").first()

    if not cogs_account or not inventory_account:
        raise Exception("Cost of Goods Sold or Inventory account not found")

    created_at = sale.created_at
    entries = []
    
    for item in sold_items:
        if float(item.get('Purchase_account', 0)) <= 0:
            continue

        description = f"Cost of Goods Sold - {item['item_name']}"
        cogs_amount = float(item['Purchase_account'])

        # Find inventory_id
        inventory_id = None
        if item.get('stockv2_id'):
            stock = ShopStockV2.query.filter_by(stockv2_id=item['stockv2_id']).first()
            if stock:
                inventory_id = stock.inventoryv2_id

        if not inventory_id:
            continue

        # DR: Cost of Goods Sold
        debit_entry = CostOfSaleLedger(
            sales_id=sale.sales_id,
            inventory_id=inventory_id,
            description=description,
            debit_account_id=cogs_account.id,
            credit_account_id=None,
            amount=cogs_amount,
            shop_id=shop_id,
            created_at=created_at
        )

        # CR: Inventory
        credit_entry = CostOfSaleLedger(
            sales_id=sale.sales_id,
            inventory_id=inventory_id,
            description=description,
            debit_account_id=None,
            credit_account_id=inventory_account.id,
            amount=cogs_amount,
            shop_id=shop_id,
            created_at=created_at
        )

        entries.extend([debit_entry, credit_entry])

    if entries:
        db.session.add_all(entries)
    
    return {
        "message": "Cost of goods sold entries posted successfully",
        "entries_count": len(entries) // 2,
        "total_cogs": sum(float(item['Purchase_account']) for item in sold_items if float(item.get('Purchase_account', 0)) > 0)
    }

# class JournalService:

#     @staticmethod
#     def post_sale_journal(
#         sale,
#         sold_items,
#         shop_id,
#         creditor_id=None,
#         amount_paid=0
#     ):
#         """
#         Posts journal entries for sales using proper double-entry:
#         - Paid → Cash DR, Revenue CR
#         - Unpaid / Partial → A/R DR, Revenue CR
#         """

#         # ===== ACCOUNT LOOKUPS =====
#         revenue_account = ChartOfAccounts.query.filter_by(type="Revenue").first()
#         receivable_account = ChartOfAccounts.query.filter_by(name="Current Asset").first()
#         cash_account = ChartOfAccounts.query.filter_by(name="Cash & Bank").first()

#         if not revenue_account:
#             raise Exception("Revenue account not found")

#         created_at = sale.created_at

#         # ==============================
#         # PAID SALE
#         # ==============================
#         if sale.status == "paid":
#             if not cash_account:
#                 raise Exception("Cash & Bank account not found")

#             entries = []
#             journal_payload_entries = []

#             for item in sold_items:
#                 description = f"Sales - {item['item_name']}"
#                 item_amount = float(item['total_price'])

#                 # DR: Cash
#                 debit_entry = SalesLedger(
#                     sales_id=sale.sales_id,
#                     description=description,
#                     debit_account_id=cash_account.id,
#                     credit_account_id=None,
#                     amount=item_amount,
#                     shop_id=shop_id,
#                     created_at=created_at
#                 )

#                 # CR: Revenue
#                 credit_entry = SalesLedger(
#                     sales_id=sale.sales_id,
#                     description=description,
#                     debit_account_id=None,
#                     credit_account_id=revenue_account.id,
#                     amount=item_amount,
#                     shop_id=shop_id,
#                     created_at=created_at
#                 )

#                 entries.extend([debit_entry, credit_entry])
                
#                 journal_payload_entries.append({
#                     "item": item['item_name'],
#                     "type": "debit", 
#                     "account": cash_account.name, 
#                     "amount": item_amount
#                 })
#                 journal_payload_entries.append({
#                     "item": item['item_name'],
#                     "type": "credit", 
#                     "account": revenue_account.name, 
#                     "amount": item_amount
#                 })

#             db.session.add_all(entries)

#             return {
#                 "journal_type": "sales",
#                 "journal_payload": {
#                     "sales_id": sale.sales_id,
#                     "status": sale.status,
#                     "entries": journal_payload_entries
#                 }
#             }

#         # ==============================
#         # CREDIT / PARTIALLY PAID SALE
#         # ==============================
#         if sale.status in ["unpaid", "partially_paid"]:

#             if not creditor_id:
#                 raise Exception("Creditor ID is required")

#             if not receivable_account:
#                 raise Exception("Accounts Receivable account not found")

#             journal_amount = (
#                 sale.balance
#                 if sale.status == "partially_paid"
#                 else sum(float(item['total_price']) for item in sold_items)
#             )

#             entries = []
#             journal_payload_entries = []

#             # For credit sales, we need to allocate the journal amount across items
#             # This example assumes proportional allocation based on item prices
#             total_sale = sum(float(item['total_price']) for item in sold_items)
            
#             for item in sold_items:
#                 description = f"Sales - {item['item_name']}"
                
#                 # Calculate proportional amount for this item
#                 item_amount = (float(item['total_price']) / total_sale) * journal_amount
                
#                 # DR: Accounts Receivable
#                 debit_entry = CreditSalesLedger(
#                     sales_id=sale.sales_id,
#                     creditor_id=creditor_id,
#                     description=description,
#                     debit_account_id=receivable_account.id,
#                     credit_account_id=None,
#                     amount=item_amount,
#                     shop_id=shop_id,
#                     created_at=created_at
#                 )

#                 # CR: Revenue
#                 credit_entry = CreditSalesLedger(
#                     sales_id=sale.sales_id,
#                     creditor_id=creditor_id,
#                     description=description,
#                     debit_account_id=None,
#                     credit_account_id=revenue_account.id,
#                     amount=item_amount,
#                     shop_id=shop_id,
#                     created_at=created_at
#                 )

#                 entries.extend([debit_entry, credit_entry])
                
#                 journal_payload_entries.append({
#                     "item": item['item_name'],
#                     "type": "debit", 
#                     "account": receivable_account.name, 
#                     "amount": item_amount
#                 })
#                 journal_payload_entries.append({
#                     "item": item['item_name'],
#                     "type": "credit", 
#                     "account": revenue_account.name, 
#                     "amount": item_amount
#                 })

#             db.session.add_all(entries)

#             return {
#                 "journal_type": "credit_sales",
#                 "journal_payload": {
#                     "sales_id": sale.sales_id,
#                     "status": sale.status,
#                     "creditor_id": creditor_id,
#                     "entries": journal_payload_entries,
#                     "balance": sale.balance
#                 }
#             }

#         raise Exception(f"Unsupported sale status: {sale.status}")


class PurchaseJournalService:
    """
    Service to handle journal entries for inventory purchases.
    """

    @staticmethod
    def post_purchase_journal(
        inventory: InventoryV2,
        debit_account_name: str = "Inventory",
        credit_account_name: str = "Cash & Bank"
    ):
        # ===== Account lookups =====
        debit_account = ChartOfAccounts.query.filter_by(name=debit_account_name).first()
        credit_account = ChartOfAccounts.query.filter_by(name=credit_account_name).first()

        if not debit_account:
            raise Exception(f"Debit account '{debit_account_name}' not found")

        if not credit_account:
            raise Exception(f"Credit account '{credit_account_name}' not found")

        # ===== Description =====
        description = f"Purchase of {inventory.itemname}, batch {inventory.BatchNumber}"

        amount = inventory.totalCost
        created_at = inventory.created_at

        # ===== DR: Inventory =====
        debit_entry = PurchaseLedgerInventory(
            inventory_id=inventory.inventoryV2_id,
            description=description,
            debit_account_id=debit_account.id,
            credit_account_id=None,
            amount=amount,
            created_at=created_at
        )

        # ===== CR: Cash / Payable =====
        credit_entry = PurchaseLedgerInventory(
            inventory_id=inventory.inventoryV2_id,
            description=description,
            debit_account_id=None,
            credit_account_id=credit_account.id,
            amount=amount,
            created_at=created_at
        )

        db.session.add_all([debit_entry, credit_entry])

        return {
            "journal_type": "purchase",
            "journal_payload": {
                "inventory_id": inventory.inventoryV2_id,
                "itemname": inventory.itemname,
                "batch_number": inventory.BatchNumber,
                "entries": [
                    {
                        "type": "debit",
                        "account": debit_account.name,
                        "amount": float(amount),
                    },
                    {
                        "type": "credit",
                        "account": credit_account.name,
                        "amount": float(amount),
                    }
                ],
                "created_at": created_at.isoformat(),
            }
        }



class DistributionJournalService:
    """
    Handles journal entries for inventory distribution (internal transfers).
    """
    @staticmethod
    def post_distribution_journal(
        transfer: TransfersV2,
        shop_id: int,
        debit_account_name: str = "Inventory",
        credit_account_name: str = "Inventory"
    ):
        # ===== Account lookups =====
        debit_account = ChartOfAccounts.query.filter_by(name=debit_account_name).first()
        credit_account = ChartOfAccounts.query.filter_by(name=credit_account_name).first()

        if not debit_account:
            raise Exception(f"Debit account '{debit_account_name}' not found")

        if not credit_account:
            raise Exception(f"Credit account '{credit_account_name}' not found")

        # ===== Description =====
        description = (
            f"Distribution of {transfer.itemname} "
            f"(Batch {transfer.BatchNumber}) "
            f"Qty {transfer.quantity}"
        )

        amount = transfer.total_cost
        created_at = transfer.created_at

        # ===== DR: Inventory =====
        dr_entry = DistributionLedger(
            transfer_id=transfer.transferv2_id,
            description=description,
            debit_account_id=debit_account.id,
            credit_account_id=None,
            amount=amount,
            shop_id=shop_id,
            created_at=created_at
        )

        # ===== CR: Cash / Bank =====
        cr_entry = DistributionLedger(
            transfer_id=transfer.transferv2_id,
            description=description,
            debit_account_id=None,
            credit_account_id=credit_account.id,
            amount=amount,
            shop_id=shop_id,
            created_at=created_at
        )

        db.session.add_all([dr_entry, cr_entry])

        # ===== Return payload =====
        return {
            "journal_type": "distribution",
            "journal_payload": {
                "transfer_id": transfer.transferv2_id,
                "itemname": transfer.itemname,
                "batch_number": transfer.BatchNumber,
                "quantity": transfer.quantity,
                "entries": [
                    {"side": "DR", "account": debit_account.name, "amount": float(amount)},
                    {"side": "CR", "account": credit_account.name, "amount": float(amount)},
                ],
                "created_at": created_at.isoformat()
            }
        }

# class SpoiltJournalService:
#     """
#     Handles journal entries for spoilt stock
#     and updates account balances.
#     """

#     @staticmethod
#     def post_spoilt_journal(spoilt: SpoiltStock):

#         # ===== Account lookups =====
#         expense_account = ChartOfAccounts.query.filter_by(
#             name="Stock Adjustment"   # changed from Spoilage Expense
#         ).with_for_update().first()

#         inventory_account = ChartOfAccounts.query.filter_by(
#             name="Inventory"
#         ).with_for_update().first()

#         if not expense_account:
#             raise Exception("Stock Adjustment account not found")

#         if not inventory_account:
#             raise Exception("Inventory account not found")

#         # ===== Amount logic =====
#         amount = float(spoilt.quantity)

#         description = f"Spoilt stock: {spoilt.item} ({spoilt.quantity} {spoilt.unit})"
#         created_at = spoilt.approved_at or spoilt.created_at

#         # ===== DR: Stock Adjustment =====
#         dr_entry = SpoiltStockLedger(
#             spoilt_id=spoilt.id,
#             shop_id=spoilt.shop_id,
#             description=description,
#             debit_account_id=expense_account.id,
#             credit_account_id=None,
#             amount=amount,
#             created_at=created_at
#         )

#         # ===== CR: Inventory =====
#         cr_entry = SpoiltStockLedger(
#             spoilt_id=spoilt.id,
#             shop_id=spoilt.shop_id,
#             description=description,
#             debit_account_id=None,
#             credit_account_id=inventory_account.id,
#             amount=amount,
#             created_at=created_at
#         )

#         # ===== Adjust Account Balances =====

#         # Debit increases expense account
#         expense_account.debit_balance = (
#             (expense_account.debit_balance or 0) + amount
#         )

#         # Credit increases credit side of inventory
#         inventory_account.credit_balance = (
#             (inventory_account.credit_balance or 0) + amount
#         )

#         # Optional: If you use a normal balance calculation
#         # expense_account.balance += amount
#         # inventory_account.balance -= amount

#         db.session.add_all([dr_entry, cr_entry])

#         return {
#             "journal_type": "spoilt_stock",
#             "journal_payload": {
#                 "spoilt_id": spoilt.id,
#                 "item": spoilt.item,
#                 "quantity": spoilt.quantity,
#                 "entries": [
#                     {"side": "DR", "account": expense_account.name, "amount": amount},
#                     {"side": "CR", "account": inventory_account.name, "amount": amount},
#                 ]
#             }
#         }

class SpoiltJournalService:
    """
    Handles journal entries for spoilt stock
    and updates account balances.
    """

    @staticmethod
    def post_spoilt_journal(spoilt: SpoiltStock):

        # ===== Account lookups =====
        # expense_account = ChartOfAccounts.query.filter_by(
        #     name="Stock Adjustment"   # changed from Spoilage Expense
        # ).with_for_update().first()

        inventory_account = ChartOfAccounts.query.filter_by(
            name="Inventory"
        ).with_for_update().first()

        # if not expense_account:
        #     raise Exception("Stock Adjustment account not found")

        if not inventory_account:
            raise Exception("Inventory account not found")

        # ===== Amount logic =====
        amount = float(spoilt.quantity)

        description = f"Spoilt stock: {spoilt.item} ({spoilt.quantity} {spoilt.unit})"
        created_at = spoilt.approved_at or spoilt.created_at

        # ===== DR: Stock Adjustment =====
        # dr_entry = SpoiltStockLedger(
        #     spoilt_id=spoilt.id,
        #     shop_id=spoilt.shop_id,
        #     description=description,
        #     debit_account_id=expense_account.id,
        #     credit_account_id=None,
        #     amount=amount,
        #     created_at=created_at
        # )

        # ===== CR: Inventory =====
        cr_entry = SpoiltStockLedger(
            spoilt_id=spoilt.id,
            shop_id=spoilt.shop_id,
            description=description,
            debit_account_id=None,
            credit_account_id=inventory_account.id,
            amount=amount,
            created_at=created_at
        )

        # ===== Adjust Account Balances =====

        # Debit increases expense account
        # expense_account.debit_balance = (
        #     (expense_account.debit_balance or 0) + amount
        # )

        # Credit increases credit side of inventory
        # inventory_account.credit_balance = (
        #     (inventory_account.credit_balance or 0) + amount
        # )

        # Optional: If you use a normal balance calculation
        # expense_account.balance += amount
        # inventory_account.balance -= amount

        db.session.add_all([cr_entry])

        return {
            "journal_type": "spoilt_stock",
            "journal_payload": {
                "spoilt_id": spoilt.id,
                "item": spoilt.item,
                "quantity": spoilt.quantity,
                "entries": [
                    # {"side": "DR", "account": expense_account.name, "amount": amount},
                    {"side": "CR", "account": inventory_account.name, "amount": amount},
                ]
            }
        }
        
class BankJournalService:

    @staticmethod
    def post_transfer_journal(transaction, from_account, to_account, amount):

        # Get chart accounts for both from_account and to_account
        debit_chart_account = from_account.chart_account
        credit_chart_account = to_account.chart_account

        if not debit_chart_account:
            raise Exception(f"Source account '{from_account.Account_name}' is not linked to Chart of Accounts.")

        if not credit_chart_account:
            raise Exception(f"Destination account '{to_account.Account_name}' is not linked to Chart of Accounts.")

        description = (
            f"Transfer from {from_account.Account_name} to {to_account.Account_name}"
        )

        # Credit entry (debit_account_id = null)
        credit_entry = BankTransfersLedger(
            bank_transaction_id=transaction.id,
            description=description,
            debit_account_id=None,
            credit_account_id=credit_chart_account.id,
            amount=amount,
            created_at=datetime.utcnow()
        )
        db.session.add(credit_entry)

        # Debit entry (credit_account_id = null)
        debit_entry = BankTransfersLedger(
            bank_transaction_id=transaction.id,
            description=description,
            debit_account_id=debit_chart_account.id,
            credit_account_id=None,
            amount=amount,
            created_at=datetime.utcnow()
        )
        db.session.add(debit_entry)



class ExpensesJournalService:
    """
    Service to handle journal entries for expenses.
    """

    @staticmethod
    def post_expense_journal(
        expense: Expenses,
        debit_account_name: str = "Expense",
        credit_account_name: str = "Cash & Bank"
    ):
        # ===== Account lookups =====
        debit_account = ChartOfAccounts.query.filter_by(name=debit_account_name).first()
        credit_account = ChartOfAccounts.query.filter_by(name=credit_account_name).first()

        if not debit_account:
            raise Exception(f"Debit account '{debit_account_name}' not found")

        if not credit_account:
            raise Exception(f"Credit account '{credit_account_name}' not found")

        # ===== Fetch Category (required by ledger FK) =====
        category_obj = ExpenseCategory.query.filter_by(category_name=expense.category).first()
        if not category_obj:
            raise Exception(f"Expense category '{expense.category}' not found")

        # ===== Description =====
        description = f"Expense: {expense.item}, Ref {expense.paymentRef}"

        amount = expense.amountPaid
        created_at = expense.created_at

        # ===== DR: Expense =====
        debit_entry = ExpensesLedger(
            expense_id=expense.expense_id,
            category_id=category_obj.id,
            debit_account_id=debit_account.id,
            credit_account_id=None,
            amount=amount,
            shop_id=expense.shop_id,
            created_at=created_at
        )

        # ===== CR: Cash & Bank =====
        credit_entry = ExpensesLedger(
            expense_id=expense.expense_id,
            category_id=category_obj.id,
            debit_account_id=None,
            credit_account_id=credit_account.id,
            amount=amount,
            shop_id=expense.shop_id,
            created_at=created_at
        )

        db.session.add_all([debit_entry, credit_entry])

        return {
            "journal_type": "expense",
            "journal_payload": {
                "expense_id": expense.expense_id,
                "item": expense.item,
                "entries": [
                    {
                        "type": "debit",
                        "account": debit_account.name,
                        "amount": float(amount),
                    },
                    {
                        "type": "credit",
                        "account": credit_account.name,
                        "amount": float(amount),
                    }
                ],
                "created_at": created_at.isoformat(),
            }
        }



