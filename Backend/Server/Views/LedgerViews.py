from flask_restful import Resource
from flask import jsonify,request
from app import db
from sqlalchemy.orm import aliased
from datetime import datetime
from flask_jwt_extended import jwt_required
from sqlalchemy import func, or_
from Server.Models.Accounting.SalesLedger import SalesLedger
from Server.Models.Accounting.ManualLedger import ManualLedger
from Server.Models.Accounting.CreditSalesLedger import CreditSalesLedger
from Server.Models.ChartOfAccounts import ChartOfAccounts
from Server.Models.Shops import Shops
from Server.Models.Expenses import Expenses
from Server.Models.Creditors import Creditors
from Server.Models.Accounting.BankTransferLedger import BankTransfersLedger
from Server.Models.Accounting.ManualLedger import ManualLedger
from Server.Models.Accounting.ExpensesLedger import ExpensesLedger
from Server.Models.Accounting.PurchaseLedger import PurchaseLedgerInventory,DistributionLedger
from Server.Models.BankAccounts import BankAccount,BankingTransaction
from Server.Models.TransferV2 import TransfersV2
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.ExpenseCategory import ExpenseCategory
from Server.Models.SpoiltStock import SpoiltStock
from Server.Models.Accounting.SpoiltStockLedger import SpoiltStockLedger


