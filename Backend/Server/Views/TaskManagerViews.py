from flask import request, jsonify
from flask_restful import Resource
from app import db, socketio
import json
from Server.Models.TaskManager import TaskManager, TaskComment, TaskEvaluation
from Server.Models.PushSubscription import PushSubscription
from pywebpush import webpush, WebPushException
from Server.Models.Users import Users
from functools import wraps
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import make_response
import datetime
from flask import current_app
from sqlalchemy.orm import joinedload


def check_role(required_role):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                return make_response(jsonify({"error": "Unauthorized access"}), 403)
            return fn(*args, **kwargs)
        return decorator
    return wrapper


class CreateTask(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        try:
            # Validate required fields
            required_fields = ['task', 'priority', 'assignee_id']
            for field in required_fields:
                if field not in data or not data.get(field):
                    return {"error": f"Missing required field: {field}"}, 400

            # Validate priority
            allowed_priorities = ['High', 'Medium', 'Low']
            priority = data.get('priority')
            if priority not in allowed_priorities:
                return {
                    "error": f"Invalid priority '{priority}'. Allowed values are: {', '.join(allowed_priorities)}"
                }, 400

            # Validate status
            allowed_statuses = ['Pending', 'In Progress', 'Complete', 'Cancelled', 'Overdue']
            status = data.get("status", "Pending")
            if status not in allowed_statuses:
                return {
                    "error": f"Invalid status '{status}'. Allowed values are: {', '.join(allowed_statuses)}"
                }, 400

            # Validate category
            category = data.get("category", "General")
            
            
            # Parse due_date
            due_date = None
            if data.get("due_date"):
                due_date_str = data.get("due_date")  # Add this line to define due_date_str
                try:
                    due_date = datetime.datetime.strptime(due_date_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        due_date = datetime.datetime.strptime(due_date_str, "%Y-%m-%d")
                    except ValueError:
                        return {"error": f"Invalid date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"}, 400

            # Recurring task fields
            is_recurring = data.get('is_recurring', False)
            recurrence_pattern = data.get('recurrence_pattern')
            recurrence_interval = data.get('recurrence_interval', 1)
            recurrence_end_date_str = data.get('recurrence_end_date')
            max_recurrences = data.get('max_recurrences')
            
            # Validate recurring task settings
            if is_recurring:
                if not recurrence_pattern:
                    return {"error": "Recurrence pattern is required for recurring tasks"}, 400
                if recurrence_pattern not in ['daily', 'weekly', 'monthly', 'yearly']:
                    return {"error": "Invalid recurrence pattern"}, 400
                if recurrence_interval < 1:
                    return {"error": "Recurrence interval must be at least 1"}, 400
            
            # Parse recurrence end date
            recurrence_end_date = None
            if recurrence_end_date_str:
                try:
                    recurrence_end_date = datetime.datetime.strptime(recurrence_end_date_str, "%Y-%m-%d")
                except ValueError:
                    return {"error": "Invalid recurrence end date format. Use YYYY-MM-DD"}, 400

            # Get assigner info for notification
            assigner = Users.query.get(current_user_id)
            assigner_name = assigner.username if assigner else "Someone"

            new_task = TaskManager(
                user_id=current_user_id,
                assignee_id=data.get("assignee_id"),
                task=data.get("task"),
                priority=priority,
                category=category,
                assigned_date=datetime.datetime.utcnow(),
                due_date=due_date,
                status=status,
                closing_date=None,
                is_recurring=is_recurring,
                recurrence_pattern=recurrence_pattern if is_recurring else None,
                recurrence_interval=recurrence_interval if is_recurring else 1,
                recurrence_end_date=recurrence_end_date if is_recurring else None,
                max_recurrences=max_recurrences if is_recurring else None,
                last_recurrence_date=datetime.datetime.utcnow() if is_recurring else None
            )

            db.session.add(new_task)
            db.session.commit()

            # Prepare task data for notification
            task_notification_data = {
                "task_id": new_task.task_id,
                "task": new_task.task,
                "priority": new_task.priority,
                "assignee_id": new_task.assignee_id,
                "assignee_name": new_task.assignee.username if new_task.assignee else "Unknown",
                "assigned_by": assigner_name,
                "assigned_date": new_task.assigned_date.isoformat(),
                "due_date": str(new_task.due_date) if new_task.due_date else None,
                "category": new_task.category,
                "status": new_task.status
            }

            # 🔔 SEND WEBSOCKET NOTIFICATION TO ASSIGNEE (REAL-TIME)
            if new_task.assignee_id:
                socketio.emit('new_task_assigned', {
                    'type': 'task_assigned',
                    'title': f'🔔 New Task: {new_task.task}',
                    'message': f'{assigner_name} assigned you a {priority} priority task',
                    'task': task_notification_data,
                    'priority': priority,
                    'assigned_by': assigner_name,
                    'timestamp': datetime.datetime.utcnow().isoformat()
                }, room=f'user_{new_task.assignee_id}')
                
                print(f"📡 WebSocket notification sent to user {new_task.assignee_id}")
                
                # Send push notification as backup (for offline users)
                self.send_push_to_user(new_task.assignee_id, new_task.task, new_task.priority, assigner_name)

            # 🔔 NOTIFY MANAGERS FOR DASHBOARD UPDATE
            managers = Users.query.filter_by(role='manager').all()
            for manager in managers:
                if manager.user_id != current_user_id:  # Don't notify the creator if they're a manager
                    socketio.emit('new_task_created', {
                        'type': 'task_created',
                        'title': f'📋 New Task Created',
                        'message': f'{assigner_name} created a new task for {new_task.assignee.username if new_task.assignee else "someone"}',
                        'task': task_notification_data,
                        'created_by': assigner_name,
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }, room=f'user_{manager.user_id}')

            return {
                "message": "Task created successfully",
                "task": new_task.to_dict(include_recurrence_info=True)
            }, 201

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    def send_push_to_user(self, user_id, task_name, priority, assigner_name):
        """Send push notification to all subscriptions for a user."""
        subscriptions = PushSubscription.query.filter_by(user_id=user_id).all()
        if not subscriptions:
            print(f"No push subscriptions found for user {user_id}")
            return

        vapid_private_key = current_app.config.get("VAPID_PRIVATE_KEY")
        vapid_email = current_app.config.get("VAPID_EMAIL")

        payload = {
            "title": f"New Task Assigned ({priority} Priority)",
            "body": f"{assigner_name} assigned: {task_name}",
            "icon": "/logo192.png",
            "badge": "/badge.png",
            "data": {
                "type": "task_assigned"
            }
        }

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh,
                            "auth": sub.auth,
                        },
                    },
                    data=json.dumps(payload),
                    vapid_private_key=vapid_private_key,
                    vapid_claims={"sub": vapid_email},
                )
                print(f"Push sent to user {user_id} subscriber {sub.id}")
            except WebPushException as e:
                print(f"Push failed for {sub.id}: {repr(e)}")


