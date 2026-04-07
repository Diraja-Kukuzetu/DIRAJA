from flask_restful import Resource
from flask import request
from sqlalchemy import func
from datetime import datetime
from flask_jwt_extended import jwt_required
from Server.Models.Sales import Sales
from Server.Models.ChartOfAccounts import ChartOfAccounts
from Server.Models.Accounting.SalesLedger import SalesLedger
from Server.Models.Accounting.ExpensesLedger import ExpensesLedger
from Server.Models.Accounting.CostOfSalesLedger import CostOfSaleLedger
from Server.Models.Accounting.SpoiltStockLedger import SpoiltStockLedger
from Server.Models.ExpenseCategory import ExpenseCategory
from Server.Models.SoldItems import SoldItem
from app import db

class IncomeStatement(Resource):

    @jwt_required()
    def get(self):
        # -----------------------------
        # Get query params
        # -----------------------------
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        shop_id = request.args.get("shop_id")

        if not start_date or not end_date:
            return {
                "success": False,
                "message": "start_date and end_date required (YYYY-MM-DD)"
            }, 400

        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%Y-%m-%d")
            if shop_id:
                shop_id = int(shop_id)
        except ValueError:
            return {
                "success": False,
                "message": "Invalid date format or shop_id. Use YYYY-MM-DD for dates and integer for shop_id"
            }, 400

        if start_date > end_date:
            return {
                "success": False,
                "message": "start_date cannot be greater than end_date"
            }, 400

        # ==========================================
        # REVENUE SECTION
        # ==========================================
        revenue_accounts = ChartOfAccounts.query.filter_by(type="Revenue").all()
        if not revenue_accounts:
            return {
                "success": False,
                "message": "No revenue accounts found"
            }, 404

        revenue_account_ids = [acc.id for acc in revenue_accounts]

        revenue_query = db.session.query(
            SalesLedger.description,
            func.sum(SalesLedger.amount).label('total_amount')
        ).filter(
            SalesLedger.created_at.between(start_date, end_date),
            SalesLedger.credit_account_id.in_(revenue_account_ids)
        )

        if shop_id:
            revenue_query = revenue_query.filter(SalesLedger.shop_id == shop_id)

        revenue_items = revenue_query.group_by(
            SalesLedger.description
        ).order_by(
            func.sum(SalesLedger.amount).desc()
        ).all()

        revenue_list = []
        total_revenue = 0

        for item in revenue_items:
            description = item.description
            if description and description.startswith("Sales - "):
                description = description.replace("Sales - ", "Sales - ")
            
            amount = round(float(item.total_amount or 0), 2)
            revenue_list.append({
                "description": description,
                "amount": amount
            })
            total_revenue += amount
            
        # ==========================================
        # COST OF GOODS SOLD (COGS) SECTION
        # ==========================================
        # Get the Cost of Goods Sold account(s)
        cogs_accounts = ChartOfAccounts.query.filter_by(type="Cost of Goods Sold").all()

        if not cogs_accounts:
            # If no account with type "Cost of Goods Sold", try by name
            cogs_accounts = ChartOfAccounts.query.filter(
                ChartOfAccounts.name.ilike('%cost of goods sold%')
            ).all()

        cogs_account_ids = [acc.id for acc in cogs_accounts]

        # For Cost of Goods Sold, we need to get debit entries where the debit_account is a COGS account
        # This represents the cost being recognized when inventory is sold
        cogs_query = db.session.query(
            CostOfSaleLedger.description,
            func.sum(CostOfSaleLedger.amount).label('total_amount')
        ).filter(
            CostOfSaleLedger.created_at.between(start_date, end_date),
            CostOfSaleLedger.debit_account_id.in_(cogs_account_ids)  # COGS account is debited
        )

        if shop_id:
            cogs_query = cogs_query.filter(CostOfSaleLedger.shop_id == shop_id)

        cogs_items = cogs_query.group_by(
            CostOfSaleLedger.description
        ).order_by(
            func.sum(CostOfSaleLedger.amount).desc()
        ).all()

        cogs_list = []
        total_cogs = 0

        for item in cogs_items:
            amount = round(float(item.total_amount or 0), 2)
            
            # Format description to be more readable
            description = item.description
            if description and description.startswith("COGS - "):
                description = description
            elif description:
                description = f"COGS - {description}"
            else:
                description = "Cost of Goods Sold"
            
            cogs_list.append({
                "description": description,
                "amount": amount
            })
            total_cogs += amount

        # If no items found with descriptions, try to get total without grouping
        if total_cogs == 0 and cogs_account_ids:
            total_query = db.session.query(
                func.sum(CostOfSaleLedger.amount).label('total_amount')
            ).filter(
                CostOfSaleLedger.created_at.between(start_date, end_date),
                CostOfSaleLedger.debit_account_id.in_(cogs_account_ids)
            )
            
            if shop_id:
                total_query = total_query.filter(CostOfSaleLedger.shop_id == shop_id)
            
            total_cogs = total_query.scalar() or 0
            total_cogs = round(float(total_cogs), 2)
            
            if total_cogs > 0:
                if len(cogs_accounts) == 1:
                    description = cogs_accounts[0].name
                else:
                    description = "Cost of Goods Sold"
                
                cogs_list.append({
                    "description": description,
                    "amount": total_cogs
                })


        # ==========================================
        # SPOILT STOCK SECTION (Total only - Debit entries)
        # ==========================================
        # Look for accounts that might be used for spoilt stock
        possible_account_names = [
            "Spoilt Stock", 
            "Stock adjustment", 
            "Stock Adjustment",
            "Inventory Adjustment",
            "Stock Write-off",
            "Wastage",
            "Damage"
        ]
        
        spoilt_accounts = ChartOfAccounts.query.filter(
            ChartOfAccounts.name.in_(possible_account_names)
        ).all()

        # If not found by exact name, try a more flexible search
        if not spoilt_accounts:
            spoilt_accounts = ChartOfAccounts.query.filter(
                (ChartOfAccounts.name.ilike('%spoilt%')) |
                (ChartOfAccounts.name.ilike('%adjust%')) |
                (ChartOfAccounts.name.ilike('%wast%')) |
                (ChartOfAccounts.name.ilike('%damage%')) |
                (ChartOfAccounts.name.ilike('%write%')) |
                (ChartOfAccounts.name.ilike('%off%'))
            ).all()

        spoilt_account_ids = [acc.id for acc in spoilt_accounts]

        # If still no accounts found, initialize empty list
        if not spoilt_account_ids:
            spoilt_account_ids = [-1]  # Use -1 to ensure no matches

        # Build the spoilt stock query
        spoilt_query = db.session.query(
            SpoiltStockLedger.description,
            func.sum(SpoiltStockLedger.amount).label('total_amount')
        ).filter(
            SpoiltStockLedger.created_at.between(start_date, end_date),
            SpoiltStockLedger.debit_account_id.in_(spoilt_account_ids)  # Only sum debit entries
        )

        # Apply shop_id filter if provided
        if shop_id:
            spoilt_query = spoilt_query.filter(SpoiltStockLedger.shop_id == shop_id)

        # Get spoilt stock items with descriptions
        spoilt_items = spoilt_query.group_by(
            SpoiltStockLedger.description
        ).order_by(
            func.sum(SpoiltStockLedger.amount).desc()
        ).all()

        spoilt_list = []
        total_spoilt = 0

        for item in spoilt_items:
            amount = round(float(item.total_amount or 0), 2)
            description = item.description or "Spoilt Stock"
            
            # Add a prefix to identify it's spoilt stock
            if not description.lower().startswith(('spoilt', 'adjust', 'wast', 'damage')):
                description = f"Spoilt - {description}"
            
            spoilt_list.append({
                "description": description,
                "amount": amount
            })
            total_spoilt += amount

        # If no items with descriptions found, try to get at least the total
        if total_spoilt == 0 and spoilt_account_ids != [-1]:
            # Fallback: get total without grouping
            total_query = db.session.query(
                func.sum(SpoiltStockLedger.amount).label('total_amount')
            ).filter(
                SpoiltStockLedger.created_at.between(start_date, end_date),
                SpoiltStockLedger.debit_account_id.in_(spoilt_account_ids)
            )
            
            if shop_id:
                total_query = total_query.filter(SpoiltStockLedger.shop_id == shop_id)
            
            total_spoilt = total_query.scalar() or 0
            total_spoilt = round(float(total_spoilt), 2)
            
            if total_spoilt > 0:
                # Use the account name(s) for description
                if len(spoilt_accounts) == 1:
                    description = spoilt_accounts[0].name
                elif spoilt_accounts:
                    description = "Stock Adjustments (Including Spoilt)"
                else:
                    description = "Spoilt Stock"
                
                spoilt_list.append({
                    "description": description,
                    "amount": total_spoilt
                })

        # Calculate total cost of goods sold including spoilt stock
        total_cogs_including_spoilt = total_cogs + total_spoilt

        # ==========================================
        # GROSS PROFIT CALCULATION
        # ==========================================
        gross_profit = total_revenue - total_cogs_including_spoilt

        # ==========================================
        # EXPENSES SECTION
        # ==========================================
        expense_query = db.session.query(
            ExpenseCategory.category_name.label('category_name'),
            func.sum(ExpensesLedger.amount).label('total_amount')
        ).join(
            ExpenseCategory, ExpenseCategory.id == ExpensesLedger.category_id
        ).filter(
            ExpensesLedger.created_at.between(start_date, end_date)
        )

        if shop_id:
            expense_query = expense_query.filter(ExpensesLedger.shop_id == shop_id)

        expense_items = expense_query.group_by(
            ExpenseCategory.id, ExpenseCategory.category_name
        ).order_by(
            func.sum(ExpensesLedger.amount).desc()
        ).all()

        expense_list = []
        total_expenses = 0

        for item in expense_items:
            amount = round(float(item.total_amount or 0), 2)
            expense_list.append({
                "category": item.category_name,
                "amount": amount
            })
            total_expenses += amount

        # ==========================================
        # NET INCOME
        # ==========================================
        net_income = gross_profit - total_expenses

        # ==========================================
        # RESPONSE
        # ==========================================
        response = {
            "success": True,
            "period": {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d")
            },
            "revenue": {
                "items": revenue_list,
                "total": total_revenue
            },
            "cost_of_goods_sold": {
                "regular_cogs": {
                    "items": cogs_list,
                    "total": total_cogs
                },
                "spoilt_stock": {
                    "items": spoilt_list,
                    "total": total_spoilt
                },
                "total": total_cogs_including_spoilt
            },
            "gross_profit": gross_profit,
            "expenses": {
                "items": expense_list,
                "total": total_expenses
            },
            "net_income": net_income
        }

        if shop_id:
            response["shop_id"] = shop_id
        else:
            response["scope"] = "all_shops"

        return response, 200