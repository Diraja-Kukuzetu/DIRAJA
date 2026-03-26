from app import db
import json
import logging
from Server.Models.Notification import Notification
from Server.Models.Users import Users
from Server.Models.Employees import Employees

logger = logging.getLogger(__name__)

class NotificationService:
    
    @staticmethod
    def create_notification(user_id, notification_type, title, message, data=None):
        """
        Create a single notification for a user
        
        Args:
            user_id (int): The user to notify
            notification_type (str): Type of notification (e.g., 'task_assigned', 'task_completed')
            title (str): Notification title
            message (str): Notification message
            data (dict, optional): Additional data to store with notification
        
        Returns:
            Notification: The created notification object
        """
        try:
            notification = Notification(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                message=message,
                data=data
            )
            db.session.add(notification)
            db.session.commit()
            logger.info(f"Notification created for user {user_id}: {notification_type}")
            return notification
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create notification: {str(e)}")
            return None
    
    @staticmethod
    def get_user_notifications(user_id, unread_only=False, limit=50, skip=0):
        """
        Retrieve notifications for a user
        
        Args:
            user_id (int): User ID
            unread_only (bool): If True, only return unread notifications
            limit (int): Maximum number of notifications to return
            skip (int): Number of notifications to skip (for pagination)
        
        Returns:
            list: List of notification dictionaries
        """
        try:
            query = Notification.query.filter_by(user_id=user_id)
            
            if unread_only:
                query = query.filter_by(is_read=False)
            
            notifications = query.order_by(
                Notification.created_at.desc()
            ).offset(skip).limit(limit).all()
            
            return [n.to_dict() for n in notifications]
        except Exception as e:
            logger.error(f"Failed to get notifications: {str(e)}")
            return []
    
    @staticmethod
    def get_unread_count(user_id):
        """Get count of unread notifications for a user"""
        try:
            return Notification.query.filter_by(
                user_id=user_id, 
                is_read=False
            ).count()
        except Exception as e:
            logger.error(f"Failed to get unread count: {str(e)}")
            return 0
    
    @staticmethod
    def mark_as_read(notification_id, user_id):
        """
        Mark a notification as read
        
        Args:
            notification_id (int): Notification ID
            user_id (int): User ID (for security verification)
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            notification = Notification.query.filter_by(
                id=notification_id, 
                user_id=user_id
            ).first()
            
            if notification:
                notification.is_read = True
                db.session.commit()
                logger.info(f"Notification {notification_id} marked as read")
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to mark notification as read: {str(e)}")
            return False
    
    @staticmethod
    def mark_all_as_read(user_id):
        """Mark all notifications as read for a user"""
        try:
            Notification.query.filter_by(
                user_id=user_id, 
                is_read=False
            ).update({"is_read": True})
            db.session.commit()
            logger.info(f"All notifications marked as read for user {user_id}")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to mark all as read: {str(e)}")
            return False
    
    @staticmethod
    def delete_notification(notification_id, user_id):
        """Delete a notification"""
        try:
            notification = Notification.query.filter_by(
                id=notification_id, 
                user_id=user_id
            ).first()
            
            if notification:
                db.session.delete(notification)
                db.session.commit()
                logger.info(f"Notification {notification_id} deleted")
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete notification: {str(e)}")
            return False
        
    # In services/notification_service.py, add this method:

    @staticmethod
    def get_users_for_shop(shop_id):
        """
        Get all users (with their employees) for a specific shop
        
        Args:
            shop_id (int): The shop ID
        
        Returns:
            list: List of user dictionaries with user_id and employee details
        """
        try:
            employees = Employees.query.filter_by(
                shop_id=shop_id,
                account_status='active'
            ).all()
            
            users_list = []
            for employee in employees:
                user = Users.query.filter_by(employee_id=employee.employee_id).first()
                if user:
                    users_list.append({
                        'user_id': user.users_id,
                        'employee_id': employee.employee_id,
                        'name': f"{employee.first_name} {employee.surname}",
                        'role': employee.role,
                        'email': user.email
                    })
            
            return users_list
        except Exception as e:
            logger.error(f"Failed to get users for shop {shop_id}: {str(e)}")
            return []