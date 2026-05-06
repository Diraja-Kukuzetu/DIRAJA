from flask_socketio import emit, join_room, leave_room
from flask_jwt_extended import decode_token
from flask import request, current_app
from Server.Models.Users import Users
from functools import wraps
import jwt

def register_task_socket_handlers(socketio):
    
    @socketio.on('connect')
    def handle_connect():
        """Authenticate user on WebSocket connection"""
        token = request.args.get('token')
        if not token:
            # Try to get from headers
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if token:
            try:
                # Decode JWT token
                decoded = decode_token(token)
                user_id = decoded['sub']
                
                # Get user from database
                user = Users.query.get(user_id)
                
                if user:
                    # Store user info in socket session
                    from flask import session as flask_session
                    flask_session['user_id'] = user.user_id
                    flask_session['username'] = user.username
                    flask_session['role'] = user.role
                    
                    # Join user-specific room for targeted messages
                    join_room(f'user_{user.user_id}')
                    
                    emit('connected', {
                        'status': 'connected',
                        'user_id': user.user_id,
                        'username': user.username,
                        'role': user.role,
                        'message': f'Connected as {user.username}'
                    })
                    
                    print(f"✅ WebSocket connected: {user.username} (ID: {user.user_id})")
                    return True
                    
            except Exception as e:
                print(f"❌ WebSocket connection error: {e}")
                return False
        
        print("❌ WebSocket connection rejected: No valid token")
        return False
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle user disconnection"""
        from flask import session as flask_session
        user_id = flask_session.get('user_id')
        username = flask_session.get('username', 'Unknown')
        
        if user_id:
            leave_room(f'user_{user_id}')
            print(f"🔌 WebSocket disconnected: {username} (ID: {user_id})")
    
    @socketio.on('join_task_room')
    def handle_join_task_room(data):
        """Join a specific task's room for real-time updates"""
        task_id = data.get('task_id')
        from flask import session as flask_session
        
        if task_id and flask_session.get('user_id'):
            room_name = f'task_{task_id}'
            join_room(room_name)
            emit('joined_task_room', {
                'task_id': task_id,
                'message': f'Joined task {task_id} room'
            }, room=room_name)
            print(f"User {flask_session.get('username')} joined task room {task_id}")
    
    @socketio.on('leave_task_room')
    def handle_leave_task_room(data):
        """Leave a task's room"""
        task_id = data.get('task_id')
        if task_id:
            leave_room(f'task_{task_id}')
            print(f"User left task room {task_id}")
    
    @socketio.on('ping')
    def handle_ping():
        """Health check"""
        emit('pong', {'status': 'alive'})