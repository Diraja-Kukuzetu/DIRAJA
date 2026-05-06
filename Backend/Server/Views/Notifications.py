# resources/notification_resource.py
from flask_restful import Resource
from flask import request
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_socketio import emit, join_room
from app import db, socketio
from Server.Models.Notification import Notification
from datetime import datetime
import logging
from functools import wraps

logger = logging.getLogger(__name__)

# WebSocket event handlers
def register_notification_socket_handlers(socketio):
    """Register WebSocket event handlers for notifications"""
    
    @socketio.on('connect_notification')
    def handle_notification_connect(data):
        """Handle notification-specific connection with JWT token"""
        token = data.get('token')
        if not token:
            # Try to get from headers or query params
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if token:
            try:
                from flask_jwt_extended import decode_token
                decoded = decode_token(token)
                user_id = decoded['sub']
                
                if user_id:
                    # Join user-specific room for notifications
                    join_room(f"notifications_{user_id}")
                    
                    # Send initial unread count
                    count = Notification.query.filter_by(
                        user_id=user_id,
                        is_read=False
                    ).count()
                    
                    emit('connection_established', {
                        'status': 'connected',
                        'user_id': user_id,
                        'unread_count': count
                    })
                    
                    logger.info(f"Notification WebSocket connected for user {user_id}")
                    return True
                    
            except Exception as e:
                logger.error(f"Notification WebSocket connection error: {e}")
                return False
        
        return False
    
    @socketio.on('mark_notification_read')
    def handle_mark_read(data):
        """Mark a notification as read via WebSocket"""
        notification_id = data.get('notification_id')
        token = data.get('token')
        
        if not token:
            return {'error': 'No token provided'}, 401
        
        try:
            from flask_jwt_extended import decode_token
            decoded = decode_token(token)
            user_id = decoded['sub']
            
            notification = Notification.query.filter_by(
                id=notification_id,
                user_id=user_id
            ).first()
            
            if notification and not notification.is_read:
                notification.is_read = True
                db.session.commit()
                
                # Send updated count
                send_unread_count(user_id)
                
                emit('notification_marked_read', {
                    'notification_id': notification_id,
                    'success': True
                }, room=f"notifications_{user_id}")
                
        except Exception as e:
            logger.error(f"Error marking notification read via WebSocket: {e}")
    
    @socketio.on('mark_all_notifications_read')
    def handle_mark_all_read(data):
        """Mark all notifications as read via WebSocket"""
        token = data.get('token')
        
        if not token:
            return {'error': 'No token provided'}, 401
        
        try:
            from flask_jwt_extended import decode_token
            decoded = decode_token(token)
            user_id = decoded['sub']
            
            # Update all unread notifications
            updated_count = Notification.query.filter_by(
                user_id=user_id,
                is_read=False
            ).update({"is_read": True})
            
            db.session.commit()
            
            if updated_count > 0:
                # Send updated count
                send_unread_count(user_id)
                
                emit('all_notifications_marked_read', {
                    'count': updated_count,
                    'success': True
                }, room=f"notifications_{user_id}")
                
        except Exception as e:
            logger.error(f"Error marking all notifications read via WebSocket: {e}")
    
    @socketio.on('request_unread_count')
    def handle_request_unread_count(data):
        """Request current unread count via WebSocket"""
        token = data.get('token')
        
        if not token:
            return {'error': 'No token provided'}, 401
        
        try:
            from flask_jwt_extended import decode_token
            decoded = decode_token(token)
            user_id = decoded['sub']
            
            count = Notification.query.filter_by(
                user_id=user_id,
                is_read=False
            ).count()
            
            emit('unread_count_update', {
                'unread_count': count,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f"notifications_{user_id}")
            
        except Exception as e:
            logger.error(f"Error requesting unread count: {e}")


def send_unread_count(user_id):
    """
    Send unread notification count to a specific user via WebSocket
    
    Args:
        user_id: The ID of the user to send the count to
    """
    try:
        count = Notification.query.filter_by(
            user_id=user_id,
            is_read=False
        ).count()
        
        notification_data = {
            'unread_count': count,
            'timestamp': datetime.utcnow().isoformat(),
            'type': 'unread_count_update'
        }
        
        # Emit to the user's notification room
        socketio.emit(
            'unread_count',
            notification_data,
            room=f"notifications_{user_id}"
        )
        
        logger.debug(f"Sent unread count {count} to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error sending unread count to user {user_id}: {e}")


def create_notification_with_websocket(user_id, notification_type, title, message, data=None):
    """
    Create a notification and send WebSocket update
    
    Args:
        user_id: The user to notify
        notification_type: Type of notification (e.g., 'task_assigned', 'comment_added')
        title: Notification title
        message: Notification message
        data: Additional data to store with notification
    
    Returns:
        The created notification object
    """
    try:
        # Create notification in database
        notification = Notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data,
            is_read=False,
            created_at=datetime.utcnow()
        )
        
        db.session.add(notification)
        db.session.commit()
        
        # Get updated unread count
        unread_count = Notification.query.filter_by(
            user_id=user_id,
            is_read=False
        ).count()
        
        # Send WebSocket notification
        socketio.emit('new_notification', {
            'notification': notification.to_dict(),
            'unread_count': unread_count,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f"notifications_{user_id}")
        
        # Also send just the unread count for badge updates
        send_unread_count(user_id)
        
        logger.info(f"Notification created for user {user_id}: {title}")
        return notification
        
    except Exception as e:
        logger.error(f"Error creating notification for user {user_id}: {e}")
        db.session.rollback()
        return None


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
        
        # Mark as read if not already
        was_unread = not notification.is_read
        notification.is_read = True
        db.session.commit()
        
        # Send WebSocket update if notification was marked as read
        if was_unread:
            send_unread_count(current_user_id)
            
            # Also emit a specific event for this notification
            socketio.emit('notification_read', {
                'notification_id': notification_id,
                'unread_count': Notification.query.filter_by(
                    user_id=current_user_id, 
                    is_read=False
                ).count()
            }, room=f"notifications_{current_user_id}")
        
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
        
        was_unread = not notification.is_read
        db.session.delete(notification)
        db.session.commit()
        
        # Send WebSocket update if a notification was deleted
        if was_unread:
            send_unread_count(current_user_id)
        
        socketio.emit('notification_deleted', {
            'notification_id': notification_id,
            'unread_count': Notification.query.filter_by(
                user_id=current_user_id, 
                is_read=False
            ).count()
        }, room=f"notifications_{current_user_id}")
        
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
        
        # Send WebSocket update if any notifications were marked as read
        if updated_count > 0:
            send_unread_count(current_user_id)
            
            socketio.emit('all_notifications_read', {
                'marked_count': updated_count,
                'unread_count': 0
            }, room=f"notifications_{current_user_id}")
        
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
        
        # Also send via WebSocket for real-time updates
        send_unread_count(current_user_id)
        
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
        
        # Get notifications to check which were unread
        notifications = Notification.query.filter(
            Notification.id.in_(notification_ids),
            Notification.user_id == current_user_id
        ).all()
        
        unread_deleted = sum(1 for n in notifications if not n.is_read)
        
        # Delete notifications that belong to the user
        deleted_count = Notification.query.filter(
            Notification.id.in_(notification_ids),
            Notification.user_id == current_user_id
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        # Send WebSocket update if any unread notifications were deleted
        if unread_deleted > 0:
            send_unread_count(current_user_id)
        
        socketio.emit('notifications_bulk_deleted', {
            'deleted_count': deleted_count,
            'unread_deleted': unread_deleted,
            'unread_count': Notification.query.filter_by(
                user_id=current_user_id, 
                is_read=False
            ).count()
        }, room=f"notifications_{current_user_id}")
        
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
        
        # Send WebSocket update if any notifications were marked as read
        if updated_count > 0:
            send_unread_count(current_user_id)
            
            socketio.emit('notifications_bulk_read', {
                'updated_count': updated_count,
                'unread_count': Notification.query.filter_by(
                    user_id=current_user_id, 
                    is_read=False
                ).count()
            }, room=f"notifications_{current_user_id}")
        
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