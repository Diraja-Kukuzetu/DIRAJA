# Server/Models/TwoFactorAuth.py
from app import db
from datetime import datetime, timedelta
import secrets
import string

class TwoFactorAuth(db.Model):
    __tablename__ = 'two_factor_auth'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=False)  # Fixed: users.users_id
    code = db.Column(db.String(6), nullable=False)
    secret = db.Column(db.String(255), nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    

    
    def __init__(self, user_id, code, secret):
        self.user_id = user_id
        self.code = code
        self.secret = secret
        self.expires_at = datetime.utcnow() + timedelta(minutes=5)
    
    def is_valid(self):
        """Check if the 2FA code is still valid"""
        return not self.is_used and datetime.utcnow() < self.expires_at
    
    def use(self):
        """Mark the 2FA code as used"""
        self.is_used = True
        db.session.commit()
    
    @staticmethod
    def generate_code():
        """Generate a 6-digit code"""
        return ''.join(secrets.choice(string.digits) for _ in range(6))
    
    @staticmethod
    def generate_secret():
        """Generate a random secret"""
        return secrets.token_hex(32)
    
    @staticmethod
    def create_for_user(user_id):
        """Create a new 2FA code for a user"""
        code = TwoFactorAuth.generate_code()
        secret = TwoFactorAuth.generate_secret()
        
        # Delete any existing unused codes for this user
        TwoFactorAuth.query.filter_by(
            user_id=user_id, 
            is_used=False
        ).delete()
        
        two_factor = TwoFactorAuth(user_id, code, secret)
        db.session.add(two_factor)
        db.session.commit()
        
        return two_factor
    
    @staticmethod
    def verify_code(user_id, code, secret=None):
        """Verify a 2FA code"""
        query = TwoFactorAuth.query.filter_by(
            user_id=user_id,
            code=code,
            is_used=False
        )
        
        if secret:
            query = query.filter_by(secret=secret)
        
        two_factor = query.first()
        
        if two_factor and two_factor.is_valid():
            two_factor.use()
            return True
        
        return False