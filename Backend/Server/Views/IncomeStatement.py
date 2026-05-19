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
from Server.Models.SpoiltStock import SpoiltStock
from Server.Models.ExpenseCategory import ExpenseCategory
from Server.Models.SoldItems import SoldItem
from Server.Models.SpoiltStock import SpoiltStock
from app import db

class IncomeStatement(Resource):

    @jwt_required()
    def get(self):

        # ==========================================
        # REQUEST PARAMS
        # ==========================================
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
                "message": "Invalid date format or shop_id"
            }, 400

        if start_date > end_date:
            return {
                "success": False,
                "message": "start_date cannot be greater than end_date"
            }, 400

        # ==========================================
        # REVENUE
        # ==========================================
        revenue_accounts = ChartOfAccounts.query.filter_by(
            type="Revenue"
        ).all()

        revenue_account_ids = [acc.id for acc in revenue_accounts]

        revenue_query = db.session.query(
            SalesLedger.description,
            func.sum(SalesLedger.amount).label("total_amount")
        ).filter(
            SalesLedger.created_at.between(start_date, end_date),
            SalesLedger.credit_account_id.in_(revenue_account_ids)
        )

        if shop_id:
            revenue_query = revenue_query.filter(
                SalesLedger.shop_id == shop_id
            )

        revenue_items = revenue_query.group_by(
            SalesLedger.description
        ).all()

        revenue_list = []
        total_revenue = 0

        for item in revenue_items:
            amount = round(float(item.total_amount or 0), 2)

            revenue_list.append({
                "description": item.description or "Sales",
                "amount": amount
            })

            total_revenue += amount

        # ==========================================
        # COGS (Regular COGS only - no spoilt stock)
        # ==========================================
        cogs_accounts = ChartOfAccounts.query.filter(
            ChartOfAccounts.name.ilike('%cost of goods sold%')
        ).all()

        cogs_account_ids = [acc.id for acc in cogs_accounts]

        cogs_query = db.session.query(
            CostOfSaleLedger.description,
            func.sum(CostOfSaleLedger.amount).label("total_amount")
        ).filter(
            CostOfSaleLedger.created_at.between(start_date, end_date),
            CostOfSaleLedger.debit_account_id.in_(cogs_account_ids)
        )

        if shop_id:
            cogs_query = cogs_query.filter(
                CostOfSaleLedger.shop_id == shop_id
            )

        cogs_items = cogs_query.group_by(
            CostOfSaleLedger.description
        ).all()

        cogs_list = []
        total_cogs = 0

        for item in cogs_items:
            amount = round(float(item.total_amount or 0), 2)
            description = item.description or "COGS"
            cogs_list.append({
                "description": description,
                "amount": amount
            })

            product_name = description.replace("COGS - ", "")
            cogs_dict[product_name] = amount

            total_cogs += amount

        # ==========================================
        # SPOILT STOCK - PICK ONLY DEBIT ENTRIES
        # ==========================================
        # Query spoilt stock from ledger - ONLY debit entries
        spoilt_query = db.session.query(
            SpoiltStockLedger.description,
            func.sum(SpoiltStockLedger.amount).label("total_amount")
        ).filter(
            SpoiltStockLedger.created_at.between(start_date, end_date),
            SpoiltStockLedger.debit_account_id.isnot(None),
            SpoiltStockLedger.credit_account_id.is_(None)
        )

        if shop_id:
            spoilt_query = spoilt_query.filter(
                SpoiltStockLedger.shop_id == shop_id
            )

        spoilt_items = spoilt_query.group_by(
            SpoiltStockLedger.description
        ).all()
        
        spoilt_list = []
        total_spoilt = 0
        
        # Process spoilt stock from ledger
        for item in spoilt_items:
            amount = round(float(item.total_amount or 0), 2)
            if amount > 0:
                spoilt_list.append({
                    "description": item.description or "Spoilt Stock",
                    "amount": amount
                })
                total_spoilt += amount

        # ==========================================
        # GROSS PROFIT (spoilt stock NOT included in COGS)
        # ==========================================
        gross_profit = total_revenue - total_cogs

        # ==========================================
        # EXPENSES (including spoilt stock)
        # ==========================================
        expense_query = db.session.query(
            ExpenseCategory.category_name,
            func.sum(ExpensesLedger.amount).label("total_amount")
        ).join(
            ExpenseCategory,
            ExpenseCategory.id == ExpensesLedger.category_id
        ).filter(
            ExpensesLedger.created_at.between(start_date, end_date),
            ExpensesLedger.debit_account_id.isnot(None),
            ExpensesLedger.credit_account_id.is_(None)
        )

        if shop_id:
            expense_query = expense_query.filter(
                ExpensesLedger.shop_id == shop_id
            )

        expense_items = expense_query.group_by(
            ExpenseCategory.category_name
        ).all()

        expense_list = []
        total_expenses = 0

        for item in expense_items:

            amount = round(
                float(item.total_amount or 0),
                2
            )

            expense_list.append({
                "category": item.category_name,
                "amount": amount
            })

            total_expenses += amount

        # Add spoilt stock as a separate expense category
        if total_spoilt > 0:
            expense_list.append({
                "category": "Spoilt Stock",
                "amount": total_spoilt
            })
            total_expenses += total_spoilt

        expense_list.sort(key=lambda x: x["amount"], reverse=True)

        # ==========================================
        # NET INCOME
        # ==========================================
        net_income = gross_profit - total_expenses

        # ==========================================
        # RESPONSE - Maintaining backward compatibility
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
                "total": total_cogs  # Total COGS without spoilt stock
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