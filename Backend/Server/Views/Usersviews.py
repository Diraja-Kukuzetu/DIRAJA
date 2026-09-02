from flask_restful import Resource
from Server.Models.Users import Users
from Server.Models.Shops import Shops
from Server.Models.Employees import Employees
from Server.Models.StockReport import StockReport
from Server.Models.TwoFactorAuth import TwoFactorAuth
from app import db
import bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token
from flask import jsonify, request, make_response
from functools import wraps
from flask_jwt_extended import jwt_required, get_jwt_identity
import re
from Server.Models.ShopReport import ShopReport
from sqlalchemy import func
from datetime import datetime, date, timedelta
import logging
from flask import g

logger = logging.getLogger(__name__)

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


class CountUsers(Resource):
    @jwt_required()
    def get(self):
        countUsers = Users.query.count()
        return {"total users": countUsers}, 200


class Addusers(Resource):   
    def post(self):
        data = request.get_json()

        if 'username' not in data or 'email' not in data or 'password' not in data:
            return {'message': 'Missing username, email, or password'}, 400

        username = data.get('username')
        email = data.get('email')
        role = data.get('role')
        password = data.get('password')
        status = data.get('status')

        # Check if user already exists
        if Users.query.filter_by(email=email).first():
            return {'message': 'User already exists'}, 400

        user = Users(username=username, email=email, password=password, role=role, status=status)
        db.session.add(user)
        db.session.commit()

        return {'message': 'User added successfully'}, 201




class UserLogin(Resource):
    def post(self):
        email = request.json.get("email", None)
        password = request.json.get("password", None)

        # Validate input
        if not email or not password:
            return make_response(jsonify({"error": "Email and password are required"}), 400)

        # Fetch the user based on email
        user = Users.query.filter_by(email=email).one_or_none()

        if not user:
            return make_response(jsonify({"error": "User not found. Please check your email."}), 404)

        # Check if user is active
        if user.status != "active":
            return make_response(jsonify({
                "error": "Account is not active. Please contact administrator.",
                "status": user.status
            }), 403)

        # Validate the password
        if not bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            return make_response(jsonify({"error": "Wrong password"}), 401)

        # Check if 2FA is enabled for this user
        if user.two_factor_enabled:
            # Generate and send 2FA code
            two_factor = TwoFactorAuth.create_for_user(user.users_id)
            
            # Send email with code (you'll need to implement this)
            from Server.Views.Services.email_utils import send_2fa_code_email
            email_sent = send_2fa_code_email(
                user_email=user.email,
                full_name=user.username,
                code=two_factor.code
            )
            
            if not email_sent:
                return make_response(jsonify({
                    "error": "Failed to send verification code. Please try again."
                }), 500)
            
            # Return user info and require 2FA
            return make_response(jsonify({
                "requires_2fa": True,
                "user_id": user.users_id,
                "email": user.email,
                "username": user.username,
                "message": "2FA code sent to your email"
            }), 200)
        
        # If 2FA is not enabled, proceed with normal login
        return self._generate_login_response(user)

    def _generate_login_response(self, user):
        """Helper method to generate login response"""
        username = user.username
        user_role = user.role

        # Create access token with additional claims including status + tenant
        access_token = create_access_token(
            identity=user.users_id, 
            additional_claims={
                'roles': [user_role],
                'username': username,
                'email': user.email,
                'status': user.status,
                'tenant': g.tenant   # 🔑 lock this token to the tenant it was issued under
            }
        )
        
        refresh_token = create_refresh_token(
            identity=user.users_id,
            additional_claims={'tenant': g.tenant}   # 🔑 lock refresh token too
        )

        response_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": username,
            "users_id": user.users_id,
            "email": user.email,
            "role": user_role,
            "status": user.status,
            "two_factor_enabled": user.two_factor_enabled
        }

        # Additional logic for clerks
        if user_role == "clerk":
            employee = Employees.query.filter_by(work_email=user.email).one_or_none()
            if employee:
                shop_id = employee.shop_id
                response_data["shop_id"] = shop_id
                response_data["designation"] = employee.designation
                response_data["employee_id"] = employee.employee_id

                # Fetch report_status directly from the Shops model
                shop = Shops.query.filter_by(shops_id=shop_id).first()
                if shop:
                    response_data["report_status"] = shop.report_status
                else:
                    response_data["report_status"] = None
                    
                # Fetch shop details
                if shop:
                    response_data["shopname"] = shop.shopname

        return make_response(jsonify(response_data), 200)


