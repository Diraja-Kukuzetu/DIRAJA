from flask_restful import Resource
from flask import request
from Server.Models.StockReport import StockReport
from Server.Models.Shops import Shops
from flask_jwt_extended import jwt_required, get_jwt_identity
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.Users import Users
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, or_
from sqlalchemy import and_
from flask import jsonify,request,make_response
from math import ceil
from flask import current_app
from Server.Models.StockReconciliation import StockReconciliation
from datetime import datetime
from app import db
from sqlalchemy import func
from sqlalchemy.orm import joinedload
import re



# class SubmitStockReport(Resource):
#     @jwt_required()
#     def post(self):
#         data = request.get_json()

#         user_id = get_jwt_identity()
#         shop_id = data.get('shop_id')
#         report_data = data.get('report')  # JSON report
#         comment = data.get('note', '')

#         if not shop_id or not report_data:
#             return {'message': 'shop_id and report data are required'}, 400

#         # ✅ Check shop existence
#         shop = Shops.query.filter_by(shops_id=shop_id).first()
#         if not shop:
#             return {'message': 'Shop not found'}, 404

#         # ✅ Check if a report has already been submitted (today) based on report_status
#         if shop.report_status:
#             return {'message': 'Stock report already submitted today'}, 400

#         # Optional: Extract comment from differences
#         if not comment:
#             differences = report_data.get("differences", {})
#             for item in differences.values():
#                 reason = item.get("reason")
#                 if reason:
#                     comment = reason
#                     break

#         # ✅ Create the StockReport
#         report = StockReport(
#             shop_id=shop_id,
#             user_id=user_id,
#             report=report_data,
#             comment=comment
#         )

#         # ✅ Mark the shop as reported for today
#         shop.report_status = True

#         db.session.add(report)
#         db.session.commit()

#         return {'message': 'Stock report submitted successfully'}, 201


