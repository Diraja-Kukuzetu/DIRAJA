from flask import request, jsonify
from flask_restful import Resource
from app import db
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
            allowed_statuses = ['Pending', 'In Progress', 'Completed', 'Cancelled', 'Overdue']
            status = data.get("status", "Pending")
            if status not in allowed_statuses:
                return {
                    "error": f"Invalid status '{status}'. Allowed values are: {', '.join(allowed_statuses)}"
                }, 400

            # Validate category
            category = data.get("category", "General")
            
            # Parse due_date if provided
            due_date = None
            if data.get("due_date"):
                try:
                    due_date = datetime.datetime.strptime(data["due_date"], "%Y-%m-%d")
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            new_task = TaskManager(
                user_id=current_user_id,  # The logged-in user is the assigner
                assignee_id=data.get("assignee_id"),
                task=data.get("task"),
                priority=priority,
                category=category,
                assigned_date=datetime.datetime.utcnow(),
                due_date=due_date,
                status=status,
            )

            db.session.add(new_task)
            db.session.commit()

            # Send push notification to the assignee
            self.send_push_to_user(new_task.assignee_id, new_task.task, new_task.priority)
            
            # Send database notification to the assignee
            from Server.Views.Services.notifications_service import NotificationService
            
            # Create notification data with task details
            notification_data = {
                'task_id': new_task.task_id,
                'assignee_id': new_task.assignee_id,
                'priority': new_task.priority,
                'due_date': new_task.due_date.isoformat() if new_task.due_date else None,
                'category': new_task.category
            }
            
            NotificationService.create_notification(
                user_id=new_task.assignee_id,
                notification_type='task_assigned',
                title=f'New Task Assigned: {new_task.priority} Priority',
                message=f'Task: {new_task.task[:100]}{"..." if len(new_task.task) > 100 else ""}',
                data=notification_data
            )
            
            # Also notify the assigner that they created a task (optional)
            if current_user_id != new_task.assignee_id:
                NotificationService.create_notification(
                    user_id=current_user_id,
                    notification_type='task_created',
                    title='Task Created',
                    message=f'You assigned a task to user {new_task.assignee_id}: {new_task.task[:100]}',
                    data=notification_data
                )

            return {
                "message": "Task created successfully",
                "task": new_task.to_dict()
            }, 201

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    def send_push_to_user(self, user_id, task_name, priority):
        """Send push notification to all subscriptions for a user."""
        subscriptions = PushSubscription.query.filter_by(user_id=user_id).all()
        if not subscriptions:
            print(f"No push subscriptions found for user {user_id}")
            return

        vapid_private_key = current_app.config.get("VAPID_PRIVATE_KEY")
        vapid_email = current_app.config.get("VAPID_EMAIL")

        payload = {
            "title": f"New Task Assigned ({priority} Priority)",
            "body": f"{task_name}",
            "icon": "/logo192.png",
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
        # Get query parameters for filtering
        category = request.args.get('category')
        status = request.args.get('status')
        priority = request.args.get('priority')
        assignee_id = request.args.get('assignee_id')
        
        # Build query
        query = TaskManager.query.options(
            joinedload(TaskManager.assigner),
            joinedload(TaskManager.assignee),
        )
        
        # Apply filters
        if category:
            query = query.filter(TaskManager.category == category)
        if status:
            query = query.filter(TaskManager.status == status)
        if priority:
            query = query.filter(TaskManager.priority == priority)
        if assignee_id:
            query = query.filter(TaskManager.assignee_id == assignee_id)
        
        # Order by due date (newest first) and priority
        tasks = query.order_by(
            TaskManager.due_date.desc(),
            TaskManager.priority.desc()
        ).all()
        
        if not tasks:
            return {"message": "No tasks found"}, 404

        return {
            "tasks": [task.to_dict() for task in tasks],
            "total_count": len(tasks)
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
        
        # Build query
        query = TaskManager.query.options(
            joinedload(TaskManager.assigner),
            joinedload(TaskManager.assignee)
        ).filter(TaskManager.assignee_id == target_user_id)
        
        # Apply filters
        if status:
            query = query.filter(TaskManager.status == status)
        if category:
            query = query.filter(TaskManager.category == category)
        if priority:
            query = query.filter(TaskManager.priority == priority)
        
        # Order by due date and priority
        tasks = query.order_by(
            TaskManager.due_date.asc(),  # Soonest first for users
            TaskManager.priority.desc()
        ).all()
        
        if not tasks:
            return {"message": "No tasks found"}, 404

        return {
            "tasks": [task.to_dict() for task in tasks],
            "total_count": len(tasks)
        }, 200


class TaskResource(Resource):
    @jwt_required()
    def get(self, task_id):
        task = TaskManager.query.options(
            joinedload(TaskManager.assigner),
            joinedload(TaskManager.assignee),
            joinedload(TaskManager.comments).joinedload(TaskComment.user),
            joinedload(TaskManager.evaluation)
        ).get(task_id)
        
        if not task:
            return {"error": "Task not found"}, 404

        return task.to_dict(include_comments=True, include_evaluation=True)

    @jwt_required()
    def put(self, task_id):
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        current_user_id = get_jwt_identity()
        data = request.get_json()

        try:
            # Update task fields
            if data.get("task"):
                task.task = data["task"]
            if data.get("assignee_id"):
                task.assignee_id = data["assignee_id"]
            if data.get("status"):
                task.status = data["status"]
                # Auto-set closing date when status changes to "Completed"
                if data["status"] == "Completed" and not task.closing_date:
                    task.closing_date = datetime.datetime.utcnow()
            if data.get("priority"):
                task.priority = data["priority"]
            if data.get("category"):
                task.category = data["category"]
            if data.get("due_date"):
                # Handle both date-only and datetime formats
                due_date_str = data["due_date"]
                try:
                    task.due_date = datetime.datetime.strptime(due_date_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        task.due_date = datetime.datetime.strptime(due_date_str, "%Y-%m-%d")
                    except ValueError:
                        return {"error": "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"}, 400
            if data.get("estimated_hours"):
                task.estimated_hours = data["estimated_hours"]
            if data.get("actual_hours"):
                task.actual_hours = data["actual_hours"]
            if data.get("progress_percentage"):
                task.progress_percentage = data["progress_percentage"]
            if data.get("location"):
                task.location = data["location"]
            if data.get("department"):
                task.department = data["department"]

            # Update audit fields
            task.last_modified_by = current_user_id
            task.last_modified_date = datetime.datetime.utcnow()

            db.session.commit()

            return {
                "message": "Task updated successfully",
                "task": task.to_dict()
            }

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400

    @jwt_required()
    def delete(self, task_id):
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        try:
            db.session.delete(task)
            db.session.commit()
            return {"message": "Task deleted successfully"}
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

            # Return simple dict without using to_dict
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
            db.session.delete(comment)
            db.session.commit()
            return {"message": "Comment deleted successfully"}

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400


class TaskEvaluationResource(Resource):
    @jwt_required()
    def post(self, task_id):
        task = TaskManager.query.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        if task.status != "Completed":
            return {"error": "Can only evaluate completed tasks"}, 400

        current_user_id = get_jwt_identity()
        data = request.get_json()

        rating = data.get("rating")
        if rating and (rating < 1 or rating > 5):
            return {"error": "Rating must be between 1 and 5"}, 400

        if not data.get("comment"):
            return {"error": "Evaluation comment is required"}, 400

        try:
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

            return {
                "message": "Evaluation saved successfully",
                "evaluation": {
                    "evaluation_id": evaluation.evaluation_id,
                    "task_id": evaluation.task_id,
                    "evaluator_id": evaluation.evaluator_id,
                    "rating": evaluation.rating,
                    "comment": evaluation.comment,
                    "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None
                }
            }, 201 if is_new else 200

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

            # Return evaluation dictionary
            evaluation_dict = {
                "evaluation_id": evaluation.evaluation_id,
                "task_id": evaluation.task_id,
                "evaluator_id": evaluation.evaluator_id,
                "rating": evaluation.rating,
                "comment": evaluation.comment,
                "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None
            }
            
            # If evaluator is loaded, add their info
            if hasattr(evaluation, 'evaluator') and evaluation.evaluator:
                evaluation_dict['evaluator'] = {
                    'id': evaluation.evaluator.users_id,
                    'username': evaluation.evaluator.username,
                    'email': evaluation.evaluator.email
                }
            
            return {"evaluation": evaluation_dict}, 200
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"Error retrieving evaluation: {str(e)}"}, 500


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

            return {
                "message": "Task marked as complete successfully",
                "task": task.to_dict()
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 400