class UserLoginWith2FA(Resource):
    """Verify 2FA code and complete login"""
    def post(self):
        try:
            data = request.get_json()
            user_id = data.get('user_id')
            code = data.get('code')
            secret = data.get('secret')  # Optional - for additional security

            if not user_id or not code:
                return make_response(jsonify({
                    "error": "User ID and verification code are required"
                }), 400)

            # Get user
            user = Users.query.get(user_id)

            if not user:
                return make_response(jsonify({
                    "error": "User not found"
                }), 404)

            # Check if user is active
            if user.status != "active":
                return make_response(jsonify({
                    "error": "Account is not active. Please contact administrator."
                }), 403)

            # Verify the 2FA code
            is_valid = TwoFactorAuth.verify_code(user_id, code, secret)

            if not is_valid:
                return make_response(jsonify({
                    "error": "Invalid or expired verification code"
                }), 401)

            # Complete login and generate tokens
            # Unchanged — g.tenant is still set on this request's context,
            # so _generate_login_response picks it up automatically.
            return UserLogin()._generate_login_response(user)

        except Exception as e:
            logger.error(f"2FA verification error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred during verification"
            }), 500)

class Resend2FACode(Resource):
    """Resend 2FA verification code"""
    def post(self):
        try:
            data = request.get_json()
            user_id = data.get('user_id')

            if not user_id:
                return make_response(jsonify({
                    "error": "User ID is required"
                }), 400)

            user = Users.query.get(user_id)

            if not user:
                return make_response(jsonify({
                    "error": "User not found"
                }), 404)

            # Check if 2FA is enabled
            if not user.two_factor_enabled:
                return make_response(jsonify({
                    "error": "2FA is not enabled for this user"
                }), 400)

            # Generate new 2FA code
            two_factor = TwoFactorAuth.create_for_user(user.users_id)

            # Send email with code
            from Server.Views.Services.email_utils import send_2fa_code_email
            email_sent = send_2fa_code_email(
                user_email=user.email,
                full_name=user.username,
                code=two_factor.code
            )

            if not email_sent:
                return make_response(jsonify({
                    "error": "Failed to send verification code. Please try again."
                }), 500)

            return make_response(jsonify({
                "message": "New verification code sent to your email",
                "user_id": user_id
            }), 200)

        except Exception as e:
            logger.error(f"Resend 2FA error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred"
            }), 500)


class Enable2FA(Resource):
    """Enable 2FA for authenticated user"""
    @jwt_required()
    def post(self):
        try:
            user_id = get_jwt_identity()
            user = Users.query.get(user_id)

            if not user:
                return make_response(jsonify({
                    "error": "User not found"
                }), 404)

            # Generate backup codes
            backup_codes = user.enable_2fa()
            
            # Send test email with backup codes
            from Server.Views.Services.email_utils import send_2fa_setup_email
            email_sent = send_2fa_setup_email(
                user_email=user.email,
                full_name=user.username,
                backup_codes=backup_codes
            )

            if not email_sent:
                # Rollback if email fails
                user.disable_2fa()
                return make_response(jsonify({
                    "error": "Failed to send setup email. Please try again."
                }), 500)

            return make_response(jsonify({
                "message": "2FA enabled successfully",
                "two_factor_enabled": True,
                "backup_codes": backup_codes  # These should be shown once to the user
            }), 200)

        except Exception as e:
            logger.error(f"Enable 2FA error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred"
            }), 500)


class Disable2FA(Resource):
    """Disable 2FA for authenticated user"""
    @jwt_required()
    def post(self):
        try:
            user_id = get_jwt_identity()
            user = Users.query.get(user_id)

            if not user:
                return make_response(jsonify({
                    "error": "User not found"
                }), 404)

            user.disable_2fa()

            return make_response(jsonify({
                "message": "2FA disabled successfully",
                "two_factor_enabled": False
            }), 200)

        except Exception as e:
            logger.error(f"Disable 2FA error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred"
            }), 500)