class SubmitStockReport(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        user_id = get_jwt_identity()
        shop_id = data.get('shop_id')
        report_data = data.get('report')  # JSON report
        comment = data.get('note', '')

        if not shop_id or not report_data:
            return {'message': 'shop_id and report data are required'}, 400

        # ✅ Check shop existence
        shop = Shops.query.filter_by(shops_id=shop_id).first()
        if not shop:
            return {'message': 'Shop not found'}, 404

        # ✅ Prevent duplicate report submissions
        if shop.report_status:
            return {'message': 'Stock report already submitted today'}, 400

        # ✅ Extract comment from differences if not provided
        if not comment:
            differences = report_data.get("differences", {})
            for item in differences.values():
                reason = item.get("reason")
                if reason:
                    comment = reason
                    break

        try:
            # Start transaction
            db.session.begin_nested()

            # ✅ Create StockReport
            report = StockReport(
                shop_id=shop_id,
                user_id=user_id,
                report=report_data,
                comment=comment
            )
            db.session.add(report)

            # ✅ Mark shop as reported
            shop.report_status = True

            # ✅ Create reconciliation records
            reconciliation_results = self.create_reconciliation_records(
                shop_id, user_id, report_data, comment
            )

            db.session.commit()

            return {
                'message': 'Stock report submitted successfully',
                'reconciliation_created': len(reconciliation_results),
                'reconciliation_details': reconciliation_results
            }, 201

        except Exception as e:
            db.session.rollback()
            return {'message': f'Error processing stock report: {str(e)}'}, 500

    def parse_report_value(self, value_str):
        """
        Parse the report value string to extract quantity and unit.
        Returns tuple (quantity, unit)
        """
        if not value_str or value_str == "null":
            return 0, ""

        value_str = str(value_str).strip()

        # Handle "null"
        if "null" in value_str.lower():
            match = re.search(r'([\d.]+)\s*null', value_str)
            if match:
                return float(match.group(1)), ""
            return 0, ""

        # Handle known units
        for unit in ["item", "kg", "pcs", "pc"]:
            if unit in value_str.lower():
                match = re.search(r'([\d.]+)\s*' + unit, value_str, re.IGNORECASE)
                if match:
                    detected_unit = unit if unit != "pc" else "pcs"
                    return float(match.group(1)), detected_unit

        # Handle generic cases
        match = re.search(r'([\d.]+)\s*([a-zA-Z]*)', value_str)
        if match:
            quantity = float(match.group(1))
            unit = match.group(2).lower().strip()
            return quantity, unit

        # Try plain numbers (no unit)
        try:
            return float(value_str), ""
        except:
            print(f"Warning: Could not parse report value: '{value_str}'")
            return 0, ""

    def normalize_item_name(self, item_name):
        """
        Normalize item names for comparison between report and stock data
        """
        normalized = ' '.join(item_name.lower().split())

        replacements = {
            'catering sausages': 'sausage',
            'smokies': 'smokie',
            'boneless breast': 'breast',
            'drumstick': 'drum stick',
            'gizzard': 'gizzards',
        }

        for old, new in replacements.items():
            if old in normalized:
                normalized = normalized.replace(old, new)

        return normalized

    def get_stock_value_for_item(self, shop_id, report_item_name, report_unit):
        """
        Find matching items in ShopStockV2 for a given shop and return total quantity
        """
        normalized_name = self.normalize_item_name(report_item_name)
        stock_items = ShopStockV2.query.filter_by(shop_id=shop_id).all()

        total_quantity = 0.0
        match_found = False
        match_type = "no_match"

        for stock_item in stock_items:
            stock_item_name_normalized = self.normalize_item_name(stock_item.itemname)

            if stock_item_name_normalized == normalized_name:
                total_quantity += float(stock_item.quantity or 0)
                match_found = True
                match_type = "exact_match"

            elif normalized_name in stock_item_name_normalized or stock_item_name_normalized in normalized_name:
                total_quantity += float(stock_item.quantity or 0)
                match_found = True
                if match_type != "exact_match":
                    match_type = "partial_match"

        print(f"Stock lookup - Item: {report_item_name}, Normalized: {normalized_name}, "
              f"Stock Qty: {total_quantity}, Match: {match_type}")

        return total_quantity, match_type if match_found else "no_match"

    def create_reconciliation_records(self, shop_id, user_id, report_data, comment):
        """
        Compare report data with ShopStockV2 and create StockReconciliation records
        for items with differences, including skipped items with report_value as 0.
        """
        reconciliation_results = []

        # Extract reported items
        reported_items = {}
        if isinstance(report_data, list):
            reported_items = {entry.get('item'): entry.get('value') for entry in report_data if entry.get('item')}
        elif isinstance(report_data, dict):
            reported_items = {k: v for k, v in report_data.items() if k not in ["differences", "note", "comment"]}
        else:
            raise ValueError("Invalid report_data format. Must be dict or list.")

        # Get all stock items for this shop
        stock_items = ShopStockV2.query.filter_by(shop_id=shop_id).all()
        
        # Create a set of all unique item names from stock (normalized for comparison)
        all_stock_items = {}
        for stock_item in stock_items:
            normalized_name = self.normalize_item_name(stock_item.itemname)
            if normalized_name not in all_stock_items:
                all_stock_items[normalized_name] = {
                    'original_name': stock_item.itemname,
                    'total_quantity': 0.0
                }
            all_stock_items[normalized_name]['total_quantity'] += float(stock_item.quantity or 0)

        # Process all items (both reported and skipped)
        processed_items = set()
        
        # First, process reported items
        for item_name, report_value_str in reported_items.items():
            normalized_name = self.normalize_item_name(item_name)
            processed_items.add(normalized_name)
            
            print(f"Processing reported item: {item_name}, value: '{report_value_str}'")

            report_quantity, report_unit = self.parse_report_value(report_value_str)
            print(f"Parsed - Quantity: {report_quantity}, Unit: '{report_unit}'")

            # Get stock quantity for this item
            stock_quantity = 0.0
            match_status = "no_match"
            
            if normalized_name in all_stock_items:
                stock_quantity = all_stock_items[normalized_name]['total_quantity']
                match_status = "exact_match"
            else:
                # Try to find partial match
                for stock_norm_name, stock_data in all_stock_items.items():
                    if normalized_name in stock_norm_name or stock_norm_name in normalized_name:
                        stock_quantity = stock_data['total_quantity']
                        match_status = "partial_match"
                        break

            difference = round(report_quantity - stock_quantity, 3)

            # ✅ Skip items with no difference
            if abs(difference) < 0.01:
                print(f"Skipping '{item_name}' - no difference (Stock: {stock_quantity}, Report: {report_quantity})")
                continue

            status = 'Unsolved'

            # ✅ Only save reconciliation when there is a difference
            reconciliation = StockReconciliation(
                shop_id=shop_id,
                user_id=user_id,
                stock_value=round(stock_quantity, 3),
                report_value=round(report_quantity, 3),
                item=item_name,
                difference=difference,
                status=status,
                comment=comment,
                created_at=func.now()
            )
            db.session.add(reconciliation)

            reconciliation_results.append({
                'item': item_name,
                'stock_value': round(stock_quantity, 3),
                'report_value': round(report_quantity, 3),
                'difference': difference,
                'status': status,
                'unit': report_unit if report_unit else None,
                'match': match_status
            })

        # Then, process skipped items (items in stock but not reported)
        for normalized_name, stock_data in all_stock_items.items():
            if normalized_name not in processed_items:
                item_name = stock_data['original_name']
                stock_quantity = stock_data['total_quantity']
                report_quantity = 0.0  # Skipped items have report value of 0
                difference = round(report_quantity - stock_quantity, 3)

                print(f"Processing skipped item: {item_name}, Stock: {stock_quantity}, Report: 0")

                # ✅ Only create record if there's a difference (which there will be for skipped items)
                if abs(difference) > 0.01:
                    status = 'Unsolved'

                    reconciliation = StockReconciliation(
                        shop_id=shop_id,
                        user_id=user_id,
                        stock_value=round(stock_quantity, 3),
                        report_value=round(report_quantity, 3),
                        item=item_name,
                        difference=difference,
                        status=status,
                        comment=comment + " (Skipped item)" if comment else "Skipped item",
                        created_at=func.now()
                    )
                    db.session.add(reconciliation)

                    reconciliation_results.append({
                        'item': item_name,
                        'stock_value': round(stock_quantity, 3),
                        'report_value': round(report_quantity, 3),
                        'difference': difference,
                        'status': status,
                        'unit': "",  # No unit for skipped items
                        'match': "exact_match",
                        'note': 'skipped'
                    })

        return reconciliation_results

class InventoryCount(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        user_id = get_jwt_identity()
        shop_id = data.get('shop_id')  # Can be null for inventory stock
        report_data = data.get('report')  # JSON report
        comment = data.get('note', '')

        if not report_data:
            return {'message': 'report data is required'}, 400

        # ✅ Handle inventory stock count (shop_id is null)
        if shop_id is None:
            # For inventory stock count, use default comment
            if not comment:
                comment = "Store weekly stock count"
            
            # No shop validation needed for inventory
            print("Processing inventory stock count - shop_id is null")
            
            try:
                # Start transaction
                db.session.begin_nested()

                # ✅ Create StockReport with null shop_id
                report = StockReport(
                    shop_id=None,  # Explicitly set to null for inventory
                    user_id=user_id,
                    report=report_data,
                    comment=comment
                )
                db.session.add(report)

                # ✅ Create reconciliation records for inventory
                reconciliation_results = self.create_reconciliation_records(
                    shop_id, user_id, report_data, comment
                )

                db.session.commit()

                return {
                    'message': 'Inventory stock count submitted successfully',
                    'reconciliation_created': len(reconciliation_results),
                    'reconciliation_details': reconciliation_results,
                    'type': 'inventory_count'
                }, 201

            except Exception as e:
                db.session.rollback()
                return {'message': f'Error processing inventory stock count: {str(e)}'}, 500
        
        # ✅ Handle regular shop stock report (existing logic)
        else:
            # Check shop existence
            shop = Shops.query.filter_by(shops_id=shop_id).first()
            if not shop:
                return {'message': 'Shop not found'}, 404

            # Prevent duplicate report submissions
            if shop.report_status:
                return {'message': 'Stock report already submitted today'}, 400

            # Extract comment from differences if not provided
            if not comment:
                differences = report_data.get("differences", {})
                for item in differences.values():
                    reason = item.get("reason")
                    if reason:
                        comment = reason
                        break

            try:
                # Start transaction
                db.session.begin_nested()

                # Create StockReport
                report = StockReport(
                    shop_id=shop_id,
                    user_id=user_id,
                    report=report_data,
                    comment=comment
                )
                db.session.add(report)

                # Mark shop as reported
                shop.report_status = True

                # Create reconciliation records
                reconciliation_results = self.create_reconciliation_records(
                    shop_id, user_id, report_data, comment
                )

                db.session.commit()

                return {
                    'message': 'Stock report submitted successfully',
                    'reconciliation_created': len(reconciliation_results),
                    'reconciliation_details': reconciliation_results
                }, 201

            except Exception as e:
                db.session.rollback()
                return {'message': f'Error processing stock report: {str(e)}'}, 500

    def parse_report_value(self, value_str):
        """
        Parse the report value string to extract quantity and unit.
        Returns tuple (quantity, unit)
        """
        if not value_str or value_str == "null":
            return 0, ""

        value_str = str(value_str).strip()

        # Handle "null"
        if "null" in value_str.lower():
            match = re.search(r'([\d.]+)\s*null', value_str)
            if match:
                return float(match.group(1)), ""
            return 0, ""

        # Handle known units
        for unit in ["item", "kg", "pcs", "pc"]:
            if unit in value_str.lower():
                match = re.search(r'([\d.]+)\s*' + unit, value_str, re.IGNORECASE)
                if match:
                    detected_unit = unit if unit != "pc" else "pcs"
                    return float(match.group(1)), detected_unit

        # Handle generic cases
        match = re.search(r'([\d.]+)\s*([a-zA-Z]*)', value_str)
        if match:
            quantity = float(match.group(1))
            unit = match.group(2).lower().strip()
            return quantity, unit

        # Try plain numbers (no unit)
        try:
            return float(value_str), ""
        except:
            print(f"Warning: Could not parse report value: '{value_str}'")
            return 0, ""

    def normalize_item_name(self, item_name):
        """
        Normalize item names for comparison between report and stock data
        """
        normalized = ' '.join(item_name.lower().split())

        replacements = {
            'catering sausages': 'sausage',
            'smokies': 'smokie',
            'boneless breast': 'breast',
            'drumstick': 'drum stick',
            'gizzard': 'gizzards',
        }

        for old, new in replacements.items():
            if old in normalized:
                normalized = normalized.replace(old, new)

        return normalized

    def get_stock_value_for_item(self, shop_id, report_item_name, report_unit):
        """
        Find matching items in ShopStockV2 for a given shop and return total quantity
        """
        normalized_name = self.normalize_item_name(report_item_name)
        
        # Handle inventory stock count (shop_id is None)
        if shop_id is None:
            # For inventory, we might want to get all stock across shops or have a different logic
            # This depends on your business logic - currently returning 0
            print(f"Inventory stock lookup - no shop_id provided")
            return 0.0, "no_match"
            
        stock_items = ShopStockV2.query.filter_by(shop_id=shop_id).all()

        total_quantity = 0.0
        match_found = False
        match_type = "no_match"

        for stock_item in stock_items:
            stock_item_name_normalized = self.normalize_item_name(stock_item.itemname)

            if stock_item_name_normalized == normalized_name:
                total_quantity += float(stock_item.quantity or 0)
                match_found = True
                match_type = "exact_match"

            elif normalized_name in stock_item_name_normalized or stock_item_name_normalized in normalized_name:
                total_quantity += float(stock_item.quantity or 0)
                match_found = True
                if match_type != "exact_match":
                    match_type = "partial_match"

        print(f"Stock lookup - Item: {report_item_name}, Normalized: {normalized_name}, "
              f"Stock Qty: {total_quantity}, Match: {match_type}")

        return total_quantity, match_type if match_found else "no_match"

    def create_reconciliation_records(self, shop_id, user_id, report_data, comment):
        """
        Compare report data with ShopStockV2 and create StockReconciliation records
        for items with differences, including skipped items with report_value as 0.
        """
        reconciliation_results = []

        # Extract reported items
        reported_items = {}
        if isinstance(report_data, list):
            reported_items = {entry.get('item'): entry.get('value') for entry in report_data if entry.get('item')}
        elif isinstance(report_data, dict):
            reported_items = {k: v for k, v in report_data.items() if k not in ["differences", "note", "comment"]}
        else:
            raise ValueError("Invalid report_data format. Must be dict or list.")

        # Get all stock items
        if shop_id is None:
            # For inventory, we might want to get all stock or have different logic
            # This depends on your business logic - currently empty list
            stock_items = []
            print("Processing inventory reconciliation - no shop stock comparison")
        else:
            stock_items = ShopStockV2.query.filter_by(shop_id=shop_id).all()
        
        # Create a set of all unique item names from stock (normalized for comparison)
        all_stock_items = {}
        for stock_item in stock_items:
            normalized_name = self.normalize_item_name(stock_item.itemname)
            if normalized_name not in all_stock_items:
                all_stock_items[normalized_name] = {
                    'original_name': stock_item.itemname,
                    'total_quantity': 0.0
                }
            all_stock_items[normalized_name]['total_quantity'] += float(stock_item.quantity or 0)

        # Process all items (both reported and skipped)
        processed_items = set()
        
        # First, process reported items
        for item_name, report_value_str in reported_items.items():
            normalized_name = self.normalize_item_name(item_name)
            processed_items.add(normalized_name)
            
            print(f"Processing reported item: {item_name}, value: '{report_value_str}'")

            report_quantity, report_unit = self.parse_report_value(report_value_str)
            print(f"Parsed - Quantity: {report_quantity}, Unit: '{report_unit}'")

            # Get stock quantity for this item
            stock_quantity = 0.0
            match_status = "no_match"
            
            if shop_id is not None:  # Only check stock if we have a shop_id
                if normalized_name in all_stock_items:
                    stock_quantity = all_stock_items[normalized_name]['total_quantity']
                    match_status = "exact_match"
                else:
                    # Try to find partial match
                    for stock_norm_name, stock_data in all_stock_items.items():
                        if normalized_name in stock_norm_name or stock_norm_name in normalized_name:
                            stock_quantity = stock_data['total_quantity']
                            match_status = "partial_match"
                            break

            difference = round(report_quantity - stock_quantity, 3)

            # ✅ Skip items with no difference
            if abs(difference) < 0.01:
                print(f"Skipping '{item_name}' - no difference (Stock: {stock_quantity}, Report: {report_quantity})")
                continue

            status = 'Unsolved'

            # ✅ Only save reconciliation when there is a difference
            reconciliation = StockReconciliation(
                shop_id=shop_id,
                user_id=user_id,
                stock_value=round(stock_quantity, 3),
                report_value=round(report_quantity, 3),
                item=item_name,
                difference=difference,
                status=status,
                comment=comment,
                created_at=func.now()
            )
            db.session.add(reconciliation)

            reconciliation_results.append({
                'item': item_name,
                'stock_value': round(stock_quantity, 3),
                'report_value': round(report_quantity, 3),
                'difference': difference,
                'status': status,
                'unit': report_unit if report_unit else None,
                'match': match_status,
                'type': 'inventory' if shop_id is None else 'shop'
            })

        # Then, process skipped items (items in stock but not reported) - only for shops
        if shop_id is not None:
            for normalized_name, stock_data in all_stock_items.items():
                if normalized_name not in processed_items:
                    item_name = stock_data['original_name']
                    stock_quantity = stock_data['total_quantity']
                    report_quantity = 0.0  # Skipped items have report value of 0
                    difference = round(report_quantity - stock_quantity, 3)

                    print(f"Processing skipped item: {item_name}, Stock: {stock_quantity}, Report: 0")

                    # ✅ Only create record if there's a difference (which there will be for skipped items)
                    if abs(difference) > 0.01:
                        status = 'Unsolved'

                        reconciliation = StockReconciliation(
                            shop_id=shop_id,
                            user_id=user_id,
                            stock_value=round(stock_quantity, 3),
                            report_value=round(report_quantity, 3),
                            item=item_name,
                            difference=difference,
                            status=status,
                            comment=comment + " (Skipped item)" if comment else "Skipped item",
                            created_at=func.now()
                        )
                        db.session.add(reconciliation)

                        reconciliation_results.append({
                            'item': item_name,
                            'stock_value': round(stock_quantity, 3),
                            'report_value': round(report_quantity, 3),
                            'difference': difference,
                            'status': status,
                            'unit': report_unit if report_unit else None,
                            'match': "exact_match",
                            'note': 'skipped',
                            'type': 'shop'
                        })

        return reconciliation_results

    
class ResetShopReportStatus(Resource):
    def put(self):
        # Reset report_status to False for all shops except shop_id = 12
        Shops.query.filter(Shops.shops_id != 12).update(
            {Shops.report_status: False},
            synchronize_session=False
        )
        db.session.commit()

        return {'message': 'All shops except shop 12 have been closed'}, 200


class GetStockReports(Resource):
    @jwt_required()
    def get(self):
        # Get query parameters
        shop_id = request.args.get('shop_id')
        user_id = request.args.get('user_id')
        date = request.args.get('date')  # Expected format: YYYY-MM-DD
        limit = request.args.get('limit', default=10, type=int)
        
        # Base query
        query = StockReport.query
        
        # Apply filters
        if shop_id:
            query = query.filter_by(shop_id=shop_id)
        if user_id:
            query = query.filter_by(user_id=user_id)
        if date:
            query = query.filter(func.DATE(StockReport.reported_at) == date)
        
        # Order and limit
        reports = query.order_by(StockReport.reported_at.desc()).limit(limit).all()
        
        # Format response
        result = []
        for report in reports:
            result.append({
                'id': report.id,
                'shop_id': report.shop_id,
                'user_id': report.user_id,
                'report': report.report,
                'comment': report.comment,
                'reported_at': report.reported_at.isoformat(),
                'shop_name': report.shop.shopname if report.shop else None,
                'user_name': report.user.username if report.user else None
            })
        
        return {'reports': result}, 200

class GetStockReportById(Resource):
    @jwt_required()
    def get(self, report_id):
        report = (
            StockReport.query
            .options(joinedload(StockReport.shop), joinedload(StockReport.user))
            .filter_by(id=report_id)
            .first()
        )

        if not report:
            return {"message": "Stock report not found"}, 404

        return {
            'id': report.id,
            'shop_id': report.shop_id,
            'user_id': report.user_id,
            'report': report.report,
            'comment': report.comment,
            'reported_at': report.reported_at.isoformat(),
            'shop_name': report.shop.shopname if report.shop else None,
            'user_name': report.user.username if report.user else None
        }, 200
        
class StockReconciliationList(Resource):
    @jwt_required()
    def get(self):
        """
        Get stock reconciliation records with filtering, pagination, and shop names
        """
        try:
            # Get query parameters - match AllExpenses structure
            page = request.args.get('page', 1, type=int)
            per_page = 50
            shop_name = request.args.get('shopname', type=str)
            item_name = request.args.get('item_name', type=str)
            status = request.args.get('status', type=str)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            search_query = request.args.get('searchQuery', '', type=str)

            # Base query - query only the main model first for pagination
            query = StockReconciliation.query.join(
                Shops, StockReconciliation.shop_id == Shops.shops_id
            )

            # Apply filters using the same pattern as AllExpenses
            filters = []

            if shop_name:
                filters.append(Shops.shopname.ilike(f"%{shop_name}%"))

            if item_name:
                filters.append(StockReconciliation.item.ilike(f"%{item_name}%"))

            if status:
                filters.append(StockReconciliation.status == status)

            if search_query:
                filters.append(or_(
                    StockReconciliation.item.ilike(f"%{search_query}%"),
                    Shops.shopname.ilike(f"%{search_query}%"),
                    StockReconciliation.comment.ilike(f"%{search_query}%")
                ))

            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d')
                    end = datetime.strptime(end_date, '%Y-%m-%d')
                    # Include the entire end date
                    end = end.replace(hour=23, minute=59, second=59)
                    filters.append(StockReconciliation.created_at.between(start, end))
                except ValueError:
                    return make_response(jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400)

            if filters:
                query = query.filter(and_(*filters))

            # Order by latest (created_at descending) like AllExpenses
            query = query.order_by(StockReconciliation.created_at.desc())

            # Use proper pagination like AllExpenses
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            recon_items = pagination.items

            # Now get the shopnames for the paginated results
            reconciliations = []
            for recon in recon_items:
                # Get the shop name for this reconciliation
                shop = Shops.query.filter_by(shops_id=recon.shop_id).first()
                shopname_val = shop.shopname if shop else "Unknown Shop"

                # Format created_at like AllExpenses
                created_at = None
                if recon.created_at:
                    if isinstance(recon.created_at, str):
                        try:
                            created_at = datetime.strptime(recon.created_at, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            created_at = recon.created_at
                    elif isinstance(recon.created_at, datetime):
                        created_at = recon.created_at.strftime('%Y-%m-%d %H:%M:%S')

                reconciliations.append({
                    'id': recon.id,
                    'shop_id': recon.shop_id,
                    'shopname': shopname_val,
                    'user_id': recon.user_id,
                    'item': recon.item,
                    'stock_value': float(recon.stock_value),
                    'report_value': float(recon.report_value),
                    'difference': float(recon.difference),
                    'status': recon.status,
                    'comment': recon.comment,
                    'created_at': created_at,
                })

            # Pagination metadata - match AllExpenses structure exactly
            pagination_info = {
                "page": page,
                "per_page": per_page,
                "total_items": pagination.total,
                "total_pages": ceil(pagination.total / per_page) if pagination.total > 0 else 1,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev,
            }

            return make_response(jsonify({
                "reconciliations": reconciliations,
                "pagination": pagination_info
            }), 200)

        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error: {str(e)}")
            return make_response(jsonify({"error": "Database operation failed."}), 500)
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return make_response(jsonify({"error": "An unexpected error occurred."}), 500)
        
        
class StockReconciliationByShop(Resource):
    @jwt_required()
    def get(self):
        """
        Get stock reconciliation records with filtering, pagination, and shop names.
        Can filter by specific shop using shop_id parameter.
        """
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 50, type=int)
            shop_id = request.args.get('shop_id', type=int)  # New parameter for specific shop
            shop_name = request.args.get('shopname', type=str)
            item_name = request.args.get('item_name', type=str)
            status = request.args.get('status', type=str)
            start_date = request.args.get('start_date', type=str)
            end_date = request.args.get('end_date', type=str)
            search_query = request.args.get('searchQuery', '', type=str)

            # Base query
            query = StockReconciliation.query.join(
                Shops, StockReconciliation.shop_id == Shops.shops_id
            )

            # Apply filters
            filters = []

            # Filter by specific shop_id if provided (exact match)
            if shop_id:
                filters.append(StockReconciliation.shop_id == shop_id)

            # Filter by shop name (partial match)
            if shop_name:
                filters.append(Shops.shopname.ilike(f"%{shop_name}%"))

            if item_name:
                filters.append(StockReconciliation.item.ilike(f"%{item_name}%"))

            if status:
                filters.append(StockReconciliation.status == status)

            if search_query:
                filters.append(or_(
                    StockReconciliation.item.ilike(f"%{search_query}%"),
                    Shops.shopname.ilike(f"%{search_query}%"),
                    StockReconciliation.comment.ilike(f"%{search_query}%")
                ))

            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d')
                    end = datetime.strptime(end_date, '%Y-%m-%d')
                    # Include the entire end date
                    end = end.replace(hour=23, minute=59, second=59)
                    filters.append(StockReconciliation.created_at.between(start, end))
                except ValueError:
                    return make_response(jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400)

            if filters:
                query = query.filter(and_(*filters))

            # Order by latest
            query = query.order_by(StockReconciliation.created_at.desc())

            # Pagination
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            recon_items = pagination.items

            # Build response
            reconciliations = []
            for recon in recon_items:
                # Get shop name
                shop = Shops.query.filter_by(shops_id=recon.shop_id).first()
                shopname_val = shop.shopname if shop else "Unknown Shop"

                # Format created_at
                created_at = None
                if recon.created_at:
                    if isinstance(recon.created_at, str):
                        try:
                            created_at = datetime.strptime(recon.created_at, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            created_at = recon.created_at
                    elif isinstance(recon.created_at, datetime):
                        created_at = recon.created_at.strftime('%Y-%m-%d %H:%M:%S')

                reconciliations.append({
                    'id': recon.id,
                    'shop_id': recon.shop_id,
                    'shopname': shopname_val,
                    'user_id': recon.user_id,
                    'item': recon.item,
                    'stock_value': float(recon.stock_value),
                    'report_value': float(recon.report_value),
                    'difference': float(recon.difference),
                    'status': recon.status,
                    'comment': recon.comment,
                    'created_at': created_at,
                })

            # Pagination metadata
            pagination_info = {
                "page": page,
                "per_page": per_page,
                "total_items": pagination.total,
                "total_pages": ceil(pagination.total / per_page) if pagination.total > 0 else 1,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev,
            }

            return make_response(jsonify({
                "reconciliations": reconciliations,
                "pagination": pagination_info
            }), 200)

        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error: {str(e)}")
            return make_response(jsonify({"error": "Database operation failed."}), 500)
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return make_response(jsonify({"error": "An unexpected error occurred."}), 500)

class GetReconciliationItemsByShop(Resource):
    @jwt_required()
    def get(self):
        """
        Get reconciliation items with detailed information grouped by shop
        Simplified version - returns only basic data with single date filter
        """
        try:
            shop_id = request.args.get('shop_id', type=int)
            status = request.args.get('status', type=str)
            item_name = request.args.get('item_name', type=str)
            specific_date = request.args.get('date', type=str)  # Single date parameter
            search_query = request.args.get('searchQuery', '', type=str)

            # Query for reconciliation items with shop details
            query = db.session.query(
                StockReconciliation,
                Shops.shopname
            ).join(
                Shops, StockReconciliation.shop_id == Shops.shops_id
            )

            # Apply filters
            if shop_id:
                query = query.filter(StockReconciliation.shop_id == shop_id)

            if status:
                query = query.filter(StockReconciliation.status == status)

            if item_name:
                query = query.filter(StockReconciliation.item.ilike(f"%{item_name}%"))

            if search_query:
                query = query.filter(or_(
                    StockReconciliation.item.ilike(f"%{search_query}%"),
                    Shops.shopname.ilike(f"%{search_query}%"),
                    StockReconciliation.comment.ilike(f"%{search_query}%")
                ))

            if specific_date:
                try:
                    # Parse the specific date
                    target_date = datetime.strptime(specific_date, '%Y-%m-%d')
                    # Filter for the entire day
                    start_of_day = target_date.replace(hour=0, minute=0, second=0)
                    end_of_day = target_date.replace(hour=23, minute=59, second=59)
                    query = query.filter(StockReconciliation.created_at.between(start_of_day, end_of_day))
                except ValueError:
                    return make_response(jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400)

            # Order by shop and creation date
            query = query.order_by(
                Shops.shopname,
                StockReconciliation.created_at.desc()
            )

            reconciliation_items = query.all()

            # Group items by shop
            shop_items_dict = {}
            for recon, shopname in reconciliation_items:
                shop_id_val = recon.shop_id
                
                if shop_id_val not in shop_items_dict:
                    shop_items_dict[shop_id_val] = {
                        "shop_id": shop_id_val,
                        "shopname": shopname,
                        "items": []
                    }
                
                # Format created_at
                created_at = None
                if recon.created_at:
                    if isinstance(recon.created_at, str):
                        try:
                            created_at = datetime.strptime(recon.created_at, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            created_at = recon.created_at
                    elif isinstance(recon.created_at, datetime):
                        created_at = recon.created_at.strftime('%Y-%m-%d %H:%M:%S')
                
                # Create item record (only basic data)
                item_record = {
                    # 'id': recon.id,
                    # 'shop_id': recon.shop_id,
                    # 'shopname': shopname,
                    # 'user_id': recon.user_id,
                    'item': recon.item,
                    # 'stock_value': float(recon.stock_value),
                    'report_value': float(recon.report_value),
                    # 'difference': float(recon.difference),
                    # 'status': recon.status,
                    # 'comment': recon.comment,
                    'created_at': created_at,
                }
                
                shop_items_dict[shop_id_val]["items"].append(item_record)

            # Convert dict to list
            shop_reconciliations = []
            for shop_data in shop_items_dict.values():
                shop_reconciliations.append(shop_data)

            # Response (simplified)
            response = {
                "shop_id": shop_id,
                "status_filter": status,
                "item_filter": item_name,
                "date_filter": specific_date,
                "search_query": search_query if search_query else None,
                "total_shops": len(shop_reconciliations),
                "total_reconciliations": sum(len(shop["items"]) for shop in shop_reconciliations),
                "shop_reconciliations": shop_reconciliations
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred while fetching reconciliation items",
                "details": str(e)
            }), 500)
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return make_response(jsonify({
                "error": "An unexpected error occurred",
                "details": str(e)
            }), 500) 
            
class ReconciliationItemsByShop(Resource):
    @jwt_required()
    def get(self):
        """
        Get reconciliation items with detailed information grouped by shop
        Fetches by shop_id for the current date
        """
        try:
            shop_id = request.args.get('shop_id', type=int)
            status = request.args.get('status', type=str)
            item_name = request.args.get('item_name', type=str)
            specific_date = request.args.get('date', type=str)  # Optional date parameter
            search_query = request.args.get('searchQuery', '', type=str)

            # Validate shop_id is required
            if not shop_id:
                return make_response(jsonify({"error": "shop_id parameter is required"}), 400)

            # Query for reconciliation items with shop details
            query = db.session.query(
                StockReconciliation,
                Shops.shopname
            ).join(
                Shops, StockReconciliation.shop_id == Shops.shops_id
            ).filter(StockReconciliation.shop_id == shop_id)  # Always filter by shop_id

            # Apply status filter
            if status:
                query = query.filter(StockReconciliation.status == status)

            # Apply item name filter
            if item_name:
                query = query.filter(StockReconciliation.item.ilike(f"%{item_name}%"))

            # Apply search query filter
            if search_query:
                query = query.filter(or_(
                    StockReconciliation.item.ilike(f"%{search_query}%"),
                    Shops.shopname.ilike(f"%{search_query}%"),
                    StockReconciliation.comment.ilike(f"%{search_query}%")
                ))

            # Handle date filtering - prioritize specific_date if provided, otherwise use current date
            if specific_date:
                try:
                    # Parse the specific date
                    target_date = datetime.strptime(specific_date, '%Y-%m-%d')
                    # Filter for the entire day
                    start_of_day = target_date.replace(hour=0, minute=0, second=0)
                    end_of_day = target_date.replace(hour=23, minute=59, second=59)
                    query = query.filter(StockReconciliation.created_at.between(start_of_day, end_of_day))
                    date_used = specific_date
                except ValueError:
                    return make_response(jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400)
            else:
                # Use current date by default
                today = datetime.now().date()
                start_of_day = datetime.combine(today, datetime.min.time())
                end_of_day = datetime.combine(today, datetime.max.time())
                query = query.filter(StockReconciliation.created_at.between(start_of_day, end_of_day))
                date_used = today.strftime('%Y-%m-%d')

            # Order by creation date (most recent first)
            query = query.order_by(StockReconciliation.created_at.desc())

            reconciliation_items = query.all()

            # Group items by shop
            shop_items_dict = {}
            for recon, shopname in reconciliation_items:
                shop_id_val = recon.shop_id
                
                if shop_id_val not in shop_items_dict:
                    shop_items_dict[shop_id_val] = {
                        "shop_id": shop_id_val,
                        "shopname": shopname,
                        "date": date_used,
                        "items": [],
                        "summary": {
                            "total_items": 0,
                            "total_report_value": 0.0
                        }
                    }
                
                # Format created_at
                created_at = None
                if recon.created_at:
                    if isinstance(recon.created_at, str):
                        try:
                            created_at = datetime.strptime(recon.created_at, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            created_at = recon.created_at
                    elif isinstance(recon.created_at, datetime):
                        created_at = recon.created_at.strftime('%Y-%m-%d %H:%M:%S')
                
                # Create item record
                item_record = {
                    # 'id': recon.id,
                    'shop_id': recon.shop_id,
                    # 'shopname': shopname,
                    # 'user_id': recon.user_id,
                    'item': recon.item,
                    'stock_value': float(recon.stock_value),
                    'report_value': float(recon.report_value),
                    'difference': float(recon.difference),
                    # 'status': recon.status,
                    # 'comment': recon.comment,
                    # 'created_at': created_at,
                }
                
                shop_items_dict[shop_id_val]["items"].append(item_record)
                # Update summary
                shop_items_dict[shop_id_val]["summary"]["total_items"] += 1
                shop_items_dict[shop_id_val]["summary"]["total_report_value"] += float(recon.report_value)

            # Convert dict to list
            shop_reconciliations = []
            for shop_data in shop_items_dict.values():
                shop_reconciliations.append(shop_data)

            # Response
            response = {
                "shop_id": shop_id,
                "date": date_used,
                "status_filter": status,
                "item_filter": item_name,
                "search_query": search_query if search_query else None,
                "total_shops": len(shop_reconciliations),
                "total_reconciliations": sum(len(shop["items"]) for shop in shop_reconciliations),
                "shop_reconciliations": shop_reconciliations
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred while fetching reconciliation items",
                "details": str(e)
            }), 500)
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return make_response(jsonify({
                "error": "An unexpected error occurred",
                "details": str(e)
            }), 500)           
                  
        
class StockReconciliationResource(Resource):
    @jwt_required()
    def put(self, reconciliation_id):
        """
        Update an existing stock reconciliation record
        """
        data = request.get_json()
        user_id = get_jwt_identity()

        if not data:
            return {'message': 'No data provided'}, 400

        try:
            # Find the reconciliation record
            reconciliation = StockReconciliation.query.get(reconciliation_id)
            if not reconciliation:
                return {'message': 'Stock reconciliation record not found'}, 404

            # Check if user has permission to update this record
            # You might want to add additional permission checks here
            # For example, check if user belongs to the same shop or has admin rights

            # Update allowed fields
            allowed_fields = ['status', 'comment', 'difference', 'report_value']
            
            for field in allowed_fields:
                if field in data:
                    setattr(reconciliation, field, data[field])

            # Update updated_at timestamp
            reconciliation.updated_at = func.now()
            
            # Add update comment if provided
            update_comment = data.get('update_comment')
            if update_comment:
                original_comment = reconciliation.comment or ""
                reconciliation.comment = f"{original_comment} | Update: {update_comment}"

            db.session.commit()

            return {
                'message': 'Stock reconciliation updated successfully',
                'reconciliation': {
                    'id': reconciliation.id,
                    'item': reconciliation.item,
                    'stock_value': reconciliation.stock_value,
                    'report_value': reconciliation.report_value,
                    'difference': reconciliation.difference,
                    'status': reconciliation.status,
                    'comment': reconciliation.comment,
                    'shop_id': reconciliation.shop_id,
                    'user_id': reconciliation.user_id,
                    'created_at': reconciliation.created_at.isoformat() if reconciliation.created_at else None,
                }
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Error updating stock reconciliation: {str(e)}'}, 500

    @jwt_required()
    def delete(self, reconciliation_id):
        """
        Delete a stock reconciliation record
        """
        users_id = get_jwt_identity()

        try:
            # Find the reconciliation record
            reconciliation = StockReconciliation.query.get(reconciliation_id)
            if not reconciliation:
                return {'message': 'Stock reconciliation record not found'}, 404

            # Check if user has permission to delete this record
            # Add your permission logic here
            # For example: check if user is admin or owns the shop
            
            # Optional: Check if user is admin or has delete privileges
            # if not self.user_can_delete(user_id, reconciliation.shop_id):
            #     return {'message': 'Unauthorized to delete this record'}, 403

            # Store record info for response before deletion
            deleted_record = {
                'id': reconciliation.id,
                'item': reconciliation.item,
                'shop_id': reconciliation.shop_id,
                'created_at': reconciliation.created_at.isoformat() if reconciliation.created_at else None
            }

            db.session.delete(reconciliation)
            db.session.commit()

            return {
                'message': 'Stock reconciliation deleted successfully',
                'deleted_record': deleted_record
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': f'Error deleting stock reconciliation: {str(e)}'}, 500

    def user_can_delete(self, user_id, shop_id):
        """
        Helper method to check if user has permission to delete reconciliation records
        Modify this based on your user roles and permissions system
        """
        # Example implementation - adjust based on your user role system
        user = Users.query.get(user_id)
        if not user:
            return False
        
        # If user is admin, allow deletion
        if user.role == 'admin':
            return True
        
        # If user manages this shop, allow deletion
        shop = Shops.query.filter_by(shops_id=shop_id, user_id=user_id).first()
        if shop:
            return True
        
        return False
    
    
class GetReportedStock(Resource):
    @jwt_required()
    def get(self):
        try:
            # Required parameters
            shop_id = request.args.get('shop_id', type=int)
            date_str = request.args.get('date')

            if not shop_id or not date_str:
                return {
                    "error": "Missing required parameters: shop_id and date are required"
                }, 400

            # Convert date
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            # Query only report_value grouped by item
            query = db.session.query(
                StockReconciliation.item,
                func.sum(StockReconciliation.report_value).label("total_reported_value")
            ).filter(
                StockReconciliation.shop_id == shop_id,
                func.date(StockReconciliation.created_at) == date_obj
            )

            # Group results
            results = query.group_by(StockReconciliation.item).all()

            # Prepare output list
            stock_list = [
                {
                    "item": item,
                    "total_reported_value": float(total_reported_value)
                }
                for item, total_reported_value in results
            ]

            response = {
                "shop_id": shop_id,
                "date": date_str,
                "total_items": len(stock_list),
                "reported_stocks": stock_list
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching reported stock data",
                "details": str(e)
            }, 500



