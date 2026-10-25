import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import request, current_app, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_restful import Resource
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app import db
from Server.Models.Employees import Employees
from Server.Models.MeritLedger import MeritLedger
from Server.Models.Meritpoints import MeritPoints
from Server.Models.Sales import Sales
from Server.Models.ShopReport import ShopReport
from Server.Models.Shops import Shops
from Server.Models.Users import Users


# ─────────────────────────────────────────────────────────────
# Upload helpers
# ─────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "heic"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────────────────────
# Role check decorator
# ─────────────────────────────────────────────────────────────
def check_role(required_role):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                return make_response(jsonify({"error": "Unauthorized access"}), 403)
            return fn(*args, **kwargs)
        return decorator
    return wrapper


# ─────────────────────────────────────────────────────────────
# GetShopReports
# ─────────────────────────────────────────────────────────────
class GetShopReports(Resource):

    @jwt_required()
    def get(self):
        """
        Get shop reports with filtering options
        Query parameters:
        - shop_id, user_id, date, start_date, end_date, username, limit, page
        """
        try:
            shop_id = request.args.get('shop_id')
            user_id = request.args.get('user_id')
            date_str = request.args.get('date')
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            username = request.args.get('username')
            limit = request.args.get('limit', default=50, type=int)
            page = request.args.get('page', default=1, type=int)

            query = ShopReport.query

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

            if date_str:
                try:
                    filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    query = query.filter(func.date(ShopReport.reported_at) == filter_date)
                except ValueError:
                    return {"message": "date must be in YYYY-MM-DD format"}, 400

            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                    query = query.filter(ShopReport.reported_at >= start_date)
                except ValueError:
                    return {"message": "start_date must be in YYYY-MM-DD format"}, 400

            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                    end_date = end_date + timedelta(days=1)
                    query = query.filter(ShopReport.reported_at < end_date)
                except ValueError:
                    return {"message": "end_date must be in YYYY-MM-DD format"}, 400

            query = query.order_by(ShopReport.reported_at.desc())

            offset = (page - 1) * limit
            total_reports = query.count()
            reports = query.limit(limit).offset(offset).all()

            EAT = timedelta(hours=3)

            reports_list = []
            for report in reports:
                opened_eat = (report.reported_at + EAT) if report.reported_at else None
                closed_eat = (report.closed_at + EAT) if report.closed_at else None

                reports_list.append({
                    "id": report.id,
                    "user_id": report.user_id,
                    "username": report.username,
                    "shop_id": report.shop_id,
                    "reported_at": opened_eat.isoformat() if opened_eat else None,
                    "date": opened_eat.date().isoformat() if opened_eat else None,
                    "time": opened_eat.time().isoformat() if opened_eat else None,
                    "closed_at": closed_eat.isoformat() if closed_eat else None,
                    "close_date": closed_eat.date().isoformat() if closed_eat else None,
                    "close_time": closed_eat.time().isoformat() if closed_eat else None,
                    "location": report.location,
                    "latitude": report.latitude,
                    "longitude": report.longitude,
                    "note": report.note,
                    "closing_location": getattr(report, "closing_location", None),
                    "closing_latitude": getattr(report, "closing_latitude", None),
                    "closing_longitude": getattr(report, "closing_longitude", None),
                    "closing_image_url": getattr(report, "closing_image_url", None),
                })

            shop_ids = list(set([r["shop_id"] for r in reports_list]))
            shops = {}
            if shop_ids:
                shop_records = db.session.query(
                    Shops.shops_id,
                    Shops.shopname,
                    Shops.location
                ).filter(Shops.shops_id.in_(shop_ids)).all()
                shops = {
                    s.shops_id: {"shopname": s.shopname, "location": s.location}
                    for s in shop_records
                }

            for report in reports_list:
                shop_info = shops.get(report["shop_id"], {})
                report["shop_name"] = shop_info.get("shopname", f"Shop #{report['shop_id']}")
                report["shop_location"] = shop_info.get("location", "N/A")

            total_pages = (total_reports + limit - 1) // limit

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
                    "username": username,
                },
                "reports": reports_list,
            }, 200

        except Exception as e:
            db.session.rollback()
            print(f"Error fetching shop reports: {str(e)}")
            return {"message": "An error occurred while fetching reports"}, 500


