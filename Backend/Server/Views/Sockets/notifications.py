from flask_socketio import emit, join_room
from flask_jwt_extended import decode_token
from app import socketio
from Server.Models.Notification import Notification

@socketio.on('connect')
def handle_connect(auth):
    token = auth.get('token')
    decoded = decode_token(token)
    user_id = decoded['sub']
    
    join_room(f"user_{user_id}")


def send_unread_count(user_id):
    count = Notification.query.filter_by(
        user_id=user_id,
        is_read=False
    ).count()

    socketio.emit(
        'unread_count',
        {'unread_count': count},
        room=f"user_{user_id}"
    )