class Get2FAStatus(Resource):
    """Get 2FA status for authenticated user"""
    @jwt_required()
    def get(self):
        try:
            user_id = get_jwt_identity()
            user = Users.query.get(user_id)

            if not user:
                return make_response(jsonify({
                    "error": "User not found"
                }), 404)

            return make_response(jsonify({
                "two_factor_enabled": user.two_factor_enabled,
                "two_factor_verified": user.two_factor_verified,
                "two_factor_setup_date": user.two_factor_setup_date.isoformat() if user.two_factor_setup_date else None
            }), 200)

        except Exception as e:
            logger.error(f"Get 2FA status error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred"
            }), 500)


class VerifyBackupCode(Resource):
    """Verify backup code for 2FA recovery"""
    def post(self):
        try:
            data = request.get_json()
            email = data.get('email')
            backup_code = data.get('backup_code')

            if not email or not backup_code:
                return make_response(jsonify({
                    "error": "Email and backup code are required"
                }), 400)

            user = Users.query.filter_by(email=email).first()

            if not user:
                return make_response(jsonify({
                    "error": "User not found"
                }), 404)

            # Verify backup code
            if user.verify_backup_code(backup_code):
                # Generate login tokens
                return UserLogin()._generate_login_response(user)
            else:
                return make_response(jsonify({
                    "error": "Invalid backup code"
                }), 401)

        except Exception as e:
            logger.error(f"Backup code verification error: {str(e)}")
            return make_response(jsonify({
                "error": "An error occurred"
            }), 500)


