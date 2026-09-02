from sqlalchemy import func
from app import db
import logging
from Server.Models.Customers import Customers,LoyaltyTransaction

logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)

class CustomerService:
    """
    Utility class for handling customer operations including:
    - Adding/updating customers
    - Loyalty points calculation
    - Customer registration
    """
    
    @staticmethod
    def calculate_loyalty_points(amount_paid: float) -> int:
        """
        Calculate loyalty points based on amount paid.
        
        Points structure:
        - 1-100: 1 point
        - 101-200: 2 points
        - 201-500: 3 points
        - 501-1000: 4 points
        - 1001+: 5 points
        """
        if amount_paid <= 0:
            return 0
        
        if 1 <= amount_paid <= 100:
            return 1
        elif 101 <= amount_paid <= 200:
            return 2
        elif 201 <= amount_paid <= 500:
            return 3
        elif 501 <= amount_paid <= 1000:
            return 4
        else:  # 1001 and above
            return 5
    
    @staticmethod
    def get_loyalty_tier(total_spent: float) -> str:
        """
        Determine loyalty tier based on total spending.
        """
        if total_spent >= 50000:
            return "Gold"
        elif total_spent >= 20000:
            return "Silver"
        elif total_spent >= 5000:
            return "Bronze"
        else:
            return "Bronze"
    
    @staticmethod
    def get_points_multiplier(tier: str) -> float:
        """
        Get points multiplier based on tier.
        """
        multipliers = {
            "Gold": 2.0,
            "Silver": 1.5,
            "Bronze": 1.0
        }
        return multipliers.get(tier, 1.0)
    
    @staticmethod
    def register_customer_for_loyalty(customer: Customers) -> bool:
        """
        Register an existing customer for loyalty program.
        
        Returns:
            bool: True if registration was successful, False otherwise.
        """
        try:
            if customer.is_loyalty_registered:
                logger.info(f"Customer {customer.customer_id} already registered for loyalty")
                return True
            
            # Set loyalty registration fields
            customer.is_loyalty_registered = True
            customer.loyalty_registration_date = func.now()
            customer.loyalty_points = 0  # Initialize with 0 points
            customer.loyalty_tier = "Bronze"
            customer.points_earned_total = 0
            customer.points_redeemed_total = 0
            
            db.session.add(customer)
            db.session.commit()
            
            logger.info(f"Customer {customer.customer_id} registered for loyalty program")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register customer for loyalty: {str(e)}")
            db.session.rollback()
            return False
    
    @staticmethod
    def add_or_update_customer(
        customer_name: str,
        customer_number: str,
        shop_id: int,
        sales_id: int,
        user_id: int,
        items: list,
        amount_paid: float,
        payment_method: str,
        created_at,
        register_for_loyalty: bool = False
    ) -> dict:
        """
        Add or update a customer and handle loyalty points.
        
        Args:
            customer_name: Customer's name
            customer_number: Customer's phone number
            shop_id: Shop ID
            sales_id: Sale ID
            user_id: User ID who processed the sale
            items: List of items purchased
            amount_paid: Amount paid by customer
            payment_method: Payment method used
            created_at: Sale creation timestamp
            register_for_loyalty: Whether to register customer for loyalty program
            
        Returns:
            dict: {
                'customer': Customer object,
                'is_new': bool,
                'points_earned': int,
                'action': 'created' | 'updated' | 'already_registered' | 'registered'
            }
        """
        try:
            # Clean phone number (remove spaces, special characters)
            clean_number = ''.join(filter(str.isdigit, str(customer_number)))
            
            # Check if customer exists
            existing_customer = Customers.query.filter(
                func.replace(Customers.customer_number, ' ', '') == clean_number,
                Customers.shop_id == shop_id
            ).first()
            
            is_new = False
            points_earned = 0
            action = 'updated'
            
            if existing_customer:
                # Customer exists - update their information
                existing_customer.customer_name = customer_name
                existing_customer.customer_number = customer_number
                existing_customer.shop_id = shop_id
                existing_customer.sales_id = sales_id
                existing_customer.user_id = user_id
                existing_customer.item = ", ".join(items) if isinstance(items, list) else items
                existing_customer.amount_paid = amount_paid
                existing_customer.payment_method = payment_method
                existing_customer.created_at = created_at
                
                # Update total spent
                existing_customer.total_spent = (existing_customer.total_spent or 0) + amount_paid
                
                # Update last purchase date
                existing_customer.last_purchase_date = created_at
                
                customer = existing_customer
                
            else:
                # Create new customer - REMOVED points_multiplier from here
                customer = Customers(
                    customer_name=customer_name,
                    customer_number=customer_number,
                    shop_id=shop_id,
                    sales_id=sales_id,
                    user_id=user_id,
                    item=", ".join(items) if isinstance(items, list) else items,
                    amount_paid=amount_paid,
                    payment_method=payment_method,
                    created_at=created_at,
                    total_spent=amount_paid,
                    loyalty_points=0,
                    is_loyalty_registered=False,
                    loyalty_tier="Bronze",
                    points_earned_total=0,
                    points_redeemed_total=0
                    # points_multiplier REMOVED - not a column in the database
                )
                is_new = True
                action = 'created'
            
            # ===== HANDLE LOYALTY =====
            if is_new or register_for_loyalty:
                # Calculate points for this transaction
                points_earned = CustomerService.calculate_loyalty_points(amount_paid)
                
                if points_earned > 0:
                    # Check if customer is registered for loyalty
                    if not customer.is_loyalty_registered:
                        # Register the customer
                        if register_for_loyalty:
                            customer.is_loyalty_registered = True
                            customer.loyalty_registration_date = func.now()
                            customer.loyalty_points = points_earned
                            customer.points_earned_total = points_earned
                            action = 'registered'
                            
                            logger.info(f"Registered customer {customer.customer_id} with {points_earned} points")
                        else:
                            # Not registered and not requested - skip points
                            logger.info(f"Customer {customer.customer_id} not registered for loyalty, skipping points")
                    else:
                        # Already registered - add points
                        customer.loyalty_points = (customer.loyalty_points or 0) + points_earned
                        customer.points_earned_total = (customer.points_earned_total or 0) + points_earned
                        
                        # Update tier based on total spent
                        customer.loyalty_tier = CustomerService.get_loyalty_tier(
                            customer.total_spent or customer.amount_paid
                        )
                        
                        # Update last earned points and date
                        customer.last_earned_points = points_earned
                        customer.last_earned_date = created_at
                        
                        # Calculate available discount (10% of points converted to discount)
                        customer.available_discount = int((customer.loyalty_points or 0) / 10)
                        
                        action = 'updated_with_points'
                        
                        logger.info(f"Added {points_earned} points to customer {customer.customer_id}")
            
            db.session.add(customer)
            
            return {
                'customer': customer,
                'is_new': is_new,
                'points_earned': points_earned,
                'action': action
            }
            
        except Exception as e:
            logger.error(f"Error in add_or_update_customer: {str(e)}")
            db.session.rollback()
            raise e

    @staticmethod
    def get_customer_by_phone(phone_number: str, shop_id: int):
        """
        Get customer by phone number.
        """
        clean_number = ''.join(filter(str.isdigit, str(phone_number)))
        return Customers.query.filter(
            func.replace(Customers.customer_number, ' ', '') == clean_number,
            Customers.shop_id == shop_id
        ).first()
    
    @staticmethod
    def get_customer_points(customer_id: int) -> dict:
        """
        Get customer points summary.
        """
        customer = Customers.query.get(customer_id)
        if not customer:
            return {}
        
        return {
            'customer_id': customer.customer_id,
            'customer_name': customer.customer_name,
            'loyalty_points': customer.loyalty_points or 0,
            'points_earned_total': customer.points_earned_total or 0,
            'points_redeemed_total': customer.points_redeemed_total or 0,
            'loyalty_tier': customer.loyalty_tier or 'Bronze',
            'is_loyalty_registered': customer.is_loyalty_registered or False,
            'available_discount': customer.available_discount or 0,
            'total_spent': customer.total_spent or 0
        }