# ─────────────────────────────────────────────────────────────
# GetTodayShopReportStatus
# ─────────────────────────────────────────────────────────────
class GetTodayShopReportStatus(Resource):
    """Check if a specific shop/user has reported today."""

    @jwt_required()
    def get(self):
        try:
            shop_id = request.args.get('shop_id')
            user_id = request.args.get('user_id')

            if not shop_id:
                return {"message": "shop_id is required"}, 400

            try:
                shop_id_int = int(shop_id)
            except ValueError:
                return {"message": "shop_id must be a valid integer"}, 400

            if not user_id:
                user_id = get_jwt_identity()

            try:
                user_id_int = int(user_id)
            except ValueError:
                return {"message": "user_id must be a valid integer"}, 400

            today = datetime.utcnow().date()

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
                    "closed_at": report.closed_at.isoformat() if report and report.closed_at else None,
                    "location": report.location if report else None,
                } if report else None,
                "date": today.isoformat(),
            }, 200

        except Exception as e:
            db.session.rollback()
            print(f"Error checking report status: {str(e)}")
            return {"message": "An error occurred while checking report status"}, 500


# ─────────────────────────────────────────────────────────────
# GetShopReportStats
# ─────────────────────────────────────────────────────────────
class GetShopReportStats(Resource):
    """Get statistics about shop reports."""

    @jwt_required()
    def get(self):
        try:
            shop_id = request.args.get('shop_id')
            days = request.args.get('days', default=30, type=int)

            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)

            query = ShopReport.query.filter(
                ShopReport.reported_at >= start_date,
                ShopReport.reported_at <= end_date
            )

            shop_id_int = None
            if shop_id:
                try:
                    shop_id_int = int(shop_id)
                    query = query.filter(ShopReport.shop_id == shop_id_int)
                except ValueError:
                    return {"message": "shop_id must be a valid integer"}, 400

            total_reports = query.count()

            reports_by_date_q = db.session.query(
                func.date(ShopReport.reported_at).label('date'),
                func.count(ShopReport.id).label('count')
            ).filter(
                ShopReport.reported_at >= start_date,
                ShopReport.reported_at <= end_date
            )
            if shop_id_int:
                reports_by_date_q = reports_by_date_q.filter(ShopReport.shop_id == shop_id_int)
            reports_by_date = reports_by_date_q.group_by(
                func.date(ShopReport.reported_at)
            ).order_by(
                func.date(ShopReport.reported_at).desc()
            ).all()

            reports_by_user_q = db.session.query(
                ShopReport.user_id,
                ShopReport.username,
                func.count(ShopReport.id).label('count')
            ).filter(
                ShopReport.reported_at >= start_date,
                ShopReport.reported_at <= end_date
            )
            if shop_id_int:
                reports_by_user_q = reports_by_user_q.filter(ShopReport.shop_id == shop_id_int)
            reports_by_user = reports_by_user_q.group_by(
                ShopReport.user_id,
                ShopReport.username
            ).order_by(
                func.count(ShopReport.id).desc()
            ).all()

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

            dates_data = [{"date": str(r.date), "count": r.count} for r in reports_by_date]
            users_data = [{"user_id": r.user_id, "username": r.username, "count": r.count} for r in reports_by_user]
            shops_data = [{"shop_id": r.shop_id, "count": r.count} for r in reports_by_shop]

            return {
                "success": True,
                "period": {
                    "start_date": start_date.date().isoformat(),
                    "end_date": end_date.date().isoformat(),
                    "days": days,
                },
                "stats": {
                    "total_reports": total_reports,
                    "average_per_day": total_reports / days if days > 0 else 0,
                    "reports_by_date": dates_data,
                    "reports_by_user": users_data,
                    "reports_by_shop": shops_data,
                },
            }, 200

        except Exception as e:
            db.session.rollback()
            print(f"Error fetching report stats: {str(e)}")
            return {"message": "An error occurred while fetching statistics"}, 500


# ─────────────────────────────────────────────────────────────
# PostShopReport (opening report)
# ─────────────────────────────────────────────────────────────
class PostShopReport(Resource):
    @jwt_required()
    def post(self):
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        shop_id = data.get("shop_id")
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        location = data.get("location")
        note = data.get("note")

        if not shop_id:
            return {"message": "shop_id is required"}, 400

        try:
            shop_id = int(shop_id)
        except (ValueError, TypeError):
            return {"message": "shop_id must be an integer"}, 400

        user = Users.query.get(user_id)
        if not user:
            return {"message": "User not found"}, 404

        now_utc = datetime.utcnow()
        today_utc = now_utc.date()

        existing_report = ShopReport.query.filter(
            ShopReport.shop_id == shop_id,
            ShopReport.user_id == user.users_id,
            func.date(ShopReport.reported_at) == today_utc
        ).first()

        if existing_report:
            return {
                "message": "You have already submitted a report for this shop today"
            }, 409

        report = ShopReport(
            user_id=user.users_id,
            username=user.username,
            shop_id=shop_id,
            latitude=latitude,
            longitude=longitude,
            location=location,
            note=note,
            reported_at=datetime.utcnow(),
        )

        db.session.add(report)
        db.session.commit()

        return {
            "message": "Shop report submitted successfully",
            "report": {
                "id": report.id,
                "shop_id": report.shop_id,
                "user_id": report.user_id,
                "username": report.username,
                "reported_at": report.reported_at.isoformat(),
                "closed_at": None,
                "location": report.location,
                "latitude": report.latitude,
                "longitude": report.longitude,
            }
        }, 201