class SalesLedgerList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            shop_id = request.args.get('shop_id', type=int)
            account_id = request.args.get('account_id', type=int)
            transaction_type = request.args.get('transaction_type', type=str)  # 'debit' or 'credit'
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            
            # Build base transaction subquery to group by sales_id
            base_transaction_subquery = db.session.query(
                SalesLedger.sales_id,
                db.func.max(SalesLedger.created_at).label('created_at'),
                db.func.max(SalesLedger.id).label('id'),
                db.func.max(SalesLedger.description).label('description'),
                db.func.max(SalesLedger.amount).label('amount'),  # CHANGED: from sum() to max() - use MAX to get single transaction amount
                db.func.max(SalesLedger.debit_account_id).label('debit_account_id'),
                db.func.max(SalesLedger.credit_account_id).label('credit_account_id'),
                db.func.max(SalesLedger.shop_id).label('shop_id')
            ).group_by(
                SalesLedger.sales_id
            ).subquery()
            
            # Subquery to get debit account info (first non-null)
            debit_subquery = db.session.query(
                SalesLedger.sales_id,
                SalesLedger.debit_account_id,
                db.func.row_number().over(
                    partition_by=SalesLedger.sales_id,
                    order_by=SalesLedger.id
                ).label('row_num')
            ).filter(SalesLedger.debit_account_id.isnot(None)).subquery()
            
            # Subquery to get credit account info (first non-null)
            credit_subquery = db.session.query(
                SalesLedger.sales_id,
                SalesLedger.credit_account_id,
                db.func.row_number().over(
                    partition_by=SalesLedger.sales_id,
                    order_by=SalesLedger.id
                ).label('row_num')
            ).filter(SalesLedger.credit_account_id.isnot(None)).subquery()
            
            # Alias chart_of_accounts for debit & credit
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)
            
            # Build base query - group by sales_id to get one row per transaction
            query = (
                db.session.query(
                    db.func.max(base_transaction_subquery.c.id).label('id'),
                    db.func.max(base_transaction_subquery.c.created_at).label('created_at'),
                    base_transaction_subquery.c.sales_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,  # This is now the single transaction amount
                    DebitAccount.name.label("debit_account"),
                    db.func.max(debit_subquery.c.debit_account_id).label("debit_account_id"),
                    CreditAccount.name.label("credit_account"),
                    db.func.max(credit_subquery.c.credit_account_id).label("credit_account_id"),
                    Shops.shopname.label("shop_name"),
                    base_transaction_subquery.c.shop_id
                )
                .select_from(base_transaction_subquery)
                .outerjoin(debit_subquery, 
                    db.and_(
                        base_transaction_subquery.c.sales_id == debit_subquery.c.sales_id,
                        debit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(credit_subquery,
                    db.and_(
                        base_transaction_subquery.c.sales_id == credit_subquery.c.sales_id,
                        credit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(DebitAccount, debit_subquery.c.debit_account_id == DebitAccount.id)
                .outerjoin(CreditAccount, credit_subquery.c.credit_account_id == CreditAccount.id)
                .join(Shops, base_transaction_subquery.c.shop_id == Shops.shops_id)
                .group_by(
                    base_transaction_subquery.c.sales_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,
                    base_transaction_subquery.c.created_at,
                    DebitAccount.name,
                    CreditAccount.name,
                    Shops.shopname,
                    base_transaction_subquery.c.shop_id
                )
            )
            
            # Apply filters
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    db.or_(
                        base_transaction_subquery.c.description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        Shops.shopname.ilike(search_term),
                        base_transaction_subquery.c.sales_id.cast(db.String).ilike(search_term)
                    )
                )
            
            if shop_id:
                query = query.filter(base_transaction_subquery.c.shop_id == shop_id)
            
            if account_id:
                query = query.filter(
                    db.or_(
                        db.func.max(debit_subquery.c.debit_account_id) == account_id,
                        db.func.max(credit_subquery.c.credit_account_id) == account_id
                    )
                )
            
            if transaction_type:
                if transaction_type.lower() == 'debit':
                    query = query.filter(base_transaction_subquery.c.amount > 0)  # CHANGED: from having(sum) to filter(max)
                elif transaction_type.lower() == 'credit':
                    query = query.filter(base_transaction_subquery.c.amount < 0)  # CHANGED: from having(sum) to filter(max)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(base_transaction_subquery.c.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(base_transaction_subquery.c.created_at <= end_date_obj)
                except ValueError:
                    pass
            
            # ============ FIXED PAGINATION COUNT ============
            # Get total count for pagination (distinct sales_ids)
            total_count_subquery = db.session.query(
                SalesLedger.sales_id
            ).filter(SalesLedger.sales_id.isnot(None))
            
            # Apply same filters to count subquery
            if search:
                total_count_subquery = total_count_subquery.join(
                    Shops, SalesLedger.shop_id == Shops.shops_id
                ).filter(
                    db.or_(
                        SalesLedger.description.ilike(f"%{search}%"),
                        Shops.shopname.ilike(f"%{search}%"),
                        SalesLedger.sales_id.cast(db.String).ilike(f"%{search}%")
                    )
                )
            
            if shop_id:
                total_count_subquery = total_count_subquery.filter(SalesLedger.shop_id == shop_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    total_count_subquery = total_count_subquery.filter(SalesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    total_count_subquery = total_count_subquery.filter(SalesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass
            
            # Handle transaction type filter for count
            if transaction_type:
                if transaction_type.lower() == 'debit':
                    total_count_subquery = total_count_subquery.filter(SalesLedger.amount > 0)
                elif transaction_type.lower() == 'credit':
                    total_count_subquery = total_count_subquery.filter(SalesLedger.amount < 0)
            
            # Get distinct count
            total_count = total_count_subquery.distinct().count()
            # ============ END FIXED PAGINATION COUNT ============
            
            # Apply pagination
            query = query.order_by(db.func.max(base_transaction_subquery.c.created_at).desc())
            
            # Since we're using paginate() instead of offset/limit, we need to adapt
            # Get total pages manually
            total_pages = (total_count + per_page - 1) // per_page
            
            # Apply pagination using offset/limit to work with our grouped query
            offset_val = (page - 1) * per_page
            paginated_items = query.offset(offset_val).limit(per_page).all()
            
            # Prepare results
            results = []
            for row in paginated_items:
                results.append({
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "sales_id": row.sales_id,
                    "description": row.description,
                    "debit_account": row.debit_account,
                    "debit_account_id": row.debit_account_id,
                    "credit_account": row.credit_account,
                    "credit_account_id": row.credit_account_id,
                    "amount": float(row.amount or 0),  # Now shows the correct single transaction amount
                    "shop": row.shop_name,
                    "shop_id": row.shop_id
                })
            
            # ============ FIXED SUMMARY STATISTICS ============
            # Get summary statistics - based on individual entries, not grouped
            # But for total_amount, we need to use distinct sales_id with their max amount
            max_amount_per_sale = db.session.query(
                SalesLedger.sales_id,
                db.func.max(SalesLedger.amount).label('max_amount')
            ).group_by(SalesLedger.sales_id).subquery()
            
            summary_query = db.session.query(
                db.func.count(SalesLedger.id).label('total_entries'),
                db.func.sum(max_amount_per_sale.c.max_amount).label('total_amount'),  # Sum of max amounts per sale
                db.func.avg(max_amount_per_sale.c.max_amount).label('average_amount')  # Avg of max amounts per sale
            ).join(max_amount_per_sale, SalesLedger.sales_id == max_amount_per_sale.c.sales_id)
            
            # Apply same filters to summary query
            if search:
                summary_query = summary_query.join(Shops, SalesLedger.shop_id == Shops.shops_id).filter(
                    db.or_(
                        SalesLedger.description.ilike(f"%{search}%"),
                        Shops.shopname.ilike(f"%{search}%"),
                        SalesLedger.sales_id.cast(db.String).ilike(f"%{search}%")
                    )
                )
            
            if shop_id:
                summary_query = summary_query.filter(SalesLedger.shop_id == shop_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(SalesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(SalesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass
            
            # Handle transaction type filter for summary
            if transaction_type:
                if transaction_type.lower() == 'debit':
                    summary_query = summary_query.filter(SalesLedger.amount > 0)
                elif transaction_type.lower() == 'credit':
                    summary_query = summary_query.filter(SalesLedger.amount < 0)
            
            summary = summary_query.first()
            
            # Get debit/credit counts - based on transactions, not entries
            if transaction_type:
                # If transaction_type is already filtering, we can use simple counts
                debit_count_query = db.session.query(db.func.count(db.distinct(SalesLedger.sales_id))).filter(SalesLedger.amount > 0)
                credit_count_query = db.session.query(db.func.count(db.distinct(SalesLedger.sales_id))).filter(SalesLedger.amount < 0)
            else:
                # Otherwise, count distinct sales_ids with positive/negative amounts
                debit_count_query = db.session.query(db.func.count(db.distinct(SalesLedger.sales_id))).filter(SalesLedger.amount > 0)
                credit_count_query = db.session.query(db.func.count(db.distinct(SalesLedger.sales_id))).filter(SalesLedger.amount < 0)
            
            if shop_id:
                debit_count_query = debit_count_query.filter(SalesLedger.shop_id == shop_id)
                credit_count_query = credit_count_query.filter(SalesLedger.shop_id == shop_id)
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    debit_count_query = debit_count_query.filter(SalesLedger.created_at >= start_date_obj)
                    credit_count_query = credit_count_query.filter(SalesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    debit_count_query = debit_count_query.filter(SalesLedger.created_at <= end_date_obj)
                    credit_count_query = credit_count_query.filter(SalesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass
            # ============ END FIXED SUMMARY STATISTICS ============
            
            # Create pagination dict compatible with original format
            pagination_info = {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
                "next_num": page + 1 if page < total_pages else None,
                "prev_num": page - 1 if page > 1 else None
            }
            
            return jsonify({
                "data": results,
                "pagination": pagination_info,
                "summary": {
                    "total_entries": summary.total_entries or 0,
                    "total_amount": float(summary.total_amount or 0),
                    "average_amount": float(summary.average_amount or 0),
                    "debit_entries": debit_count_query.scalar() or 0,
                    "credit_entries": credit_count_query.scalar() or 0
                }
            })
            
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500

        

class CreditSalesLedgerList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            shop_id = request.args.get('shop_id', type=int)
            creditor_id = request.args.get('creditor_id', type=int)
            account_id = request.args.get('account_id', type=int)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            min_amount = request.args.get('min_amount', type=float)
            max_amount = request.args.get('max_amount', type=float)
            min_balance = request.args.get('min_balance', type=float)
            max_balance = request.args.get('max_balance', type=float)
            
            # Build base transaction subquery to group by sales_id
            # FIXED: Use MAX instead of SUM for amount to get the actual transaction amount (not doubled)
            base_transaction_subquery = db.session.query(
                CreditSalesLedger.sales_id,
                db.func.max(CreditSalesLedger.created_at).label('created_at'),
                db.func.max(CreditSalesLedger.id).label('id'),
                db.func.max(CreditSalesLedger.description).label('description'),
                db.func.max(CreditSalesLedger.amount).label('amount'),  # CHANGED: from sum() to max()
                db.func.max(CreditSalesLedger.balance).label('balance'),
                db.func.max(CreditSalesLedger.debit_account_id).label('debit_account_id'),
                db.func.max(CreditSalesLedger.credit_account_id).label('credit_account_id'),
                db.func.max(CreditSalesLedger.shop_id).label('shop_id'),
                db.func.max(CreditSalesLedger.creditor_id).label('creditor_id')
            ).group_by(
                CreditSalesLedger.sales_id
            ).subquery()
            
            # Subquery to get debit account info (first non-null)
            debit_subquery = db.session.query(
                CreditSalesLedger.sales_id,
                CreditSalesLedger.debit_account_id,
                db.func.row_number().over(
                    partition_by=CreditSalesLedger.sales_id,
                    order_by=CreditSalesLedger.id
                ).label('row_num')
            ).filter(CreditSalesLedger.debit_account_id.isnot(None)).subquery()
            
            # Subquery to get credit account info (first non-null)
            credit_subquery = db.session.query(
                CreditSalesLedger.sales_id,
                CreditSalesLedger.credit_account_id,
                db.func.row_number().over(
                    partition_by=CreditSalesLedger.sales_id,
                    order_by=CreditSalesLedger.id
                ).label('row_num')
            ).filter(CreditSalesLedger.credit_account_id.isnot(None)).subquery()
            
            # Alias chart_of_accounts for debit & credit
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)

            # Build base query - group by sales_id to get one row per transaction
            query = (
                db.session.query(
                    db.func.max(base_transaction_subquery.c.id).label('id'),
                    db.func.max(base_transaction_subquery.c.created_at).label('created_at'),
                    base_transaction_subquery.c.sales_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,  # This is now the single transaction amount
                    base_transaction_subquery.c.balance,
                    DebitAccount.name.label("debit_account"),
                    db.func.max(debit_subquery.c.debit_account_id).label("debit_account_id"),
                    CreditAccount.name.label("credit_account"),
                    db.func.max(credit_subquery.c.credit_account_id).label("credit_account_id"),
                    Shops.shopname.label("shop_name"),
                    base_transaction_subquery.c.shop_id,
                    base_transaction_subquery.c.creditor_id,
                    Creditors.name.label("creditor_name")
                )
                .select_from(base_transaction_subquery)
                .outerjoin(debit_subquery, 
                    db.and_(
                        base_transaction_subquery.c.sales_id == debit_subquery.c.sales_id,
                        debit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(credit_subquery,
                    db.and_(
                        base_transaction_subquery.c.sales_id == credit_subquery.c.sales_id,
                        credit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(DebitAccount, debit_subquery.c.debit_account_id == DebitAccount.id)
                .outerjoin(CreditAccount, credit_subquery.c.credit_account_id == CreditAccount.id)
                .join(Shops, base_transaction_subquery.c.shop_id == Shops.shops_id)
                .join(Creditors, base_transaction_subquery.c.creditor_id == Creditors.id)
                .group_by(
                    base_transaction_subquery.c.sales_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,
                    base_transaction_subquery.c.balance,
                    base_transaction_subquery.c.created_at,
                    DebitAccount.name,
                    CreditAccount.name,
                    Shops.shopname,
                    base_transaction_subquery.c.shop_id,
                    base_transaction_subquery.c.creditor_id,
                    Creditors.name
                )
            )

            # Apply filters
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    db.or_(
                        base_transaction_subquery.c.description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        Shops.shopname.ilike(search_term),
                        Creditors.name.ilike(search_term),
                        base_transaction_subquery.c.sales_id.cast(db.String).ilike(search_term)
                    )
                )

            if shop_id:
                query = query.filter(base_transaction_subquery.c.shop_id == shop_id)

            if creditor_id:
                query = query.filter(base_transaction_subquery.c.creditor_id == creditor_id)

            if account_id:
                query = query.filter(
                    db.or_(
                        db.func.max(debit_subquery.c.debit_account_id) == account_id,
                        db.func.max(credit_subquery.c.credit_account_id) == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(base_transaction_subquery.c.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(base_transaction_subquery.c.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: Use amount from base_transaction_subquery, not sum
            if min_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount <= max_amount)

            if min_balance is not None:
                query = query.filter(base_transaction_subquery.c.balance >= min_balance)

            if max_balance is not None:
                query = query.filter(base_transaction_subquery.c.balance <= max_balance)

            # ============ FIXED PAGINATION COUNT ============
            # Get total count for pagination (distinct sales_ids)
            total_count_subquery = db.session.query(
                CreditSalesLedger.sales_id
            ).filter(CreditSalesLedger.sales_id.isnot(None))

            # Apply same filters to count subquery
            if search:
                total_count_subquery = total_count_subquery.join(
                    Shops, CreditSalesLedger.shop_id == Shops.shops_id
                ).join(
                    Creditors, CreditSalesLedger.creditor_id == Creditors.id
                ).filter(
                    db.or_(
                        CreditSalesLedger.description.ilike(f"%{search}%"),
                        Shops.shopname.ilike(f"%{search}%"),
                        Creditors.name.ilike(f"%{search}%"),
                        CreditSalesLedger.sales_id.cast(db.String).ilike(f"%{search}%")
                    )
                )

            if shop_id:
                total_count_subquery = total_count_subquery.filter(CreditSalesLedger.shop_id == shop_id)
            
            if creditor_id:
                total_count_subquery = total_count_subquery.filter(CreditSalesLedger.creditor_id == creditor_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    total_count_subquery = total_count_subquery.filter(CreditSalesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    total_count_subquery = total_count_subquery.filter(CreditSalesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # Handle amount filters for count - FIXED: Use MAX not SUM
            if min_amount is not None or max_amount is not None:
                amount_subquery = db.session.query(
                    CreditSalesLedger.sales_id,
                    db.func.max(CreditSalesLedger.amount).label('amount')  # CHANGED: from sum() to max()
                ).filter(CreditSalesLedger.sales_id.isnot(None))\
                 .group_by(CreditSalesLedger.sales_id)
                
                if min_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(CreditSalesLedger.amount) >= min_amount)
                if max_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(CreditSalesLedger.amount) <= max_amount)
                
                amount_subquery = amount_subquery.subquery()
                total_count_subquery = total_count_subquery.join(amount_subquery, 
                    CreditSalesLedger.sales_id == amount_subquery.c.sales_id
                )

            # Handle balance filters for count
            if min_balance is not None or max_balance is not None:
                balance_subquery = db.session.query(
                    CreditSalesLedger.sales_id,
                    db.func.max(CreditSalesLedger.balance).label('balance')
                ).filter(CreditSalesLedger.sales_id.isnot(None))\
                 .group_by(CreditSalesLedger.sales_id)
                
                if min_balance is not None:
                    balance_subquery = balance_subquery.having(db.func.max(CreditSalesLedger.balance) >= min_balance)
                if max_balance is not None:
                    balance_subquery = balance_subquery.having(db.func.max(CreditSalesLedger.balance) <= max_balance)
                
                balance_subquery = balance_subquery.subquery()
                total_count_subquery = total_count_subquery.join(balance_subquery, 
                    CreditSalesLedger.sales_id == balance_subquery.c.sales_id
                )

            # Get distinct count
            total_count = total_count_subquery.distinct().count()
            total_pages = (total_count + per_page - 1) // per_page
            # ============ END FIXED PAGINATION COUNT ============

            # Apply pagination
            query = query.order_by(db.func.max(base_transaction_subquery.c.created_at).desc())
            paginated_query = query.offset((page - 1) * per_page).limit(per_page).all()

            # Prepare results
            data = []
            for row in paginated_query:
                data.append({
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "sales_id": row.sales_id,
                    "description": row.description,
                    "creditor": {
                        "id": row.creditor_id,
                        "name": row.creditor_name
                    },
                    "debit_account": row.debit_account,
                    "debit_account_id": row.debit_account_id,
                    "credit_account": row.credit_account,
                    "credit_account_id": row.credit_account_id,
                    "amount": float(row.amount or 0),  # Now shows the correct single transaction amount
                    "balance": float(row.balance or 0),
                    "shop": row.shop_name,
                    "shop_id": row.shop_id
                })

            # ============ FIXED SUMMARY STATISTICS ============
            # Get summary statistics - based on individual entries, not grouped
            # But for total_amount, we need to use distinct sales_id with their max amount
            total_amount_subquery = db.session.query(
                CreditSalesLedger.sales_id,
                db.func.max(CreditSalesLedger.amount).label('max_amount')
            ).group_by(CreditSalesLedger.sales_id).subquery()
            
            summary_query = db.session.query(
                db.func.count(CreditSalesLedger.id).label('total_entries'),
                db.func.sum(total_amount_subquery.c.max_amount).label('total_amount'),  # Sum of max amounts per sale
                db.func.avg(total_amount_subquery.c.max_amount).label('average_amount'),  # Avg of max amounts per sale
                db.func.sum(CreditSalesLedger.balance).label('total_balance'),
                db.func.avg(CreditSalesLedger.balance).label('average_balance')
            ).join(total_amount_subquery, CreditSalesLedger.sales_id == total_amount_subquery.c.sales_id)

            # Apply same filters to summary query
            if search:
                summary_query = summary_query.join(DebitAccount, CreditSalesLedger.debit_account_id == DebitAccount.id, isouter=True)\
                    .join(CreditAccount, CreditSalesLedger.credit_account_id == CreditAccount.id, isouter=True)\
                    .join(Shops, CreditSalesLedger.shop_id == Shops.shops_id)\
                    .join(Creditors, CreditSalesLedger.creditor_id == Creditors.id)\
                    .filter(
                        db.or_(
                            CreditSalesLedger.description.ilike(f"%{search}%"),
                            DebitAccount.name.ilike(f"%{search}%"),
                            CreditAccount.name.ilike(f"%{search}%"),
                            Shops.shopname.ilike(f"%{search}%"),
                            Creditors.name.ilike(f"%{search}%"),
                            CreditSalesLedger.sales_id.cast(db.String).ilike(f"%{search}%")
                        )
                    )
            else:
                summary_query = summary_query.join(Creditors, CreditSalesLedger.creditor_id == Creditors.id)

            if shop_id:
                summary_query = summary_query.filter(CreditSalesLedger.shop_id == shop_id)

            if creditor_id:
                summary_query = summary_query.filter(CreditSalesLedger.creditor_id == creditor_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(CreditSalesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(CreditSalesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: For amount filters on summary, we need to filter by the max amount per sale
            if min_amount is not None or max_amount is not None:
                filtered_sales = db.session.query(
                    CreditSalesLedger.sales_id,
                    db.func.max(CreditSalesLedger.amount).label('amount')
                ).group_by(CreditSalesLedger.sales_id)
                
                if min_amount is not None:
                    filtered_sales = filtered_sales.having(db.func.max(CreditSalesLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_sales = filtered_sales.having(db.func.max(CreditSalesLedger.amount) <= max_amount)
                
                filtered_sales = filtered_sales.subquery()
                summary_query = summary_query.join(filtered_sales, 
                    CreditSalesLedger.sales_id == filtered_sales.c.sales_id)

            if min_balance is not None:
                summary_query = summary_query.filter(CreditSalesLedger.balance >= min_balance)

            if max_balance is not None:
                summary_query = summary_query.filter(CreditSalesLedger.balance <= max_balance)

            summary = summary_query.first()

            # Get unique creditors count - based on filtered individual entries
            unique_creditors_query = db.session.query(db.func.count(db.distinct(CreditSalesLedger.creditor_id)))
            
            # Apply filters to unique creditors query
            if search:
                unique_creditors_query = unique_creditors_query.join(DebitAccount, CreditSalesLedger.debit_account_id == DebitAccount.id, isouter=True)\
                    .join(CreditAccount, CreditSalesLedger.credit_account_id == CreditAccount.id, isouter=True)\
                    .join(Shops, CreditSalesLedger.shop_id == Shops.shops_id)\
                    .join(Creditors, CreditSalesLedger.creditor_id == Creditors.id)\
                    .filter(
                        db.or_(
                            CreditSalesLedger.description.ilike(f"%{search}%"),
                            DebitAccount.name.ilike(f"%{search}%"),
                            CreditAccount.name.ilike(f"%{search}%"),
                            Shops.shopname.ilike(f"%{search}%"),
                            Creditors.name.ilike(f"%{search}%"),
                            CreditSalesLedger.sales_id.cast(db.String).ilike(f"%{search}%")
                        )
                    )
            else:
                unique_creditors_query = unique_creditors_query.join(Creditors, CreditSalesLedger.creditor_id == Creditors.id)
            
            if shop_id:
                unique_creditors_query = unique_creditors_query.filter(CreditSalesLedger.shop_id == shop_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    unique_creditors_query = unique_creditors_query.filter(CreditSalesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    unique_creditors_query = unique_creditors_query.filter(CreditSalesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass
            
            # FIXED: Use filtered sales for amount conditions
            if min_amount is not None or max_amount is not None:
                filtered_sales = db.session.query(
                    CreditSalesLedger.sales_id,
                    db.func.max(CreditSalesLedger.amount).label('amount')
                ).group_by(CreditSalesLedger.sales_id)
                
                if min_amount is not None:
                    filtered_sales = filtered_sales.having(db.func.max(CreditSalesLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_sales = filtered_sales.having(db.func.max(CreditSalesLedger.amount) <= max_amount)
                
                filtered_sales = filtered_sales.subquery()
                unique_creditors_query = unique_creditors_query.join(filtered_sales, 
                    CreditSalesLedger.sales_id == filtered_sales.c.sales_id)
            
            if min_balance is not None:
                unique_creditors_query = unique_creditors_query.filter(CreditSalesLedger.balance >= min_balance)
            
            if max_balance is not None:
                unique_creditors_query = unique_creditors_query.filter(CreditSalesLedger.balance <= max_balance)

            unique_creditors = unique_creditors_query.scalar() or 0

            # Get unique shops count - based on filtered individual entries
            unique_shops_query = db.session.query(db.func.count(db.distinct(CreditSalesLedger.shop_id)))
            
            if search:
                unique_shops_query = unique_shops_query.join(DebitAccount, CreditSalesLedger.debit_account_id == DebitAccount.id, isouter=True)\
                    .join(CreditAccount, CreditSalesLedger.credit_account_id == CreditAccount.id, isouter=True)\
                    .join(Shops, CreditSalesLedger.shop_id == Shops.shops_id)\
                    .join(Creditors, CreditSalesLedger.creditor_id == Creditors.id)\
                    .filter(
                        db.or_(
                            CreditSalesLedger.description.ilike(f"%{search}%"),
                            DebitAccount.name.ilike(f"%{search}%"),
                            CreditAccount.name.ilike(f"%{search}%"),
                            Shops.shopname.ilike(f"%{search}%"),
                            Creditors.name.ilike(f"%{search}%"),
                            CreditSalesLedger.sales_id.cast(db.String).ilike(f"%{search}%")
                        )
                    )
            else:
                unique_shops_query = unique_shops_query.join(Shops, CreditSalesLedger.shop_id == Shops.shops_id)
            
            if creditor_id:
                unique_shops_query = unique_shops_query.join(Creditors, CreditSalesLedger.creditor_id == Creditors.id)\
                    .filter(CreditSalesLedger.creditor_id == creditor_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    unique_shops_query = unique_shops_query.filter(CreditSalesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    unique_shops_query = unique_shops_query.filter(CreditSalesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass
            
            # FIXED: Use filtered sales for amount conditions
            if min_amount is not None or max_amount is not None:
                filtered_sales = db.session.query(
                    CreditSalesLedger.sales_id,
                    db.func.max(CreditSalesLedger.amount).label('amount')
                ).group_by(CreditSalesLedger.sales_id)
                
                if min_amount is not None:
                    filtered_sales = filtered_sales.having(db.func.max(CreditSalesLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_sales = filtered_sales.having(db.func.max(CreditSalesLedger.amount) <= max_amount)
                
                filtered_sales = filtered_sales.subquery()
                unique_shops_query = unique_shops_query.join(filtered_sales, 
                    CreditSalesLedger.sales_id == filtered_sales.c.sales_id)
            
            if min_balance is not None:
                unique_shops_query = unique_shops_query.filter(CreditSalesLedger.balance >= min_balance)
            
            if max_balance is not None:
                unique_shops_query = unique_shops_query.filter(CreditSalesLedger.balance <= max_balance)

            unique_shops = unique_shops_query.scalar() or 0
            # ============ END FIXED SUMMARY STATISTICS ============

            return jsonify({
                "data": data,
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "next_num": page + 1 if page < total_pages else None,
                    "prev_num": page - 1 if page > 1 else None
                },
                "summary": {
                    "total_entries": summary.total_entries or 0,
                    "total_amount": float(summary.total_amount or 0),
                    "average_amount": float(summary.average_amount or 0),
                    "total_balance": float(summary.total_balance or 0),
                    "average_balance": float(summary.average_balance or 0),
                    "unique_creditors": unique_creditors,
                    "unique_shops": unique_shops
                }
            })

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500


class DistributionLedgerList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            transfer_id = request.args.get('transfer_id', type=int)
            shop_id = request.args.get('shop_id', type=int)
            debit_account_id = request.args.get('debit_account_id', type=int)
            credit_account_id = request.args.get('credit_account_id', type=int)
            account_id = request.args.get('account_id', type=int)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            min_amount = request.args.get('min_amount', type=float)
            max_amount = request.args.get('max_amount', type=float)
            
            # Alias chart_of_accounts
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)

            # Build subquery to get the latest entry for each transfer_id
            # FIXED: Changed from SUM to MAX for amount to get the actual transaction amount (not doubled)
            base_transaction_subquery = db.session.query(
                DistributionLedger.transfer_id,
                db.func.max(DistributionLedger.created_at).label('created_at'),
                db.func.max(DistributionLedger.id).label('id'),
                db.func.max(DistributionLedger.description).label('description'),
                db.func.max(DistributionLedger.amount).label('amount'),  # CHANGED: from sum() to max()
                db.func.max(DistributionLedger.debit_account_id).label('debit_account_id'),
                db.func.max(DistributionLedger.credit_account_id).label('credit_account_id'),
                db.func.max(DistributionLedger.shop_id).label('shop_id')
            ).group_by(
                DistributionLedger.transfer_id
            ).subquery()
            
            # Subquery to get debit account info (first non-null)
            debit_subquery = db.session.query(
                DistributionLedger.transfer_id,
                DistributionLedger.debit_account_id,
                db.func.row_number().over(
                    partition_by=DistributionLedger.transfer_id,
                    order_by=DistributionLedger.id
                ).label('row_num')
            ).filter(DistributionLedger.debit_account_id.isnot(None)).subquery()
            
            # Subquery to get credit account info (first non-null)
            credit_subquery = db.session.query(
                DistributionLedger.transfer_id,
                DistributionLedger.credit_account_id,
                db.func.row_number().over(
                    partition_by=DistributionLedger.transfer_id,
                    order_by=DistributionLedger.id
                ).label('row_num')
            ).filter(DistributionLedger.credit_account_id.isnot(None)).subquery()

            # Build base query - group by transfer_id to get one row per distribution
            query = (
                db.session.query(
                    db.func.max(base_transaction_subquery.c.id).label('id'),
                    db.func.max(base_transaction_subquery.c.created_at).label('created_at'),
                    base_transaction_subquery.c.transfer_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,  # This is now the single transaction amount
                    DebitAccount.name.label("debit_account_name"),
                    DebitAccount.code.label("debit_account_code"),
                    db.func.max(debit_subquery.c.debit_account_id).label("debit_account_id"),
                    DebitAccount.type.label("debit_account_type"),
                    CreditAccount.name.label("credit_account_name"),
                    CreditAccount.code.label("credit_account_code"),
                    db.func.max(credit_subquery.c.credit_account_id).label("credit_account_id"),
                    CreditAccount.type.label("credit_account_type"),
                    # Shop details
                    Shops.shops_id,
                    Shops.shopname.label("shop_name"),
                    # Transfer details - using transferv2_id as identifier
                    TransfersV2.transferv2_id,
                    TransfersV2.transferv2_id.label("transfer_number"),
                    TransfersV2.status,
                    TransfersV2.quantity.label("transfer_quantity"),
                    TransfersV2.itemname.label("item_name"),
                    TransfersV2.BatchNumber.label("batch_number"),
                    TransfersV2.metric.label("unit_of_measure"),
                    TransfersV2.total_cost.label("total_transfer_cost"),
                    TransfersV2.unitCost.label("unit_cost"),
                    TransfersV2.created_at.label("transfer_date")
                )
                .select_from(base_transaction_subquery)
                .outerjoin(debit_subquery, 
                    db.and_(
                        base_transaction_subquery.c.transfer_id == debit_subquery.c.transfer_id,
                        debit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(credit_subquery,
                    db.and_(
                        base_transaction_subquery.c.transfer_id == credit_subquery.c.transfer_id,
                        credit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(DebitAccount, debit_subquery.c.debit_account_id == DebitAccount.id)
                .outerjoin(CreditAccount, credit_subquery.c.credit_account_id == CreditAccount.id)
                .join(Shops, base_transaction_subquery.c.shop_id == Shops.shops_id)
                .join(TransfersV2, base_transaction_subquery.c.transfer_id == TransfersV2.transferv2_id)
                .group_by(
                    base_transaction_subquery.c.transfer_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,
                    base_transaction_subquery.c.created_at,
                    DebitAccount.name,
                    DebitAccount.code,
                    DebitAccount.type,
                    CreditAccount.name,
                    CreditAccount.code,
                    CreditAccount.type,
                    Shops.shops_id,
                    Shops.shopname,
                    TransfersV2.transferv2_id,
                    TransfersV2.status,
                    TransfersV2.quantity,
                    TransfersV2.itemname,
                    TransfersV2.BatchNumber,
                    TransfersV2.metric,
                    TransfersV2.total_cost,
                    TransfersV2.unitCost,
                    TransfersV2.created_at
                )
            )

            # Apply filters
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    db.or_(
                        base_transaction_subquery.c.description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        DebitAccount.code.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        CreditAccount.code.ilike(search_term),
                        Shops.shopname.ilike(search_term),
                        TransfersV2.itemname.ilike(search_term),
                        TransfersV2.BatchNumber.ilike(search_term),
                        base_transaction_subquery.c.transfer_id.cast(db.String).ilike(search_term),
                        TransfersV2.transferv2_id.cast(db.String).ilike(search_term)
                    )
                )

            if transfer_id:
                query = query.filter(base_transaction_subquery.c.transfer_id == transfer_id)

            if shop_id:
                query = query.filter(base_transaction_subquery.c.shop_id == shop_id)

            if debit_account_id:
                query = query.having(db.func.max(debit_subquery.c.debit_account_id) == debit_account_id)

            if credit_account_id:
                query = query.having(db.func.max(credit_subquery.c.credit_account_id) == credit_account_id)

            if account_id:
                query = query.having(
                    db.or_(
                        db.func.max(debit_subquery.c.debit_account_id) == account_id,
                        db.func.max(credit_subquery.c.credit_account_id) == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(base_transaction_subquery.c.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(base_transaction_subquery.c.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: Use amount from base_transaction_subquery, not total_amount
            if min_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount <= max_amount)

            # ============ FIXED PAGINATION COUNT ============
            # Get total count for pagination (distinct transfer_id)
            total_count_subquery = db.session.query(
                DistributionLedger.transfer_id
            ).filter(DistributionLedger.transfer_id.isnot(None))

            # Apply same filters to count subquery
            if search:
                total_count_subquery = total_count_subquery.join(
                    TransfersV2, 
                    DistributionLedger.transfer_id == TransfersV2.transferv2_id
                ).join(
                    Shops, 
                    DistributionLedger.shop_id == Shops.shops_id
                ).filter(
                    db.or_(
                        DistributionLedger.description.ilike(f"%{search}%"),
                        Shops.shopname.ilike(f"%{search}%"),
                        TransfersV2.itemname.ilike(f"%{search}%"),
                        TransfersV2.BatchNumber.ilike(f"%{search}%")
                    )
                )

            if transfer_id:
                total_count_subquery = total_count_subquery.filter(DistributionLedger.transfer_id == transfer_id)
            
            if shop_id:
                total_count_subquery = total_count_subquery.filter(DistributionLedger.shop_id == shop_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    total_count_subquery = total_count_subquery.filter(DistributionLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    total_count_subquery = total_count_subquery.filter(DistributionLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # Handle amount filters for count - FIXED: Changed from SUM to MAX
            if min_amount is not None or max_amount is not None:
                amount_subquery = db.session.query(
                    DistributionLedger.transfer_id,
                    db.func.max(DistributionLedger.amount).label('amount')  # CHANGED: from sum() to max()
                ).filter(DistributionLedger.transfer_id.isnot(None))\
                 .group_by(DistributionLedger.transfer_id)
                
                if min_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(DistributionLedger.amount) >= min_amount)
                if max_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(DistributionLedger.amount) <= max_amount)
                
                amount_subquery = amount_subquery.subquery()
                total_count_subquery = total_count_subquery.join(amount_subquery, 
                    DistributionLedger.transfer_id == amount_subquery.c.transfer_id
                )

            # Get distinct count
            total_count = total_count_subquery.distinct().count()
            total_pages = (total_count + per_page - 1) // per_page
            # ============ END FIXED PAGINATION COUNT ============

            # Apply pagination
            query = query.order_by(db.func.max(base_transaction_subquery.c.created_at).desc())
            paginated_query = query.offset((page - 1) * per_page).limit(per_page).all()

            # Prepare results
            data = []
            for row in paginated_query:
                # Format transfer number safely
                transfer_number = row.transfer_number
                if transfer_number is not None:
                    try:
                        transfer_number = f"TRF-{int(transfer_number):06d}"
                    except (ValueError, TypeError):
                        transfer_number = f"TRF-{transfer_number}"
                
                entry = {
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "transfer_id": row.transfer_id,
                    "description": row.description,
                    "debit_account": {
                        "id": row.debit_account_id,
                        "name": row.debit_account_name,
                        "code": row.debit_account_code,
                        "type": row.debit_account_type
                    } if row.debit_account_id else None,
                    "credit_account": {
                        "id": row.credit_account_id,
                        "name": row.credit_account_name,
                        "code": row.credit_account_code,
                        "type": row.credit_account_type
                    } if row.credit_account_id else None,
                    "amount": float(row.amount or 0),  # Now shows the correct single transaction amount
                    "shop": {
                        "id": row.shops_id,
                        "name": row.shop_name
                    },
                    "transfer": {
                        "id": row.transferv2_id,
                        "transfer_number": transfer_number,
                        "status": row.status,
                        "quantity": float(row.transfer_quantity) if row.transfer_quantity else 0,
                        "item_name": row.item_name,
                        "batch_number": row.batch_number,
                        "unit_of_measure": row.unit_of_measure,
                        "total_cost": float(row.total_transfer_cost) if row.total_transfer_cost else 0,
                        "unit_cost": float(row.unit_cost) if row.unit_cost else 0,
                        "transfer_date": row.transfer_date.strftime("%Y-%m-%d %H:%M:%S") if row.transfer_date else None
                    }
                }
                data.append(entry)

            # ============ FIXED SUMMARY STATISTICS ============
            # Get summary statistics - based on individual entries, not grouped
            # But for total_amount, we need to use distinct transfer_id with their max amount
            total_amount_subquery = db.session.query(
                DistributionLedger.transfer_id,
                db.func.max(DistributionLedger.amount).label('max_amount')
            ).group_by(DistributionLedger.transfer_id).subquery()
            
            summary_query = db.session.query(
                db.func.count(DistributionLedger.id).label('total_entries'),
                db.func.sum(total_amount_subquery.c.max_amount).label('total_amount'),  # Sum of max amounts per transfer
                db.func.avg(total_amount_subquery.c.max_amount).label('average_amount'),  # Avg of max amounts per transfer
                db.func.max(DistributionLedger.amount).label('max_amount'),
                db.func.min(DistributionLedger.amount).label('min_amount'),
                db.func.count(db.distinct(DistributionLedger.transfer_id)).label('unique_transfers'),
                db.func.count(db.distinct(DistributionLedger.shop_id)).label('unique_shops'),
                db.func.count(db.distinct(DistributionLedger.debit_account_id)).label('unique_debit_accounts'),
                db.func.count(db.distinct(DistributionLedger.credit_account_id)).label('unique_credit_accounts')
            ).join(total_amount_subquery, DistributionLedger.transfer_id == total_amount_subquery.c.transfer_id)

            # Apply same filters to summary query
            if search:
                summary_query = summary_query.join(Shops, DistributionLedger.shop_id == Shops.shops_id)\
                    .join(TransfersV2, DistributionLedger.transfer_id == TransfersV2.transferv2_id)\
                    .filter(
                        db.or_(
                            DistributionLedger.description.ilike(f"%{search}%"),
                            Shops.shopname.ilike(f"%{search}%"),
                            TransfersV2.itemname.ilike(f"%{search}%"),
                            TransfersV2.BatchNumber.ilike(f"%{search}%")
                        )
                    )

            if transfer_id:
                summary_query = summary_query.filter(DistributionLedger.transfer_id == transfer_id)

            if shop_id:
                summary_query = summary_query.filter(DistributionLedger.shop_id == shop_id)

            if debit_account_id:
                summary_query = summary_query.filter(DistributionLedger.debit_account_id == debit_account_id)

            if credit_account_id:
                summary_query = summary_query.filter(DistributionLedger.credit_account_id == credit_account_id)

            if account_id:
                summary_query = summary_query.filter(
                    db.or_(
                        DistributionLedger.debit_account_id == account_id,
                        DistributionLedger.credit_account_id == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(DistributionLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(DistributionLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: For amount filters on summary, we need to filter by the max amount per transfer
            if min_amount is not None or max_amount is not None:
                filtered_transfers = db.session.query(
                    DistributionLedger.transfer_id,
                    db.func.max(DistributionLedger.amount).label('amount')
                ).group_by(DistributionLedger.transfer_id)
                
                if min_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) <= max_amount)
                
                filtered_transfers = filtered_transfers.subquery()
                summary_query = summary_query.join(filtered_transfers, 
                    DistributionLedger.transfer_id == filtered_transfers.c.transfer_id)

            summary = summary_query.first()

            # Get distribution by shop - based on grouped transactions
            # FIXED: Use MAX amount per transfer for totals
            shop_summary_query = db.session.query(
                Shops.shopname.label("shop_name"),
                db.func.count(db.distinct(DistributionLedger.transfer_id)).label("distribution_count"),
                db.func.sum(total_amount_subquery.c.max_amount).label("total_amount"),
                db.func.avg(total_amount_subquery.c.max_amount).label("average_amount")
            ).join(Shops, DistributionLedger.shop_id == Shops.shops_id)\
             .join(total_amount_subquery, DistributionLedger.transfer_id == total_amount_subquery.c.transfer_id)\
             .filter(DistributionLedger.transfer_id.isnot(None))

            # Apply filters to shop summary
            if search:
                shop_summary_query = shop_summary_query.join(TransfersV2, DistributionLedger.transfer_id == TransfersV2.transferv2_id)\
                    .filter(
                        db.or_(
                            Shops.shopname.ilike(f"%{search}%"),
                            DistributionLedger.description.ilike(f"%{search}%"),
                            TransfersV2.itemname.ilike(f"%{search}%")
                        )
                    )

            if transfer_id:
                shop_summary_query = shop_summary_query.filter(DistributionLedger.transfer_id == transfer_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    shop_summary_query = shop_summary_query.filter(DistributionLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    shop_summary_query = shop_summary_query.filter(DistributionLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_transfers = db.session.query(
                    DistributionLedger.transfer_id,
                    db.func.max(DistributionLedger.amount).label('amount')
                ).group_by(DistributionLedger.transfer_id)
                
                if min_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) <= max_amount)
                
                filtered_transfers = filtered_transfers.subquery()
                shop_summary_query = shop_summary_query.join(filtered_transfers, 
                    DistributionLedger.transfer_id == filtered_transfers.c.transfer_id)

            shop_summary = shop_summary_query.group_by(Shops.shopname)\
                .order_by(db.func.sum(total_amount_subquery.c.max_amount).desc())\
                .all()

            # Get distribution by transfer status - based on grouped transactions
            status_summary_query = db.session.query(
                TransfersV2.status,
                db.func.count(db.distinct(DistributionLedger.transfer_id)).label("distribution_count"),
                db.func.sum(total_amount_subquery.c.max_amount).label("total_amount"),
                db.func.avg(total_amount_subquery.c.max_amount).label("average_amount")
            ).join(TransfersV2, DistributionLedger.transfer_id == TransfersV2.transferv2_id)\
             .join(total_amount_subquery, DistributionLedger.transfer_id == total_amount_subquery.c.transfer_id)\
             .filter(DistributionLedger.transfer_id.isnot(None))

            # Apply filters to status summary
            if shop_id:
                status_summary_query = status_summary_query.filter(DistributionLedger.shop_id == shop_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    status_summary_query = status_summary_query.filter(DistributionLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    status_summary_query = status_summary_query.filter(DistributionLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_transfers = db.session.query(
                    DistributionLedger.transfer_id,
                    db.func.max(DistributionLedger.amount).label('amount')
                ).group_by(DistributionLedger.transfer_id)
                
                if min_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) <= max_amount)
                
                filtered_transfers = filtered_transfers.subquery()
                status_summary_query = status_summary_query.join(filtered_transfers, 
                    DistributionLedger.transfer_id == filtered_transfers.c.transfer_id)

            status_summary = status_summary_query.group_by(TransfersV2.status)\
                .order_by(db.func.sum(total_amount_subquery.c.max_amount).desc())\
                .all()

            # Get top items distributed - based on grouped transactions
            items_summary_query = db.session.query(
                TransfersV2.itemname.label("item_name"),
                db.func.count(db.distinct(DistributionLedger.transfer_id)).label("distribution_count"),
                db.func.sum(total_amount_subquery.c.max_amount).label("total_amount"),
                db.func.avg(total_amount_subquery.c.max_amount).label("average_amount")
            ).join(TransfersV2, DistributionLedger.transfer_id == TransfersV2.transferv2_id)\
             .join(total_amount_subquery, DistributionLedger.transfer_id == total_amount_subquery.c.transfer_id)\
             .filter(DistributionLedger.transfer_id.isnot(None))

            # Apply filters to items summary
            if shop_id:
                items_summary_query = items_summary_query.filter(DistributionLedger.shop_id == shop_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    items_summary_query = items_summary_query.filter(DistributionLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    items_summary_query = items_summary_query.filter(DistributionLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_transfers = db.session.query(
                    DistributionLedger.transfer_id,
                    db.func.max(DistributionLedger.amount).label('amount')
                ).group_by(DistributionLedger.transfer_id)
                
                if min_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transfers = filtered_transfers.having(db.func.max(DistributionLedger.amount) <= max_amount)
                
                filtered_transfers = filtered_transfers.subquery()
                items_summary_query = items_summary_query.join(filtered_transfers, 
                    DistributionLedger.transfer_id == filtered_transfers.c.transfer_id)

            items_summary = items_summary_query.group_by(TransfersV2.itemname)\
                .order_by(db.func.sum(total_amount_subquery.c.max_amount).desc())\
                .limit(10)\
                .all()
            # ============ END FIXED SUMMARY STATISTICS ============

            return jsonify({
                "data": data,
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "next_num": page + 1 if page < total_pages else None,
                    "prev_num": page - 1 if page > 1 else None
                },
                "summary": {
                    "total_entries": summary.total_entries or 0,
                    "total_amount": float(summary.total_amount or 0),
                    "average_amount": float(summary.average_amount or 0),
                    "max_amount": float(summary.max_amount or 0),
                    "min_amount": float(summary.min_amount or 0),
                    "unique_transfers": summary.unique_transfers or 0,
                    "unique_shops": summary.unique_shops or 0,
                    "unique_debit_accounts": summary.unique_debit_accounts or 0,
                    "unique_credit_accounts": summary.unique_credit_accounts or 0,
                    "distribution_by_shop": [{
                        "shop_name": row.shop_name,
                        "entry_count": row.distribution_count,
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in shop_summary],
                    "distribution_by_status": [{
                        "status": row.status,
                        "entry_count": row.distribution_count,
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in status_summary],
                    "top_items_distributed": [{
                        "item_name": row.item_name,
                        "distribution_count": row.distribution_count,
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in items_summary]
                }
            })

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500


class PurchaseLedgerInventoryList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            inventory_id = request.args.get('inventory_id', type=int)
            debit_account_id = request.args.get('debit_account_id', type=int)
            credit_account_id = request.args.get('credit_account_id', type=int)
            account_id = request.args.get('account_id', type=int)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            min_amount = request.args.get('min_amount', type=float)
            max_amount = request.args.get('max_amount', type=float)
            
            # Alias chart_of_accounts
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)

            # Build subquery to get the latest entry for each purchase transaction
            # FIXED: Changed from SUM to MAX for amount to get the actual transaction amount (not doubled)
            base_description_subquery = db.session.query(
                PurchaseLedgerInventory.inventory_id,
                db.func.regexp_replace(
                    PurchaseLedgerInventory.description, 
                    ' #\\d+$', 
                    ''
                ).label('base_description'),
                db.func.max(PurchaseLedgerInventory.created_at).label('created_at'),
                db.func.max(PurchaseLedgerInventory.id).label('id'),
                db.func.max(PurchaseLedgerInventory.amount).label('amount'),  # CHANGED: from sum() to max()
                db.func.max(PurchaseLedgerInventory.debit_account_id).label('debit_account_id'),
                db.func.max(PurchaseLedgerInventory.credit_account_id).label('credit_account_id')
            ).group_by(
                PurchaseLedgerInventory.inventory_id,
                db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '')
            ).subquery()
            
            # Subquery to get debit account info
            debit_subquery = db.session.query(
                PurchaseLedgerInventory.inventory_id,
                PurchaseLedgerInventory.description,
                PurchaseLedgerInventory.debit_account_id,
                db.func.row_number().over(
                    partition_by=PurchaseLedgerInventory.inventory_id,
                    order_by=PurchaseLedgerInventory.id
                ).label('row_num')
            ).filter(PurchaseLedgerInventory.debit_account_id.isnot(None)).subquery()
            
            # Subquery to get credit account info
            credit_subquery = db.session.query(
                PurchaseLedgerInventory.inventory_id,
                PurchaseLedgerInventory.credit_account_id,
                db.func.row_number().over(
                    partition_by=PurchaseLedgerInventory.inventory_id,
                    order_by=PurchaseLedgerInventory.id
                ).label('row_num')
            ).filter(PurchaseLedgerInventory.credit_account_id.isnot(None)).subquery()

            # Build base query - group by inventory_id and base description to get one row per purchase transaction
            query = (
                db.session.query(
                    db.func.max(base_description_subquery.c.id).label('id'),
                    db.func.max(base_description_subquery.c.created_at).label('created_at'),
                    base_description_subquery.c.inventory_id,
                    base_description_subquery.c.base_description.label('description'),
                    base_description_subquery.c.amount,  # This is now the single transaction amount
                    DebitAccount.name.label("debit_account_name"),
                    DebitAccount.code.label("debit_account_code"),
                    db.func.max(debit_subquery.c.debit_account_id).label("debit_account_id"),
                    DebitAccount.type.label("debit_account_type"),
                    CreditAccount.name.label("credit_account_name"),
                    CreditAccount.code.label("credit_account_code"),
                    db.func.max(credit_subquery.c.credit_account_id).label("credit_account_id"),
                    CreditAccount.type.label("credit_account_type"),
                    # Inventory details
                    InventoryV2.inventoryV2_id,
                    InventoryV2.itemname.label("inventory_name"),
                    InventoryV2.BatchNumber.label("batch_number"),
                    InventoryV2.quantity.label("quantity"),
                    InventoryV2.unitPrice.label("unit_price"),
                    InventoryV2.Suppliername.label("supplier_name")
                )
                .select_from(base_description_subquery)
                .outerjoin(debit_subquery, 
                    db.and_(
                        base_description_subquery.c.inventory_id == debit_subquery.c.inventory_id,
                        debit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(credit_subquery,
                    db.and_(
                        base_description_subquery.c.inventory_id == credit_subquery.c.inventory_id,
                        credit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(DebitAccount, debit_subquery.c.debit_account_id == DebitAccount.id)
                .outerjoin(CreditAccount, credit_subquery.c.credit_account_id == CreditAccount.id)
                .join(InventoryV2, base_description_subquery.c.inventory_id == InventoryV2.inventoryV2_id)
                .group_by(
                    base_description_subquery.c.inventory_id,
                    base_description_subquery.c.base_description,
                    base_description_subquery.c.amount,
                    base_description_subquery.c.created_at,
                    DebitAccount.name,
                    DebitAccount.code,
                    DebitAccount.type,
                    CreditAccount.name,
                    CreditAccount.code,
                    CreditAccount.type,
                    InventoryV2.inventoryV2_id,
                    InventoryV2.itemname,
                    InventoryV2.BatchNumber,
                    InventoryV2.quantity,
                    InventoryV2.unitPrice,
                    InventoryV2.Suppliername
                )
            )

            # Apply filters
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    db.or_(
                        base_description_subquery.c.base_description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        DebitAccount.code.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        CreditAccount.code.ilike(search_term),
                        InventoryV2.itemname.ilike(search_term),
                        InventoryV2.BatchNumber.ilike(search_term),
                        InventoryV2.Suppliername.ilike(search_term),
                        base_description_subquery.c.inventory_id.cast(db.String).ilike(search_term)
                    )
                )

            if inventory_id:
                query = query.filter(base_description_subquery.c.inventory_id == inventory_id)

            if debit_account_id:
                query = query.having(db.func.max(debit_subquery.c.debit_account_id) == debit_account_id)

            if credit_account_id:
                query = query.having(db.func.max(credit_subquery.c.credit_account_id) == credit_account_id)

            if account_id:
                query = query.having(
                    db.or_(
                        db.func.max(debit_subquery.c.debit_account_id) == account_id,
                        db.func.max(credit_subquery.c.credit_account_id) == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(base_description_subquery.c.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(base_description_subquery.c.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: Use amount from base_description_subquery, not total_amount
            if min_amount is not None:
                query = query.filter(base_description_subquery.c.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(base_description_subquery.c.amount <= max_amount)

            # ============ FIXED PAGINATION COUNT ============
            # Get total count for pagination (distinct purchase transactions)
            total_count_subquery = db.session.query(
                PurchaseLedgerInventory.inventory_id,
                db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '').label('base_desc')
            ).join(InventoryV2, PurchaseLedgerInventory.inventory_id == InventoryV2.inventoryV2_id)

            # Apply same filters to count subquery
            if search:
                total_count_subquery = total_count_subquery.filter(
                    db.or_(
                        PurchaseLedgerInventory.description.ilike(f"%{search}%"),
                        InventoryV2.itemname.ilike(f"%{search}%"),
                        InventoryV2.BatchNumber.ilike(f"%{search}%"),
                        InventoryV2.Suppliername.ilike(f"%{search}%")
                    )
                )

            if inventory_id:
                total_count_subquery = total_count_subquery.filter(PurchaseLedgerInventory.inventory_id == inventory_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    total_count_subquery = total_count_subquery.filter(PurchaseLedgerInventory.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    total_count_subquery = total_count_subquery.filter(PurchaseLedgerInventory.created_at <= end_date_obj)
                except ValueError:
                    pass

            # Handle amount filters for count - FIXED: Changed from SUM to MAX
            if min_amount is not None or max_amount is not None:
                amount_subquery = db.session.query(
                    PurchaseLedgerInventory.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '').label('base_desc'),
                    db.func.max(PurchaseLedgerInventory.amount).label('amount')  # CHANGED: from sum() to max()
                ).group_by(
                    PurchaseLedgerInventory.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '')
                )
                
                if min_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(PurchaseLedgerInventory.amount) >= min_amount)
                if max_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(PurchaseLedgerInventory.amount) <= max_amount)
                
                amount_subquery = amount_subquery.subquery()
                total_count_subquery = total_count_subquery.join(amount_subquery, 
                    db.and_(
                        total_count_subquery.c.inventory_id == amount_subquery.c.inventory_id,
                        total_count_subquery.c.base_desc == amount_subquery.c.base_desc
                    )
                )

            # Get distinct count
            total_count = total_count_subquery.distinct().count()
            total_pages = (total_count + per_page - 1) // per_page
            # ============ END FIXED PAGINATION COUNT ============

            # Apply pagination
            query = query.order_by(db.func.max(base_description_subquery.c.created_at).desc())
            paginated_query = query.offset((page - 1) * per_page).limit(per_page).all()

            # Prepare results
            data = []
            for row in paginated_query:
                data.append({
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "inventory_id": row.inventory_id,
                    "description": row.description,
                    "debit_account": {
                        "id": row.debit_account_id,
                        "name": row.debit_account_name,
                        "code": row.debit_account_code,
                        "type": row.debit_account_type
                    } if row.debit_account_id else None,
                    "credit_account": {
                        "id": row.credit_account_id,
                        "name": row.credit_account_name,
                        "code": row.credit_account_code,
                        "type": row.credit_account_type
                    } if row.credit_account_id else None,
                    "amount": float(row.amount or 0),  # Now shows the correct single transaction amount
                    "inventory": {
                        "id": row.inventoryV2_id,
                        "name": row.inventory_name,
                        "batch_number": row.batch_number,
                        "quantity": float(row.quantity) if row.quantity else 0,
                        "unit_price": float(row.unit_price) if row.unit_price else 0,
                        "supplier_name": row.supplier_name
                    }
                })

            # ============ FIXED SUMMARY STATISTICS ============
            # Get summary statistics - based on individual entries, not grouped
            # But for total_amount, we need to use distinct transactions with their max amount
            total_amount_subquery = db.session.query(
                PurchaseLedgerInventory.inventory_id,
                db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '').label('base_desc'),
                db.func.max(PurchaseLedgerInventory.amount).label('max_amount')
            ).group_by(
                PurchaseLedgerInventory.inventory_id,
                db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '')
            ).subquery()
            
            summary_query = db.session.query(
                db.func.count(PurchaseLedgerInventory.id).label('total_entries'),
                db.func.sum(total_amount_subquery.c.max_amount).label('total_amount'),  # Sum of max amounts per transaction
                db.func.avg(total_amount_subquery.c.max_amount).label('average_amount'),  # Avg of max amounts per transaction
                db.func.max(PurchaseLedgerInventory.amount).label('max_amount'),
                db.func.min(PurchaseLedgerInventory.amount).label('min_amount'),
                db.func.count(db.distinct(PurchaseLedgerInventory.inventory_id)).label('unique_inventories'),
                db.func.count(db.distinct(PurchaseLedgerInventory.debit_account_id)).label('unique_debit_accounts'),
                db.func.count(db.distinct(PurchaseLedgerInventory.credit_account_id)).label('unique_credit_accounts'),
                db.func.count(db.distinct(InventoryV2.Suppliername)).label('unique_suppliers')
            ).join(InventoryV2, PurchaseLedgerInventory.inventory_id == InventoryV2.inventoryV2_id)\
             .join(total_amount_subquery, 
                db.and_(
                    PurchaseLedgerInventory.inventory_id == total_amount_subquery.c.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '') == total_amount_subquery.c.base_desc
                )
             )

            # Apply same filters to summary query
            if search:
                summary_query = summary_query.filter(
                    db.or_(
                        PurchaseLedgerInventory.description.ilike(f"%{search}%"),
                        InventoryV2.itemname.ilike(f"%{search}%"),
                        InventoryV2.BatchNumber.ilike(f"%{search}%"),
                        InventoryV2.Suppliername.ilike(f"%{search}%")
                    )
                )

            if inventory_id:
                summary_query = summary_query.filter(PurchaseLedgerInventory.inventory_id == inventory_id)

            if debit_account_id:
                summary_query = summary_query.filter(PurchaseLedgerInventory.debit_account_id == debit_account_id)

            if credit_account_id:
                summary_query = summary_query.filter(PurchaseLedgerInventory.credit_account_id == credit_account_id)

            if account_id:
                summary_query = summary_query.filter(
                    db.or_(
                        PurchaseLedgerInventory.debit_account_id == account_id,
                        PurchaseLedgerInventory.credit_account_id == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(PurchaseLedgerInventory.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(PurchaseLedgerInventory.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: For amount filters on summary, we need to filter by the max amount per transaction
            if min_amount is not None or max_amount is not None:
                filtered_transactions = db.session.query(
                    PurchaseLedgerInventory.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '').label('base_desc'),
                    db.func.max(PurchaseLedgerInventory.amount).label('amount')
                ).group_by(
                    PurchaseLedgerInventory.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '')
                )
                
                if min_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(PurchaseLedgerInventory.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(PurchaseLedgerInventory.amount) <= max_amount)
                
                filtered_transactions = filtered_transactions.subquery()
                summary_query = summary_query.join(filtered_transactions,
                    db.and_(
                        PurchaseLedgerInventory.inventory_id == filtered_transactions.c.inventory_id,
                        db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '') == filtered_transactions.c.base_desc
                    )
                )

            summary = summary_query.first()

            # ============ FIXED SUPPLIER SUMMARY ============
            # Additional summary: Top suppliers by purchase amount - based on grouped transactions
            supplier_summary = db.session.query(
                InventoryV2.Suppliername.label("supplier_name"),
                db.func.count(db.func.distinct(
                    db.func.concat(
                        PurchaseLedgerInventory.inventory_id,
                        '-',
                        db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '')
                    )
                )).label("purchase_count"),
                db.func.sum(total_amount_subquery.c.max_amount).label("total_purchased"),  # Sum of max amounts
                db.func.avg(total_amount_subquery.c.max_amount).label("avg_purchase")  # Avg of max amounts
            ).join(InventoryV2, PurchaseLedgerInventory.inventory_id == InventoryV2.inventoryV2_id)\
             .join(total_amount_subquery,
                db.and_(
                    PurchaseLedgerInventory.inventory_id == total_amount_subquery.c.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '') == total_amount_subquery.c.base_desc
                )
             )

            # Apply filters to supplier summary
            if search:
                supplier_summary = supplier_summary.filter(
                    db.or_(
                        InventoryV2.Suppliername.ilike(f"%{search}%"),
                        InventoryV2.itemname.ilike(f"%{search}%"),
                        PurchaseLedgerInventory.description.ilike(f"%{search}%")
                    )
                )

            if inventory_id:
                supplier_summary = supplier_summary.filter(PurchaseLedgerInventory.inventory_id == inventory_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    supplier_summary = supplier_summary.filter(PurchaseLedgerInventory.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    supplier_summary = supplier_summary.filter(PurchaseLedgerInventory.created_at <= end_date_obj)
                except ValueError:
                    pass

            # Handle amount filters for supplier summary - FIXED: Use max amount
            if min_amount is not None or max_amount is not None:
                transaction_totals = db.session.query(
                    PurchaseLedgerInventory.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '').label('base_desc'),
                    db.func.max(PurchaseLedgerInventory.amount).label('amount')  # CHANGED: from sum() to max()
                ).group_by(
                    PurchaseLedgerInventory.inventory_id,
                    db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '')
                )
                
                if min_amount is not None:
                    transaction_totals = transaction_totals.having(db.func.max(PurchaseLedgerInventory.amount) >= min_amount)
                if max_amount is not None:
                    transaction_totals = transaction_totals.having(db.func.max(PurchaseLedgerInventory.amount) <= max_amount)
                
                transaction_totals = transaction_totals.subquery()
                supplier_summary = supplier_summary.join(transaction_totals,
                    db.and_(
                        PurchaseLedgerInventory.inventory_id == transaction_totals.c.inventory_id,
                        db.func.regexp_replace(PurchaseLedgerInventory.description, ' #\\d+$', '') == transaction_totals.c.base_desc
                    )
                )

            supplier_summary = supplier_summary.group_by(InventoryV2.Suppliername)\
                .order_by(db.func.sum(total_amount_subquery.c.max_amount).desc())\
                .limit(5).all()
            # ============ END FIXED SUPPLIER SUMMARY ============

            return jsonify({
                "data": data,
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "next_num": page + 1 if page < total_pages else None,
                    "prev_num": page - 1 if page > 1 else None
                },
                "summary": {
                    "total_entries": summary.total_entries or 0,
                    "total_amount": float(summary.total_amount or 0),
                    "average_amount": float(summary.average_amount or 0),
                    "max_amount": float(summary.max_amount or 0),
                    "min_amount": float(summary.min_amount or 0),
                    "unique_inventories": summary.unique_inventories or 0,
                    "unique_debit_accounts": summary.unique_debit_accounts or 0,
                    "unique_credit_accounts": summary.unique_credit_accounts or 0,
                    "unique_suppliers": summary.unique_suppliers or 0,
                    "top_suppliers": [{
                        "supplier_name": row.supplier_name,
                        "purchase_count": row.purchase_count,
                        "total_purchased": float(row.total_purchased or 0),
                        "avg_purchase": float(row.avg_purchase or 0)
                    } for row in supplier_summary]
                }
            })

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500


class BankTransfersLedgerList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            bank_transaction_id = request.args.get('bank_transaction_id', type=int)
            debit_account_id = request.args.get('debit_account_id', type=int)
            credit_account_id = request.args.get('credit_account_id', type=int)
            account_id = request.args.get('account_id', type=int)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            min_amount = request.args.get('min_amount', type=float)
            max_amount = request.args.get('max_amount', type=float)
            
            # Alias chart_of_accounts
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)
            DebitAccountForBank = aliased(ChartOfAccounts)
            CreditAccountForBank = aliased(ChartOfAccounts)

            # Build subquery to get the latest entry for each bank_transaction_id
            # FIXED: Changed from SUM to MAX for amount to get the actual transaction amount (not doubled)
            base_transaction_subquery = db.session.query(
                BankTransfersLedger.bank_transaction_id,
                db.func.max(BankTransfersLedger.created_at).label('created_at'),
                db.func.max(BankTransfersLedger.id).label('id'),
                db.func.max(BankTransfersLedger.description).label('description'),
                db.func.max(BankTransfersLedger.amount).label('amount'),  # CHANGED: from sum() to max()
                db.func.max(BankTransfersLedger.debit_account_id).label('debit_account_id'),
                db.func.max(BankTransfersLedger.credit_account_id).label('credit_account_id')
            ).group_by(
                BankTransfersLedger.bank_transaction_id
            ).subquery()
            
            # Subquery to get debit account info (first non-null)
            debit_subquery = db.session.query(
                BankTransfersLedger.bank_transaction_id,
                BankTransfersLedger.debit_account_id,
                db.func.row_number().over(
                    partition_by=BankTransfersLedger.bank_transaction_id,
                    order_by=BankTransfersLedger.id
                ).label('row_num')
            ).filter(BankTransfersLedger.debit_account_id.isnot(None)).subquery()
            
            # Subquery to get credit account info (first non-null)
            credit_subquery = db.session.query(
                BankTransfersLedger.bank_transaction_id,
                BankTransfersLedger.credit_account_id,
                db.func.row_number().over(
                    partition_by=BankTransfersLedger.bank_transaction_id,
                    order_by=BankTransfersLedger.id
                ).label('row_num')
            ).filter(BankTransfersLedger.credit_account_id.isnot(None)).subquery()

            # Build base query - group by bank_transaction_id to get one row per transfer
            query = (
                db.session.query(
                    db.func.max(base_transaction_subquery.c.id).label('id'),
                    db.func.max(base_transaction_subquery.c.created_at).label('created_at'),
                    base_transaction_subquery.c.bank_transaction_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,  # This is now the single transaction amount
                    DebitAccount.name.label("debit_account_name"),
                    DebitAccount.code.label("debit_account_code"),
                    db.func.max(debit_subquery.c.debit_account_id).label("debit_account_id"),
                    DebitAccount.type.label("debit_account_type"),
                    CreditAccount.name.label("credit_account_name"),
                    CreditAccount.code.label("credit_account_code"),
                    db.func.max(credit_subquery.c.credit_account_id).label("credit_account_id"),
                    CreditAccount.type.label("credit_account_type"),
                    # BankingTransaction fields
                    BankingTransaction.id.label("bank_transaction_ref_id"),
                    BankingTransaction.Transaction_type_debit,
                    BankingTransaction.Transaction_type_credit,
                    # BankAccount fields
                    BankAccount.id.label("bank_account_id"),
                    BankAccount.Account_name.label("bank_account_name"),
                    BankAccount.Account_Balance.label("bank_account_balance"),
                    BankAccount.chart_account_id.label("bank_chart_account_id"),
                    # Linked ChartOfAccounts for bank account
                    DebitAccountForBank.name.label("linked_debit_account_name"),
                    DebitAccountForBank.code.label("linked_debit_account_code"),
                    CreditAccountForBank.name.label("linked_credit_account_name"),
                    CreditAccountForBank.code.label("linked_credit_account_code")
                )
                .select_from(base_transaction_subquery)
                .outerjoin(debit_subquery, 
                    db.and_(
                        base_transaction_subquery.c.bank_transaction_id == debit_subquery.c.bank_transaction_id,
                        debit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(credit_subquery,
                    db.and_(
                        base_transaction_subquery.c.bank_transaction_id == credit_subquery.c.bank_transaction_id,
                        credit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(DebitAccount, debit_subquery.c.debit_account_id == DebitAccount.id)
                .outerjoin(CreditAccount, credit_subquery.c.credit_account_id == CreditAccount.id)
                .outerjoin(BankingTransaction, base_transaction_subquery.c.bank_transaction_id == BankingTransaction.id)
                .outerjoin(BankAccount, BankingTransaction.account_id == BankAccount.id)
                .outerjoin(
                    DebitAccountForBank, 
                    db.and_(
                        BankAccount.chart_account_id == DebitAccountForBank.id,
                        debit_subquery.c.debit_account_id == DebitAccountForBank.id
                    )
                )
                .outerjoin(
                    CreditAccountForBank,
                    db.and_(
                        BankAccount.chart_account_id == CreditAccountForBank.id,
                        credit_subquery.c.credit_account_id == CreditAccountForBank.id
                    )
                )
                .group_by(
                    base_transaction_subquery.c.bank_transaction_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,
                    base_transaction_subquery.c.created_at,
                    DebitAccount.name,
                    DebitAccount.code,
                    DebitAccount.type,
                    CreditAccount.name,
                    CreditAccount.code,
                    CreditAccount.type,
                    BankingTransaction.id,
                    BankingTransaction.Transaction_type_debit,
                    BankingTransaction.Transaction_type_credit,
                    BankAccount.id,
                    BankAccount.Account_name,
                    BankAccount.Account_Balance,
                    BankAccount.chart_account_id,
                    DebitAccountForBank.name,
                    DebitAccountForBank.code,
                    CreditAccountForBank.name,
                    CreditAccountForBank.code
                )
            )

            # Apply filters
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    db.or_(
                        base_transaction_subquery.c.description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        DebitAccount.code.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        CreditAccount.code.ilike(search_term),
                        BankAccount.Account_name.ilike(search_term),
                        DebitAccountForBank.name.ilike(search_term),
                        CreditAccountForBank.name.ilike(search_term),
                        DebitAccountForBank.code.ilike(search_term),
                        CreditAccountForBank.code.ilike(search_term),
                        base_transaction_subquery.c.bank_transaction_id.cast(db.String).ilike(search_term),
                        BankingTransaction.id.cast(db.String).ilike(search_term)
                    )
                )

            if bank_transaction_id:
                query = query.filter(base_transaction_subquery.c.bank_transaction_id == bank_transaction_id)

            if debit_account_id:
                query = query.having(db.func.max(debit_subquery.c.debit_account_id) == debit_account_id)

            if credit_account_id:
                query = query.having(db.func.max(credit_subquery.c.credit_account_id) == credit_account_id)

            if account_id:
                query = query.having(
                    db.or_(
                        db.func.max(debit_subquery.c.debit_account_id) == account_id,
                        db.func.max(credit_subquery.c.credit_account_id) == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(base_transaction_subquery.c.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(base_transaction_subquery.c.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: Use amount from base_transaction_subquery, not total_amount
            if min_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount <= max_amount)

            # ============ FIXED PAGINATION COUNT ============
            # Get total count for pagination (distinct bank_transaction_id)
            total_count_subquery = db.session.query(
                BankTransfersLedger.bank_transaction_id
            ).filter(BankTransfersLedger.bank_transaction_id.isnot(None))

            # Apply same filters to count subquery
            if search:
                total_count_subquery = total_count_subquery.join(
                    BankingTransaction, 
                    BankTransfersLedger.bank_transaction_id == BankingTransaction.id, 
                    isouter=True
                ).join(
                    BankAccount, 
                    BankingTransaction.account_id == BankAccount.id, 
                    isouter=True
                ).filter(
                    db.or_(
                        BankTransfersLedger.description.ilike(f"%{search}%"),
                        BankAccount.Account_name.ilike(f"%{search}%")
                    )
                )

            if bank_transaction_id:
                total_count_subquery = total_count_subquery.filter(BankTransfersLedger.bank_transaction_id == bank_transaction_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    total_count_subquery = total_count_subquery.filter(BankTransfersLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    total_count_subquery = total_count_subquery.filter(BankTransfersLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # Handle amount filters for count - FIXED: Changed from SUM to MAX
            if min_amount is not None or max_amount is not None:
                amount_subquery = db.session.query(
                    BankTransfersLedger.bank_transaction_id,
                    db.func.max(BankTransfersLedger.amount).label('amount')  # CHANGED: from sum() to max()
                ).filter(BankTransfersLedger.bank_transaction_id.isnot(None))\
                 .group_by(BankTransfersLedger.bank_transaction_id)
                
                if min_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(BankTransfersLedger.amount) >= min_amount)
                if max_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(BankTransfersLedger.amount) <= max_amount)
                
                amount_subquery = amount_subquery.subquery()
                total_count_subquery = total_count_subquery.join(amount_subquery, 
                    BankTransfersLedger.bank_transaction_id == amount_subquery.c.bank_transaction_id
                )

            # Get distinct count
            total_count = total_count_subquery.distinct().count()
            total_pages = (total_count + per_page - 1) // per_page
            # ============ END FIXED PAGINATION COUNT ============

            # Apply pagination
            query = query.order_by(db.func.max(base_transaction_subquery.c.created_at).desc())
            paginated_query = query.offset((page - 1) * per_page).limit(per_page).all()

            # Prepare results
            data = []
            for row in paginated_query:
                # Calculate net banking transaction amount
                bank_trans_debit = float(row.Transaction_type_debit) if row.Transaction_type_debit else 0
                bank_trans_credit = float(row.Transaction_type_credit) if row.Transaction_type_credit else 0
                bank_net_amount = bank_trans_debit - bank_trans_credit
                
                # Determine which account is linked to the bank account
                is_debit_account_linked = bool(row.linked_debit_account_name)
                is_credit_account_linked = bool(row.linked_credit_account_name)
                linked_account_name = row.linked_debit_account_name or row.linked_credit_account_name
                linked_account_code = row.linked_debit_account_code or row.linked_credit_account_code
                
                entry = {
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "bank_transaction_id": row.bank_transaction_id,
                    "description": row.description,
                    "debit_account": {
                        "id": row.debit_account_id,
                        "name": row.debit_account_name,
                        "code": row.debit_account_code,
                        "type": row.debit_account_type,
                        "is_linked_to_bank_account": is_debit_account_linked
                    } if row.debit_account_id else None,
                    "credit_account": {
                        "id": row.credit_account_id,
                        "name": row.credit_account_name,
                        "code": row.credit_account_code,
                        "type": row.credit_account_type,
                        "is_linked_to_bank_account": is_credit_account_linked
                    } if row.credit_account_id else None,
                    "amount": float(row.amount or 0)  # Now shows the correct single transaction amount
                }
                
                # Add banking transaction info if available
                if row.bank_transaction_ref_id:
                    entry["banking_transaction"] = {
                        "id": row.bank_transaction_ref_id,
                        "debit_amount": bank_trans_debit,
                        "credit_amount": bank_trans_credit,
                        "net_amount": bank_net_amount,
                        "transaction_type": "Debit" if bank_trans_debit > 0 else "Credit",
                        "bank_account": {
                            "id": row.bank_account_id,
                            "name": row.bank_account_name,
                            "balance": float(row.bank_account_balance) if row.bank_account_balance else 0,
                            "chart_account_id": row.bank_chart_account_id,
                            "linked_account_name": linked_account_name,
                            "linked_account_code": linked_account_code
                        }
                    } if row.bank_account_id else None
                
                data.append(entry)

            # ============ FIXED SUMMARY STATISTICS ============
            # Create a subquery for the max amount per transaction
            max_amount_per_transaction = db.session.query(
                BankTransfersLedger.bank_transaction_id,
                db.func.max(BankTransfersLedger.amount).label('max_amount')
            ).filter(BankTransfersLedger.bank_transaction_id.isnot(None))\
             .group_by(BankTransfersLedger.bank_transaction_id).subquery()
            
            # Get summary statistics - based on individual entries, not grouped
            # But for total_amount, we need to use distinct transactions with their max amount
            summary_query = db.session.query(
                db.func.count(BankTransfersLedger.id).label('total_entries'),
                db.func.sum(max_amount_per_transaction.c.max_amount).label('total_amount'),  # Sum of max amounts per transaction
                db.func.avg(max_amount_per_transaction.c.max_amount).label('average_amount'),  # Avg of max amounts per transaction
                db.func.max(BankTransfersLedger.amount).label('max_amount'),
                db.func.min(BankTransfersLedger.amount).label('min_amount'),
                db.func.count(db.distinct(BankTransfersLedger.debit_account_id)).label('unique_debit_accounts'),
                db.func.count(db.distinct(BankTransfersLedger.credit_account_id)).label('unique_credit_accounts'),
                db.func.count(db.distinct(BankingTransaction.account_id)).label('linked_bank_accounts'),
                db.func.count(db.distinct(BankTransfersLedger.bank_transaction_id)).label('linked_bank_transactions')
            ).outerjoin(BankingTransaction, BankTransfersLedger.bank_transaction_id == BankingTransaction.id)\
             .join(max_amount_per_transaction, BankTransfersLedger.bank_transaction_id == max_amount_per_transaction.c.bank_transaction_id)

            # Apply filters to summary query
            if search:
                summary_query = summary_query.filter(
                    BankTransfersLedger.description.ilike(f"%{search}%")
                )

            if bank_transaction_id:
                summary_query = summary_query.filter(BankTransfersLedger.bank_transaction_id == bank_transaction_id)

            if debit_account_id:
                summary_query = summary_query.filter(BankTransfersLedger.debit_account_id == debit_account_id)

            if credit_account_id:
                summary_query = summary_query.filter(BankTransfersLedger.credit_account_id == credit_account_id)

            if account_id:
                summary_query = summary_query.filter(
                    db.or_(
                        BankTransfersLedger.debit_account_id == account_id,
                        BankTransfersLedger.credit_account_id == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(BankTransfersLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(BankTransfersLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # FIXED: For amount filters on summary, we need to filter by the max amount per transaction
            if min_amount is not None or max_amount is not None:
                filtered_transactions = db.session.query(
                    BankTransfersLedger.bank_transaction_id,
                    db.func.max(BankTransfersLedger.amount).label('amount')
                ).filter(BankTransfersLedger.bank_transaction_id.isnot(None))\
                 .group_by(BankTransfersLedger.bank_transaction_id)
                
                if min_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(BankTransfersLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(BankTransfersLedger.amount) <= max_amount)
                
                filtered_transactions = filtered_transactions.subquery()
                summary_query = summary_query.join(filtered_transactions, 
                    BankTransfersLedger.bank_transaction_id == filtered_transactions.c.bank_transaction_id
                )

            summary_data = summary_query.first()

            # Debit accounts summary - based on individual entries (these are fine as is)
            debit_summary_query = db.session.query(
                ChartOfAccounts.name.label("account_name"),
                ChartOfAccounts.code.label("account_code"),
                ChartOfAccounts.type.label("account_type"),
                db.func.count(BankTransfersLedger.id).label("count"),
                db.func.sum(BankTransfersLedger.amount).label("total_debited"),
                db.func.avg(BankTransfersLedger.amount).label("average_debit")
            ).join(ChartOfAccounts, BankTransfersLedger.debit_account_id == ChartOfAccounts.id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    debit_summary_query = debit_summary_query.filter(BankTransfersLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    debit_summary_query = debit_summary_query.filter(BankTransfersLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            debit_summary = debit_summary_query.group_by(
                ChartOfAccounts.name, 
                ChartOfAccounts.code, 
                ChartOfAccounts.type
            ).order_by(db.func.sum(BankTransfersLedger.amount).desc())\
             .limit(10).all()

            # Credit accounts summary - based on individual entries (these are fine as is)
            credit_summary_query = db.session.query(
                ChartOfAccounts.name.label("account_name"),
                ChartOfAccounts.code.label("account_code"),
                ChartOfAccounts.type.label("account_type"),
                db.func.count(BankTransfersLedger.id).label("count"),
                db.func.sum(BankTransfersLedger.amount).label("total_credited"),
                db.func.avg(BankTransfersLedger.amount).label("average_credit")
            ).join(ChartOfAccounts, BankTransfersLedger.credit_account_id == ChartOfAccounts.id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    credit_summary_query = credit_summary_query.filter(BankTransfersLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    credit_summary_query = credit_summary_query.filter(BankTransfersLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            credit_summary = credit_summary_query.group_by(
                ChartOfAccounts.name, 
                ChartOfAccounts.code, 
                ChartOfAccounts.type
            ).order_by(db.func.sum(BankTransfersLedger.amount).desc())\
             .limit(10).all()

            # Bank account summary - based on grouped transactions with max amount
            bank_account_summary_query = db.session.query(
                BankAccount.Account_name.label("bank_account_name"),
                BankAccount.Account_Balance.label("current_balance"),
                db.func.count(db.distinct(BankTransfersLedger.bank_transaction_id)).label("transaction_count"),
                db.func.sum(max_amount_per_transaction.c.max_amount).label("total_amount")  # Use max amount per transaction
            ).join(BankingTransaction, BankTransfersLedger.bank_transaction_id == BankingTransaction.id)\
             .join(BankAccount, BankingTransaction.account_id == BankAccount.id)\
             .join(max_amount_per_transaction, BankTransfersLedger.bank_transaction_id == max_amount_per_transaction.c.bank_transaction_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    bank_account_summary_query = bank_account_summary_query.filter(BankTransfersLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    bank_account_summary_query = bank_account_summary_query.filter(BankTransfersLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_transactions = db.session.query(
                    BankTransfersLedger.bank_transaction_id,
                    db.func.max(BankTransfersLedger.amount).label('amount')
                ).filter(BankTransfersLedger.bank_transaction_id.isnot(None))\
                 .group_by(BankTransfersLedger.bank_transaction_id)
                
                if min_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(BankTransfersLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(BankTransfersLedger.amount) <= max_amount)
                
                filtered_transactions = filtered_transactions.subquery()
                bank_account_summary_query = bank_account_summary_query.join(filtered_transactions, 
                    BankTransfersLedger.bank_transaction_id == filtered_transactions.c.bank_transaction_id
                )

            bank_account_summary = bank_account_summary_query.group_by(
                BankAccount.Account_name, 
                BankAccount.Account_Balance
            ).order_by(db.func.sum(max_amount_per_transaction.c.max_amount).desc())\
             .limit(10).all()

            # Monthly summary - based on grouped transactions with max amount
            monthly_summary_query = db.session.query(
                db.func.extract('year', BankTransfersLedger.created_at).label("year"),
                db.func.extract('month', BankTransfersLedger.created_at).label("month"),
                db.func.count(db.distinct(BankTransfersLedger.bank_transaction_id)).label("transfer_count"),
                db.func.sum(max_amount_per_transaction.c.max_amount).label("total_amount"),  # Use max amount per transaction
                db.func.avg(max_amount_per_transaction.c.max_amount).label("average_amount")  # Use max amount per transaction
            ).join(max_amount_per_transaction, BankTransfersLedger.bank_transaction_id == max_amount_per_transaction.c.bank_transaction_id)\
             .filter(BankTransfersLedger.bank_transaction_id.isnot(None))

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    monthly_summary_query = monthly_summary_query.filter(BankTransfersLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    monthly_summary_query = monthly_summary_query.filter(BankTransfersLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_transactions = db.session.query(
                    BankTransfersLedger.bank_transaction_id,
                    db.func.max(BankTransfersLedger.amount).label('amount')
                ).filter(BankTransfersLedger.bank_transaction_id.isnot(None))\
                 .group_by(BankTransfersLedger.bank_transaction_id)
                
                if min_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(BankTransfersLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_transactions = filtered_transactions.having(db.func.max(BankTransfersLedger.amount) <= max_amount)
                
                filtered_transactions = filtered_transactions.subquery()
                monthly_summary_query = monthly_summary_query.join(filtered_transactions, 
                    BankTransfersLedger.bank_transaction_id == filtered_transactions.c.bank_transaction_id
                )

            monthly_summary = monthly_summary_query.group_by(
                db.func.extract('year', BankTransfersLedger.created_at),
                db.func.extract('month', BankTransfersLedger.created_at)
            ).order_by(
                db.func.extract('year', BankTransfersLedger.created_at).desc(),
                db.func.extract('month', BankTransfersLedger.created_at).desc()
            ).limit(12).all()
            # ============ END FIXED SUMMARY STATISTICS ============

            summary = {
                "total_entries": summary_data.total_entries or 0,
                "total_amount": float(summary_data.total_amount or 0),
                "average_amount": float(summary_data.average_amount or 0),
                "max_amount": float(summary_data.max_amount or 0),
                "min_amount": float(summary_data.min_amount or 0),
                "unique_debit_accounts": summary_data.unique_debit_accounts or 0,
                "unique_credit_accounts": summary_data.unique_credit_accounts or 0,
                "unique_bank_accounts": summary_data.linked_bank_accounts or 0,
                "linked_bank_transactions": summary_data.linked_bank_transactions or 0,
                "unlinked_transfers": (summary_data.linked_bank_transactions or 0) - (summary_data.linked_bank_transactions or 0),  # Fixed calculation
                "top_debit_accounts": [{
                    "account_name": row.account_name,
                    "account_code": row.account_code,
                    "account_type": row.account_type,
                    "count": row.count,
                    "total_debited": float(row.total_debited or 0),
                    "average_debit": float(row.average_debit or 0)
                } for row in debit_summary],
                "top_credit_accounts": [{
                    "account_name": row.account_name,
                    "account_code": row.account_code,
                    "account_type": row.account_type,
                    "count": row.count,
                    "total_credited": float(row.total_credited or 0),
                    "average_credit": float(row.average_credit or 0)
                } for row in credit_summary],
                "top_bank_accounts": [{
                    "bank_account_name": row.bank_account_name,
                    "current_balance": float(row.current_balance or 0),
                    "transaction_count": row.transaction_count,
                    "total_amount": float(row.total_amount or 0)
                } for row in bank_account_summary],
                "monthly_summary": [{
                    "year": int(row.year),
                    "month": int(row.month),
                    "month_name": datetime(2000, int(row.month), 1).strftime('%B'),
                    "transfer_count": row.transfer_count,
                    "total_amount": float(row.total_amount or 0),
                    "average_amount": float(row.average_amount or 0)
                } for row in monthly_summary]
            }

            return jsonify({
                "data": data,
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "next_num": page + 1 if page < total_pages else None,
                    "prev_num": page - 1 if page > 1 else None
                },
                "summary": summary
            })

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500
        
        
class ExpensesLedgerList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            expense_id = request.args.get('expense_id', type=int)
            category_id = request.args.get('category_id', type=int)
            shop_id = request.args.get('shop_id', type=int)
            debit_account_id = request.args.get('debit_account_id', type=int)
            credit_account_id = request.args.get('credit_account_id', type=int)
            account_id = request.args.get('account_id', type=int)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            min_amount = request.args.get('min_amount', type=float)
            max_amount = request.args.get('max_amount', type=float)

            # Alias chart_of_accounts
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)

            # Build base transaction subquery to group by expense_id
            # Use MAX for amount to get the actual transaction amount (not doubled from debit/credit entries)
            base_transaction_subquery = db.session.query(
                ExpensesLedger.expense_id,
                db.func.max(ExpensesLedger.created_at).label('created_at'),
                db.func.max(ExpensesLedger.id).label('id'),
                db.func.max(ExpensesLedger.amount).label('amount'),  # MAX gives single transaction amount
                db.func.max(ExpensesLedger.debit_account_id).label('debit_account_id'),
                db.func.max(ExpensesLedger.credit_account_id).label('credit_account_id'),
                db.func.max(ExpensesLedger.shop_id).label('shop_id'),
                db.func.max(ExpensesLedger.category_id).label('category_id')
            ).group_by(
                ExpensesLedger.expense_id
            ).subquery()

            # Subquery to get debit account info (first non-null)
            debit_subquery = db.session.query(
                ExpensesLedger.expense_id,
                ExpensesLedger.debit_account_id,
                db.func.row_number().over(
                    partition_by=ExpensesLedger.expense_id,
                    order_by=ExpensesLedger.id
                ).label('row_num')
            ).filter(ExpensesLedger.debit_account_id.isnot(None)).subquery()

            # Subquery to get credit account info (first non-null)
            credit_subquery = db.session.query(
                ExpensesLedger.expense_id,
                ExpensesLedger.credit_account_id,
                db.func.row_number().over(
                    partition_by=ExpensesLedger.expense_id,
                    order_by=ExpensesLedger.id
                ).label('row_num')
            ).filter(ExpensesLedger.credit_account_id.isnot(None)).subquery()

            # Build base query - group by expense_id to get one row per expense transaction
            query = (
                db.session.query(
                    db.func.max(base_transaction_subquery.c.id).label('id'),
                    db.func.max(base_transaction_subquery.c.created_at).label('created_at'),
                    base_transaction_subquery.c.expense_id,
                    Expenses.description.label('description'),  # Get description from Expenses table
                    base_transaction_subquery.c.amount,
                    DebitAccount.name.label("debit_account_name"),
                    DebitAccount.code.label("debit_account_code"),
                    db.func.max(debit_subquery.c.debit_account_id).label("debit_account_id"),
                    DebitAccount.type.label("debit_account_type"),
                    CreditAccount.name.label("credit_account_name"),
                    CreditAccount.code.label("credit_account_code"),
                    db.func.max(credit_subquery.c.credit_account_id).label("credit_account_id"),
                    CreditAccount.type.label("credit_account_type"),
                    # Shop details
                    Shops.shops_id,
                    Shops.shopname.label("shop_name"),
                    # Category details - Use category_name instead of name
                    ExpenseCategory.id.label("category_id"),
                    ExpenseCategory.category_name.label("category_name"),
                    ExpenseCategory.type.label("category_type"),
                    # Expense details - FIXED: Use correct field names from Expenses model
                    Expenses.expense_id,
                    Expenses.created_at.label("expense_created_at"),  # Changed from expense_date to created_at
                    Expenses.item.label("item"),
                    Expenses.category.label("expense_category"),  # This is a string field, not the relationship
                    Expenses.quantity,
                    Expenses.paidTo,
                    Expenses.totalPrice.label("total_price"),
                    Expenses.amountPaid.label("amount_paid"),
                    Expenses.source,
                    Expenses.comments,
                    Expenses.paymentRef.label("payment_reference"),
                    Expenses.user_id
                )
                .select_from(base_transaction_subquery)
                .outerjoin(debit_subquery,
                    db.and_(
                        base_transaction_subquery.c.expense_id == debit_subquery.c.expense_id,
                        debit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(credit_subquery,
                    db.and_(
                        base_transaction_subquery.c.expense_id == credit_subquery.c.expense_id,
                        credit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(DebitAccount, debit_subquery.c.debit_account_id == DebitAccount.id)
                .outerjoin(CreditAccount, credit_subquery.c.credit_account_id == CreditAccount.id)
                .join(Shops, base_transaction_subquery.c.shop_id == Shops.shops_id)
                .join(ExpenseCategory, base_transaction_subquery.c.category_id == ExpenseCategory.id)
                .join(Expenses, base_transaction_subquery.c.expense_id == Expenses.expense_id)
                .group_by(
                    base_transaction_subquery.c.expense_id,
                    base_transaction_subquery.c.amount,
                    base_transaction_subquery.c.created_at,
                    DebitAccount.name,
                    DebitAccount.code,
                    DebitAccount.type,
                    CreditAccount.name,
                    CreditAccount.code,
                    CreditAccount.type,
                    Shops.shops_id,
                    Shops.shopname,
                    ExpenseCategory.id,
                    ExpenseCategory.category_name,
                    ExpenseCategory.type,
                    Expenses.expense_id,
                    Expenses.description,
                    Expenses.created_at,
                    Expenses.item,
                    Expenses.category,
                    Expenses.quantity,
                    Expenses.paidTo,
                    Expenses.totalPrice,
                    Expenses.amountPaid,
                    Expenses.source,
                    Expenses.comments,
                    Expenses.paymentRef,
                    Expenses.user_id
                )
            )

            # Apply filters
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    db.or_(
                        Expenses.description.ilike(search_term),
                        Expenses.item.ilike(search_term),
                        Expenses.paidTo.ilike(search_term),
                        Expenses.source.ilike(search_term),
                        Expenses.comments.ilike(search_term),
                        Expenses.paymentRef.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        DebitAccount.code.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        CreditAccount.code.ilike(search_term),
                        Shops.shopname.ilike(search_term),
                        ExpenseCategory.category_name.ilike(search_term),
                        ExpenseCategory.type.ilike(search_term),
                        base_transaction_subquery.c.expense_id.cast(db.String).ilike(search_term)
                    )
                )

            if expense_id:
                query = query.filter(base_transaction_subquery.c.expense_id == expense_id)

            if category_id:
                query = query.filter(base_transaction_subquery.c.category_id == category_id)

            if shop_id:
                query = query.filter(base_transaction_subquery.c.shop_id == shop_id)

            if debit_account_id:
                query = query.having(db.func.max(debit_subquery.c.debit_account_id) == debit_account_id)

            if credit_account_id:
                query = query.having(db.func.max(credit_subquery.c.credit_account_id) == credit_account_id)

            if account_id:
                query = query.having(
                    db.or_(
                        db.func.max(debit_subquery.c.debit_account_id) == account_id,
                        db.func.max(credit_subquery.c.credit_account_id) == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(base_transaction_subquery.c.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(base_transaction_subquery.c.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount <= max_amount)

            # ============ PAGINATION COUNT ============
            # Get total count for pagination (distinct expense_id)
            total_count_subquery = db.session.query(
                ExpensesLedger.expense_id
            ).filter(ExpensesLedger.expense_id.isnot(None))

            # Apply same filters to count subquery
            if search:
                total_count_subquery = total_count_subquery.join(
                    Expenses, ExpensesLedger.expense_id == Expenses.expense_id
                ).join(
                    Shops, ExpensesLedger.shop_id == Shops.shops_id, isouter=True
                ).join(
                    ExpenseCategory, ExpensesLedger.category_id == ExpenseCategory.id, isouter=True
                ).filter(
                    db.or_(
                        Expenses.description.ilike(f"%{search}%"),
                        Expenses.item.ilike(f"%{search}%"),
                        Expenses.paidTo.ilike(f"%{search}%"),
                        Expenses.source.ilike(f"%{search}%"),
                        Shops.shopname.ilike(f"%{search}%"),
                        ExpenseCategory.category_name.ilike(f"%{search}%"),
                        ExpenseCategory.type.ilike(f"%{search}%")
                    )
                )

            if expense_id:
                total_count_subquery = total_count_subquery.filter(ExpensesLedger.expense_id == expense_id)

            if category_id:
                total_count_subquery = total_count_subquery.filter(ExpensesLedger.category_id == category_id)

            if shop_id:
                total_count_subquery = total_count_subquery.filter(ExpensesLedger.shop_id == shop_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    total_count_subquery = total_count_subquery.filter(ExpensesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    total_count_subquery = total_count_subquery.filter(ExpensesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # Handle amount filters for count
            if min_amount is not None or max_amount is not None:
                amount_subquery = db.session.query(
                    ExpensesLedger.expense_id,
                    db.func.max(ExpensesLedger.amount).label('amount')  # Use MAX for single transaction amount
                ).filter(ExpensesLedger.expense_id.isnot(None))\
                 .group_by(ExpensesLedger.expense_id)

                if min_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(ExpensesLedger.amount) >= min_amount)
                if max_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(ExpensesLedger.amount) <= max_amount)

                amount_subquery = amount_subquery.subquery()
                total_count_subquery = total_count_subquery.join(amount_subquery,
                    ExpensesLedger.expense_id == amount_subquery.c.expense_id
                )

            # Get distinct count
            total_count = total_count_subquery.distinct().count()
            total_pages = (total_count + per_page - 1) // per_page
            # ============ END PAGINATION COUNT ============

            # Apply pagination
            query = query.order_by(db.func.max(base_transaction_subquery.c.created_at).desc())
            paginated_query = query.offset((page - 1) * per_page).limit(per_page).all()

            # Prepare results
            data = []
            for row in paginated_query:
                entry = {
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "expense_id": row.expense_id,
                    "description": row.description,
                    "amount": float(row.amount or 0),
                    "debit_account": {
                        "id": row.debit_account_id,
                        "name": row.debit_account_name,
                        "code": row.debit_account_code,
                        "type": row.debit_account_type
                    } if row.debit_account_id else None,
                    "credit_account": {
                        "id": row.credit_account_id,
                        "name": row.credit_account_name,
                        "code": row.credit_account_code,
                        "type": row.credit_account_type
                    } if row.credit_account_id else None,
                    "shop": {
                        "id": row.shops_id,
                        "name": row.shop_name
                    },
                    "category": {
                        "id": row.category_id,
                        "name": row.category_name,
                        "type": row.category_type
                    },
                    "expense_details": {
                        "created_at": row.expense_created_at.strftime("%Y-%m-%d %H:%M:%S") if row.expense_created_at else None,
                        "item": row.item,
                        "category": row.expense_category,  # String field from Expenses table
                        "quantity": float(row.quantity) if row.quantity else 0,
                        "paid_to": row.paidTo,
                        "total_price": float(row.total_price) if row.total_price else 0,
                        "amount_paid": float(row.amount_paid) if row.amount_paid else 0,
                        "source": row.source,
                        "comments": row.comments,
                        "payment_reference": row.payment_reference,
                        "user_id": row.user_id
                    }
                }
                data.append(entry)

            # ============ SUMMARY STATISTICS ============
            # Create subquery for max amount per expense
            max_amount_per_expense = db.session.query(
                ExpensesLedger.expense_id,
                db.func.max(ExpensesLedger.amount).label('max_amount')
            ).filter(ExpensesLedger.expense_id.isnot(None))\
             .group_by(ExpensesLedger.expense_id).subquery()

            # Get summary statistics
            summary_query = db.session.query(
                db.func.count(ExpensesLedger.id).label('total_entries'),
                db.func.sum(max_amount_per_expense.c.max_amount).label('total_amount'),
                db.func.avg(max_amount_per_expense.c.max_amount).label('average_amount'),
                db.func.max(ExpensesLedger.amount).label('max_amount'),
                db.func.min(ExpensesLedger.amount).label('min_amount'),
                db.func.count(db.distinct(ExpensesLedger.expense_id)).label('unique_expenses'),
                db.func.count(db.distinct(ExpensesLedger.shop_id)).label('unique_shops'),
                db.func.count(db.distinct(ExpensesLedger.category_id)).label('unique_categories'),
                db.func.count(db.distinct(ExpensesLedger.debit_account_id)).label('unique_debit_accounts'),
                db.func.count(db.distinct(ExpensesLedger.credit_account_id)).label('unique_credit_accounts')
            ).join(max_amount_per_expense, ExpensesLedger.expense_id == max_amount_per_expense.c.expense_id)

            # Apply filters to summary query
            if search:
                summary_query = summary_query.join(Expenses, ExpensesLedger.expense_id == Expenses.expense_id)\
                    .join(Shops, ExpensesLedger.shop_id == Shops.shops_id)\
                    .join(ExpenseCategory, ExpensesLedger.category_id == ExpenseCategory.id)\
                    .filter(
                        db.or_(
                            Expenses.description.ilike(f"%{search}%"),
                            Expenses.item.ilike(f"%{search}%"),
                            Expenses.paidTo.ilike(f"%{search}%"),
                            Expenses.source.ilike(f"%{search}%"),
                            Shops.shopname.ilike(f"%{search}%"),
                            ExpenseCategory.category_name.ilike(f"%{search}%"),
                            ExpenseCategory.type.ilike(f"%{search}%")
                        )
                    )

            if expense_id:
                summary_query = summary_query.filter(ExpensesLedger.expense_id == expense_id)

            if category_id:
                summary_query = summary_query.filter(ExpensesLedger.category_id == category_id)

            if shop_id:
                summary_query = summary_query.filter(ExpensesLedger.shop_id == shop_id)

            if debit_account_id:
                summary_query = summary_query.filter(ExpensesLedger.debit_account_id == debit_account_id)

            if credit_account_id:
                summary_query = summary_query.filter(ExpensesLedger.credit_account_id == credit_account_id)

            if account_id:
                summary_query = summary_query.filter(
                    db.or_(
                        ExpensesLedger.debit_account_id == account_id,
                        ExpensesLedger.credit_account_id == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(ExpensesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(ExpensesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_expenses = db.session.query(
                    ExpensesLedger.expense_id,
                    db.func.max(ExpensesLedger.amount).label('amount')
                ).filter(ExpensesLedger.expense_id.isnot(None))\
                 .group_by(ExpensesLedger.expense_id)

                if min_amount is not None:
                    filtered_expenses = filtered_expenses.having(db.func.max(ExpensesLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_expenses = filtered_expenses.having(db.func.max(ExpensesLedger.amount) <= max_amount)

                filtered_expenses = filtered_expenses.subquery()
                summary_query = summary_query.join(filtered_expenses,
                    ExpensesLedger.expense_id == filtered_expenses.c.expense_id
                )

            summary = summary_query.first()

            # Category summary
            category_summary = db.session.query(
                ExpenseCategory.category_name.label("category_name"),
                ExpenseCategory.type.label("category_type"),
                db.func.count(db.distinct(ExpensesLedger.expense_id)).label("expense_count"),
                db.func.sum(max_amount_per_expense.c.max_amount).label("total_amount"),
                db.func.avg(max_amount_per_expense.c.max_amount).label("average_amount")
            ).join(ExpensesLedger, ExpensesLedger.category_id == ExpenseCategory.id)\
             .join(max_amount_per_expense, ExpensesLedger.expense_id == max_amount_per_expense.c.expense_id)\
             .filter(ExpensesLedger.expense_id.isnot(None))

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    category_summary = category_summary.filter(ExpensesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    category_summary = category_summary.filter(ExpensesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if shop_id:
                category_summary = category_summary.filter(ExpensesLedger.shop_id == shop_id)

            if min_amount is not None or max_amount is not None:
                filtered_expenses = db.session.query(
                    ExpensesLedger.expense_id,
                    db.func.max(ExpensesLedger.amount).label('amount')
                ).filter(ExpensesLedger.expense_id.isnot(None))\
                 .group_by(ExpensesLedger.expense_id)

                if min_amount is not None:
                    filtered_expenses = filtered_expenses.having(db.func.max(ExpensesLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_expenses = filtered_expenses.having(db.func.max(ExpensesLedger.amount) <= max_amount)

                filtered_expenses = filtered_expenses.subquery()
                category_summary = category_summary.join(filtered_expenses,
                    ExpensesLedger.expense_id == filtered_expenses.c.expense_id
                )

            category_summary = category_summary.group_by(ExpenseCategory.category_name, ExpenseCategory.type)\
                .order_by(db.func.sum(max_amount_per_expense.c.max_amount).desc())\
                .limit(10).all()

            # Monthly summary
            monthly_summary = db.session.query(
                db.func.extract('year', ExpensesLedger.created_at).label("year"),
                db.func.extract('month', ExpensesLedger.created_at).label("month"),
                db.func.count(db.distinct(ExpensesLedger.expense_id)).label("expense_count"),
                db.func.sum(max_amount_per_expense.c.max_amount).label("total_amount"),
                db.func.avg(max_amount_per_expense.c.max_amount).label("average_amount")
            ).join(max_amount_per_expense, ExpensesLedger.expense_id == max_amount_per_expense.c.expense_id)\
             .filter(ExpensesLedger.expense_id.isnot(None))

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    monthly_summary = monthly_summary.filter(ExpensesLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    monthly_summary = monthly_summary.filter(ExpensesLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_expenses = db.session.query(
                    ExpensesLedger.expense_id,
                    db.func.max(ExpensesLedger.amount).label('amount')
                ).filter(ExpensesLedger.expense_id.isnot(None))\
                 .group_by(ExpensesLedger.expense_id)

                if min_amount is not None:
                    filtered_expenses = filtered_expenses.having(db.func.max(ExpensesLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_expenses = filtered_expenses.having(db.func.max(ExpensesLedger.amount) <= max_amount)

                filtered_expenses = filtered_expenses.subquery()
                monthly_summary = monthly_summary.join(filtered_expenses,
                    ExpensesLedger.expense_id == filtered_expenses.c.expense_id
                )

            monthly_summary = monthly_summary.group_by(
                db.func.extract('year', ExpensesLedger.created_at),
                db.func.extract('month', ExpensesLedger.created_at)
            ).order_by(
                db.func.extract('year', ExpensesLedger.created_at).desc(),
                db.func.extract('month', ExpensesLedger.created_at).desc()
            ).limit(12).all()
            # ============ END SUMMARY STATISTICS ============

            return jsonify({
                "data": data,
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "next_num": page + 1 if page < total_pages else None,
                    "prev_num": page - 1 if page > 1 else None
                },
                "summary": {
                    "total_entries": summary.total_entries or 0,
                    "total_amount": float(summary.total_amount or 0),
                    "average_amount": float(summary.average_amount or 0),
                    "max_amount": float(summary.max_amount or 0),
                    "min_amount": float(summary.min_amount or 0),
                    "unique_expenses": summary.unique_expenses or 0,
                    "unique_shops": summary.unique_shops or 0,
                    "unique_categories": summary.unique_categories or 0,
                    "unique_debit_accounts": summary.unique_debit_accounts or 0,
                    "unique_credit_accounts": summary.unique_credit_accounts or 0,
                    "top_categories": [{
                        "category_name": row.category_name,
                        "category_type": row.category_type,
                        "expense_count": row.expense_count,
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in category_summary],
                    "monthly_summary": [{
                        "year": int(row.year),
                        "month": int(row.month),
                        "month_name": datetime(2000, int(row.month), 1).strftime('%B'),
                        "expense_count": row.expense_count,
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in monthly_summary]
                }
            })

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500
        
class SpoiltStockLedgerList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            spoilt_id = request.args.get('spoilt_id', type=int)
            shop_id = request.args.get('shop_id', type=int)
            debit_account_id = request.args.get('debit_account_id', type=int)
            credit_account_id = request.args.get('credit_account_id', type=int)
            account_id = request.args.get('account_id', type=int)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            min_amount = request.args.get('min_amount', type=float)
            max_amount = request.args.get('max_amount', type=float)
            
            # Alias chart_of_accounts
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)

            # Build subquery to get the latest entry for each spoilt_id
            base_transaction_subquery = db.session.query(
                SpoiltStockLedger.spoilt_id,
                db.func.max(SpoiltStockLedger.created_at).label('created_at'),
                db.func.max(SpoiltStockLedger.id).label('id'),
                db.func.max(SpoiltStockLedger.description).label('description'),
                db.func.max(SpoiltStockLedger.amount).label('amount'),
                db.func.max(SpoiltStockLedger.debit_account_id).label('debit_account_id'),
                db.func.max(SpoiltStockLedger.credit_account_id).label('credit_account_id'),
                db.func.max(SpoiltStockLedger.shop_id).label('shop_id')
            ).group_by(
                SpoiltStockLedger.spoilt_id
            ).subquery()
            
            # Subquery to get debit account info (first non-null)
            debit_subquery = db.session.query(
                SpoiltStockLedger.spoilt_id,
                SpoiltStockLedger.debit_account_id,
                db.func.row_number().over(
                    partition_by=SpoiltStockLedger.spoilt_id,
                    order_by=SpoiltStockLedger.id
                ).label('row_num')
            ).filter(SpoiltStockLedger.debit_account_id.isnot(None)).subquery()
            
            # Subquery to get credit account info (first non-null)
            credit_subquery = db.session.query(
                SpoiltStockLedger.spoilt_id,
                SpoiltStockLedger.credit_account_id,
                db.func.row_number().over(
                    partition_by=SpoiltStockLedger.spoilt_id,
                    order_by=SpoiltStockLedger.id
                ).label('row_num')
            ).filter(SpoiltStockLedger.credit_account_id.isnot(None)).subquery()

            # Build base query - group by spoilt_id to get one row per spoilt stock entry
            query = (
                db.session.query(
                    db.func.max(base_transaction_subquery.c.id).label('id'),
                    db.func.max(base_transaction_subquery.c.created_at).label('created_at'),
                    base_transaction_subquery.c.spoilt_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,
                    DebitAccount.name.label("debit_account_name"),
                    DebitAccount.code.label("debit_account_code"),
                    db.func.max(debit_subquery.c.debit_account_id).label("debit_account_id"),
                    DebitAccount.type.label("debit_account_type"),
                    CreditAccount.name.label("credit_account_name"),
                    CreditAccount.code.label("credit_account_code"),
                    db.func.max(credit_subquery.c.credit_account_id).label("credit_account_id"),
                    CreditAccount.type.label("credit_account_type"),
                    # Shop details
                    Shops.shops_id,
                    Shops.shopname.label("shop_name"),
                    # Spoilt stock details
                    SpoiltStock.id.label("spoilt_stock_id"),
                    SpoiltStock.item.label("item_name"),
                    SpoiltStock.quantity,
                    SpoiltStock.unit,
                    SpoiltStock.disposal_method,
                    SpoiltStock.collector_name,
                    SpoiltStock.comment,
                    SpoiltStock.status,
                    SpoiltStock.batches_affected,
                    SpoiltStock.livestock_deduction,
                    SpoiltStock.created_at.label("spoilt_date"),
                    
                )
                .select_from(base_transaction_subquery)
                .outerjoin(debit_subquery, 
                    db.and_(
                        base_transaction_subquery.c.spoilt_id == debit_subquery.c.spoilt_id,
                        debit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(credit_subquery,
                    db.and_(
                        base_transaction_subquery.c.spoilt_id == credit_subquery.c.spoilt_id,
                        credit_subquery.c.row_num == 1
                    )
                )
                .outerjoin(DebitAccount, debit_subquery.c.debit_account_id == DebitAccount.id)
                .outerjoin(CreditAccount, credit_subquery.c.credit_account_id == CreditAccount.id)
                .join(Shops, base_transaction_subquery.c.shop_id == Shops.shops_id)
                .join(SpoiltStock, base_transaction_subquery.c.spoilt_id == SpoiltStock.id)
                .group_by(
                    base_transaction_subquery.c.spoilt_id,
                    base_transaction_subquery.c.description,
                    base_transaction_subquery.c.amount,
                    base_transaction_subquery.c.created_at,
                    DebitAccount.name,
                    DebitAccount.code,
                    DebitAccount.type,
                    CreditAccount.name,
                    CreditAccount.code,
                    CreditAccount.type,
                    Shops.shops_id,
                    Shops.shopname,
                    SpoiltStock.id,
                    SpoiltStock.item,
                    SpoiltStock.quantity,
                    SpoiltStock.unit,
                    SpoiltStock.disposal_method,
                    SpoiltStock.collector_name,
                    SpoiltStock.comment,
                    SpoiltStock.status,
                    SpoiltStock.batches_affected,
                    SpoiltStock.livestock_deduction,
                    SpoiltStock.created_at
                   
                )
            )

            # Apply filters
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    db.or_(
                        base_transaction_subquery.c.description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        DebitAccount.code.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        CreditAccount.code.ilike(search_term),
                        Shops.shopname.ilike(search_term),
                        SpoiltStock.item.ilike(search_term),
                        SpoiltStock.disposal_method.ilike(search_term),
                        SpoiltStock.collector_name.ilike(search_term),
                        SpoiltStock.comment.ilike(search_term),
                        SpoiltStock.batches_affected.ilike(search_term),
                        base_transaction_subquery.c.spoilt_id.cast(db.String).ilike(search_term)
                    )
                )

            if spoilt_id:
                query = query.filter(base_transaction_subquery.c.spoilt_id == spoilt_id)

            if shop_id:
                query = query.filter(base_transaction_subquery.c.shop_id == shop_id)

            if debit_account_id:
                query = query.having(db.func.max(debit_subquery.c.debit_account_id) == debit_account_id)

            if credit_account_id:
                query = query.having(db.func.max(credit_subquery.c.credit_account_id) == credit_account_id)

            if account_id:
                query = query.having(
                    db.or_(
                        db.func.max(debit_subquery.c.debit_account_id) == account_id,
                        db.func.max(credit_subquery.c.credit_account_id) == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(base_transaction_subquery.c.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(base_transaction_subquery.c.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(base_transaction_subquery.c.amount <= max_amount)

            # ============ PAGINATION COUNT ============
            # Get total count for pagination (distinct spoilt_id)
            total_count_subquery = db.session.query(
                SpoiltStockLedger.spoilt_id
            ).filter(SpoiltStockLedger.spoilt_id.isnot(None))

            # Apply same filters to count subquery
            if search:
                total_count_subquery = total_count_subquery.join(
                    SpoiltStock, 
                    SpoiltStockLedger.spoilt_id == SpoiltStock.id
                ).join(
                    Shops, 
                    SpoiltStockLedger.shop_id == Shops.shops_id
                ).filter(
                    db.or_(
                        SpoiltStockLedger.description.ilike(f"%{search}%"),
                        Shops.shopname.ilike(f"%{search}%"),
                        SpoiltStock.item.ilike(f"%{search}%"),
                        SpoiltStock.disposal_method.ilike(f"%{search}%"),
                        SpoiltStock.collector_name.ilike(f"%{search}%"),
                        SpoiltStock.batches_affected.ilike(f"%{search}%")
                    )
                )

            if spoilt_id:
                total_count_subquery = total_count_subquery.filter(SpoiltStockLedger.spoilt_id == spoilt_id)
            
            if shop_id:
                total_count_subquery = total_count_subquery.filter(SpoiltStockLedger.shop_id == shop_id)
            
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    total_count_subquery = total_count_subquery.filter(SpoiltStockLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    total_count_subquery = total_count_subquery.filter(SpoiltStockLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # Handle amount filters for count
            if min_amount is not None or max_amount is not None:
                amount_subquery = db.session.query(
                    SpoiltStockLedger.spoilt_id,
                    db.func.max(SpoiltStockLedger.amount).label('amount')
                ).filter(SpoiltStockLedger.spoilt_id.isnot(None))\
                 .group_by(SpoiltStockLedger.spoilt_id)
                
                if min_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(SpoiltStockLedger.amount) >= min_amount)
                if max_amount is not None:
                    amount_subquery = amount_subquery.having(db.func.max(SpoiltStockLedger.amount) <= max_amount)
                
                amount_subquery = amount_subquery.subquery()
                total_count_subquery = total_count_subquery.join(amount_subquery, 
                    SpoiltStockLedger.spoilt_id == amount_subquery.c.spoilt_id
                )

            # Get distinct count
            total_count = total_count_subquery.distinct().count()
            total_pages = (total_count + per_page - 1) // per_page
            # ============ END PAGINATION COUNT ============

            # Apply pagination
            query = query.order_by(db.func.max(base_transaction_subquery.c.created_at).desc())
            paginated_query = query.offset((page - 1) * per_page).limit(per_page).all()

            # Prepare results
            data = []
            for row in paginated_query:
                entry = {
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "spoilt_id": row.spoilt_id,
                    "description": row.description,
                    "debit_account": {
                        "id": row.debit_account_id,
                        "name": row.debit_account_name,
                        "code": row.debit_account_code,
                        "type": row.debit_account_type
                    } if row.debit_account_id else None,
                    "credit_account": {
                        "id": row.credit_account_id,
                        "name": row.credit_account_name,
                        "code": row.credit_account_code,
                        "type": row.credit_account_type
                    } if row.credit_account_id else None,
                    "amount": float(row.amount or 0),
                    "shop": {
                        "id": row.shops_id,
                        "name": row.shop_name
                    },
                    "spoilt_stock": {
                        "id": row.spoilt_stock_id,
                        "item_name": row.item_name,
                        "quantity": float(row.quantity) if row.quantity else 0,
                        "unit": row.unit,
                        "disposal_method": row.disposal_method,
                        "collector_name": row.collector_name,
                        "comment": row.comment,
                        "status": row.status,
                        "batches_affected": row.batches_affected,
                        "livestock_deduction": float(row.livestock_deduction) if row.livestock_deduction else 0,
                        "spoilt_date": row.spoilt_date.strftime("%Y-%m-%d %H:%M:%S") if row.spoilt_date else None,
                        
                    }
                }
                data.append(entry)

            # ============ SUMMARY STATISTICS ============
            # Get summary statistics - based on individual entries, not grouped
            total_amount_subquery = db.session.query(
                SpoiltStockLedger.spoilt_id,
                db.func.max(SpoiltStockLedger.amount).label('max_amount')
            ).group_by(SpoiltStockLedger.spoilt_id).subquery()
            
            summary_query = db.session.query(
                db.func.count(SpoiltStockLedger.id).label('total_entries'),
                db.func.sum(total_amount_subquery.c.max_amount).label('total_amount'),
                db.func.avg(total_amount_subquery.c.max_amount).label('average_amount'),
                db.func.max(SpoiltStockLedger.amount).label('max_amount'),
                db.func.min(SpoiltStockLedger.amount).label('min_amount'),
                db.func.count(db.distinct(SpoiltStockLedger.spoilt_id)).label('unique_spoilt_entries'),
                db.func.count(db.distinct(SpoiltStockLedger.shop_id)).label('unique_shops'),
                db.func.count(db.distinct(SpoiltStockLedger.debit_account_id)).label('unique_debit_accounts'),
                db.func.count(db.distinct(SpoiltStockLedger.credit_account_id)).label('unique_credit_accounts')
            ).join(total_amount_subquery, SpoiltStockLedger.spoilt_id == total_amount_subquery.c.spoilt_id)

            # Apply same filters to summary query
            if search:
                summary_query = summary_query.join(Shops, SpoiltStockLedger.shop_id == Shops.shops_id)\
                    .join(SpoiltStock, SpoiltStockLedger.spoilt_id == SpoiltStock.id)\
                    .filter(
                        db.or_(
                            SpoiltStockLedger.description.ilike(f"%{search}%"),
                            Shops.shopname.ilike(f"%{search}%"),
                            SpoiltStock.item.ilike(f"%{search}%"),
                            SpoiltStock.disposal_method.ilike(f"%{search}%"),
                            SpoiltStock.collector_name.ilike(f"%{search}%"),
                            SpoiltStock.batches_affected.ilike(f"%{search}%")
                        )
                    )

            if spoilt_id:
                summary_query = summary_query.filter(SpoiltStockLedger.spoilt_id == spoilt_id)

            if shop_id:
                summary_query = summary_query.filter(SpoiltStockLedger.shop_id == shop_id)

            if debit_account_id:
                summary_query = summary_query.filter(SpoiltStockLedger.debit_account_id == debit_account_id)

            if credit_account_id:
                summary_query = summary_query.filter(SpoiltStockLedger.credit_account_id == credit_account_id)

            if account_id:
                summary_query = summary_query.filter(
                    db.or_(
                        SpoiltStockLedger.debit_account_id == account_id,
                        SpoiltStockLedger.credit_account_id == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(SpoiltStockLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(SpoiltStockLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            # For amount filters on summary, filter by the max amount per spoilt entry
            if min_amount is not None or max_amount is not None:
                filtered_spoilt = db.session.query(
                    SpoiltStockLedger.spoilt_id,
                    db.func.max(SpoiltStockLedger.amount).label('amount')
                ).group_by(SpoiltStockLedger.spoilt_id)
                
                if min_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) <= max_amount)
                
                filtered_spoilt = filtered_spoilt.subquery()
                summary_query = summary_query.join(filtered_spoilt, 
                    SpoiltStockLedger.spoilt_id == filtered_spoilt.c.spoilt_id)

            summary = summary_query.first()

            # Get distribution by shop
            shop_summary_query = db.session.query(
                Shops.shopname.label("shop_name"),
                db.func.count(db.distinct(SpoiltStockLedger.spoilt_id)).label("spoilt_count"),
                db.func.sum(total_amount_subquery.c.max_amount).label("total_amount"),
                db.func.avg(total_amount_subquery.c.max_amount).label("average_amount")
            ).join(Shops, SpoiltStockLedger.shop_id == Shops.shops_id)\
             .join(total_amount_subquery, SpoiltStockLedger.spoilt_id == total_amount_subquery.c.spoilt_id)\
             .filter(SpoiltStockLedger.spoilt_id.isnot(None))

            # Apply filters to shop summary
            if search:
                shop_summary_query = shop_summary_query.join(SpoiltStock, SpoiltStockLedger.spoilt_id == SpoiltStock.id)\
                    .filter(
                        db.or_(
                            Shops.shopname.ilike(f"%{search}%"),
                            SpoiltStockLedger.description.ilike(f"%{search}%"),
                            SpoiltStock.item.ilike(f"%{search}%")
                        )
                    )

            if spoilt_id:
                shop_summary_query = shop_summary_query.filter(SpoiltStockLedger.spoilt_id == spoilt_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    shop_summary_query = shop_summary_query.filter(SpoiltStockLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    shop_summary_query = shop_summary_query.filter(SpoiltStockLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_spoilt = db.session.query(
                    SpoiltStockLedger.spoilt_id,
                    db.func.max(SpoiltStockLedger.amount).label('amount')
                ).group_by(SpoiltStockLedger.spoilt_id)
                
                if min_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) <= max_amount)
                
                filtered_spoilt = filtered_spoilt.subquery()
                shop_summary_query = shop_summary_query.join(filtered_spoilt, 
                    SpoiltStockLedger.spoilt_id == filtered_spoilt.c.spoilt_id)

            shop_summary = shop_summary_query.group_by(Shops.shopname)\
                .order_by(db.func.sum(total_amount_subquery.c.max_amount).desc())\
                .all()

            # Get distribution by status
            status_summary_query = db.session.query(
                SpoiltStock.status,
                db.func.count(db.distinct(SpoiltStockLedger.spoilt_id)).label("spoilt_count"),
                db.func.sum(total_amount_subquery.c.max_amount).label("total_amount"),
                db.func.avg(total_amount_subquery.c.max_amount).label("average_amount")
            ).join(SpoiltStock, SpoiltStockLedger.spoilt_id == SpoiltStock.id)\
             .join(total_amount_subquery, SpoiltStockLedger.spoilt_id == total_amount_subquery.c.spoilt_id)\
             .filter(SpoiltStockLedger.spoilt_id.isnot(None))

            # Apply filters to status summary
            if shop_id:
                status_summary_query = status_summary_query.filter(SpoiltStockLedger.shop_id == shop_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    status_summary_query = status_summary_query.filter(SpoiltStockLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    status_summary_query = status_summary_query.filter(SpoiltStockLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_spoilt = db.session.query(
                    SpoiltStockLedger.spoilt_id,
                    db.func.max(SpoiltStockLedger.amount).label('amount')
                ).group_by(SpoiltStockLedger.spoilt_id)
                
                if min_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) <= max_amount)
                
                filtered_spoilt = filtered_spoilt.subquery()
                status_summary_query = status_summary_query.join(filtered_spoilt, 
                    SpoiltStockLedger.spoilt_id == filtered_spoilt.c.spoilt_id)

            status_summary = status_summary_query.group_by(SpoiltStock.status)\
                .order_by(db.func.sum(total_amount_subquery.c.max_amount).desc())\
                .all()

            # Get top items spoilt
            items_summary_query = db.session.query(
                SpoiltStock.item.label("item_name"),
                db.func.count(db.distinct(SpoiltStockLedger.spoilt_id)).label("spoilt_count"),
                db.func.sum(SpoiltStock.quantity).label("total_quantity"),
                db.func.sum(total_amount_subquery.c.max_amount).label("total_amount"),
                db.func.avg(total_amount_subquery.c.max_amount).label("average_amount")
            ).join(SpoiltStock, SpoiltStockLedger.spoilt_id == SpoiltStock.id)\
             .join(total_amount_subquery, SpoiltStockLedger.spoilt_id == total_amount_subquery.c.spoilt_id)\
             .filter(SpoiltStockLedger.spoilt_id.isnot(None))

            # Apply filters to items summary
            if shop_id:
                items_summary_query = items_summary_query.filter(SpoiltStockLedger.shop_id == shop_id)

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    items_summary_query = items_summary_query.filter(SpoiltStockLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    items_summary_query = items_summary_query.filter(SpoiltStockLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None or max_amount is not None:
                filtered_spoilt = db.session.query(
                    SpoiltStockLedger.spoilt_id,
                    db.func.max(SpoiltStockLedger.amount).label('amount')
                ).group_by(SpoiltStockLedger.spoilt_id)
                
                if min_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) >= min_amount)
                if max_amount is not None:
                    filtered_spoilt = filtered_spoilt.having(db.func.max(SpoiltStockLedger.amount) <= max_amount)
                
                filtered_spoilt = filtered_spoilt.subquery()
                items_summary_query = items_summary_query.join(filtered_spoilt, 
                    SpoiltStockLedger.spoilt_id == filtered_spoilt.c.spoilt_id)

            items_summary = items_summary_query.group_by(SpoiltStock.item)\
                .order_by(db.func.sum(total_amount_subquery.c.max_amount).desc())\
                .limit(10)\
                .all()
            # ============ END SUMMARY STATISTICS ============

            return jsonify({
                "data": data,
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "next_num": page + 1 if page < total_pages else None,
                    "prev_num": page - 1 if page > 1 else None
                },
                "summary": {
                    "total_entries": summary.total_entries or 0,
                    "total_amount": float(summary.total_amount or 0),
                    "average_amount": float(summary.average_amount or 0),
                    "max_amount": float(summary.max_amount or 0),
                    "min_amount": float(summary.min_amount or 0),
                    "unique_spoilt_entries": summary.unique_spoilt_entries or 0,
                    "unique_shops": summary.unique_shops or 0,
                    "unique_debit_accounts": summary.unique_debit_accounts or 0,
                    "unique_credit_accounts": summary.unique_credit_accounts or 0,
                    "distribution_by_shop": [{
                        "shop_name": row.shop_name,
                        "spoilt_count": row.spoilt_count,
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in shop_summary],
                    "distribution_by_status": [{
                        "status": row.status,
                        "spoilt_count": row.spoilt_count,
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in status_summary],
                    "top_items_spoilt": [{
                        "item_name": row.item_name,
                        "spoilt_count": row.spoilt_count,
                        "total_quantity": float(row.total_quantity or 0),
                        "total_amount": float(row.total_amount or 0),
                        "average_amount": float(row.average_amount or 0)
                    } for row in items_summary]
                }
            })

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500
        
class CreateManualLedger(Resource):

    @jwt_required()
    def post(self):
        data = request.get_json()

        debit_account_id = data.get("debit_account_id")
        credit_account_id = data.get("credit_account_id")
        shop_id = data.get("shop_id")
        amount = data.get("amount")
        description = data.get("description")
        

        # ===== Strict Double Entry Validation =====
        if not amount:
            return {"message": "Amount is required"}, 400

        if not debit_account_id or not credit_account_id:
            return {"message": "Both debit and credit accounts are required"}, 400

        if debit_account_id == credit_account_id:
            return {"message": "Debit and Credit accounts cannot be the same"}, 400

        # Validate debit account
        debit_account = ChartOfAccounts.query.get(debit_account_id)
        if not debit_account:
            return {"message": "Invalid debit account"}, 404

        # Validate credit account
        credit_account = ChartOfAccounts.query.get(credit_account_id)
        if not credit_account:
            return {"message": "Invalid credit account"}, 404

        # Validate shop
        if shop_id:
            shop = Shops.query.get(shop_id)
            if not shop:
                return {"message": "Invalid shop_id"}, 404

        timestamp = datetime.utcnow()

        # ===== Entry 1 → Debit Side =====
        debit_entry = ManualLedger(
            debit_account_id=debit_account_id,
            credit_account_id=None,
            description=description,
            shop_id=shop_id,
            amount=amount,
            created_at=timestamp
        )

        # ===== Entry 2 → Credit Side =====
        credit_entry = ManualLedger(
            debit_account_id=None,
            credit_account_id=credit_account_id,
            description=description,
            shop_id=shop_id,
            amount=amount,
            created_at=timestamp
        )

        db.session.add(debit_entry)
        db.session.add(credit_entry)
        db.session.commit()

        return {
            "message": "Double entry posted successfully",
            "debit_entry_id": debit_entry.id,
            "credit_entry_id": credit_entry.id,
            "amount": amount,
            "description": description,
            "shop_id": shop_id,
            "created_at": timestamp.isoformat()
        }, 201
        
class ManualLedgerList(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            search = request.args.get('search', '', type=str)
            ledger_id = request.args.get('id', type=int)
            shop_id = request.args.get('shop_id', type=int)
            debit_account_id = request.args.get('debit_account_id', type=int)
            credit_account_id = request.args.get('credit_account_id', type=int)
            account_id = request.args.get('account_id', type=int)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            min_amount = request.args.get('min_amount', type=float)
            max_amount = request.args.get('max_amount', type=float)
            
            # Aliases for ChartOfAccounts
            DebitAccount = aliased(ChartOfAccounts)
            CreditAccount = aliased(ChartOfAccounts)

            # Build base query
            query = db.session.query(
                ManualLedger.id,
                ManualLedger.created_at,
                ManualLedger.description,
                ManualLedger.amount,
                # Debit account details
                DebitAccount.id.label("debit_account_id"),
                DebitAccount.name.label("debit_account_name"),
                DebitAccount.code.label("debit_account_code"),
                DebitAccount.type.label("debit_account_type"),
                # Credit account details
                CreditAccount.id.label("credit_account_id"),
                CreditAccount.name.label("credit_account_name"),
                CreditAccount.code.label("credit_account_code"),
                CreditAccount.type.label("credit_account_type"),
                # Shop details
                Shops.shops_id,
                Shops.shopname.label("shop_name")
            ).outerjoin(
                DebitAccount, 
                ManualLedger.debit_account_id == DebitAccount.id
            ).outerjoin(
                CreditAccount, 
                ManualLedger.credit_account_id == CreditAccount.id
            ).outerjoin(
                Shops, 
                ManualLedger.shop_id == Shops.shops_id
            )

            # Apply filters
            if ledger_id:
                query = query.filter(ManualLedger.id == ledger_id)

            if shop_id:
                query = query.filter(ManualLedger.shop_id == shop_id)

            if debit_account_id:
                query = query.filter(ManualLedger.debit_account_id == debit_account_id)

            if credit_account_id:
                query = query.filter(ManualLedger.credit_account_id == credit_account_id)

            if account_id:
                query = query.filter(
                    or_(
                        ManualLedger.debit_account_id == account_id,
                        ManualLedger.credit_account_id == account_id
                    )
                )

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    query = query.filter(ManualLedger.created_at >= start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    query = query.filter(ManualLedger.created_at <= end_date_obj)
                except ValueError:
                    pass

            if min_amount is not None:
                query = query.filter(ManualLedger.amount >= min_amount)

            if max_amount is not None:
                query = query.filter(ManualLedger.amount <= max_amount)

            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    or_(
                        ManualLedger.description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        DebitAccount.code.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        CreditAccount.code.ilike(search_term),
                        Shops.shopname.ilike(search_term),
                        func.cast(ManualLedger.amount, db.String).ilike(search_term)
                    )
                )

            # Get total count for pagination
            total_count = query.count()
            total_pages = (total_count + per_page - 1) // per_page

            # Apply pagination and ordering
            query = query.order_by(ManualLedger.created_at.desc())
            paginated_query = query.offset((page - 1) * per_page).limit(per_page).all()

            # Prepare results
            data = []
            for row in paginated_query:
                entry = {
                    "id": row.id,
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "description": row.description,
                    "amount": float(row.amount or 0),
                    "debit_account": {
                        "id": row.debit_account_id,
                        "name": row.debit_account_name,
                        "code": row.debit_account_code,
                        "type": row.debit_account_type
                    } if row.debit_account_id else None,
                    "credit_account": {
                        "id": row.credit_account_id,
                        "name": row.credit_account_name,
                        "code": row.credit_account_code,
                        "type": row.credit_account_type
                    } if row.credit_account_id else None,
                    "shop": {
                        "id": row.shops_id,
                        "name": row.shop_name
                    } if row.shops_id else None
                }
                data.append(entry)

            # Summary statistics
            summary_query = db.session.query(
                func.count(ManualLedger.id).label('total_entries'),
                func.sum(ManualLedger.amount).label('total_amount'),
                func.avg(ManualLedger.amount).label('average_amount'),
                func.max(ManualLedger.amount).label('max_amount'),
                func.min(ManualLedger.amount).label('min_amount'),
                func.count(db.distinct(ManualLedger.shop_id)).label('unique_shops'),
                func.count(db.distinct(ManualLedger.debit_account_id)).label('unique_debit_accounts'),
                func.count(db.distinct(ManualLedger.credit_account_id)).label('unique_credit_accounts')
            )

            # Apply same filters to summary
            if ledger_id:
                summary_query = summary_query.filter(ManualLedger.id == ledger_id)
            if shop_id:
                summary_query = summary_query.filter(ManualLedger.shop_id == shop_id)
            if debit_account_id:
                summary_query = summary_query.filter(ManualLedger.debit_account_id == debit_account_id)
            if credit_account_id:
                summary_query = summary_query.filter(ManualLedger.credit_account_id == credit_account_id)
            if account_id:
                summary_query = summary_query.filter(
                    or_(
                        ManualLedger.debit_account_id == account_id,
                        ManualLedger.credit_account_id == account_id
                    )
                )
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    summary_query = summary_query.filter(ManualLedger.created_at >= start_date_obj)
                except ValueError:
                    pass
            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    summary_query = summary_query.filter(ManualLedger.created_at <= end_date_obj)
                except ValueError:
                    pass
            if min_amount is not None:
                summary_query = summary_query.filter(ManualLedger.amount >= min_amount)
            if max_amount is not None:
                summary_query = summary_query.filter(ManualLedger.amount <= max_amount)
            if search:
                search_term = f"%{search}%"
                summary_query = summary_query.join(
                    DebitAccount, 
                    ManualLedger.debit_account_id == DebitAccount.id, 
                    isouter=True
                ).join(
                    CreditAccount, 
                    ManualLedger.credit_account_id == CreditAccount.id, 
                    isouter=True
                ).join(
                    Shops, 
                    ManualLedger.shop_id == Shops.shops_id, 
                    isouter=True
                ).filter(
                    or_(
                        ManualLedger.description.ilike(search_term),
                        DebitAccount.name.ilike(search_term),
                        DebitAccount.code.ilike(search_term),
                        CreditAccount.name.ilike(search_term),
                        CreditAccount.code.ilike(search_term),
                        Shops.shopname.ilike(search_term)
                    )
                )

            summary = summary_query.first()

            return jsonify({
                "data": data,
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "next_num": page + 1 if page < total_pages else None,
                    "prev_num": page - 1 if page > 1 else None
                },
                "summary": {
                    "total_entries": summary.total_entries or 0,
                    "total_amount": float(summary.total_amount or 0),
                    "average_amount": float(summary.average_amount or 0),
                    "max_amount": float(summary.max_amount or 0),
                    "min_amount": float(summary.min_amount or 0),
                    "unique_shops": summary.unique_shops or 0,
                    "unique_debit_accounts": summary.unique_debit_accounts or 0,
                    "unique_credit_accounts": summary.unique_credit_accounts or 0
                }
            })

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500