# Update UsersResourceById to handle 2FA fields
class UsersResourceById(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, users_id):
        user = Users.query.get(users_id)

        if user:
            return {
                "users_id": user.users_id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "status": user.status,
                "two_factor_enabled": user.two_factor_enabled,
                "two_factor_verified": user.two_factor_verified,
                "two_factor_setup_date": user.two_factor_setup_date.isoformat() if user.two_factor_setup_date else None
            }, 200
        else:
            return {"error": "User not found"}, 404
    
    @jwt_required()
    @check_role('manager')
    def delete(self, users_id):
        user = Users.query.get(users_id)

        if user:
            db.session.delete(user)
            db.session.commit()
            return {"message": f"User with id {users_id} deleted successfully"}, 200
        else:
            return {"error": "User not found"}, 404

    @jwt_required()
    @check_role('manager')
    def put(self, users_id):
        user = Users.query.get(users_id)

        if not user:
            return {"error": "User not found"}, 404

        data = request.get_json()

        # Validate input data
        username = data.get("username")
        email = data.get("email")
        password = data.get("password")
        role = data.get("role")
        status = data.get("status")

        # Validate status if provided
        if status:
            valid_statuses = ['active', 'inactive', 'former employee']
            if status not in valid_statuses:
                return {
                    "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                }, 400

        # Validate role if provided
        if role:
            valid_roles = ['manager', 'clerk', 'super_admin', 'procurement']
            if role not in valid_roles:
                return {
                    "error": f"Invalid role. Must be one of: {', '.join(valid_roles)}"
                }, 400

        # Update fields if provided
        if username:
            user.username = username
        if email:
            # Validate email format
            if '@' not in email or '.' not in email.split('@')[-1]:
                return {"error": "Invalid email format"}, 400
            user.email = email
        if role:
            user.role = role
        if status:
            user.status = status
        if password:
            # Let the model's validate_password method handle hashing
            user.password = password

        # Save changes to the database
        try:
            db.session.commit()
        except AssertionError as e:
            db.session.rollback()
            return {"error": str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {"error": f"Failed to update user: {str(e)}"}, 500

        return {
            "message": f"User with id {users_id} updated successfully",
            "user": {
                "users_id": user.users_id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "status": user.status,
                "two_factor_enabled": user.two_factor_enabled
            }
        }, 200


class GetAllUsers(Resource):
    @jwt_required()
    def get(self):
        users = Users.query.all()

        all_users = [{
            "user_id": user.users_id,
            "username": user.username,
            "email": user.email,
            "password": user.password,
            "role": user.role,
            "status": user.status,
            "two_factor_enabled": user.two_factor_enabled
        } for user in users]

        return make_response(jsonify(all_users), 200)


# Keep your existing PostShopReport class unchanged
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

        # ---- Validation ----
        if not shop_id:
            return {"message": "shop_id is required"}, 400

        try:
            shop_id = int(shop_id)
        except (ValueError, TypeError):
            return {"message": "shop_id must be an integer"}, 400

        user = Users.query.get(user_id)
        if not user:
            return {"message": "User not found"}, 404

        # ---- Get current time in EAT (UTC+3) ----
        now_utc = datetime.utcnow()
        now_eat = now_utc + timedelta(hours=3)
        today_eat = now_eat.date()

        # ---- Prevent multiple reports per day ----
        existing_report = ShopReport.query.filter(
            ShopReport.shop_id == shop_id,
            ShopReport.user_id == user.users_id,
            func.date(ShopReport.reported_at + timedelta(hours=3)) == today_eat
        ).first()

        if existing_report:
            return {
                "message": "You have already submitted a report for this shop today"
            }, 409

        # ---- Create report ----
        report = ShopReport(
            user_id=user.users_id,
            username=user.username,
            shop_id=shop_id,
            latitude=latitude,
            longitude=longitude,
            location=location,
            note=note,
            reported_at=datetime.utcnow()
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
                "reported_at": (report.reported_at + timedelta(hours=3)).isoformat(),
                "location": report.location,
                "latitude": report.latitude,
                "longitude": report.longitude
            }
        }, 201


# Server/Views/api_endpoint.py
from flask import jsonify, request, current_app
from flask_mail import Message
from app import mail
from flask_restful import Resource
import logging
import smtplib
from datetime import datetime
import socket
import traceback

logger = logging.getLogger(__name__)

class TestEmail(Resource):
    def post(self):
        debug_info = {
            "steps": [],
            "success": False,
            "message": "",
            "error": None,
            "details": {}
        }
        
        try:
            data = request.get_json()
            email = data.get('email', 'test@example.com')
            debug_info["details"]["recipient"] = email
            
            logger.info(f"Starting email test to: {email}")
            debug_info["steps"].append({"step": "Started", "message": f"Testing email to {email}"})
            
            # Step 1: Check if mail is initialized
            debug_info["steps"].append({"step": "Mail Check", "message": "Checking mail object"})
            
            if mail is None:
                logger.error("Mail object is None - not initialized")
                debug_info["steps"].append({"step": "Mail Check", "message": "Mail object is None - not initialized", "status": "error"})
                return {
                    "success": False,
                    "message": "Email service is not initialized",
                    "error": "Mail object is None. Please check your app configuration.",
                    "debug": debug_info
                }, 500
            
            # Get mail configuration from app
            try:
                # Try to get config from mail.app first
                mail_app = mail.app
                if mail_app is None:
                    # Try to get from current_app
                    mail_app = current_app._get_current_object()
                    debug_info["details"]["config_source"] = "current_app"
                else:
                    debug_info["details"]["config_source"] = "mail.app"
                
                debug_info["steps"].append({"step": "Mail Check", "message": f"Mail app found: {mail_app.name}", "status": "success"})
                
            except Exception as e:
                logger.error(f"Failed to get mail app: {str(e)}")
                debug_info["steps"].append({"step": "Mail Check", "message": f"Failed to get mail app: {str(e)}", "status": "error"})
                return {
                    "success": False,
                    "message": "Failed to get mail application context",
                    "error": str(e),
                    "debug": debug_info
                }, 500
            
            # Step 2: Get mail configuration
            debug_info["steps"].append({"step": "Config Check", "message": "Getting mail configuration"})
            
            # Use current_app if mail.app is None
            config_source = mail_app if mail_app else current_app
            
            mail_config = {
                "server": config_source.config.get('MAIL_SERVER'),
                "port": config_source.config.get('MAIL_PORT'),
                "username": config_source.config.get('MAIL_USERNAME'),
                "password_set": bool(config_source.config.get('MAIL_PASSWORD')),
                "use_ssl": config_source.config.get('MAIL_USE_SSL'),
                "use_tls": config_source.config.get('MAIL_USE_TLS'),
                "default_sender": config_source.config.get('MAIL_DEFAULT_SENDER')
            }
            
            debug_info["details"]["mail_config"] = mail_config
            debug_info["steps"].append({"step": "Config Check", "message": "Mail configuration loaded", "status": "success"})
            
            # Step 3: Check if MAIL_PASSWORD is set
            password = config_source.config.get('MAIL_PASSWORD')
            if not password:
                logger.error("MAIL_PASSWORD is not set in configuration")
                debug_info["steps"].append({"step": "Config Error", "message": "MAIL_PASSWORD not set", "status": "error"})
                return {
                    "success": False,
                    "message": "Mail password is not configured",
                    "error": "MAIL_PASSWORD is not set in environment variables",
                    "debug": debug_info
                }, 500
            
            # Step 4: Validate mail server configuration
            if not mail_config["server"]:
                debug_info["steps"].append({"step": "Config Error", "message": "MAIL_SERVER not set", "status": "error"})
                return {
                    "success": False,
                    "message": "Mail server not configured",
                    "error": "MAIL_SERVER is not set in configuration",
                    "debug": debug_info
                }, 500
            
            if not mail_config["username"]:
                debug_info["steps"].append({"step": "Config Error", "message": "MAIL_USERNAME not set", "status": "error"})
                return {
                    "success": False,
                    "message": "Mail username not configured",
                    "error": "MAIL_USERNAME is not set in configuration",
                    "debug": debug_info
                }, 500
            
            # Step 5: Test DNS resolution
            debug_info["steps"].append({"step": "DNS Check", "message": f"Testing DNS resolution for {mail_config['server']}"})
            try:
                server_ip = socket.gethostbyname(mail_config["server"])
                debug_info["details"]["server_ip"] = server_ip
                debug_info["steps"].append({"step": "DNS Check", "message": f"DNS resolved to {server_ip}", "status": "success"})
            except Exception as e:
                logger.error(f"DNS resolution failed: {str(e)}")
                debug_info["steps"].append({"step": "DNS Check", "message": f"DNS resolution failed: {str(e)}", "status": "error"})
                return {
                    "success": False,
                    "message": "DNS resolution failed",
                    "error": str(e),
                    "debug": debug_info
                }, 500
            
            # Step 6: Test port connection
            debug_info["steps"].append({"step": "Port Check", "message": f"Testing port {mail_config['port']} connectivity"})
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                result = sock.connect_ex((mail_config["server"], mail_config["port"]))
                sock.close()
                
                if result == 0:
                    debug_info["steps"].append({"step": "Port Check", "message": f"Port {mail_config['port']} is open", "status": "success"})
                else:
                    debug_info["steps"].append({"step": "Port Check", "message": f"Port {mail_config['port']} is not accessible (Error: {result})", "status": "warning"})
            except Exception as e:
                logger.warning(f"Port check failed: {str(e)}")
                debug_info["steps"].append({"step": "Port Check", "message": f"Port check failed: {str(e)}", "status": "warning"})
            
            # Step 7: Create and send email using the correct sender
            debug_info["steps"].append({"step": "Send Email", "message": "Creating and sending email"})
            
            # Use the authenticated username as sender (this is what the mail server expects)
            sender = mail_config["username"]  # Use the authenticated username
            debug_info["details"]["sender"] = sender
            
            # Check if sender matches domain
            sender_domain = sender.split('@')[1] if '@' in sender else None
            server_domain = mail_config["server"].replace('mail.', '') if mail_config["server"] else None
            
            if sender_domain and server_domain and sender_domain != server_domain:
                debug_info["steps"].append({
                    "step": "Warning", 
                    "message": f"Sender domain ({sender_domain}) doesn't match mail server domain ({server_domain}). This may cause authentication issues.", 
                    "status": "warning"
                })
            
            msg = Message(
                subject="Test Email Configuration - Diraja System",
                recipients=[email],
                html=f"""
                <html>
                    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                        <div style="background: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
                            <h1>✅ Email Test Successful</h1>
                        </div>
                        <div style="background: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 5px 5px;">
                            <h2>Configuration Test</h2>
                            <p>This email confirms that your Flask email configuration is working correctly.</p>
                            
                            <h3>Test Details:</h3>
                            <ul>
                                <li><strong>Sent To:</strong> {email}</li>
                                <li><strong>From:</strong> {sender}</li>
                                <li><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</li>
                                <li><strong>Server:</strong> {mail_config.get('server', 'N/A')}</li>
                                <li><strong>Port:</strong> {mail_config.get('port', 'N/A')}</li>
                            </ul>
                            
                            <p style="margin-top: 20px; color: #666; font-size: 12px;">
                                This is an automated test email from the Diraja System.
                            </p>
                        </div>
                    </body>
                </html>
                """,
                body=f"""
                Email Test from Diraja System
                
                This is a test email to verify your email configuration is working properly.
                
                Test Details:
                - Sent To: {email}
                - From: {sender}
                - Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                - Server: {mail_config.get('server', 'N/A')}
                - Port: {mail_config.get('port', 'N/A')}
                
                If you received this email, your email configuration is working correctly!
                """,
                sender=sender
            )
            
            # Add extra headers to help avoid spam filters
            msg.extra_headers = {
                'X-Mailer': 'Diraja System',
                'X-Priority': '3 (Normal)',
                'Message-ID': f'<{datetime.now().timestamp()}@{mail_config.get("server", "diraja.online")}>',
                'Reply-To': sender,
                'Return-Path': sender
            }
            
            debug_info["steps"].append({"step": "Send Email", "message": "Calling mail.send()", "status": "in_progress"})
            
            # Send with detailed error handling
            try:
                # Use the mail object directly
                mail.send(msg)
                debug_info["steps"].append({"step": "Send Email", "message": "Email sent successfully", "status": "success"})
                logger.info(f"Email sent successfully to {email}")
                
                debug_info["success"] = True
                debug_info["message"] = f"Test email sent to {email}"
                
                return {
                    "success": True,
                    "message": f"Test email sent to {email}",
                    "debug": debug_info
                }, 200
                
            except smtplib.SMTPAuthenticationError as e:
                logger.error(f"SMTP Authentication Error: {str(e)}")
                debug_info["steps"].append({"step": "Send Email", "message": f"Authentication failed: {str(e)}", "status": "error"})
                debug_info["error"] = str(e)
                
                # Provide helpful diagnosis
                diagnosis = "Check that your MAIL_USERNAME and MAIL_PASSWORD are correct."
                if mail_config["username"] and mail_config["server"]:
                    username_domain = mail_config["username"].split('@')[1] if '@' in mail_config["username"] else None
                    server_domain = mail_config["server"].replace('mail.', '') if mail_config["server"] else None
                    if username_domain and server_domain and username_domain != server_domain:
                        diagnosis = f"Your MAIL_USERNAME domain ({username_domain}) doesn't match the mail server domain ({server_domain}). They should match."
                
                return {
                    "success": False,
                    "message": "SMTP Authentication failed. " + diagnosis,
                    "error": str(e),
                    "debug": debug_info
                }, 500
                
            except smtplib.SMTPRecipientsRefused as e:
                logger.error(f"SMTP Recipients Refused: {str(e)}")
                debug_info["steps"].append({"step": "Send Email", "message": f"Recipient refused: {str(e)}", "status": "error"})
                debug_info["error"] = str(e)
                return {
                    "success": False,
                    "message": "Recipient email address was refused. Please check the email address.",
                    "error": str(e),
                    "debug": debug_info
                }, 500
                
            except smtplib.SMTPConnectError as e:
                logger.error(f"SMTP Connection Error: {str(e)}")
                debug_info["steps"].append({"step": "Send Email", "message": f"Connection failed: {str(e)}", "status": "error"})
                debug_info["error"] = str(e)
                return {
                    "success": False,
                    "message": "Cannot connect to mail server. Please check server address and port.",
                    "error": str(e),
                    "debug": debug_info
                }, 500
                
            except smtplib.SMTPServerDisconnected as e:
                logger.error(f"SMTP Server Disconnected: {str(e)}")
                debug_info["steps"].append({"step": "Send Email", "message": f"Server disconnected: {str(e)}", "status": "error"})
                debug_info["error"] = str(e)
                return {
                    "success": False,
                    "message": "Mail server disconnected. Please check your network connection.",
                    "error": str(e),
                    "debug": debug_info
                }, 500
                
            except smtplib.SMTPException as e:
                logger.error(f"SMTP Exception: {str(e)}")
                debug_info["steps"].append({"step": "Send Email", "message": f"SMTP error: {str(e)}", "status": "error"})
                debug_info["error"] = str(e)
                return {
                    "success": False,
                    "message": f"SMTP error occurred: {str(e)}",
                    "error": str(e),
                    "debug": debug_info
                }, 500
                
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            logger.error(traceback.format_exc())
            debug_info["steps"].append({"step": "Unexpected Error", "message": str(e), "status": "error"})
            debug_info["error"] = str(e)
            return {
                "success": False,
                "message": "An unexpected error occurred",
                "error": str(e),
                "debug": debug_info
            }, 500