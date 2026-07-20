# Server/utils/email_utils.py
from flask import render_template, current_app
from flask_mail import Message
from app import mail
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def send_email_with_template(recipient, subject, html_content, text_content=None, sender=None):
    """
    Centralized email sending function that handles RFC compliance
    """
    try:
        if sender is None:
            sender = current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@kukuzetu.co.ke')
        
        msg = Message(
            subject=subject,
            recipients=[recipient],
            html=html_content,
            body=text_content,
            sender=sender
        )
        
        # Add only necessary headers - DO NOT add Message-ID
        # Flask-Mail auto-generates a compliant Message-ID
        msg.extra_headers = {
            'X-Mailer': 'kukuzetu System',
            'X-Priority': '3 (Normal)',
            'Reply-To': sender,
            'Return-Path': sender
        }
        
        mail.send(msg)
        logger.info(f"Email sent successfully to {recipient}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {recipient}: {str(e)}")
        return False


def send_2fa_code_email(user_email, full_name, code):
    """
    Send 2FA code to user's email
    """
    try:
        subject = "Your 2FA Verification Code - kukuzetu"
        
        # Simple HTML email body
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
                    <h1>Two-Factor Authentication</h1>
                </div>
                <div style="background: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 5px 5px;">
                    <h2>Hello {full_name},</h2>
                    <p>You've requested to log in to your account. Please use the verification code below to complete your login:</p>
                    
                    <div style="background: white; border: 2px dashed #4CAF50; padding: 20px; text-align: center; margin: 20px 0; font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #4CAF50;">
                        {code}
                    </div>
                    
                    <p><strong>This code will expire in 5 minutes.</strong></p>
                    
                    <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 10px; margin: 15px 0; font-size: 14px;">
                        <strong>⚠️ Security Notice:</strong>
                        <ul style="margin: 5px 0 0 20px;">
                            <li>Never share this code with anyone</li>
                            <li>If you didn't request this code, please ignore this email</li>
                            <li>Your account is secure - this is an automated security measure</li>
                        </ul>
                    </div>
                    
                    <p style="margin-top: 20px;">Best regards,<br><strong>kukuzetu Team</strong></p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Two-Factor Authentication - kukuzetu
        
        Hello {full_name},
        
        You've requested to log in to your account. Please use the verification code below to complete your login:
        
        Your verification code: {code}
        
        This code will expire in 5 minutes.
        
        Security Notice:
        - Never share this code with anyone
        - If you didn't request this code, please ignore this email
        - Your account is secure - this is an automated security measure
        
        Best regards,
        kukuzetu Team
        """
        
        return send_email_with_template(
            recipient=user_email,
            subject=subject,
            html_content=html_body,
            text_content=text_body
        )
        
    except Exception as e:
        logger.error(f"Failed to send 2FA email to {user_email}: {str(e)}")
        return False


def send_2fa_setup_email(user_email, full_name, backup_codes):
    """
    Send 2FA setup confirmation with backup codes
    """
    try:
        subject = "2FA Setup Confirmation - kukuzetu"
        
        backup_codes_html = "".join([f"<li><strong>{code}</strong></li>" for code in backup_codes])
        backup_codes_text = "\n".join([f"• {code}" for code in backup_codes])
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
                    <h1>2FA Setup Confirmation</h1>
                </div>
                <div style="background: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 5px 5px;">
                    <h2>Hello {full_name},</h2>
                    <p>Two-Factor Authentication has been successfully enabled for your account.</p>
                    
                    <h3>Your Backup Codes:</h3>
                    <div style="background: white; padding: 20px; border: 1px solid #ddd; margin: 20px 0;">
                        <p style="color: #ff6b6b; font-weight: bold;">⚠️ Important: Save these backup codes in a safe place.</p>
                        <p style="color: #ff6b6b; font-weight: bold;">These codes can only be used once!</p>
                        <ul style="font-size: 18px; list-style: none; padding: 0;">
                            {backup_codes_html}
                        </ul>
                    </div>
                    
                    <p style="margin-top: 20px;">Best regards,<br><strong>kukuzetu Team</strong></p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        2FA Setup Confirmation - kukuzetu
        
        Hello {full_name},
        
        Two-Factor Authentication has been successfully enabled for your account.
        
        Your Backup Codes:
        {backup_codes_text}
        
        ⚠️ Important: Save these backup codes in a safe place.
        These codes can only be used once!
        
        Best regards,
        kukuzetu Team
        """
        
        return send_email_with_template(
            recipient=user_email,
            subject=subject,
            html_content=html_body,
            text_content=text_body
        )
        
    except Exception as e:
        logger.error(f"Failed to send 2FA setup email to {user_email}: {str(e)}")
        return False


def send_test_email(email):
    """
    Send test email for configuration testing
    """
    try:
        subject = "Test Email Configuration - kukuzetu System"
        
        html_body = f"""
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
                        <li><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</li>
                    </ul>
                    
                    <p style="margin-top: 20px; color: #666; font-size: 12px;">
                        This is an automated test email from the kukuzetu System.
                    </p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Email Test from kukuzetu System
        
        This is a test email to verify your email configuration is working properly.
        
        Test Details:
        - Sent To: {email}
        - Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        
        If you received this email, your email configuration is working correctly!
        """
        
        return send_email_with_template(
            recipient=email,
            subject=subject,
            html_content=html_body,
            text_content=text_body
        )
        
    except Exception as e:
        logger.error(f"Failed to send test email to {email}: {str(e)}")
        return False


