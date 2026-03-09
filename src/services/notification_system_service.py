import logging
import uuid
from datetime import datetime, timezone
from models.test import Test
from models.notification import Notification
from producer.kafka_producer import notification_producer
from services.mongodb_service import mongodb_service

logger = logging.getLogger(__name__)

class NotificationSystemService:
    """
    Unified service for handling all notification system operations
    Uses PostgreSQL for notifications and MongoDB for test data storage
    """
    
    # ==================== TEST OPERATIONS ====================
    
    @staticmethod
    def submit_test(student_id, faculty_id, class_id, section_id, title, body, time, socketio_instance=None):
        """
        Student submits a test and faculty gets notified
        
        Args:
            student_id: UUID of the student submitting the test
            faculty_id: UUID of the faculty to notify
            class_id: UUID of the class
            section_id: UUID of the section
            title: Notification title from frontend
            body: Notification body from frontend
            time: Submission time from frontend
            socketio_instance: SocketIO instance for real-time notifications
            
        Returns:
            dict: Submission data and notification status
        """
        try:
            # Create a test_id for this submission
            test_id = str(uuid.uuid4())
            
            # Create notification message for faculty
            message = f"{title}: {body}"
            
            # Create notification for faculty (store in PostgreSQL)
            notification = Notification.create_notification(
                student_id=faculty_id,  # Faculty receives the notification
                test_id=test_id,
                message=message
            )
            notification.mark_as_delivered()
            
            logger.info(f"Faculty notification created: {notification.notification_id}")
            
            # Prepare notification data for Socket.IO
            notification_dict = notification.to_dict()
            notification_dict['title'] = title
            notification_dict['body'] = body
            notification_dict['time'] = time
            notification_dict['submission_type'] = 'test_submission'
            
            # Emit real-time notification to faculty via Socket.IO
            socketio_sent = False
            if socketio_instance:
                try:
                    room = f"faculty_{faculty_id}"  # Faculty room
                    socketio_instance.emit('test_submission_notification', notification_dict, room=room)
                    logger.info(f"Socket.IO test submission notification sent to faculty {faculty_id}")
                    socketio_sent = True
                except Exception as e:
                    logger.warning(f"Socket.IO emission failed for faculty {faculty_id}: {str(e)}")
            
            # Store comprehensive notification in MongoDB admin.notification collection
            mongodb_stored = False
            try:
                # Prepare faculty info
                faculty_info = {
                    'faculty_id': faculty_id,
                    'faculty_name': 'Faculty',
                }
                
                # Prepare student info
                student_info = {
                    'student_id': student_id,
                    'student_name': 'Student',
                    'email': '',
                }
                
                # Prepare test info
                test_info = {
                    'test_id': test_id,
                    'class_id': class_id,
                    'section_id': section_id,
                    'submitted_at': time,
                    'title': title,
                    'body': body
                }
                
                # Store with comprehensive data
                mongodb_service.store_notification_data(
                    notification.to_dict(),
                    faculty_info=faculty_info,
                    student_info=student_info,
                    test_info=test_info
                )
                mongodb_stored = True
                logger.info(f"Test submission notification stored in MongoDB")
            except Exception as e:
                logger.warning(f"MongoDB notification storage failed: {str(e)}")
            
            # Try to send notification message to Kafka (optional)
            kafka_sent = False
            try:
                submission_kafka_data = {
                    'submission_id': test_id,
                    'test_id': test_id,
                    'student_id': student_id,
                    'faculty_id': faculty_id,
                    'class_id': class_id,
                    'section_id': section_id,
                    'title': title,
                    'body': body,
                    'submitted_at': time
                }
                kafka_sent = notification_producer.send_test_submission(submission_kafka_data)
                if kafka_sent:
                    logger.info(f"Test submission sent to Kafka topic: test-submissions")
            except Exception as e:
                logger.warning(f"Kafka submission failed (continuing without it): {str(e)}")
            
            return {
                'submission': {
                    'student_id': student_id,
                    'faculty_id': faculty_id,
                    'test_id': test_id,
                    'class_id': class_id,
                    'section_id': section_id,
                    'submitted_at': time,
                    'title': title,
                    'body': body
                },
                'notification': notification.to_dict(),
                'faculty_notified': True,
                'socketio_sent': socketio_sent,
                'mongodb_stored': mongodb_stored,
                'kafka_sent': kafka_sent,
                'message': f'Test submitted successfully and faculty {faculty_id} has been notified'
            }
                
        except Exception as e:
            logger.error(f"Error submitting test: {str(e)}")
            raise
    
    @staticmethod
    def create_test(faculty_id, class_id, section_id, test_name, text, body, socketio_instance=None):
        """
        Create a new test and trigger notifications
        Stores test in both PostgreSQL (for notifications) and MongoDB (for test data)
        
        Args:
            faculty_id: UUID of the faculty creating the test
            class_id: UUID of the class
            section_id: UUID of the section
            test_name: Name of the test
            text: Notification text/title from frontend
            body: Notification body/description from frontend
            socketio_instance: SocketIO instance for real-time notifications
            
        Returns:
            dict: Test data and notification status
        """
        try:
            # Create the test in PostgreSQL (for notification system)
            test = Test.create_test(faculty_id, class_id, section_id, test_name)
            logger.info(f"Test created in PostgreSQL: {test.test_id}")
            
            # Store test data in MongoDB (for academia system) - optional
            test_data = test.to_dict()
            mongodb_stored = False
            try:
                mongodb_stored = mongodb_service.store_test_data(test_data)
                if mongodb_stored:
                    logger.info(f"Test data stored in MongoDB: {test.test_id}")
            except Exception as e:
                logger.warning(f"MongoDB storage failed (continuing without it): {str(e)}")
            
            # Get all students for this class and section from PostgreSQL
            students = Notification.get_students_by_class_section(class_id, section_id)
            
            if not students:
                logger.warning(f"No students found for class_id: {class_id}, section_id: {section_id}")
                return {
                    'test': test_data,
                    'students_notified': 0,
                    'notification_sent': False,
                    'mongodb_stored': mongodb_stored,
                    'message': 'Test created but no students found to notify'
                }
            
            # Create notifications directly in database (instead of using Kafka)
            notifications_created = 0
            socketio_sent = 0
            
            try:
                for student in students:
                    # Use the text and body from frontend
                    message = f"{text}: {body}"
                    notification = Notification.create_notification(
                        student_id=student['student_id'],
                        test_id=test.test_id,
                        message=message
                    )
                    # Mark as delivered immediately for testing
                    notification.mark_as_delivered()
                    
                    # Prepare notification data for Socket.IO
                    notification_dict = notification.to_dict()
                    notification_dict['student_name'] = student['student_name']
                    notification_dict['text'] = text
                    notification_dict['body'] = body
                    
                    # Emit real-time notification via Socket.IO
                    if socketio_instance:
                        try:
                            room = f"student_{student['student_id']}"
                            socketio_instance.emit('new_test_notification', notification_dict, room=room)
                            logger.info(f"Socket.IO notification sent to student {student['student_id']}")
                            socketio_sent += 1
                        except Exception as e:
                            logger.warning(f"Socket.IO emission failed for student {student['student_id']}: {str(e)}")
                    
                    # Store comprehensive notification in MongoDB admin.notification collection
                    try:
                        # Prepare faculty info
                        faculty_info = {
                            'faculty_id': faculty_id,
                            'faculty_name': 'Faculty Name',  # You can enhance this with actual faculty data
                        }
                        
                        # Prepare student info
                        student_info = {
                            'student_id': student['student_id'],
                            'student_name': student['student_name'],
                            'email': student.get('email', ''),
                        }
                        
                        # Prepare test info
                        test_info = {
                            'test_id': test.test_id,
                            'test_name': test_name,
                            'class_id': class_id,
                            'section_id': section_id,
                            'created_at': test.created_at.isoformat() if test.created_at else None,
                            'text': text,
                            'body': body
                        }
                        
                        # Store with comprehensive data
                        mongodb_service.store_notification_data(
                            notification.to_dict(),
                            faculty_info=faculty_info,
                            student_info=student_info,
                            test_info=test_info
                        )
                    except Exception as e:
                        logger.warning(f"MongoDB notification storage failed: {str(e)}")
                    
                    notifications_created += 1
                
                logger.info(f"Created {notifications_created} notifications directly in database and stored in MongoDB admin.notification")
                logger.info(f"Sent {socketio_sent} real-time Socket.IO notifications")
            except Exception as e:
                logger.error(f"Error creating notifications: {str(e)}")
            
            # Try to send notification message to Kafka (optional)
            notification_sent = False
            try:
                notification_sent = notification_producer.send_test_notification(test_data, students)
                if notification_sent:
                    logger.info(f"Notification sent to Kafka for {len(students)} students")
            except Exception as e:
                logger.warning(f"Kafka notification failed (continuing without it): {str(e)}")
            
            return {
                'test': test_data,
                'students_notified': notifications_created,
                'socketio_notifications_sent': socketio_sent,
                'notification_sent': notification_sent,
                'mongodb_stored': mongodb_stored,
                'message': f'Test created and {notifications_created} notifications created for students ({socketio_sent} sent via Socket.IO)'
            }
                
        except Exception as e:
            logger.error(f"Error creating test: {str(e)}")
            raise
    
    @staticmethod
    def get_test_by_id(test_id):
        """Get test by ID from both PostgreSQL and MongoDB"""
        # Try PostgreSQL first
        test = Test.query.get(test_id)
        if test:
            test_data = test.to_dict()
            
            # Enhance with MongoDB data if available
            mongo_data = mongodb_service.get_test_data(test_id)
            if mongo_data:
                test_data['mongodb_data'] = mongo_data
            
            return test_data
        
        # If not in PostgreSQL, try MongoDB only
        mongo_data = mongodb_service.get_test_data(test_id)
        return mongo_data
    
    @staticmethod
    def get_tests_by_faculty(faculty_id, limit=50, offset=0):
        """Get tests created by a faculty member from both databases"""
        # Get from PostgreSQL
        pg_tests = Test.get_tests_by_faculty(faculty_id, limit, offset)
        pg_test_data = [test.to_dict() for test in pg_tests]
        
        # Get from MongoDB
        mongo_tests = mongodb_service.get_tests_by_faculty(faculty_id, limit, offset)
        
        # Combine and deduplicate by test_id
        all_tests = {}
        
        # Add PostgreSQL tests
        for test in pg_test_data:
            all_tests[test['test_id']] = test
            all_tests[test['test_id']]['source'] = 'postgresql'
        
        # Add MongoDB tests (merge if exists, add if new)
        for test in mongo_tests:
            test_id = test['test_id']
            if test_id in all_tests:
                all_tests[test_id]['mongodb_data'] = test
                all_tests[test_id]['source'] = 'both'
            else:
                all_tests[test_id] = test
                all_tests[test_id]['source'] = 'mongodb'
        
        # Return as list, sorted by created_at
        result = list(all_tests.values())
        result.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return result
    
    # ==================== NOTIFICATION OPERATIONS ====================
    
    @staticmethod
    def get_student_notifications(student_id, limit=50, offset=0):
        """
        Get notifications for a student
        
        Args:
            student_id: UUID of the student
            limit: Maximum number of notifications to return
            offset: Number of notifications to skip
            
        Returns:
            list: List of notification dictionaries
        """
        try:
            notifications = Notification.get_student_notifications(student_id, limit, offset)
            return [notification.to_dict() for notification in notifications]
        except Exception as e:
            logger.error(f"Error fetching notifications for student {student_id}: {str(e)}")
            raise
    
    @staticmethod
    def mark_notification_as_seen(notification_id, student_id, socketio_instance=None):
        """
        Mark a notification as seen by a student
        
        Args:
            notification_id: UUID of the notification
            student_id: UUID of the student (for security check)
            socketio_instance: SocketIO instance for real-time notifications
            
        Returns:
            dict: Updated notification data or error message
        """
        try:
            # Get notification and verify it belongs to the student
            notification = Notification.query.filter_by(
                notification_id=notification_id,
                student_id=student_id
            ).first()
            
            if not notification:
                return {
                    'success': False,
                    'message': 'Notification not found or does not belong to this student'
                }
            
            if notification.status == 'SEEN':
                return {
                    'success': True,
                    'message': 'Notification was already marked as seen',
                    'notification': notification.to_dict()
                }
            
            # Mark as seen
            notification.mark_as_seen()
            logger.info(f"Notification {notification_id} marked as seen by student {student_id}")
            
            # Emit real-time notification_seen event via Socket.IO
            if socketio_instance:
                try:
                    notification_dict = notification.to_dict()
                    room = f"student_{student_id}"
                    socketio_instance.emit('notification_seen', notification_dict, room=room)
                    logger.info(f"Socket.IO notification_seen event sent to student {student_id}")
                except Exception as e:
                    logger.warning(f"Socket.IO emission failed for notification_seen: {str(e)}")
            
            # Update student profile in MongoDB
            try:
                mongodb_service.update_student_profile_status(student_id, notification_id, 'seen')
            except Exception as e:
                logger.warning(f"MongoDB student profile update failed: {str(e)}")
            
            return {
                'success': True,
                'message': 'Notification marked as seen',
                'notification': notification.to_dict()
            }
            
        except Exception as e:
            logger.error(f"Error marking notification {notification_id} as seen: {str(e)}")
            raise
    
    @staticmethod
    def get_notification_stats(student_id):
        """
        Get notification statistics for a student
        
        Args:
            student_id: UUID of the student
            
        Returns:
            dict: Notification statistics
        """
        try:
            total = Notification.query.filter_by(student_id=student_id).count()
            pending = Notification.query.filter_by(student_id=student_id, status='PENDING').count()
            delivered = Notification.query.filter_by(student_id=student_id, status='DELIVERED').count()
            seen = Notification.query.filter_by(student_id=student_id, status='SEEN').count()
            
            return {
                'total': total,
                'pending': pending,
                'delivered': delivered,
                'seen': seen
            }
        except Exception as e:
            logger.error(f"Error fetching notification stats for student {student_id}: {str(e)}")
            raise
    
    @staticmethod
    def get_notification_by_id(notification_id):
        """Get notification by ID"""
        notification = Notification.query.get(notification_id)
        return notification.to_dict() if notification else None
    
    # ==================== UTILITY OPERATIONS ====================
    
    @staticmethod
    def get_students_by_class_section(class_id, section_id):
        """Get all students for a given class and section"""
        return Notification.get_students_by_class_section(class_id, section_id)
    
    @staticmethod
    def create_notification(student_id, test_id, message):
        """Create a new notification"""
        return Notification.create_notification(student_id, test_id, message)
    
    @staticmethod
    def get_system_stats():
        """Get overall system statistics"""
        try:
            total_tests = Test.query.count()
            total_notifications = Notification.query.count()
            pending_notifications = Notification.query.filter_by(status='PENDING').count()
            delivered_notifications = Notification.query.filter_by(status='DELIVERED').count()
            seen_notifications = Notification.query.filter_by(status='SEEN').count()
            
            return {
                'total_tests': total_tests,
                'total_notifications': total_notifications,
                'pending_notifications': pending_notifications,
                'delivered_notifications': delivered_notifications,
                'seen_notifications': seen_notifications
            }
        except Exception as e:
            logger.error(f"Error fetching system stats: {str(e)}")
            raise