# ─────────────────────────────────────────────────────────────
# CheckShopOpeningReports
# ─────────────────────────────────────────────────────────────
class CheckShopOpeningReports(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        try:
            now_utc = datetime.utcnow()
            yesterday_utc = now_utc.date() - timedelta(days=1)

            start_utc = datetime.combine(yesterday_utc, datetime.min.time())
            end_utc = datetime.combine(yesterday_utc, datetime.max.time())

            demerit = MeritPoints.query.filter(
                func.lower(MeritPoints.reason) ==
                "not reporting to shop in the app"
            ).first()

            if not demerit:
                return {
                    "message": (
                        "Demerit reason 'not reporting to shop in the app' "
                        "was not found."
                    )
                }, 404

            users = Users.query.all()
            deducted = []
            skipped = []

            for user in users:
                user_id = user.users_id

                report = ShopReport.query.filter(
                    ShopReport.user_id == user_id,
                    ShopReport.reported_at >= start_utc,
                    ShopReport.reported_at <= end_utc
                ).first()

                if report:
                    skipped.append({
                        "user_id": user_id,
                        "username": user.username,
                        "reason": "Shop opening report submitted",
                    })
                    continue

                sale = Sales.query.filter(
                    Sales.user_id == user_id,
                    Sales.created_at >= start_utc,
                    Sales.created_at <= end_utc
                ).first()

                if not sale:
                    skipped.append({
                        "user_id": user_id,
                        "username": user.username,
                        "reason": "No sales recorded",
                    })
                    continue

                if not user.employee_id:
                    skipped.append({
                        "user_id": user_id,
                        "username": user.username,
                        "reason": "User is not linked to an employee",
                    })
                    continue

                employee = Employees.query.get(user.employee_id)
                if not employee:
                    skipped.append({
                        "user_id": user_id,
                        "username": user.username,
                        "employee_id": user.employee_id,
                        "reason": "Employee not found",
                    })
                    continue

                comment = f"Not reporting to shop in the app on {yesterday_utc}"

                existing_demerit = MeritLedger.query.filter(
                    MeritLedger.employee_id == employee.employee_id,
                    MeritLedger.merit_id == demerit.meritpoint_id,
                    MeritLedger.comment == comment
                ).first()

                if existing_demerit:
                    skipped.append({
                        "user_id": user_id,
                        "username": user.username,
                        "employee_id": employee.employee_id,
                        "reason": "Demerit already applied",
                    })
                    continue

                old_points = employee.merit_points
                employee.merit_points += demerit.point
                employee.merit_points_updated_at = datetime.utcnow()

                ledger_entry = MeritLedger(
                    employee_id=employee.employee_id,
                    merit_id=demerit.meritpoint_id,
                    comment=comment,
                    resulting_points=employee.merit_points,
                    date=datetime.utcnow()
                )
                db.session.add(ledger_entry)
                db.session.flush()

                deducted.append({
                    "user_id": user_id,
                    "username": user.username,
                    "employee_id": employee.employee_id,
                    "old_points": old_points,
                    "point_change": demerit.point,
                    "resulting_points": employee.merit_points,
                    "ledger_created": True,
                })

            db.session.commit()

            return {
                "message": "Shop opening report check completed successfully.",
                "date_checked": str(yesterday_utc),
                "demerit_reason": demerit.reason,
                "demerit_points": demerit.point,
                "total_users_checked": len(users),
                "total_deductions": len(deducted),
                "total_skipped": len(skipped),
                "deducted": deducted,
                "skipped": skipped,
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                "message": "An error occurred while checking shop reports.",
                "error": str(e),
            }, 500


# ─────────────────────────────────────────────────────────────
# CloseShopReport (with image upload)
# ─────────────────────────────────────────────────────────────
class CloseShopReport(Resource):
    @jwt_required()
    def post(self):
        user_id = get_jwt_identity()

        # Accept BOTH multipart (with file) and JSON (no file)
        if request.content_type and request.content_type.startswith("multipart/"):
            data = request.form
            file = request.files.get("closing_image")
        else:
            data = request.get_json() or {}
            file = None

        shop_id = data.get("shop_id")
        if not shop_id:
            return {"message": "shop_id is required"}, 400
        try:
            shop_id = int(shop_id)
        except (ValueError, TypeError):
            return {"message": "shop_id must be an integer"}, 400

        user = Users.query.get(user_id)
        if not user:
            return {"message": "User not found"}, 404

        # Optional closing fields
        closing_location = data.get("closing_location")
        closing_latitude = data.get("closing_latitude")
        closing_longitude = data.get("closing_longitude")

        if closing_latitude not in (None, ""):
            try:
                closing_latitude = float(closing_latitude)
            except (ValueError, TypeError):
                return {"message": "closing_latitude must be a number"}, 400
        else:
            closing_latitude = None

        if closing_longitude not in (None, ""):
            try:
                closing_longitude = float(closing_longitude)
            except (ValueError, TypeError):
                return {"message": "closing_longitude must be a number"}, 400
        else:
            closing_longitude = None

        # Validate image extension BEFORE touching disk
        has_file = bool(file and file.filename)

        if has_file and not _allowed(file.filename):
            return {"message": "Unsupported image type"}, 400

        # Locate the latest opening report for this shop + user
        now_utc = datetime.utcnow()

        report = (
            ShopReport.query
            .filter(
                ShopReport.shop_id == shop_id,
                ShopReport.user_id == user.users_id,
            )
            .order_by(ShopReport.reported_at.desc(), ShopReport.id.desc())
            .first()
        )

        if not report:
            other = (
                ShopReport.query
                .filter(ShopReport.shop_id == shop_id)
                .order_by(ShopReport.reported_at.desc(), ShopReport.id.desc())
                .first()
            )
            current_app.logger.warning(
                "close-shop: no report for shop_id=%s user_id=%s (jwt identity=%r); "
                "latest report for shop belongs to user_id=%s",
                shop_id, user.users_id, user_id, other.user_id if other else None,
            )
            if other:
                return {
                    "message": "The opening report for this shop was submitted "
                               "by a different user."
                }, 403
            return {
                "message": "No opening report found for this shop today. "
                           "Please submit an opening report first."
            }, 404

        # Ignore stale reports (older than 24h)
        if now_utc - report.reported_at > timedelta(hours=24):
            return {
                "message": "No opening report found for this shop today. "
                           "Please submit an opening report first."
            }, 404

        if report.closed_at is not None:
            return {
                "message": "This shop has already been closed today",
                "closed_at": report.closed_at.isoformat(),
            }, 409

        # Save the uploaded image
        closing_image_url = None
        save_path = None

        if has_file:
            ext = file.filename.rsplit(".", 1)[1].lower()
            fname = secure_filename(f"{uuid.uuid4().hex}.{ext}")

            folder = current_app.config["CLOSING_IMAGES_FOLDER"]
            os.makedirs(folder, exist_ok=True)

            save_path = os.path.join(folder, fname)
            file.save(save_path)

            # Build FULL public URL:
            # local → http://127.0.0.1:8000/dirauploads/closing_stock_images/<uuid>.jpg
            # prod  → https://server.kukuzetu.co.ke/dirauploads/closing_stock_images/<uuid>.jpg
            base = current_app.config["UPLOADS_BASE_URL"].rstrip("/")
            prefix = current_app.config["UPLOADS_URL_PREFIX"].strip("/")
            closing_image_url = f"{base}/{prefix}/closing_stock_images/{fname}"

        # Stamp closing info on the same row
        try:
            report.closed_at = now_utc
            report.closing_location = closing_location
            report.closing_latitude = closing_latitude
            report.closing_longitude = closing_longitude
            report.closing_image_url = closing_image_url
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("close-shop: commit failed")
            if save_path and os.path.exists(save_path):
                os.remove(save_path)
            return {"message": "Failed to record shop closing"}, 500

        return {
            "message": "Shop closing recorded successfully",
            "report": {
                "id": report.id,
                "shop_id": report.shop_id,
                "user_id": report.user_id,
                "username": report.username,
                "reported_at": report.reported_at.isoformat(),
                "closed_at": report.closed_at.isoformat(),
                "closing_location": report.closing_location,
                "closing_latitude": report.closing_latitude,
                "closing_longitude": report.closing_longitude,
                "closing_image_url": report.closing_image_url,
            },
        }, 200