from flask_sqlalchemy import SQLAlchemy
from app import db
from sqlalchemy.orm import validates
from sqlalchemy import func

class Customers(db.Model):
    __tablename__= "customers"

    customer_id = db.Column(db.Integer, primary_key=True , autoincrement=True)
    customer_name = db.Column(db.String(50), nullable=True)
    customer_number = db.Column(db.Integer, nullable=True)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.shops_id'))
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.sales_id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'))
    item = db.Column(db.String(50), unique=False, nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Loyalty Points Fields
    loyalty_points = db.Column(db.Integer, default=0, nullable=False)
    total_spent = db.Column(db.Float, default=0.0, nullable=False)
    points_earned_total = db.Column(db.Integer, default=0, nullable=False)
    points_redeemed_total = db.Column(db.Integer, default=0, nullable=False)
    loyalty_tier = db.Column(db.String(20), default='Bronze', nullable=False)
    last_purchase_date = db.Column(db.DateTime, nullable=True)
    
    # Loyalty Registration Status
    is_loyalty_registered = db.Column(db.Boolean, default=False, nullable=False)
    loyalty_registration_date = db.Column(db.DateTime, nullable=True)

    # relationship 
    shops = db.relationship('Shops' ,backref='customers', lazy=True)
    users = db.relationship('Users', backref='customers', lazy=True)
    sales = db.relationship('Sales', backref='customers', lazy=True)
    
    # Relationship for loyalty transactions
    loyalty_transactions = db.relationship('LoyaltyTransaction', backref='customer', lazy=True)

    @validates('customer_number')
    def validate_customer_number(self, key, customer_number):
        if customer_number == '':
            return None  # Set to None if an empty string is provided
        return customer_number

    @validates('payment_method')
    def validate_payment_method(self, key, payment_method):
        valid_method = ['bank', 'cash', 'mpesa', 'sasapay']
        if payment_method not in valid_method:
            raise ValueError(f"Invalid Payment Method. Must be one of: {', '.join(valid_method)}")
        return payment_method

    def register_for_loyalty(self):
        """
        Register customer for loyalty program
        """
        if not self.is_loyalty_registered:
            self.is_loyalty_registered = True
            self.loyalty_registration_date = func.now()
            
            # Create registration transaction record
            transaction = LoyaltyTransaction(
                customer_id=self.customer_id,
                points_earned=0,
                points_redeemed=0,
                transaction_type='registration',
                amount_spent=0.0,
                description='Customer registered for loyalty program'
            )
            db.session.add(transaction)
            
            # Optionally give bonus points for registering
            bonus_points = 50  # Welcome bonus
            self.loyalty_points += bonus_points
            self.points_earned_total += bonus_points
            
            # Create bonus transaction
            bonus_transaction = LoyaltyTransaction(
                customer_id=self.customer_id,
                points_earned=bonus_points,
                points_redeemed=0,
                transaction_type='bonus',
                amount_spent=0.0,
                description=f'Welcome bonus points for registration ({bonus_points} points)'
            )
            db.session.add(bonus_transaction)
            
            return True
        return False

    def unregister_from_loyalty(self):
        """
        Unregister customer from loyalty program
        This will keep their points history but prevent future point accumulation
        """
        if self.is_loyalty_registered:
            self.is_loyalty_registered = False
            
            # Create unregistration transaction record
            transaction = LoyaltyTransaction(
                customer_id=self.customer_id,
                points_earned=0,
                points_redeemed=0,
                transaction_type='unregistration',
                amount_spent=0.0,
                description='Customer unregistered from loyalty program'
            )
            db.session.add(transaction)
            return True
        return False

    def add_loyalty_points(self, amount_spent, points_multiplier=1.0):
        """
        Add loyalty points based on amount spent
        Points are calculated as: 1 point per 100 currency units * multiplier
        """
        # Check if customer is registered for loyalty program
        if not self.is_loyalty_registered:
            raise ValueError("Customer is not registered for loyalty program")
        
        points_earned = int((amount_spent / 100) * points_multiplier)
        
        self.loyalty_points += points_earned
        self.points_earned_total += points_earned
        self.total_spent += amount_spent
        self.last_purchase_date = func.now()
        
        # Update loyalty tier based on total points earned
        self.update_loyalty_tier()
        
        # Create transaction record
        transaction = LoyaltyTransaction(
            customer_id=self.customer_id,
            points_earned=points_earned,
            points_redeemed=0,
            transaction_type='earned',
            amount_spent=amount_spent,
            description=f'Points earned from purchase of {amount_spent}'
        )
        db.session.add(transaction)
        
        return points_earned

    def redeem_points(self, points_to_redeem):
        """
        Redeem loyalty points for discounts or rewards
        Returns the discount amount (1 point = 1 currency unit discount)
        """
        # Check if customer is registered for loyalty program
        if not self.is_loyalty_registered:
            raise ValueError("Customer is not registered for loyalty program")
        
        if points_to_redeem <= 0:
            raise ValueError("Points to redeem must be positive")
        
        if points_to_redeem > self.loyalty_points:
            raise ValueError(f"Insufficient points. You have {self.loyalty_points} points")
        
        # Calculate discount (1 point = 1 currency unit)
        discount_amount = points_to_redeem
        
        self.loyalty_points -= points_to_redeem
        self.points_redeemed_total += points_to_redeem
        
        # Create transaction record
        transaction = LoyaltyTransaction(
            customer_id=self.customer_id,
            points_earned=0,
            points_redeemed=points_to_redeem,
            transaction_type='redeemed',
            amount_spent=0,
            description=f'Points redeemed for discount of {discount_amount}'
        )
        db.session.add(transaction)
        
        return discount_amount

    def update_loyalty_tier(self):
        """
        Update customer's loyalty tier based on total points earned
        """
        if self.points_earned_total >= 500000:
            self.loyalty_tier = 'Platinum'
        elif self.points_earned_total >= 100000:
            self.loyalty_tier = 'Gold'
        elif self.points_earned_total >= 50000:
            self.loyalty_tier = 'Silver'
        else:
            self.loyalty_tier = 'Bronze'

    def get_points_multiplier(self):
        """
        Get points multiplier based on loyalty tier
        """
        multipliers = {
            'Bronze': 1.0,
            'Silver': 1.2,
            'Gold': 1.5,
            'Platinum': 2.0
        }
        return multipliers.get(self.loyalty_tier, 1.0)

    def get_available_discount(self):
        """
        Calculate available discount in currency units
        """
        if not self.is_loyalty_registered:
            return 0
        return self.loyalty_points  # 1 point = 1 currency unit

    @staticmethod
    def get_top_loyalty_customers(limit=10):
        """
        Get customers with highest loyalty points
        """
        return Customers.query.filter_by(
            is_loyalty_registered=True
        ).order_by(
            Customers.loyalty_points.desc()
        ).limit(limit).all()

    @staticmethod
    def get_registered_customers():
        """
        Get all registered loyalty customers
        """
        return Customers.query.filter_by(is_loyalty_registered=True).all()

    @staticmethod
    def get_unregistered_customers():
        """
        Get all unregistered loyalty customers
        """
        return Customers.query.filter_by(is_loyalty_registered=False).all()

    def __repr__(self):
        return f"Customers(id={self.customer_id}, customer_name='{self.customer_name}', " \
               f"customer_number='{self.customer_number}', shopId='{self.shop_id}', " \
               f"userId='{self.user_id}', amount_paid='{self.amount_paid}', " \
               f"payment_method='{self.payment_method}', loyalty_points={self.loyalty_points}, " \
               f"loyalty_tier='{self.loyalty_tier}', registered={self.is_loyalty_registered})"


class LoyaltyTransaction(db.Model):
    __tablename__ = "loyalty_transactions"
    
    transaction_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.customer_id'), nullable=False)
    points_earned = db.Column(db.Integer, default=0)
    points_redeemed = db.Column(db.Integer, default=0)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'earned', 'redeemed', 'registration', 'unregistration', 'bonus'
    amount_spent = db.Column(db.Float, default=0.0)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    def __repr__(self):
        return f"LoyaltyTransaction(id={self.transaction_id}, customer_id={self.customer_id}, " \
               f"type='{self.transaction_type}', points_earned={self.points_earned}, " \
               f"points_redeemed={self.points_redeemed})"