from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func, cast, Date
from datetime import datetime, timedelta
from Server.Models.ShopReport import ShopReport
from Server.Models.Shops import Shops
from app import db

class GetShopReports(Resource):
    
    @jwt_required()
    def get(self):
        """
        Get shop reports with filtering options
        Query parameters:
        - shop_id: Filter by specific shop
        - user_id: Filter by specific user
        - date: Filter by specific date (YYYY-MM-DD format)
        - start_date: Start date for date range (YYYY-MM-DD)
        - end_date: End date for date range (YYYY-MM-DD)
        - username: Filter by username
        - limit: Limit number of results
        - page: Page number for pagination
        """
        try:
            # Get current user info
            current_user_id = get_jwt_identity()
            
            # Get query parameters
            shop_id = request.args.get('shop_id')
            user_id = request.args.get('user_id')
            date_str = request.args.get('date')
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            username = request.args.get('username')
            limit = request.args.get('limit', default=50, type=int)
            page = request.args.get('page', default=1, type=int)
            
            # Base query
            query = ShopReport.query
            
            # Apply filters
            if shop_id:
                try:
                    shop_id_int = int(shop_id)
                    query = query.filter(ShopReport.shop_id == shop_id_int)
                except ValueError:
                    return {"message": "shop_id must be a valid integer"}, 400
            
            if user_id:
                try:
                    user_id_int = int(user_id)
                    query = query.filter(ShopReport.user_id == user_id_int)
                except ValueError:
                    return {"message": "user_id must be a valid integer"}, 400
            
            if username:
                query = query.filter(ShopReport.username.ilike(f"%{username}%"))
            
            # Date filtering
            if date_str:
                try:
                    filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    query = query.filter(
                        func.date(ShopReport.timestamp) == filter_date
                    )
                except ValueError:
                    return {"message": "date must be in YYYY-MM-DD format"}, 400
            
            # Date range filtering
            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                    query = query.filter(ShopReport.timestamp >= start_date)
                except ValueError:
                    return {"message": "start_date must be in YYYY-MM-DD format"}, 400
            
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                    # Add one day to include the entire end date
                    end_date = end_date + timedelta(days=1)
                    query = query.filter(ShopReport.timestamp < end_date)
                except ValueError:
                    return {"message": "end_date must be in YYYY-MM-DD format"}, 400
            
            # Order by most recent first
            query = query.order_by(ShopReport.timestamp.desc())
            
            # Pagination
            offset = (page - 1) * limit
            total_reports = query.count()
            reports = query.limit(limit).offset(offset).all()
            
            # Prepare response
            reports_list = []
            for report in reports:
                reports_list.append({
                    "id": report.id,
                    "user_id": report.user_id,
                    "username": report.username,
                    "shop_id": report.shop_id,
                    "timestamp": report.timestamp.isoformat() if report.timestamp else None,
                    "date": report.timestamp.date().isoformat() if report.timestamp else None,
                    "time": report.timestamp.time().isoformat() if report.timestamp else None,
                    "location": report.location,
                    "latitude": report.latitude,
                    "longitude": report.longitude,
                    "note": report.note
                })
            
            # Get shop names for better display
            shop_ids = list(set([report["shop_id"] for report in reports_list]))
            shops = {}
            if shop_ids:
                shop_records = db.session.query(
                    Shops.shops_id, 
                    Shops.shopname,
                    Shops.location
                ).filter(Shops.shops_id.in_(shop_ids)).all()
                shops = {shop.shops_id: {"shopname": shop.shopname, "location": shop.location} for shop in shop_records}
            
            # Add shop info to reports
            for report in reports_list:
                shop_info = shops.get(report["shop_id"], {})
                report["shop_name"] = shop_info.get("shopname", f"Shop #{report['shop_id']}")
                report["shop_location"] = shop_info.get("location", "N/A")
            
            # Calculate pagination info
            total_pages = (total_reports + limit - 1) // limit  # Ceiling division
            
            return {
                "success": True,
                "total_reports": total_reports,
                "total_pages": total_pages,
                "current_page": page,
                "limit": limit,
                "filters_applied": {
                    "shop_id": shop_id,
                    "user_id": user_id,
                    "date": date_str,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "username": username
                },
                "reports": reports_list
            }, 200
            
        except Exception as e:
            db.session.rollback()
            print(f"Error fetching shop reports: {str(e)}")
            return {"message": "An error occurred while fetching reports"}, 500