def send_password_reset_email(user_email, full_name, reset_link):
    """
    Send password reset email
    """
    try:
        subject = "Password Reset Request - kukuzetu"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #ff6b6b; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
                    <h1>🔑 Password Reset Request</h1>
                </div>
                <div style="background: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 5px 5px;">
                    <h2>Hello {full_name},</h2>
                    <p>We received a request to reset your password. Click the button below to set a new password:</p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{reset_link}" style="background: #4CAF50; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                            Reset Password
                        </a>
                    </div>
                    
                    <p><strong>This link will expire in 1 hour.</strong></p>
                    
                    <p style="color: #666; font-size: 12px; margin-top: 20px;">
                        If you didn't request this, please ignore this email. Your password won't change until you create a new one.
                    </p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Password Reset Request - kukuzetu
        
        Hello {full_name},
        
        We received a request to reset your password. Click the link below to set a new password:
        
        {reset_link}
        
        This link will expire in 1 hour.
        
        If you didn't request this, please ignore this email. Your password won't change until you create a new one.
        """
        
        return send_email_with_template(
            recipient=user_email,
            subject=subject,
            html_content=html_body,
            text_content=text_body
        )
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user_email}: {str(e)}")
        return False


def send_shop_report_email(manager_email, shop_name, report_data):
    """
    Send shop report notification to manager
    """
    try:
        subject = f"Shop Report Submitted - {shop_name}"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #2196F3; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
                    <h1>📋 New Shop Report</h1>
                </div>
                <div style="background: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 5px 5px;">
                    <h2>Shop: {shop_name}</h2>
                    <p>A new report has been submitted by <strong>{report_data.get('username', 'Unknown')}</strong>.</p>
                    
                    <h3>Report Details:</h3>
                    <ul>
                        <li><strong>Report ID:</strong> {report_data.get('id', 'N/A')}</li>
                        <li><strong>Submitted At:</strong> {report_data.get('reported_at', 'N/A')}</li>
                        <li><strong>Location:</strong> {report_data.get('location', 'Not specified')}</li>
                        <li><strong>Note:</strong> {report_data.get('note', 'No notes')}</li>
                    </ul>
                    
                    <p style="color: #666; font-size: 12px; margin-top: 20px;">
                        This is an automated notification from the kukuzetu System.
                    </p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        New Shop Report - {shop_name}
        
        A new report has been submitted by {report_data.get('username', 'Unknown')}.
        
        Report Details:
        - Report ID: {report_data.get('id', 'N/A')}
        - Submitted At: {report_data.get('reported_at', 'N/A')}
        - Location: {report_data.get('location', 'Not specified')}
        - Note: {report_data.get('note', 'No notes')}
        
        This is an automated notification from the kukuzetu System.
        """
        
        return send_email_with_template(
            recipient=manager_email,
            subject=subject,
            html_content=html_body,
            text_content=text_body
        )
        
    except Exception as e:
        logger.error(f"Failed to send shop report email to {manager_email}: {str(e)}")
        return False


def send_stock_report_email(recipient, report_data):
    """
    Send stock report email
    """
    try:
        subject = f"Stock Report - {report_data.get('date', datetime.now().strftime('%Y-%m-%d'))}"
        
        # Build HTML table for stock items
        items_html = ""
        if report_data.get('items'):
            items_html = "<table style='width:100%; border-collapse: collapse;'>"
            items_html += "<tr style='background: #f2f2f2;'><th style='padding: 10px; border: 1px solid #ddd;'>Item</th><th style='padding: 10px; border: 1px solid #ddd;'>Quantity</th><th style='padding: 10px; border: 1px solid #ddd;'>Status</th></tr>"
            for item in report_data['items']:
                status_color = "#4CAF50" if item.get('status') == "In Stock" else "#ff6b6b"
                items_html += f"<tr><td style='padding: 10px; border: 1px solid #ddd;'>{item.get('name', 'N/A')}</td><td style='padding: 10px; border: 1px solid #ddd; text-align: center;'>{item.get('quantity', 0)}</td><td style='padding: 10px; border: 1px solid #ddd; color: {status_color};'>{item.get('status', 'Unknown')}</td></tr>"
            items_html += "</table>"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #FF9800; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
                    <h1>📊 Stock Report</h1>
                </div>
                <div style="background: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 5px 5px;">
                    <h2>Stock Report for {report_data.get('date', datetime.now().strftime('%Y-%m-%d'))}</h2>
                    
                    <h3>Summary</h3>
                    <ul>
                        <li><strong>Total Items:</strong> {report_data.get('total_items', 0)}</li>
                        <li><strong>Total Value:</strong> ${report_data.get('total_value', 0.00)}</li>
                        <li><strong>Low Stock Items:</strong> {report_data.get('low_stock_count', 0)}</li>
                    </ul>
                    
                    {items_html}
                    
                    <p style="color: #666; font-size: 12px; margin-top: 20px;">
                        This is an automated stock report from the kukuzetu System.
                    </p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Stock Report - {report_data.get('date', datetime.now().strftime('%Y-%m-%d'))}
        
        Summary:
        - Total Items: {report_data.get('total_items', 0)}
        - Total Value: ${report_data.get('total_value', 0.00)}
        - Low Stock Items: {report_data.get('low_stock_count', 0)}
        
        This is an automated stock report from the kukuzetu System.
        """
        
        return send_email_with_template(
            recipient=recipient,
            subject=subject,
            html_content=html_body,
            text_content=text_body
        )
        
    except Exception as e:
        logger.error(f"Failed to send stock report email to {recipient}: {str(e)}")
        return False