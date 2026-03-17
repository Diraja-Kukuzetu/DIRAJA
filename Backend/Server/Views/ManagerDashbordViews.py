from  flask_restful import Resource,reqparse
from app import db
from Server.Models.Inventory import Inventory
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.TransferV2 import  TransfersV2
from Server.Models.Transfer import Transfer
from Server.Models.Users import Users
from Server.Models.Paymnetmethods import SalesPaymentMethods
from Server.Models.Shops import Shops
from Server.Models.Shopstock import ShopStock
from Server.Models.Sales import Sales
from Server.Models.Stock import Stock
from Server.Models.SoldItems import SoldItem
from Server.Models.Employees import Employees
from Server.Models.Expenses import Expenses
from Server.Models.Transfer import Transfer
from Server.Models.SpoiltStock import SpoiltStock
from Server.Models.ShopTransfers import ShopTransfer
from Server.Models.Shoptoshoptransfer import Shoptoshoptransfer
from Server.Models.StoreReturn import ReturnsV2
from Server.Models.Mabandafarm import MabandaSale, MabandaExpense
from flask_jwt_extended import jwt_required,get_jwt_identity
from functools import wraps
from flask import jsonify,request,make_response
from sqlalchemy.orm import aliased
from sqlalchemy import extract
from sqlalchemy import or_
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
from collections import defaultdict
from flask import current_app
import traceback
from pywebpush import webpush, WebPushException
from sqlalchemy import func


def check_role(required_role):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                 return make_response( jsonify({"error": "Unauthorized access"}), 403 )       
            return fn(*args, **kwargs)
        return decorator
    return wrapper


