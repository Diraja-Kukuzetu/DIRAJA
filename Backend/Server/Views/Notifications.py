# resources/notification_resource.py
from flask_restful import Resource
from flask import request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from Server.Models.Notification import Notification
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class NotificationsResource(Resource):
    @jwt_required()
    def get(self):
        """
        Get notifications for the current user
        
        Query Parameters:
        - unread_only: (boolean) If true, only return unread notifications (default: false)
        - limit: (int) Maximum number of notifications to return (default: 50, max: 100)
        - skip: (int) Number of notifications to skip for pagination (default: 0)
        - type: (string) Filter by notification type (optional)
        - from_date: (string) ISO format date to filter notifications after (optional)
        - to_date: (string) ISO format date to filter notifications before (optional)
        """
        current_user_id = get_jwt_identity()
        
        # Get query parameters
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        limit = min(int(request.args.get('limit', 50)), 100)  # Max 100 items
        skip = int(request.args.get('skip', 0))
        notification_type = request.args.get('type', None)
        from_date = request.args.get('from_date', None)
        to_date = request.args.get('to_date', None)
        
        try:
            # Build query
            query = Notification.query.filter_by(user_id=current_user_id)
            
            # Apply filters
            if unread_only:
                query = query.filter_by(is_read=False)
            
            if notification_type:
                query = query.filter_by(notification_type=notification_type)
            
            if from_date:
                try:
                    from_date_obj = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
                    query = query.filter(Notification.created_at >= from_date_obj)
                except ValueError:
                    return {'message': 'Invalid from_date format. Use ISO format (e.g., 2024-01-01T00:00:00)'}, 400
            
            if to_date:
                try:
                    to_date_obj = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
                    query = query.filter(Notification.created_at <= to_date_obj)
                except ValueError:
                    return {'message': 'Invalid to_date format. Use ISO format (e.g., 2024-01-01T00:00:00)'}, 400
            
            # Get total count before pagination
            total_count = query.count()
            
            # Get unread count
            unread_count = Notification.query.filter_by(
                user_id=current_user_id, 
                is_read=False
            ).count()
            
            # Apply pagination and ordering
            notifications = query.order_by(
                Notification.created_at.desc()
            ).offset(skip).limit(limit).all()
            
            # Get unique notification types for this user (for filtering options)
            notification_types = db.session.query(Notification.notification_type)\
                .filter_by(user_id=current_user_id)\
                .distinct()\
                .all()
            notification_types = [nt[0] for nt in notification_types]
            
            return {
                'notifications': [n.to_dict() for n in notifications],
                'pagination': {
                    'total': total_count,
                    'limit': limit,
                    'skip': skip,
                    'has_more': (skip + limit) < total_count
                },
                'unread_count': unread_count,
                'available_types': notification_types
            }, 200
            
        except Exception as e:
            logger.error(f"Error fetching notifications: {str(e)}")
            return {'message': 'Error fetching notifications', 'error': str(e)}, 500


class NotificationDetailResource(Resource):
    @jwt_required()
    def get(self, notification_id):
        """Get a single notification by ID"""
        current_user_id = get_jwt_identity()
        
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=current_user_id
        ).first()
        
        if not notification:
            return {'message': 'Notification not found'}, 404
        
        return notification.to_dict(), 200
    
    @jwt_required()
    def patch(self, notification_id):
        """Mark a specific notification as read"""
        current_user_id = get_jwt_identity()
        
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=current_user_id
        ).first()
        
        if not notification:
            return {'message': 'Notification not found'}, 404
        
        notification.is_read = True
        db.session.commit()
        
        return {
            'message': 'Notification marked as read',
            'notification': notification.to_dict()
        }, 200
    
    @jwt_required()
    def delete(self, notification_id):
        """Delete a notification"""
        current_user_id = get_jwt_identity()
        
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=current_user_id
        ).first()
        
        if not notification:
            return {'message': 'Notification not found'}, 404
        
        db.session.delete(notification)
        db.session.commit()
        
        return {'message': 'Notification deleted successfully'}, 200


class NotificationReadAllResource(Resource):
    @jwt_required()
    def post(self):
        """Mark all notifications as read for the current user"""
        current_user_id = get_jwt_identity()
        
        # Update all unread notifications
        updated_count = Notification.query.filter_by(
            user_id=current_user_id,
            is_read=False
        ).update({"is_read": True})
        
        db.session.commit()
        
        return {
            'message': f'Marked {updated_count} notifications as read',
            'marked_count': updated_count
        }, 200


class NotificationUnreadCountResource(Resource):
    @jwt_required()
    def get(self):
        """Get unread notification count for the current user"""
        current_user_id = get_jwt_identity()
        
        count = Notification.query.filter_by(
            user_id=current_user_id,
            is_read=False
        ).count()
        
        return {'unread_count': count}, 200


class NotificationBulkResource(Resource):
    @jwt_required()
    def delete(self):
        """Delete multiple notifications (bulk delete)"""
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        notification_ids = data.get('notification_ids', [])
        
        if not notification_ids:
            return {'message': 'No notification IDs provided'}, 400
        
        # Delete notifications that belong to the user
        deleted_count = Notification.query.filter(
            Notification.id.in_(notification_ids),
            Notification.user_id == current_user_id
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        return {
            'message': f'Deleted {deleted_count} notifications',
            'deleted_count': deleted_count
        }, 200
    
    @jwt_required()
    def patch(self):
        """Mark multiple notifications as read (bulk update)"""
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        notification_ids = data.get('notification_ids', [])
        
        if not notification_ids:
            return {'message': 'No notification IDs provided'}, 400
        
        # Update notifications that belong to the user
        updated_count = Notification.query.filter(
            Notification.id.in_(notification_ids),
            Notification.user_id == current_user_id,
            Notification.is_read == False
        ).update({"is_read": True}, synchronize_session=False)
        
        db.session.commit()
        
        return {
            'message': f'Marked {updated_count} notifications as read',
            'updated_count': updated_count
        }, 200


class NotificationTypesResource(Resource):
    @jwt_required()
    def get(self):
        """Get all notification types available for the current user"""
        current_user_id = get_jwt_identity()
        
        # Get unique notification types
        types = db.session.query(Notification.notification_type)\
            .filter_by(user_id=current_user_id)\
            .distinct()\
            .all()
        
        # Get counts for each type
        result = []
        for notification_type in types:
            type_name = notification_type[0]
            total_count = Notification.query.filter_by(
                user_id=current_user_id,
                notification_type=type_name
            ).count()
            unread_count = Notification.query.filter_by(
                user_id=current_user_id,
                notification_type=type_name,
                is_read=False
            ).count()
            
            result.append({
                'type': type_name,
                'total_count': total_count,
                'unread_count': unread_count
            })
        
        return {'notification_types': result}, 200