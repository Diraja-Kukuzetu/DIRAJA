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

            # Send push notification to the assignee
            if new_task.assignee_id:
                self.send_push_to_user(new_task.assignee_id, new_task.task, new_task.priority)

            return {
                "message": "Task created successfully",
                "task": new_task.to_dict(include_recurrence_info=True)
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
        category    = request.args.get('category')
        status      = request.args.get('status')
        priority    = request.args.get('priority')
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
            "tasks": [task.to_dict(include_recurrence_info=True) for task in tasks],  # ← changed
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

        try:
            # Update task fields
            if data.get("task"):
                task.task = data["task"]
            if data.get("assignee_id"):
                task.assignee_id = data["assignee_id"]
            if data.get("status"):
                old_status = task.status
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
            # If this is a recurring task, also delete child tasks
            if task.is_recurring and task.child_tasks:
                for child in task.child_tasks:
                    db.session.delete(child)
            
            db.session.delete(task)
            db.session.commit()
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

            return {
                "message": "Evaluation saved successfully",
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
            return jsonify({"error": "Task not found"}), 404

        return jsonify(task.to_dict(include_comments=True, include_evaluation=True, include_recurrence_info=True))

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
                old_status = task.status
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
            return jsonify({"error": "Task not found"}), 404

        try:
            # If this is a recurring task, also delete child tasks
            if task.is_recurring and task.child_tasks:
                for child in task.child_tasks:
                    db.session.delete(child)
            
            db.session.delete(task)
            db.session.commit()
            return jsonify({"message": "Task and its recurring instances deleted successfully"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400


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
            return {
                "message": f"Processed {count} recurring tasks",
                "tasks_regenerated": count
            }, 200
        except Exception as e:
            return {"error": str(e)}, 500


    

# Add to_dict methods to your models (add these to your model files)

"""
Add this to TaskManager model:

def to_dict(self, include_comments=False, include_evaluation=False):
    data = {
        "task_id": self.task_id,
        "assigner_id": self.user_id,
        "assigner_username": self.assigner.username if self.assigner else "Unknown",
        "assignee_id": self.assignee_id,
        "assignee_username": self.assignee.username if self.assignee else "Unknown",
        "task": self.task,
        "priority": self.priority,
        "category": self.category,
        "status": self.status,
        "assigned_date": str(self.assigned_date) if self.assigned_date else None,
        "due_date": str(self.due_date) if self.due_date else None,
        "closing_date": str(self.closing_date) if self.closing_date else None,
        "estimated_hours": self.estimated_hours,
        "actual_hours": self.actual_hours,
        "progress_percentage": self.progress_percentage,
        "requires_approval": self.requires_approval,
        "approved_by": self.approved_by,
        "approval_date": str(self.approval_date) if self.approval_date else None,
        "location": self.location,
        "department": self.department,
        "project_id": self.project_id,
        "comment_count": self.comment_count if hasattr(self, 'comment_count') else 0,
        "is_overdue": self.is_overdue if hasattr(self, 'is_overdue') else False
    }
    
    if include_comments and hasattr(self, 'comments'):
        data["comments"] = [comment.to_dict() for comment in self.comments]
    
    if include_evaluation and hasattr(self, 'evaluation') and self.evaluation:
        data["evaluation"] = self.evaluation.to_dict()
    
    return data
"""

"""
Add this to TaskComment model:

def to_dict(self, include_replies=False):
    data = {
        "comment_id": self.comment_id,
        "task_id": self.task_id,
        "user_id": self.user_id,
        "username": self.user.username if self.user else "Unknown",
        "comment": self.comment,
        "created_at": str(self.created_at),
        "updated_at": str(self.updated_at) if self.updated_at else None,
        "parent_comment_id": self.parent_comment_id,
        "is_reply": self.is_reply,
        "reply_count": self.reply_count
    }
    
    if include_replies and hasattr(self, 'replies'):
        data["replies"] = [reply.to_dict(include_replies=False) for reply in self.replies]
    
    return data
"""

"""
Add this to TaskEvaluation model:

def to_dict(self):
    return {
        "evaluation_id": self.evaluation_id,
        "task_id": self.task_id,
        "evaluator_id": self.evaluator_id,
        "evaluator_name": self.evaluator.username if self.evaluator else "Unknown",
        "rating": self.rating,
        "comment": self.comment,
        "created_at": str(self.created_at)
    }
"""