class CountEmployees(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        countUsers =Employees.query.count()
        return {"total employees": countUsers}, 200

class TotalAmountPaidAllSales(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            period = request.args.get('period', 'today')
            today = datetime.utcnow()

            start_date_str = request.args.get('startDate')
            end_date_str = request.args.get('endDate')

            # -------------------------
            # DATE HANDLING
            # -------------------------
            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(
                        hour=23, minute=59, second=59, microsecond=999999
                    )
                except ValueError:
                    return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
            else:
                if period == 'today':
                    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)

                elif period == 'yesterday':
                    yesterday = today - timedelta(days=1)
                    start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

                elif period == 'week':
                    start_date = (today - timedelta(days=7)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)

                elif period == 'month':
                    start_date = (today - timedelta(days=30)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)

                elif period == 'alltime':
                    start_date = None
                    end_date = None

                else:
                    return {"message": "Invalid period specified"}, 400

            # -------------------------
            # BASE QUERIES
            # -------------------------

            query_paid = (
                db.session.query(func.sum(SalesPaymentMethods.amount_paid))
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
            )

            query_unpaid = (
                db.session.query(func.sum(Sales.balance))
                .filter(
                    Sales.balance > 0,
                    Sales.status.in_(["unpaid", "partially paid"])
                )
            )

            # -------------------------
            # APPLY DATE FILTER
            # -------------------------
            if start_date and end_date:
                query_paid = query_paid.filter(
                    Sales.created_at.between(start_date, end_date)
                )

                query_unpaid = query_unpaid.filter(
                    Sales.created_at.between(start_date, end_date)
                )

            total_paid = query_paid.scalar() or 0
            total_unpaid = query_unpaid.scalar() or 0
            total_sales = total_paid + total_unpaid

            # -------------------------
            # ALL TIME TOTALS
            # -------------------------

            all_time_paid = (
                db.session.query(func.sum(SalesPaymentMethods.amount_paid))
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                .scalar() or 0
            )

            all_time_unpaid = (
                db.session.query(func.sum(Sales.balance))
                .filter(
                    Sales.balance > 0,
                    Sales.status.in_(["unpaid", "partially paid"])
                )
                .scalar() or 0
            )

            all_time_sales = all_time_paid + all_time_unpaid

            return {
                "total_sales_amount": "Ksh {:,.2f}".format(total_sales),
                "total_paid": "Ksh {:,.2f}".format(total_paid),
                "total_unpaid": "Ksh {:,.2f}".format(total_unpaid),
                "all_time_total_sales_amount": "Ksh {:,.2f}".format(all_time_sales),
                "all_time_total_paid": "Ksh {:,.2f}".format(all_time_paid),
                "all_time_total_unpaid": "Ksh {:,.2f}".format(all_time_unpaid),
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching the total sales amount",
                "details": str(e)
            }, 500





class TotalAmountPaidSalesPerShop(Resource):
    @jwt_required()
    def get(self):
        # Get period and shop_id from query parameters
        period = request.args.get('period', 'today')
        shop_id = request.args.get('shop_id')

        # Validate shop_id
        if not shop_id:
            return {"message": "Shop ID is required"}, 400

        today = datetime.utcnow()
        start_date = None
        end_date = None

        # Set the start date based on the requested period
        if period == 'today':
            start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        elif period == 'date':
            date_str = request.args.get('date')
            if not date_str:
                return {"message": "Date parameter is required when period is 'date'"}, 400

            try:
                start_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        elif period == 'alltime':
            pass  # No date filtering
        else:
            return {"message": "Invalid period specified"}, 400

        try:
            # Query for total paid
            query_paid = db.session.query(
                func.sum(SalesPaymentMethods.amount_paid)
            ).join(
                Sales, Sales.sales_id == SalesPaymentMethods.sale_id
            ).filter(
                Sales.shop_id == shop_id
            )

            # Query for total unpaid (only if status is unpaid or partially_paid)
            query_unpaid = db.session.query(
                func.sum(Sales.balance)
            ).filter(
                Sales.shop_id == shop_id,
                Sales.status.in_(["unpaid", "partially_paid"])
            )

            # Apply date filters if not 'alltime'
            if period != 'alltime':
                if period == 'date':
                    query_paid = query_paid.filter(Sales.created_at.between(start_date, end_date))
                    query_unpaid = query_unpaid.filter(Sales.created_at.between(start_date, end_date))
                else:
                    query_paid = query_paid.filter(Sales.created_at >= start_date)
                    query_unpaid = query_unpaid.filter(Sales.created_at >= start_date)

            # Execute queries
            total_paid = query_paid.scalar() or 0
            total_unpaid = query_unpaid.scalar() or 0
            total_sales_amount = total_paid + total_unpaid

            return {
                "total_sales_amount": "{:,.2f}".format(total_sales_amount),
                "total_paid": "{:,.2f}".format(total_paid),
                "total_unpaid": "{:,.2f}".format(total_unpaid),
                "period": period,
                "shop_id": shop_id
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": f"Database error: {str(e)}"}, 500




class TotalAmountPaidExpenses(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        today = datetime.utcnow()
        start_date = None
        end_date = None

        # Handle custom date range
        start_date_str = request.args.get('start_date')  # Match frontend
        end_date_str = request.args.get('end_date')  # Match frontend

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            # Handle predefined periods if no custom date is provided
            period = request.args.get('period', 'today')
            if period == 'today':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today
            elif period == 'yesterday':
                start_date = (today - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = today - timedelta(days=7)
                end_date = today
            elif period == 'month':
                start_date = today - timedelta(days=30)
                end_date = today
            elif period == 'alltime':
                start_date = None
                end_date = None
            else:
                return {"message": "Invalid period specified"}, 400

        try:
            # Build query to sum the `amountPaid`
            query = db.session.query(db.func.sum(Expenses.amountPaid))

            # Apply date filtering only if start_date and end_date are defined
            if start_date and end_date:
                query = query.filter(Expenses.created_at.between(start_date, end_date))
            elif start_date:
                query = query.filter(Expenses.created_at >= start_date)

            total_amount = query.scalar() or 0

            # Format the total amount with currency symbol
            formatted_amount = "Ksh {:,.2f}".format(total_amount)

            return {"total_amount_paid": formatted_amount}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching the total expenses amount",
                "details": str(e)
            }, 500



class TotalAmountPaidPurchasesInventory (Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        today = datetime.utcnow()
        start_date = None
        end_date = None

        # Check for custom date range
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')

        if start_date_str and end_date_str:
            try:
                # Parse custom start and end dates
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            # Handle predefined periods if no custom date is provided
            period = request.args.get('period', 'today')
            if period == 'today':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today
            elif period == 'yesterday':
                start_date = (today - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = today - timedelta(days=7)
                end_date = today
            elif period == 'month':
                start_date = today - timedelta(days=30)
                end_date = today
            elif period == 'alltime':
                start_date = None
                end_date = None
            # else:
            #     return {"message": "Invalid period specified"}, 400

        try:
            # Build query to sum the `amountPaid`
            query = db.session.query(db.func.sum(InventoryV2.amountPaid))

            # Apply date filtering only if start_date and end_date are defined
            if start_date and end_date:
                query = query.filter(InventoryV2.created_at.between(start_date, end_date))
            elif start_date:
                query = query.filter(InventoryV2.created_at >= start_date)

            total_amount = query.scalar() or 0

            # Format the total amount with currency symbol
            formatted_amount = "Ksh {:,.2f}".format(total_amount)

            return {"total_amount_paid": formatted_amount}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching the total purchases amount",
                "details": str(e)
            }, 500


class TotalAmountPaidPurchases(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        today = datetime.utcnow()
        start_date = None
        end_date = None

        # Check for custom date range
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')

        if start_date_str and end_date_str:
            try:
                # Parse custom start and end dates
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            # Handle predefined periods if no custom date is provided
            period = request.args.get('period', 'today')
            if period == 'today':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today
            elif period == 'yesterday':
                start_date = (today - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = today - timedelta(days=7)
                end_date = today
            elif period == 'month':
                start_date = today - timedelta(days=30)
                end_date = today
            elif period == 'alltime':
                start_date = None
                end_date = None
            # else:
            #     return {"message": "Invalid period specified"}, 400

        try:
            # Build query to sum the `amountPaid`
            query = db.session.query(db.func.sum(TransfersV2.amountPaid))

            # Apply date filtering only if start_date and end_date are defined
            if start_date and end_date:
                query = query.filter(TransfersV2.created_at.between(start_date, end_date))
            elif start_date:
                query = query.filter(TransfersV2.created_at >= start_date)

            total_amount = query.scalar() or 0

            # Format the total amount with currency symbol
            formatted_amount = "Ksh {:,.2f}".format(total_amount)

            return {"total_amount_paid": formatted_amount}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching the total purchases amount",
                "details": str(e)
            }, 500



class CountShops(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        countShops = Shops.query.filter(Shops.shopstatus == "Active").count()
        return {"total active shops": countShops}, 200
     



class TotalAmountPaidPerShop(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        today = datetime.utcnow()
        start_date = None
        end_date = None
        period = None  # Initialize period variable

        # Check if custom date range is provided
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                period = "custom"
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            # Check if a single custom date is provided (for backward compatibility)
            date_str = request.args.get('date')
            if date_str:
                try:
                    start_date = datetime.strptime(date_str, '%Y-%m-%d').replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                    period = "custom"
                except ValueError:
                    return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
            else:
                period = request.args.get('period', 'today')

                if period == 'today':
                    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
                elif period == 'yesterday':
                    yesterday = today - timedelta(days=1)
                    start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
                elif period == 'week':
                    # Last 7 days inclusive (including today)
                    start_date = (today - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
                elif period == 'month':
                    # Last 30 days inclusive (including today)
                    start_date = (today - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
                else:
                    return {
                        "message": "Invalid period specified. Use 'today', 'yesterday', 'week', 'month', or provide start_date and end_date."
                    }, 400

        # Validate date range
        if start_date > end_date:
            return {"message": "Start date cannot be after end date."}, 400

        try:
            shops = Shops.query.filter_by(shopstatus="active").all()
            results = []
            overall_paid = 0
            overall_unpaid = 0
            
            # NEW: Track total transaction count across all shops
            overall_transaction_count = 0

            overall_payment_totals = {"sasapay": 0, "cash": 0, "not_payed": 0}

            for shop in shops:
                shop_id = shop.shops_id

                # --- Total paid for requested period ---
                total_paid = (
                    db.session.query(func.sum(SalesPaymentMethods.amount_paid))
                    .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                    .filter(Sales.shop_id == shop_id)
                    .filter(Sales.created_at.between(start_date, end_date))
                    .scalar() or 0
                )

                # --- Total unpaid (balance) for requested period ---
                total_unpaid = (
                    db.session.query(func.sum(Sales.balance))
                    .filter(Sales.shop_id == shop_id)
                    .filter(Sales.created_at.between(start_date, end_date))
                    .filter(Sales.status.in_(["unpaid", "partially paid"]))  # ✅ Only unpaid or partially paid
                    .scalar() or 0
                )

                # --- Total sales = paid + unpaid ---
                total_sales = total_paid + total_unpaid

                # --- Transaction count for the shop (number of records in salespaymentmethod table) ---
                transaction_count = (
                    db.session.query(func.count(SalesPaymentMethods.id))
                    .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                    .filter(Sales.shop_id == shop_id)
                    .filter(Sales.created_at.between(start_date, end_date))
                    .scalar() or 0
                )
                
                # Add to overall transaction count
                overall_transaction_count += transaction_count

                # --- Totals by payment method ---
                payment_totals = (
                    db.session.query(
                        SalesPaymentMethods.payment_method,
                        func.sum(SalesPaymentMethods.amount_paid).label("total")
                    )
                    .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                    .filter(Sales.shop_id == shop_id)
                    .filter(Sales.created_at.between(start_date, end_date))
                    .group_by(SalesPaymentMethods.payment_method)
                    .all()
                )

                payment_summary = {"sasapay": 0, "cash": 0, "not_payed": 0}
                for method, total in payment_totals:
                    if method == "sasapay":
                        payment_summary["sasapay"] = float(total or 0)
                        overall_payment_totals["sasapay"] += float(total or 0)
                    elif method == "cash":
                        payment_summary["cash"] = float(total or 0)
                        overall_payment_totals["cash"] += float(total or 0)

                # --- Ensure not_payed comes from Sales.balance with correct status ---
                payment_summary["not_payed"] = float(total_unpaid or 0)
                overall_payment_totals["not_payed"] += float(total_unpaid or 0)

                # --- Comparison with previous period ---
                comparison_diff = 0  # Initialize with default value
                
                # Only calculate comparison for predefined periods, not custom dates
                if period != "custom":
                    comparison_start, comparison_end = None, None
                    
                    if period == "today":
                        # For today, compare with yesterday
                        comparison_start = (start_date - timedelta(days=1))
                        comparison_end = comparison_start.replace(hour=23, minute=59, second=59, microsecond=999999)
                    elif period == "yesterday":
                        # For yesterday, compare with day before yesterday
                        comparison_start = (start_date - timedelta(days=1))
                        comparison_end = comparison_start.replace(hour=23, minute=59, second=59, microsecond=999999)
                    elif period == "week":
                        # For this week, compare with previous 7 days
                        comparison_start = (start_date - timedelta(days=7))
                        comparison_end = (start_date - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
                    elif period == "month":
                        # For this month, compare with previous 30 days
                        comparison_start = (start_date - timedelta(days=30))
                        comparison_end = (start_date - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)

                    if comparison_start and comparison_end:
                        previous_paid = (
                            db.session.query(func.sum(SalesPaymentMethods.amount_paid))
                            .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                            .filter(Sales.shop_id == shop_id)
                            .filter(Sales.created_at.between(comparison_start, comparison_end))
                            .scalar() or 0
                        )
                        previous_unpaid = (
                            db.session.query(func.sum(Sales.balance))
                            .filter(Sales.shop_id == shop_id)
                            .filter(Sales.created_at.between(comparison_start, comparison_end))
                            .filter(Sales.status.in_(["unpaid", "partially paid"]))  # ✅ Apply same filter here
                            .scalar() or 0
                        )
                        previous_total = previous_paid + previous_unpaid
                        comparison_diff = total_sales - previous_total

                overall_paid += total_paid
                overall_unpaid += total_unpaid

                results.append({
                    "shop_id": shop_id,
                    "shop_name": shop.shopname,
                    "total_paid": "Ksh {:,.2f}".format(total_paid),
                    "total_unpaid": "Ksh {:,.2f}".format(total_unpaid),
                    "total_sales": "Ksh {:,.2f}".format(total_sales),
                    "transaction_count": transaction_count,  # Add transaction count per shop
                    "payment_breakdown": payment_summary,
                    "comparison": comparison_diff
                })

            # --- Overall summary ---
            overall_total_sales = overall_paid + overall_unpaid
            overall_avg = overall_total_sales / len(shops) if shops else 0
            summary = {
                "overall_total_sales": "Ksh {:,.2f}".format(overall_total_sales),
                "overall_total_paid": "Ksh {:,.2f}".format(overall_paid),
                "overall_total_unpaid": "Ksh {:,.2f}".format(overall_unpaid),
                "average_per_shop": "Ksh {:,.2f}".format(overall_avg),
                "overall_payment_breakdown": {
                    "sasapay": "Ksh {:,.2f}".format(overall_payment_totals["sasapay"]),
                    "cash": "Ksh {:,.2f}".format(overall_payment_totals["cash"]),
                    "not_payed": "Ksh {:,.2f}".format(overall_payment_totals["not_payed"])
                },
                "transaction_count": overall_transaction_count  # NEW: Add overall transaction count to summary
            }

            return {"total_sales_per_shop": results, "summary": summary}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching total sales amounts for all shops",
                "details": str(e)
            }, 500





class StockAlert(Resource):
    @jwt_required()
    def get(self):
        low_stock_threshold = 50
        out_of_stock_threshold = 0
        shop_name = request.args.get('shop')  # Filter by shop name if provided

        try:
            # Query ShopStock data, optionally filtered by shop name if provided
            if shop_name:
                # Query ShopStock with a join on Shops to get shop names
                shop_stock_items = db.session.query(ShopStock, Shops.shopname, ShopStock.itemname).join(
                    Shops, Shops.shops_id == ShopStock.shop_id).filter(Shops.shopname == shop_name).all()
            else:
                shop_stock_items = db.session.query(ShopStock, Shops.shopname, ShopStock.itemname).join(
                    Shops, Shops.shops_id == ShopStock.shop_id).all()

            # Create a dictionary to group items by shop and item name
            grouped_items = {}

            for stock, shopname, itemname in shop_stock_items:
                key = (shopname, itemname)  # Use shop name and item name as the key
                if key not in grouped_items:
                    grouped_items[key] = 0
                grouped_items[key] += stock.quantity  # Sum up the quantities for the same item

            # Identify low stock items
            low_stock_items = [
                {
                    "item": item_name,
                    "shop": shop_name,
                    "status": "low stock",
                    "classname": "low-stock"
                }
                for (shop_name, item_name), total_quantity in grouped_items.items()
                if low_stock_threshold >= total_quantity > out_of_stock_threshold
            ]

            # Identify out of stock items
            out_of_stock_items = [
                {
                    "item": item_name,
                    "shop": shop_name,
                    "status": "out of stock",
                    "classname": "out-of-stock"
                }
                for (shop_name, item_name), total_quantity in grouped_items.items()
                if total_quantity == out_of_stock_threshold
            ]

            # Return response with categorized stock data
            return jsonify({
                "low_stock_items": low_stock_items,
                "out_of_stock_items": out_of_stock_items
            })

        except SQLAlchemyError as e:
            # Handle database query errors and log the error message
            current_app.logger.error(f"Error fetching shop stock data: {str(e)}")
            return {"error": "Unable to fetch shop stock data"}, 500



class TotalSalesByShop(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, shop_id):
        today = datetime.utcnow()
        start_date = None
        end_date = None

        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        offset = (page - 1) * limit

        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            period = request.args.get('period', 'today')
            if period == 'today':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'yesterday':
                yesterday = today - timedelta(days=1)
                start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = (today - timedelta(days=6)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'month':
                start_date = (today - timedelta(days=29)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                return {
                    "message": "Invalid period specified. Use 'today', 'yesterday', 'week', 'month', "
                               "or provide start_date and end_date."
                }, 400

        try:
            shop = Shops.query.filter_by(shops_id=shop_id).first()
            if not shop:
                return {"message": "Shop not found."}, 404

            # --------- Helpers: case-insensitive aliases ----------
            sasapay_aliases = ['sasapay', 'sasa pay', 'sasa-pay', 'sasa_pay']
            cash_aliases = ['cash', 'cash payment', 'cash-pay', 'cash_pay']

            sasapay_aliases_l = [s.lower() for s in sasapay_aliases]
            cash_aliases_l = [s.lower() for s in cash_aliases]

            # --------- Totals by method ----------
            sasapay_total = (
                db.session.query(db.func.coalesce(db.func.sum(SalesPaymentMethods.amount_paid), 0.0))
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                .filter(
                    Sales.shop_id == shop_id,
                    Sales.created_at.between(start_date, end_date),
                    db.func.lower(SalesPaymentMethods.payment_method).in_(sasapay_aliases_l)
                )
                .scalar() or 0.0
            )

            cash_total = (
                db.session.query(db.func.coalesce(db.func.sum(SalesPaymentMethods.amount_paid), 0.0))
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                .filter(
                    Sales.shop_id == shop_id,
                    Sales.created_at.between(start_date, end_date),
                    db.func.lower(SalesPaymentMethods.payment_method).in_(cash_aliases_l)
                )
                .scalar() or 0.0
            )

            grand_total_paid = (
                db.session.query(db.func.coalesce(db.func.sum(SalesPaymentMethods.amount_paid), 0.0))
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                .filter(
                    Sales.shop_id == shop_id,
                    Sales.created_at.between(start_date, end_date),
                )
                .scalar() or 0.0
            )

            # ✅ Only unpaid or partially_paid count as credit
            credit_total = (
                db.session.query(db.func.coalesce(db.func.sum(Sales.balance), 0.0))
                .filter(
                    Sales.shop_id == shop_id,
                    Sales.created_at.between(start_date, end_date),
                    Sales.balance > 0,
                    Sales.status.in_(["unpaid", "partially_paid"])
                )
                .scalar() or 0.0
            )

            # --------- TRANSACTION COUNT ----------
            # Count total number of transactions (payment records) for the shop in the selected period
            transaction_count = (
                db.session.query(db.func.count(SalesPaymentMethods.id))
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                .filter(
                    Sales.shop_id == shop_id,
                    Sales.created_at.between(start_date, end_date)
                )
                .scalar() or 0
            )

            # Get total count for pagination
            total_records = Sales.query.filter(
                Sales.shop_id == shop_id,
                Sales.created_at.between(start_date, end_date)
            ).count()

            # --------- Sales records with pagination ----------
            sales_records = Sales.query.filter(
                Sales.shop_id == shop_id,
                Sales.created_at.between(start_date, end_date)
            ).order_by(Sales.created_at.desc()).offset(offset).limit(limit).all()

            sales_list = []
            for sale in sales_records:
                user = Users.query.filter_by(users_id=sale.user_id).first()
                username = user.username if user else "Unknown User"

                payment_data = [
                    {
                        "payment_method": p.payment_method,
                        "amount_paid": float(p.amount_paid) if p.amount_paid else 0,
                        "balance": float(p.balance) if p.balance else 0,
                        "transaction_code": p.transaction_code,
                    }
                    for p in sale.payment
                ]

                total_amount_paid = sum((pd["amount_paid"] or 0) for pd in payment_data)

                sold_items = [
                    {
                        "item_name": it.item_name,
                        "quantity": float(it.quantity) if it.quantity else 0,
                        "metric": it.metric,
                        "unit_price": float(it.unit_price) if it.unit_price else 0,
                        "total_price": float(it.total_price) if it.total_price else 0,
                        "batch_number": it.BatchNumber,
                        "stockv2_id": it.stockv2_id,
                        "cost_of_sale": float(it.Cost_of_sale) if it.Cost_of_sale else 0,
                        "purchase_account": it.Purchase_account,
                    }
                    for it in sale.items
                ]

                sales_list.append({
                    "sale_id": sale.sales_id,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "user_id": sale.user_id,
                    "username": username,
                    "customer_name": sale.customer_name or "Walk-in Customer",
                    "status": sale.status,
                    "customer_number": sale.customer_number,
                    "items": sold_items,
                    "total_amount_paid": float(total_amount_paid),
                    "payment_methods": payment_data,
                    "balance": float(sale.balance) if sale.balance else 0,
                    "note": sale.note,
                    "delivery": bool(sale.delivery),
                    "promocode": sale.promocode
                })

            total_sales = grand_total_paid + credit_total

            return {
                "shop_id": shop_id,
                "shop_name": shop.shopname,
                "total_sales_amount_paid": f"Ksh {grand_total_paid:,.2f}",
                "total_sasapay": float(sasapay_total),
                "total_cash": float(cash_total),
                "total_credit": float(credit_total),
                "total_sales": f"Ksh {total_sales:,.2f}",
                "transaction_count": transaction_count,  # ADDED: Total transaction count
                "formatted": {
                    "sasapay": f"Ksh {sasapay_total:,.2f}",
                    "cash": f"Ksh {cash_total:,.2f}",
                    "credit": f"Ksh {credit_total:,.2f}",
                    "total_sales": f"Ksh {total_sales:,.2f}",
                },
                "sales_records": sales_list,
                "start_date": start_date.strftime('%Y-%m-%d %H:%M:%S'),
                "end_date": end_date.strftime('%Y-%m-%d %H:%M:%S'),
                "pagination": {
                    "current_page": page,
                    "per_page": limit,
                    "total_records": total_records,
                    "total_pages": (total_records + limit - 1) // limit
                }
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching total sales for the shop",
                "details": str(e)
            }, 500



class TotalUnpaidAmountAllSales(Resource):
    @jwt_required()
    def get(self):
        today = datetime.utcnow()
        start_date = None
        end_date = None

        # Check if a custom date range is provided with startDate and endDate
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            # Handle period if no custom dates are provided
            period = request.args.get('period', 'today')

            if period == 'today':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'yesterday':
                yesterday_date = today - timedelta(days=1)
                start_date = yesterday_date.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = yesterday_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = today - timedelta(days=7)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=0)
            elif period == 'month':
                start_date = today - timedelta(days=30)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=0)
            elif period == 'alltime':
                start_date = None
                end_date = None
            else:
                return {"message": "Invalid period specified"}, 400

        try:
            # Query to sum up balances for partially_paid or unpaid sales within the date range
            query = (
                db.session.query(db.func.sum(Sales.balance))
                .filter(Sales.created_at.between(start_date, end_date))
                .filter(Sales.status.in_(["partially_paid", "unpaid"]))
            )

            total_unpaid = query.scalar() or 0

            # Format the total unpaid amount with currency formatting
            formatted_unpaid = "Ksh {:,.2f}".format(total_unpaid)
            
            return {"total_unpaid_amount": formatted_unpaid}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching the total unpaid amount", 
                "details": str(e)
            }, 500


            
            
# Credit sales total amoount card on the clerks' dashboard

class TotalUnpaidAmountPerClerk(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get the logged-in clerk's user ID from the token
            clerk_id = get_jwt_identity()
            
            if not clerk_id:
                return {"message": "Unauthorized"}, 401

            today = datetime.utcnow()
            start_date = None
            end_date = None

            # Check if a custom date is provided
            date_str = request.args.get('date')
            if date_str:
                try:
                    start_date = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                except ValueError:
                    return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
            else:
                # Check for start_date and end_date
                start_date_str = request.args.get('start_date')
                end_date_str = request.args.get('end_date')

                if start_date_str and end_date_str:
                    try:
                        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
                    except ValueError:
                        return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
                else:
                    # Default period filter
                    period = request.args.get('period', 'today')

                    if period == 'today':
                        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
                    elif period == 'yesterday':
                        yesterday_date = today - timedelta(days=1)
                        start_date = yesterday_date.replace(hour=0, minute=0, second=0, microsecond=0)
                        end_date = yesterday_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                    elif period == 'week':
                        start_date = today - timedelta(days=7)
                        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
                    elif period == 'month':
                        start_date = today - timedelta(days=30)
                        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
                    else:
                        return {"message": "Invalid period specified"}, 400

            # Query to sum unpaid balances for this clerk only
            total_unpaid = (
                db.session.query(db.func.sum(Sales.balance))
                .filter(Sales.created_at.between(start_date, end_date))
                .filter(Sales.status.in_(["partially_paid", "unpaid"]))
                .filter(Sales.user_id == clerk_id)  # Filter by logged-in clerk
                .scalar() or 0
            )

            formatted_unpaid = "{:,.2f}".format(total_unpaid)

            return {"total_unpaid_amount": formatted_unpaid}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching the total unpaid amount",
                "details": str(e)
            }, 500



class TotalAmountPaidForMabanda(Resource):
    @jwt_required()
    def get(self):
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = None
        end_date = None

        # Fetch start_date and end_date from query params
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
       
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD for start_date and end_date."}, 400
        else:
            # No custom start and end date provided; check period parameter
            period = request.args.get('period', 'today')

            if period == 'today':
                start_date = today
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'yesterday':
                start_date = today - timedelta(days=1)
                end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = today - timedelta(days=7)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'month':
                start_date = today - timedelta(days=30)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                return {"message": "Invalid period specified. Use 'today', 'yesterday', 'week', 'month' or specify start_date and end_date."}, 400

        try:
            # Fetch total sales amount
            total_sales = (
                db.session.query(db.func.sum(MabandaSale.amount_paid))
                .filter(MabandaSale.shop_id == 12)
                .filter(MabandaSale.sale_date >= start_date, MabandaSale.sale_date <= end_date)
                .scalar() or 0
            )
            formatted_sales = "Ksh {:,.2f}".format(total_sales)

            # Fetch all sales data within the given date range
            sales_records = (
            db.session.query(MabandaSale)
            .filter(MabandaSale.shop_id == 12)
            .filter(MabandaSale.sale_date >= start_date, MabandaSale.sale_date <= end_date)
            .order_by(MabandaSale.sale_date.desc())
            .all()  
            )

            # Serialize the sales data
            sales_data = [
                {
                    "id": sale.mabandasale_id,
                    "sale_date": sale.sale_date.strftime('%Y-%m-%d'),
                    "amount_paid": "Ksh {:,.2f}".format(sale.amount_paid),
                    "item_name": sale.itemname,  # Assuming you have this field
                    "quantity": sale.quantity_sold,    # Assuming you have this field
                }
                for sale in sales_records
            ]

            return {
                "shop_id": 12,
                "total_sales_amount_paid": formatted_sales,
                "start_date": start_date.strftime('%Y-%m-%d'),
                "end_date": end_date.strftime('%Y-%m-%d'),
                "sales_data": sales_data  # Returning the individual sales records
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "An error occurred while fetching total sales amount", "details": str(e)}, 500

        
        

class TotalExpensesForMabanda(Resource):
    @jwt_required()
    def get(self):
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Get query parameters
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        period = request.args.get('period', 'today')

        # If both start_date and end_date are provided, use them
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400

        # If only one date is provided, return an error
        elif start_date_str or end_date_str:
            return {"message": "Both start_date and end_date must be provided."}, 400

        # If no date range is provided, fallback to period-based filtering
        else:
            if period == 'today':
                start_date = today
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'yesterday':
                start_date = today - timedelta(days=1)
                end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = today - timedelta(days=7)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'month':
                start_date = today - timedelta(days=30)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                return {"message": "Invalid period specified. Use 'today', 'yesterday', 'week', 'month', or provide start_date and end_date."}, 400

        try:
            # Query total expenses
            total_expenses = (
                db.session.query(db.func.sum(MabandaExpense.amount))
                .filter(MabandaExpense.shop_id == 12)
                .filter(MabandaExpense.expense_date >= start_date, MabandaExpense.expense_date <= end_date)
                .scalar() or 0  # Default to 0 if no expenses found
            )

            # Query individual expense records
            expense_records = (
                db.session.query(MabandaExpense)
                .filter(MabandaExpense.shop_id == 12)
                .filter(MabandaExpense.expense_date >= start_date, MabandaExpense.expense_date <= end_date)
                .all()
            )

            formatted_expenses = "Ksh {:,.2f}".format(total_expenses)

            return {
                "shop_id": 12,
                "total_expenses_amount": formatted_expenses,
                "start_date": start_date.strftime('%Y-%m-%d'),
                "end_date": end_date.strftime('%Y-%m-%d'),
                "expenses_records": [
                    {
                        "description": expense.description,
                        "amount": "Ksh {:,.2f}".format(expense.amount),
                        "expense_date": expense.expense_date.strftime('%Y-%m-%d')
                    }
                    for expense in expense_records
                ]
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "An error occurred while fetching expenses", "details": str(e)}, 500
    

class SalesSummary(Resource):
    def get(self):
        # Assuming shop_id and batch_number are provided as query parameters
        shop_id = request.args.get('shop_id', type=int)  # Get shop_id from request params
        batch_number = request.args.get('batch_number', type=str)  # Get batch_number from request params

        # Query to calculate the total sales, remaining quantity for each item,
        # and total amount paid from SalesPaymentMethods for a specific shop and batch
        summary = db.session.query(
            ShopStock.itemname,
            ShopStock.BatchNumber,
            ShopStock.metric,  # Include the metric from the ShopStock table
            Transfer.quantity.label('initial_quantity_transferred'),  # Initial quantity transferred from the Transfer table
            (Transfer.quantity - ShopStock.quantity).label('total_quantity_sold'),  # Subtraction for total_quantity_sold
            (Transfer.quantity * Transfer.unitCost).label('purchase_value'),  # Purchase value as Transfer.quantity * Transfer.unitCost
            ShopStock.quantity.label('remaining_quantity'),  # Remaining quantity based on ShopStock.quantity
            ShopStock.shop_id  # Include the shop_id for grouping
        ).join(Sales, Sales.BatchNumber == ShopStock.BatchNumber) \
         .join(Transfer, Transfer.inventory_id == ShopStock.inventory_id)  # Join with Transfer to get initial quantity transferred

        # Apply filters for shop_id and batch_number (if provided)
        if shop_id:
            summary = summary.filter(ShopStock.shop_id == shop_id)  # Filter by shop_id
        if batch_number:
            summary = summary.filter(ShopStock.BatchNumber == batch_number)  # Filter by batch_number

        # Group by shop_id and batch_number to ensure total_amount_paid is specific to each
        summary = summary.group_by(
            ShopStock.itemname,
            ShopStock.BatchNumber,
            ShopStock.metric,
            Transfer.quantity,
            ShopStock.shop_id
        ).all()  # Get all the results

        # Now query Sales and SalesPaymentMethods to calculate the total_amount_paid for each combination of batch_number and shop_id
        total_payments = db.session.query(
            Sales.BatchNumber,
            Sales.shop_id,
            func.sum(SalesPaymentMethods.amount_paid).label('total_amount_paid')  # Summing the amount_paid
        ).join(SalesPaymentMethods, Sales.sales_id == SalesPaymentMethods.sale_id)  # Join with SalesPaymentMethods to get the amount_paid
        if shop_id:
            total_payments = total_payments.filter(Sales.shop_id == shop_id)  # Filter by shop_id
        if batch_number:
            total_payments = total_payments.filter(Sales.BatchNumber == batch_number)  # Filter by batch_number
        
        total_payments = total_payments.group_by(Sales.BatchNumber, Sales.shop_id).all()  # Group by batch_number and shop_id
        
        # Now, build the response by combining the summary data with the total payments
        response = []
        for item in summary:
            # Find the total_amount_paid for this batch_number and shop_id
            total_paid_for_batch = next((payment.total_amount_paid for payment in total_payments 
                                         if payment.BatchNumber == item.BatchNumber and payment.shop_id == item.shop_id), 0.0)
            
            response.append({
                "item_name": item.itemname,
                "batch_number": item.BatchNumber,
                "metric": item.metric,
                "initial_quantity_transferred": round(item.initial_quantity_transferred, 2),
                "total_quantity_sold": round(item.total_quantity_sold, 2),
                "purchase_value": round(item.purchase_value, 2),
                "total_amount_paid": round(total_paid_for_batch, 2),  # Total amount paid for this specific batch and shop
                "remaining_quantity": round(item.remaining_quantity, 2),
                "shop_id": item.shop_id
            })

        return jsonify(response)



class TotalFinancialSummary(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        today = datetime.utcnow()
        start_date = None
        end_date = None

        # Handle custom date range
        start_date_str = request.args.get('startDate')
        end_date_str = request.args.get('endDate')
        period = request.args.get('period', 'today')

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            # Predefined period filters
            if period == 'today':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'yesterday':
                yesterday = today - timedelta(days=1)
                start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'week':
                start_date = (today - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'month':
                start_date = (today - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif period == 'alltime':
                start_date = None
                end_date = None
            else:
                return {"message": "Invalid period specified"}, 400

        try:
            # ========== 1. Total Sales ========== 
            sales_query = (
                db.session.query(db.func.sum(SalesPaymentMethods.amount_paid))
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
            )
            if start_date and end_date:
                sales_query = sales_query.filter(Sales.created_at.between(start_date, end_date))
            total_sales = sales_query.scalar() or 0

            # ========== 2. Total Expenses ========== 
            expenses_query = db.session.query(db.func.sum(Expenses.amountPaid))
            if start_date and end_date:
                expenses_query = expenses_query.filter(Expenses.created_at.between(start_date, end_date))
            total_expenses = expenses_query.scalar() or 0

            # ========== 3. Total Inventory Purchases ========== 
            inventory_query = db.session.query(db.func.sum(Transfer.amountPaid))
            if start_date and end_date:
                inventory_query = inventory_query.filter(Transfer.created_at.between(start_date, end_date))
            total_inventory = inventory_query.scalar() or 0

            # ========== 4. Total Unsold Goods Value (Stock Table Only) ========== 
            remaining_stock_value = db.session.query(
                db.func.sum(ShopStock.quantity * Transfer.unitCost)
            ).join(Transfer, Transfer.transfer_id == ShopStock.transfer_id).scalar() or 0


            # ========== 5. Value of Sold Goods ========== 
            value_of_sold_goods = total_inventory - remaining_stock_value

            # ========== Format Response ========== 
            response = {
                "total_sales_amount_paid": "Ksh {:,.2f}".format(total_sales),
                "total_expenses_amount_paid": "Ksh {:,.2f}".format(total_expenses),
                "total_inventory_purchases_amount_paid": "Ksh {:,.2f}".format(total_inventory),
                "remaining_stock_value": "Ksh {:,.2f}".format(remaining_stock_value),
                "value_of_sold_goods": "Ksh {:,.2f}".format(value_of_sold_goods),
            }

            return response, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching the financial summary.",
                "details": str(e)
            }, 500

class StockMovement(Resource):
    @jwt_required()
    def get(self):
        # Set up request parser to parse from args (query parameters) instead of JSON
        parser = reqparse.RequestParser()
        parser.add_argument('shop_id', type=int, help='Filter by specific shop ID', location='args')
        parser.add_argument('days', type=int, default=30, help='Number of days to look back (ignored if from_date & end_date are provided)', location='args')
        parser.add_argument('from_date', type=str, help='Start date in YYYY-MM-DD format', location='args')
        parser.add_argument('end_date', type=str, help='End date in YYYY-MM-DD format', location='args')
        args = parser.parse_args()

        shop_id = args['shop_id']
        days = args['days']
        from_date = args['from_date']
        end_date_arg = args['end_date']

        try:
            # Calculate date range
            if from_date and end_date_arg:
                start_date = datetime.strptime(from_date, "%Y-%m-%d")
                end_date = datetime.strptime(end_date_arg, "%Y-%m-%d") + timedelta(days=1)
                period_label = f"{from_date} to {end_date_arg}"
            else:
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)
                period_label = f"Last {days} days"

            # Initialize response
            response = {
                'time_period': period_label,
                'transfers': [],
                'spoilt_items': [],
                'returns': [],
                'shop_transfers': []
            }
            if shop_id:
                response['shop_id'] = shop_id

            # Get all shops for name lookup
            shops = Shops.query.all()
            shop_name_map = {shop.shops_id: shop.shopname for shop in shops}
            shop_id_map = {shop.shopname: shop.shops_id for shop in shops}  # Reverse mapping for name to ID

            # Helper function to get shop name
            def get_shop_name(shop_id):
                return shop_name_map.get(shop_id, f"Shop {shop_id}")

            # Helper function to get shop ID from name
            def get_shop_id(shop_name):
                return shop_id_map.get(shop_name)

            # --- Transfers ---
            transfer_filters = [
                TransfersV2.created_at >= start_date,
                TransfersV2.created_at < end_date
            ]
            if shop_id:
                transfer_filters.append(TransfersV2.shop_id == shop_id)
            
           

            for transfer in TransfersV2.query.filter(*transfer_filters).all():
                response['transfers'].append({
                    'type': 'inventory_transfer',
                    'id': transfer.transferv2_id,
                    'item_name': transfer.itemname,
                    'status':transfer.status,
                    'quantity': transfer.quantity,
                    'metric': transfer.metric,
                    'batch_number': transfer.BatchNumber,
                    'unit_cost': transfer.unitCost,
                    'total_cost': transfer.total_cost,
                    'created_at': transfer.created_at.isoformat(),
                    'source': 'inventory',
                    'destination': get_shop_name(transfer.shop_id),
                    'shop_id': transfer.shop_id,
                    'shop_name': get_shop_name(transfer.shop_id)
                })

            # --- Spoilt Items ---
            spoilt_filters = [
                SpoiltStock.created_at >= start_date,
                SpoiltStock.created_at < end_date
            ]
            if shop_id:
                spoilt_filters.append(SpoiltStock.shop_id == shop_id)

            for item in SpoiltStock.query.filter(*spoilt_filters).all():
                response['spoilt_items'].append({
                    'type': 'spoilt_item',
                    'id': item.id,
                    'item_name': item.item,
                    'quantity': item.quantity,
                    'metric': item.unit,
                    'disposal_method': item.disposal_method,
                    'collector_name': item.collector_name,
                    'comment': item.comment,
                    'created_at': item.created_at.isoformat(),
                    'location': get_shop_name(item.shop_id),
                    'shop_id': item.shop_id,
                    'shop_name': get_shop_name(item.shop_id)
                })

            # --- Returns ---
            return_filters = [
                ReturnsV2.return_date >= start_date,
                ReturnsV2.return_date < end_date
            ]
            if shop_id:
                return_filters.append(ReturnsV2.shop_id == shop_id)

            for ret in ReturnsV2.query.filter(*return_filters).all():
                response['returns'].append({
                    'type': 'return',
                    'id': ret.returnv2_id,
                    'item_name': ret.inventory.itemname if ret.inventory else 'Unknown',
                    'quantity': ret.quantity,
                    'reason': ret.reason,
                    'created_at': ret.return_date.isoformat(),
                    'source': get_shop_name(ret.shop_id),
                    'destination': 'inventory',
                    'shop_id': ret.shop_id,
                    'shop_name': get_shop_name(ret.shop_id)
                })

            # --- Shop Transfers ---
            # Only show shop transfers that involve the current shop (either as source or destination)
            shop_transfer_filters = [
                Shoptoshoptransfer.transfer_date >= start_date,
                Shoptoshoptransfer.transfer_date < end_date
            ]
            
            if shop_id:
                # Filter for transfers where the current shop is either the source or destination
                shop_transfer_filters.append(or_(
                    Shoptoshoptransfer.from_shop_id == shop_id,  # Outgoing transfers
                    Shoptoshoptransfer.to_shop_id == shop_id     # Incoming transfers
                ))

            for transfer in Shoptoshoptransfer.query.filter(*shop_transfer_filters).all():
                # Get source and destination shop names
                source_shop_name = get_shop_name(transfer.from_shop_id)
                destination_shop_name = get_shop_name(transfer.to_shop_id)
                
                # Determine direction based on current shop
                is_outgoing = transfer.from_shop_id == shop_id
                is_incoming = transfer.to_shop_id == shop_id
                
                direction = 'outgoing' if is_outgoing else 'incoming'
                
                response['shop_transfers'].append({
                    'type': 'shop_transfer',
                    'id': transfer.transfer_id,
                    'item_name': transfer.itemname,
                    'quantity': transfer.quantity,
                    'metric': transfer.metric,
                    'created_at': transfer.transfer_date.isoformat(),
                    'source': source_shop_name,
                    'destination': destination_shop_name,
                    'direction': direction,
                    'shop_id': shop_id,
                    'shop_name': get_shop_name(shop_id),
                    'source_shop_id': transfer.from_shop_id,
                    'destination_shop_id': transfer.to_shop_id,
                    'source_shop_name': source_shop_name,
                    'destination_shop_name': destination_shop_name,
                    'status': transfer.status
                })

            # ✅ Return the response dictionary directly
            return response, 200

        except Exception as e:
            return {
                "message": "Error retrieving stock movement data",
                "error": str(e)
            }, 500
        


class MonthlyIncome(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            # Query total per month for the current year
            results = (
                db.session.query(
                    extract('month', Sales.created_at).label("month"),
                    db.func.sum(SalesPaymentMethods.amount_paid).label("total_income")
                )
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                .group_by(extract('month', Sales.created_at))
                .order_by(extract('month', Sales.created_at))
                .all()
            )

            # Format data
            data = [
                {"month": int(month), "total_income": float(total or 0)}
                for month, total in results
            ]

            return {"monthly_income": data}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": str(e)}, 500
            
class GetInventoryStock(Resource):
    @jwt_required()
    def get(self):
        try:
            # Optional filters
            supplier_name = request.args.get('supplier_name', type=str)
            item_name = request.args.get('item_name', type=str)
            
            # Query from InventoryV2 - group only by itemname and metric
            query = db.session.query(
                InventoryV2.itemname,
                InventoryV2.metric,
                func.sum(InventoryV2.quantity).label("total_quantity"),
                func.avg(InventoryV2.unitCost).label("average_unit_cost"),
                func.count(InventoryV2.BatchNumber).label("batch_count")
            ).filter(
                InventoryV2.quantity > 0  # Only items with stock remaining
            )

            # Optional filters
            if supplier_name:
                query = query.filter(InventoryV2.Suppliername.ilike(f'%{supplier_name}%'))
            
            if item_name:
                query = query.filter(InventoryV2.itemname.ilike(f'%{item_name}%'))

            # Group by item and metric only (not by supplier/location)
            inventory_stock = query.group_by(
                InventoryV2.itemname, 
                InventoryV2.metric
            ).all()

            # Prepare list with aggregated information
            inventory_stock_list = [
                {
                    "itemname": itemname,
                    "metric": metric,
                    "total_remaining": round(total_quantity, 3),
                    "average_unit_cost": round(average_unit_cost, 2),
                    "batch_count": batch_count,
                    "total_value": round(total_quantity * average_unit_cost, 2)
                }
                for itemname, metric, total_quantity, average_unit_cost, batch_count in inventory_stock
            ]

            # Calculate totals
            total_items = len(inventory_stock_list)
            total_value = sum(item['total_value'] for item in inventory_stock_list)
            total_quantity = sum(item['total_remaining'] for item in inventory_stock_list)

            # Response
            response = {
                "total_items": total_items,
                "total_quantity": round(total_quantity, 3),
                "total_value": round(total_value, 2),
                "inventory_stocks": inventory_stock_list,
                "filters": {
                    "supplier_name": supplier_name,
                    "item_name": item_name
                }
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching inventory stock data",
                "details": str(e)
            }, 500


class SendNotification(Resource):
    def post(self):
        data = request.get_json()

        subscription_info = data.get("subscription")
        payload = data.get("message", "Hello from KUKUZETU!")

        if not subscription_info:
            return {"error": "Missing subscription info"}, 400

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=current_app.config["VAPID_PRIVATE_KEY"],
                vapid_claims={
                    "sub": current_app.config["VAPID_EMAIL"]
                }
            )
            return {"success": True}, 200
        except WebPushException as ex:
            return {"error": str(ex)}, 500