class GetTasks(Resource):
    @jwt_required()
    def get(self):
        category = request.args.get('category')
        status = request.args.get('status')
        priority = request.args.get('priority')
        assignee_id = request.args.get('assignee_id')
 
        query = TaskManager.query.options(
            joinedload(TaskManager.assigner),
            joinedload(TaskManager.assignee),
        )
 
        if category:
            query = query.filter(TaskManager.category == category)
        if status:
            query = query.filter(TaskManager.status == status)
        if priority:
            query = query.filter(TaskManager.priority == priority)
        if assignee_id:
            query = query.filter(TaskManager.assignee_id == assignee_id)
 
        tasks = query.order_by(
            TaskManager.due_date.desc(),
            TaskManager.priority.desc()
        ).all()
 
        if not tasks:
            return {"message": "No tasks found"}, 404
 
        return {
            "tasks": [task.to_dict(include_recurrence_info=True) for task in tasks],
            "total_count": len(tasks),
        }, 200


class GetUserTasks(Resource):
    @jwt_required()
    def get(self, user_id=None):
        current_user_id = get_jwt_identity()
        
        # If no user_id provided, use current user
        target_user_id = user_id if user_id else current_user_id
        
        # Get query parameters
        status = request.args.get('status')
        category = request.args.get('category')
        priority = request.args.get('priority')
        include_recurring = request.args.get('include_recurring', 'true').lower() == 'true'
        
        # Build query
        query = TaskManager.query.options(
            joinedload(TaskManager.assigner),
            joinedload(TaskManager.assignee)
        ).filter(TaskManager.assignee_id == target_user_id)
        
        # Filter out parent recurring tasks if needed
        if not include_recurring:
            query = query.filter(TaskManager.parent_task_id.is_(None))
        
        # Apply filters
        if status:
            query = query.filter(TaskManager.status == status)
        if category:
            query = query.filter(TaskManager.category == category)
        if priority:
            query = query.filter(TaskManager.priority == priority)
        
        # Order by due date (soonest first) and priority
        tasks = query.order_by(
            TaskManager.due_date.asc(),
            TaskManager.priority.desc()
        ).all()
        
        if not tasks:
            return {"message": "No tasks found"}, 404

        return {
            "tasks": [task.to_dict(include_recurrence_info=True) for task in tasks],
            "total_count": len(tasks)
        }, 200


