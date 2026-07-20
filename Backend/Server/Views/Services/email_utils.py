# Server/utils/email_utils.py
from flask import render_template, current_app
from flask_mail import Message
from app import mail
import logging

logger = logging.getLogger(__name__)

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
        
        msg = Message(
            subject=subject,
            recipients=[user_email],
            html=html_body,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@kukuzetu.co.ke')
        )
        
        mail.send(msg)
        logger.info(f"2FA email sent successfully to {user_email}")
        return True
        
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
                    
                    <p style="margin-top: 20px;">Best regards,<br><strong>Kulima Team</strong></p>
                </div>
            </body>
        </html>
        """
        
        msg = Message(
            subject=subject,
            recipients=[user_email],
            html=html_body,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@kulima.co.ke')
        )
        
        mail.send(msg)
        logger.info(f"2FA setup email sent successfully to {user_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send 2FA setup email to {user_email}: {str(e)}")
        return False