class GetTodayShopReportStatus(Resource):
    """
    Check if a specific shop/user has reported today
    """
    
    @jwt_required()
    def get(self):
        """
        Check if report exists for today
        Query parameters:
        - shop_id: Required, shop to check
        - user_id: Optional, user to check (if not provided, uses current user)
        """
        try:
            shop_id = request.args.get('shop_id')
            user_id = request.args.get('user_id')
            
            if not shop_id:
                return {"message": "shop_id is required"}, 400
            
            try:
                shop_id_int = int(shop_id)
            except ValueError:
                return {"message": "shop_id must be a valid integer"}, 400
            
            # If user_id not provided, use current user
            if not user_id:
                user_id = get_jwt_identity()
            
            try:
                user_id_int = int(user_id)
            except ValueError:
                return {"message": "user_id must be a valid integer"}, 400
            
            # Get today's date
            today = datetime.utcnow().date()
            
            # Check if report exists for today
            report = ShopReport.query.filter(
                ShopReport.shop_id == shop_id_int,
                ShopReport.user_id == user_id_int,
                func.date(ShopReport.reported_at) == today
            ).first()
            
            return {
                "success": True,
                "already_reported": report is not None,
                "report": {
                    "id": report.id if report else None,
                    "reported_at": report.reported_at.isoformat() if report else None,
                    "location": report.location if report else None
                } if report else None,
                "date": today.isoformat()
            }, 200
            
        except Exception as e:
            db.session.rollback()
            print(f"Error checking report status: {str(e)}")
            return {"message": "An error occurred while checking report status"}, 500


class GetShopReportStats(Resource):
    """
    Get statistics about shop reports
    """
    
    @jwt_required()
    def get(self):
        """
        Get report statistics
        Query parameters:
        - shop_id: Filter by shop
        - days: Number of days to look back (default: 30)
        """
        try:
            shop_id = request.args.get('shop_id')
            days = request.args.get('days', default=30, type=int)
            
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            query = ShopReport.query.filter(
                ShopReport.reported_at >= start_date,
                ShopReport.reported_at <= end_date
            )
            
            if shop_id:
                try:
                    shop_id_int = int(shop_id)
                    query = query.filter(ShopReport.shop_id == shop_id_int)
                except ValueError:
                    return {"message": "shop_id must be a valid integer"}, 400
            
            # Get total reports
            total_reports = query.count()
            
            # Get reports by date
            reports_by_date = db.session.query(
                func.date(ShopReport.reported_at).label('date'),
                func.count(ShopReport.id).label('count')
            ).filter(
                ShopReport.reported_at >= start_date,
                ShopReport.reported_at <= end_date
            )
            
            if shop_id:
                reports_by_date = reports_by_date.filter(ShopReport.shop_id == shop_id_int)
            
            reports_by_date = reports_by_date.group_by(
                func.date(ShopReport.reported_at)
            ).order_by(
                func.date(ShopReport.reported_at).desc()
            ).all()
            
            # Get reports by user
            reports_by_user = db.session.query(
                ShopReport.user_id,
                ShopReport.username,
                func.count(ShopReport.id).label('count')
            ).filter(
                ShopReport.reported_at >= start_date,
                ShopReport.reported_at <= end_date
            )
            
            if shop_id:
                reports_by_user = reports_by_user.filter(ShopReport.shop_id == shop_id_int)
            
            reports_by_user = reports_by_user.group_by(
                ShopReport.user_id,
                ShopReport.username
            ).order_by(
                func.count(ShopReport.id).desc()
            ).all()
            
            # Get reports by shop
            reports_by_shop = db.session.query(
                ShopReport.shop_id,
                func.count(ShopReport.id).label('count')
            ).filter(
                ShopReport.reported_at >= start_date,
                ShopReport.reported_at <= end_date
            ).group_by(
                ShopReport.shop_id
            ).order_by(
                func.count(ShopReport.id).desc()
            ).all()
            
            # Format response
            dates_data = [{"date": str(r.date), "count": r.count} for r in reports_by_date]
            users_data = [{"user_id": r.user_id, "username": r.username, "count": r.count} for r in reports_by_user]
            shops_data = [{"shop_id": r.shop_id, "count": r.count} for r in reports_by_shop]
            
            return {
                "success": True,
                "period": {
                    "start_date": start_date.date().isoformat(),
                    "end_date": end_date.date().isoformat(),
                    "days": days
                },
                "stats": {
                    "total_reports": total_reports,
                    "average_per_day": total_reports / days if days > 0 else 0,
                    "reports_by_date": dates_data,
                    "reports_by_user": users_data,
                    "reports_by_shop": shops_data
                }
            }, 200
            
        except Exception as e:
            db.session.rollback()
            print(f"Error fetching report stats: {str(e)}")
            return {"message": "An error occurred while fetching statistics"}, 500