class TaskResource(Resource):
    @jwt_required()
    def get(self, task_id):
        task = TaskManager.query.options(
            joinedload(TaskManager.assigner),
            joinedload(TaskManager.assignee),
            joinedload(TaskManager.comments).joinedload(TaskComment.user),
            joinedload(TaskManager.evaluation),
            joinedload(TaskManager.child_tasks)
        ).get(task_id)
        
        if not task:
            return {"error": "Task not found"}, 404

        return jsonify(task.to_dict(include_comments=True, include_evaluation=True, include_recurrence_info=True))
        return task.to_dict(include_comments=True, include_evaluation=True)

    @jwt_required()
    def put(self, task_id):
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        # Store old values for notifications
        old_status = task.status
        old_assignee_id = task.assignee_id

        try:
            # Update task fields
            if data.get("task"):
                task.task = data["task"]
            if data.get("assignee_id"):
                task.assignee_id = data["assignee_id"]
            if data.get("status"):
                task.status = data["status"]
                # Auto-set closing date when status changes to "Complete"
                if data["status"] == "Complete" and not task.closing_date:
                    task.complete_task()
            if data.get("priority"):
                task.priority = data["priority"]
            if data.get("category"):
                task.category = data["category"]
            if data.get("due_date"):
                due_date_str = data["due_date"]
                try:
                    task.due_date = datetime.datetime.strptime(due_date_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        task.due_date = datetime.datetime.strptime(due_date_str, "%Y-%m-%d")
                    except ValueError:
                        return {"error": "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"}, 400
            
            # Update recurring task settings
            if data.get("is_recurring") is not None:
                task.is_recurring = data["is_recurring"]
            if data.get("recurrence_pattern"):
                task.recurrence_pattern = data["recurrence_pattern"]
            if data.get("recurrence_interval"):
                task.recurrence_interval = data["recurrence_interval"]
            if data.get("recurrence_end_date"):
                try:
                    task.recurrence_end_date = datetime.datetime.strptime(data["recurrence_end_date"], "%Y-%m-%d")
                except ValueError:
                    return {"error": "Invalid recurrence end date format. Use YYYY-MM-DD"}, 400
            if data.get("max_recurrences"):
                task.max_recurrences = data["max_recurrences"]

            db.session.commit()

            # 🔔 SEND WEBSOCKET NOTIFICATIONS FOR CHANGES
            updater = Users.query.get(current_user_id)
            updater_name = updater.username if updater else "Someone"

            # Notify about status change
            if data.get("status") and old_status != task.status:
                if task.assignee_id:
                    socketio.emit('task_status_changed', {
                        'type': 'status_change',
                        'title': f'📊 Task Status Updated: {task.task}',
                        'message': f'Task status changed from {old_status} to {task.status} by {updater_name}',
                        'task_id': task.task_id,
                        'task_title': task.task,
                        'old_status': old_status,
                        'new_status': task.status,
                        'updated_by': updater_name,
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }, room=f'user_{task.assignee_id}')
                    
                    print(f"📡 Status change notification sent to user {task.assignee_id}")

            # Notify about assignee change
            if data.get("assignee_id") and old_assignee_id != task.assignee_id:
                # Notify new assignee
                if task.assignee_id:
                    socketio.emit('task_reassigned', {
                        'type': 'task_reassigned',
                        'title': f'🔄 Task Reassigned: {task.task}',
                        'message': f'Task has been reassigned to you by {updater_name}',
                        'task_id': task.task_id,
                        'task_title': task.task,
                        'priority': task.priority,
                        'due_date': str(task.due_date) if task.due_date else None,
                        'reassigned_by': updater_name,
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }, room=f'user_{task.assignee_id}')
                    
                    print(f"📡 Task reassigned notification sent to user {task.assignee_id}")

                # Notify old assignee (if different from new)
                if old_assignee_id and old_assignee_id != task.assignee_id:
                    socketio.emit('task_unassigned', {
                        'type': 'task_unassigned',
                        'title': f'📤 Task Removed: {task.task}',
                        'message': f'Task has been reassigned from you to someone else',
                        'task_id': task.task_id,
                        'task_title': task.task,
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }, room=f'user_{old_assignee_id}')

            return {
                "message": "Task updated successfully",
                "task": task.to_dict(include_recurrence_info=True)
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    @jwt_required()
    def delete(self, task_id):
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        try:
            # Store task info for notification
            task_title = task.task
            task_assignee_id = task.assignee_id
            
            # If this is a recurring task, also delete child tasks
            if task.is_recurring and task.child_tasks:
                for child in task.child_tasks:
                    db.session.delete(child)
            
            db.session.delete(task)
            db.session.commit()
            
            # 🔔 Notify assignee about task deletion
            if task_assignee_id:
                socketio.emit('task_deleted', {
                    'type': 'task_deleted',
                    'title': f'🗑️ Task Deleted: {task_title}',
                    'message': f'The task "{task_title}" has been deleted',
                    'task_id': task_id,
                    'timestamp': datetime.datetime.utcnow().isoformat()
                }, room=f'user_{task_assignee_id}')
            
            return jsonify({"message": "Task and its recurring instances deleted successfully"})
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class TaskCommentResource(Resource):
    @jwt_required()
    def post(self, task_id):
        """Add a comment to a task"""
        try:
            task = TaskManager.query.get(task_id)
            if not task:
                return {"error": "Task not found"}, 404

            current_user_id = get_jwt_identity()
            data = request.get_json()

            if not data or not data.get("comment"):
                return {"error": "Comment text is required"}, 400

            comment = TaskComment(
                task_id=task_id,
                user_id=current_user_id,
                comment=data["comment"].strip(),
                parent_comment_id=data.get("parent_comment_id")
            )

            db.session.add(comment)
            db.session.commit()

            # Get user info
            user = Users.query.get(current_user_id)
            username = user.username if user else "Unknown"

            # Prepare comment data for notification
            comment_data = {
                "comment_id": comment.comment_id,
                "task_id": task_id,
                "task_title": task.task,
                "user_id": current_user_id,
                "username": username,
                "comment": comment.comment,
                "created_at": comment.created_at.isoformat() if comment.created_at else None,
                "parent_comment_id": comment.parent_comment_id,
                "is_reply": comment.parent_comment_id is not None
            }

            # 🔔 SEND WEBSOCKET NOTIFICATION TO TASK ASSIGNEE (if not the commenter)
            if task.assignee_id and task.assignee_id != current_user_id:
                socketio.emit('new_comment_on_task', {
                    'type': 'new_comment',
                    'title': f'💬 New Comment on: {task.task}',
                    'message': f'{username} commented: {comment.comment[:100]}...',
                    'comment': comment_data,
                    'timestamp': datetime.datetime.utcnow().isoformat()
                }, room=f'user_{task.assignee_id}')
                
                print(f"📡 Comment notification sent to assignee {task.assignee_id}")

            # 🔔 NOTIFY THE USER WHO WAS MENTIONED IN COMMENT (if any)
            # Check for @mentions in comment
            import re
            mentions = re.findall(r'@(\w+)', comment.comment)
            for mentioned_username in mentions:
                mentioned_user = Users.query.filter_by(username=mentioned_username).first()
                if mentioned_user and mentioned_user.user_id != current_user_id and mentioned_user.user_id != task.assignee_id:
                    socketio.emit('user_mentioned', {
                        'type': 'user_mentioned',
                        'title': f'📢 You were mentioned in a comment',
                        'message': f'{username} mentioned you in a comment on task "{task.task}": {comment.comment[:100]}...',
                        'comment': comment_data,
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }, room=f'user_{mentioned_user.user_id}')
                    
                    print(f"📡 Mention notification sent to {mentioned_username}")

            # 🔔 NOTIFY EVERYONE IN THE TASK ROOM (for real-time collaboration)
            socketio.emit('task_comment_added', {
                'type': 'comment_added',
                'comment': comment_data,
                'timestamp': datetime.datetime.utcnow().isoformat()
            }, room=f'task_{task_id}')

            return {
                "message": "Comment added successfully",
                "comment": {
                    "comment_id": comment.comment_id,
                    "task_id": comment.task_id,
                    "user_id": comment.user_id,
                    "username": username,
                    "comment": comment.comment,
                    "created_at": comment.created_at.isoformat() if comment.created_at else None,
                    "parent_comment_id": comment.parent_comment_id,
                    "is_reply": comment.parent_comment_id is not None,
                    "reply_count": 0
                }
            }, 201

        except Exception as e:
            db.session.rollback()
            print(f"Error adding comment: {str(e)}")
            return {"error": "Failed to add comment. Please try again."}, 400

    @jwt_required()
    def get(self, task_id):
        """Get all comments for a task"""
        try:
            comments = TaskComment.query.filter_by(task_id=task_id).order_by(
                TaskComment.created_at.desc()
            ).all()

            # Simple serialization without complex relationships
            comments_data = []
            for comment in comments:
                user = Users.query.get(comment.user_id)
                comments_data.append({
                    "comment_id": comment.comment_id,
                    "task_id": comment.task_id,
                    "user_id": comment.user_id,
                    "username": user.username if user else "Unknown",
                    "comment": comment.comment,
                    "created_at": comment.created_at.isoformat() if comment.created_at else None,
                    "parent_comment_id": comment.parent_comment_id,
                    "is_reply": comment.parent_comment_id is not None,
                })

            return {
                "comments": comments_data,
                "total_count": len(comments_data)
            }, 200

        except Exception as e:
            print(f"Error fetching comments: {str(e)}")
            return {"error": "Failed to fetch comments"}, 400


class CommentResource(Resource):
    @jwt_required()
    def put(self, comment_id):
        """Update a comment"""
        comment = TaskComment.query.get(comment_id)
        if not comment:
            return {"error": "Comment not found"}, 404

        current_user_id = get_jwt_identity()
        
        # Check if user owns the comment
        if comment.user_id != current_user_id:
            return {"error": "You can only edit your own comments"}, 403

        data = request.get_json()
        
        if not data.get("comment"):
            return {"error": "Comment text is required"}, 400

        try:
            old_comment = comment.comment
            comment.comment = data["comment"]
            db.session.commit()

            return {
                "message": "Comment updated successfully",
                "comment": {
                    "comment_id": comment.comment_id,
                    "task_id": comment.task_id,
                    "user_id": comment.user_id,
                    "comment": comment.comment,
                    "created_at": comment.created_at.isoformat() if comment.created_at else None,
                    "parent_comment_id": comment.parent_comment_id
                }
            }

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    @jwt_required()
    def delete(self, comment_id):
        """Delete a comment"""
        comment = TaskComment.query.get(comment_id)
        if not comment:
            return {"error": "Comment not found"}, 404

        current_user_id = get_jwt_identity()
        
        # Check if user owns the comment or is manager
        user = Users.query.get(current_user_id)
        if comment.user_id != current_user_id and user.role != 'manager':
            return {"error": "You don't have permission to delete this comment"}, 403

        try:
            # Store task info for notification
            task = TaskManager.query.get(comment.task_id)
            
            db.session.delete(comment)
            db.session.commit()
            return {"message": "Comment deleted successfully"}

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class TaskEvaluationResource(Resource):
    @jwt_required()
    def post(self, task_id):
        """Add or update evaluation for a completed task"""
        try:
            task = TaskManager.query.get(task_id)
            if not task:
                return {"error": "Task not found"}, 404

            # Check if task is completed
            if task.status != "Complete":
                return {"error": "Can only evaluate completed tasks"}, 400

            current_user_id = get_jwt_identity()
            data = request.get_json()

            # Validate rating if provided
            rating = data.get("rating")
            if rating and (rating < 1 or rating > 5):
                return {"error": "Rating must be between 1 and 5"}, 400

            if not data.get("comment"):
                return {"error": "Evaluation comment is required"}, 400

            # Check if evaluation already exists
            evaluation = TaskEvaluation.query.filter_by(task_id=task_id).first()
            is_new = False

            if evaluation:
                evaluation.rating = rating
                evaluation.comment = data["comment"]
                evaluation.evaluator_id = current_user_id
            else:
                evaluation = TaskEvaluation(
                    task_id=task_id,
                    evaluator_id=current_user_id,
                    rating=rating,
                    comment=data["comment"]
                )
                db.session.add(evaluation)
                is_new = True

            db.session.commit()

            # 🔔 Notify task assignee about evaluation
            evaluator = Users.query.get(current_user_id)
            if task.assignee_id and task.assignee_id != current_user_id:
                socketio.emit('task_evaluated', {
                    'type': 'task_evaluated',
                    'title': f'⭐ Task Evaluated: {task.task}',
                    'message': f'{evaluator.username if evaluator else "Someone"} evaluated your task',
                    'task_id': task_id,
                    'task_title': task.task,
                    'rating': rating,
                    'evaluator': evaluator.username if evaluator else "Unknown",
                    'timestamp': datetime.datetime.utcnow().isoformat()
                }, room=f'user_{task.assignee_id}')
                
                print(f"📡 Evaluation notification sent to assignee {task.assignee_id}")

            return {
                "message": message,
                "evaluation": evaluation.to_dict()
            }, 201 if not evaluation else 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    @jwt_required()
    def get(self, task_id):
        """Get evaluation for a task"""
        try:
            task = TaskManager.query.get(task_id)
            if not task:
                return {"error": "Task not found"}, 404

            evaluation = TaskEvaluation.query.options(
                joinedload(TaskEvaluation.evaluator)
            ).filter_by(task_id=task_id).first()

            if not evaluation:
                return {"message": "No evaluation found for this task"}, 404

            return evaluation.to_dict(), 200

        except Exception as e:
            return {"error": str(e)}, 400


class TaskProgressResource(Resource):
    @jwt_required()
    def put(self, task_id):
        """Update task progress"""
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        current_user_id = get_jwt_identity()
        data = request.get_json()

        # Check if user is assignee or manager
        user = Users.query.get(current_user_id)
        if task.assignee_id != current_user_id and user.role != 'manager':
            return {"error": "Only assignee or manager can update progress"}, 403

        try:
            old_progress = task.progress_percentage
            old_status = task.status
            
            if data.get("progress_percentage") is not None:
                progress = data["progress_percentage"]
                if progress < 0 or progress > 100:
                    return {"error": "Progress must be between 0 and 100"}, 400
                task.progress_percentage = progress

            if data.get("actual_hours"):
                task.actual_hours = data["actual_hours"]

            # Auto-update status based on progress
            if task.progress_percentage == 100:
                task.status = "Completed"
                task.closing_date = datetime.datetime.utcnow()
            elif task.progress_percentage > 0 and task.status == "Pending":
                task.status = "In Progress"

            task.last_modified_by = current_user_id
            task.last_modified_date = datetime.datetime.utcnow()

            db.session.commit()

            return {
                "message": "Progress updated successfully",
                "task": task.to_dict()
            }

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class TaskStatsResource(Resource):
    @jwt_required()
    def get(self):
        """Get task statistics"""
        current_user_id = get_jwt_identity()
        user = Users.query.get(current_user_id)

        # Base query
        if user.role == 'manager':
            # Managers see all tasks
            query = TaskManager.query
        else:
            # Regular users see only their tasks
            query = TaskManager.query.filter_by(assignee_id=current_user_id)

        # Get statistics
        total_tasks = query.count()
        
        stats = {
            "total_tasks": total_tasks,
            "by_status": {
                "pending": query.filter_by(status="Pending").count(),
                "in_progress": query.filter_by(status="In Progress").count(),
                "completed": query.filter_by(status="Completed").count(),
                "cancelled": query.filter_by(status="Cancelled").count()
            },
            "by_priority": {
                "high": query.filter_by(priority="High").count(),
                "medium": query.filter_by(priority="Medium").count(),
                "low": query.filter_by(priority="Low").count()
            },
            "by_category": {}
        }

        # Get category counts
        categories = ["General", "Delivery", "Cleaning", "Maintenance", "Office Work", "Field Work", "Other"]
        for category in categories:
            stats["by_category"][category.lower()] = query.filter_by(category=category).count()

        # Overdue tasks (tasks past due date not completed)
        overdue_count = query.filter(
            TaskManager.due_date < datetime.datetime.utcnow(),
            TaskManager.status.notin_(["Completed", "Cancelled"])
        ).count()
        stats["by_status"]["overdue"] = overdue_count

        return stats, 200


class CompleteTask(Resource):
    @jwt_required()
    def put(self, task_id):
        """Mark a task as complete"""
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        current_user_id = get_jwt_identity()

        # Check if user is assignee or manager
        user = Users.query.get(current_user_id)
        if task.assignee_id != current_user_id and user.role != 'manager':
            return {"error": "Only assignee or manager can complete tasks"}, 403

        # Check if task is already completed
        if task.status == "Completed":
            return {"message": "Task is already completed"}, 400

        try:
            # Update task
            task.status = "Completed"
            task.closing_date = datetime.datetime.utcnow()
            task.progress_percentage = 100
            task.last_modified_by = current_user_id
            task.last_modified_date = datetime.datetime.utcnow()
            
            db.session.commit()

            # 🔔 Notify manager about task completion
            completer = Users.query.get(current_user_id)
            managers = Users.query.filter_by(role='manager').all()
            for manager in managers:
                if manager.user_id != current_user_id:
                    socketio.emit('task_completed', {
                        'type': 'task_completed',
                        'title': f'✅ Task Completed: {task.task}',
                        'message': f'{completer.username if completer else "Someone"} completed the task',
                        'task_id': task_id,
                        'task_title': task.task,
                        'completed_by': completer.username if completer else "Unknown",
                        'assignee': task.assignee.username if task.assignee else "Unknown",
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }, room=f'user_{manager.user_id}')

            return {
                "message": "Task marked as complete successfully",
                "task": task.to_dict()
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class CancelRecurringTask(Resource):
    @jwt_required()
    def post(self, task_id):
        """Cancel a recurring task and prevent future regenerations"""
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        current_user_id = get_jwt_identity()
        user = Users.query.get(current_user_id)

        # Check if user is assignee or manager
        if task.assignee_id != current_user_id and user.role != 'manager':
            return {"error": "Only assignee or manager can cancel recurring tasks"}, 403

        if not task.is_recurring:
            return {"error": "Task is not recurring"}, 400

        try:
            task.cancel_recurring_task()
            db.session.commit()

            # 🔔 Notify assignee about cancellation
            if task.assignee_id:
                canceller = Users.query.get(current_user_id)
                socketio.emit('recurring_task_cancelled', {
                    'type': 'recurring_cancelled',
                    'title': f'🔄 Recurring Task Cancelled: {task.task}',
                    'message': f'{canceller.username if canceller else "Someone"} cancelled this recurring task',
                    'task_id': task_id,
                    'task_title': task.task,
                    'cancelled_by': canceller.username if canceller else "Unknown",
                    'timestamp': datetime.datetime.utcnow().isoformat()
                }, room=f'user_{task.assignee_id}')

            return {
                "message": "Recurring task cancelled successfully",
                "task": task.to_dict(include_recurrence_info=True)
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class ProcessRecurringTasks(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        """Manually trigger processing of recurring tasks that need regeneration"""
        try:
            from Server.Models.TaskManager import process_recurring_tasks
            count = process_recurring_tasks()
            
            # 🔔 Notify managers about processed recurring tasks
            if count > 0:
                managers = Users.query.filter_by(role='manager').all()
                for manager in managers:
                    socketio.emit('recurring_tasks_processed', {
                        'type': 'recurring_processed',
                        'title': f'🔄 Recurring Tasks Processed',
                        'message': f'{count} recurring task(s) were regenerated',
                        'count': count,
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }, room=f'user_{manager.user_id}')
            
            return {
                "message": f"Processed {count} recurring tasks",
                "tasks_regenerated": count
            }, 200
        except Exception as e:
            return {"error": str(e)}, 500


class UserTasksSimpleOverview(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        """
        Simple overview - returns counts of pending tasks and tasks with comments for each user
        """
        try:
            from sqlalchemy import func
            
            # Get all users
            users = Users.query.all()
            
            result = []
            
            for user in users:
                # Count pending tasks
                pending_count = TaskManager.query.filter(
                    TaskManager.assignee_id == user.user_id,
                    TaskManager.status.in_(['Pending', 'In Progress', 'Overdue'])
                ).count()
                
                # Count tasks with comments
                tasks_with_comments_count = TaskManager.query.filter(
                    TaskManager.assignee_id == user.user_id,
                    TaskManager.comments.any()
                ).count()
                
                # Count overdue tasks
                current_time = datetime.datetime.utcnow()
                overdue_count = TaskManager.query.filter(
                    TaskManager.assignee_id == user.user_id,
                    TaskManager.status.in_(['Pending', 'In Progress']),
                    TaskManager.due_date < current_time
                ).count()
                
                # Get tasks with new comments (comments not made by the assignee)
                tasks_with_new_comments = db.session.query(TaskComment.task_id).filter(
                    TaskComment.user_id != user.user_id,
                    TaskManager.assignee_id == user.user_id,
                    TaskManager.task_id == TaskComment.task_id
                ).distinct().count()
                
                result.append({
                    "user_id": user.user_id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "pending_tasks_count": pending_count,
                    "overdue_tasks_count": overdue_count,
                    "tasks_with_comments_count": tasks_with_comments_count,
                    "tasks_with_new_comments_count": tasks_with_new_comments,
                    "has_pending_tasks": pending_count > 0,
                    "has_comments_on_tasks": tasks_with_comments_count > 0
                })
            
            # Filter to only users with pending tasks or comments
            result = [r for r in result if r["has_pending_tasks"] or r["has_comments_on_tasks"]]
            
            # Sort by pending tasks count
            result.sort(key=lambda x: x["pending_tasks_count"], reverse=True)
            
            return {
                "users": result,
                "total_users_with_pending": len([r for r in result if r["has_pending_tasks"]]),
                "total_users_with_comments": len([r for r in result if r["has_comments_on_tasks"]]),
                "total_pending_tasks": sum(r["pending_tasks_count"] for r in result),
                "total_overdue_tasks": sum(r["overdue_tasks_count"] for r in result)
            }, 200
            
        except Exception as e:
            print(f"Error in UserTasksSimpleOverview: {str(e)}")
            return {"error": str(e)}, 500


class UserTasksOverview(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        """
        Get overview of all users' pending tasks and tasks with comments.
        Returns a summary for each user including:
        - Pending tasks count and details
        - Tasks with recent comments
        - Overdue tasks
        """
        try:
            # Get all users (or filter by role if needed)
            users = Users.query.all()
            
            result = []
            
            for user in users:
                # Get pending and in-progress tasks for this user
                pending_tasks = TaskManager.query.filter(
                    TaskManager.assignee_id == user.user_id,
                    TaskManager.status.in_(['Pending', 'In Progress', 'Overdue'])
                ).options(
                    joinedload(TaskManager.assigner),
                    joinedload(TaskManager.comments)
                ).order_by(
                    TaskManager.due_date.asc(),
                    TaskManager.priority.desc()
                ).all()
                
                # Get tasks with comments (all tasks that have at least one comment)
                tasks_with_comments = TaskManager.query.filter(
                    TaskManager.assignee_id == user.user_id,
                    TaskManager.comments.any()  # Tasks that have at least one comment
                ).options(
                    joinedload(TaskManager.comments)
                ).all()
                
                # Separate overdue tasks
                current_time = datetime.datetime.utcnow()
                overdue_tasks = [
                    task for task in pending_tasks 
                    if task.due_date and task.due_date < current_time and task.status != 'Complete'
                ]
                
                # Get tasks with unread comments (comments made by others after last user view)
                tasks_with_new_comments = []
                for task in tasks_with_comments:
                    if task.comments:
                        # Get comments not made by the assignee
                        other_comments = [
                            comment for comment in task.comments 
                            if comment.user_id != user.user_id
                        ]
                        if other_comments:
                            # Check if there are comments after last viewed time
                            if hasattr(task, 'last_viewed_at') and task.last_viewed_at:
                                new_comments = [
                                    comment for comment in other_comments
                                    if comment.created_at > task.last_viewed_at
                                ]
                                if new_comments:
                                    tasks_with_new_comments.append({
                                        "task": task.to_dict(include_recurrence_info=True),
                                        "new_comments_count": len(new_comments),
                                        "new_comments": [comment.to_dict() for comment in new_comments]
                                    })
                            else:
                                # Never viewed or no last_viewed_at field, all comments are new
                                tasks_with_new_comments.append({
                                    "task": task.to_dict(include_recurrence_info=True),
                                    "new_comments_count": len(other_comments),
                                    "new_comments": [comment.to_dict() for comment in other_comments]
                                })
                
                # Prepare user data
                user_data = {
                    "user_id": user.user_id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "summary": {
                        "total_pending_tasks": len(pending_tasks),
                        "overdue_tasks_count": len(overdue_tasks),
                        "tasks_with_comments_count": len(tasks_with_comments),
                        "tasks_with_new_comments_count": len(tasks_with_new_comments)
                    },
                    "pending_tasks": [
                        {
                            "task_id": task.task_id,
                            "task": task.task,
                            "priority": task.priority,
                            "status": task.status,
                            "due_date": str(task.due_date) if task.due_date else None,
                            "is_overdue": task.due_date and task.due_date < current_time if task.due_date else False,
                            "progress_percentage": task.progress_percentage,
                            "assigned_by": task.assigner.username if task.assigner else "Unknown",
                            "comments_count": len(task.comments) if task.comments else 0
                        }
                        for task in pending_tasks
                    ],
                    "tasks_with_comments": [
                        {
                            "task_id": task.task_id,
                            "task": task.task,
                            "priority": task.priority,
                            "status": task.status,
                            "due_date": str(task.due_date) if task.due_date else None,
                            "comments_count": len(task.comments),
                            "latest_comment": {
                                "comment": task.comments[-1].comment if task.comments else None,
                                "created_at": str(task.comments[-1].created_at) if task.comments else None,
                                "commenter": task.comments[-1].user.username if task.comments and task.comments[-1].user else None
                            } if task.comments else None
                        }
                        for task in tasks_with_comments
                    ],
                    "overdue_tasks": [
                        {
                            "task_id": task.task_id,
                            "task": task.task,
                            "priority": task.priority,
                            "due_date": str(task.due_date),
                            "days_overdue": (current_time - task.due_date).days if task.due_date else 0
                        }
                        for task in overdue_tasks
                    ]
                }
                
                # Only include users who have pending tasks or tasks with comments
                if user_data["summary"]["total_pending_tasks"] > 0 or user_data["summary"]["tasks_with_comments_count"] > 0:
                    result.append(user_data)
            
            # Sort by total pending tasks (highest first)
            result.sort(key=lambda x: x["summary"]["total_pending_tasks"], reverse=True)
            
            return {
                "users_overview": result,
                "summary": {
                    "total_users_with_pending_tasks": len([u for u in result if u["summary"]["total_pending_tasks"] > 0]),
                    "total_users_with_comments": len([u for u in result if u["summary"]["tasks_with_comments_count"] > 0]),
                    "total_pending_tasks_across_all_users": sum(u["summary"]["total_pending_tasks"] for u in result),
                    "total_overdue_tasks_across_all_users": sum(u["summary"]["overdue_tasks_count"] for u in result)
                }
            }, 200
            
        except Exception as e:
            print(f"Error in UserTasksOverview: {str(e)}")
            return {"error": str(e)}, 500