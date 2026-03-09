import logging
import atexit
import uuid
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from marshmallow import Schema, fields, ValidationError
from config import Config
from database import init_db, create_tables, execute_sql_file
from services.notification_system_service import NotificationSystemService
from services.mongodb_service import mongodb_service
from consumer.kafka_consumer import NotificationConsumer
from consumer.submission_consumer import SubmissionConsumer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize SocketIO (will be configured with app)
socketio = None

# Store connected students: {student_id: [sid1, sid2, ...]}
connected_students = {}

# Store connected faculty: {faculty_id: [sid1, sid2, ...]}
connected_faculty = {}

# Validation schemas
class CreateTestSchema(Schema):
    faculty_id = fields.Str(required=True)
    class_id = fields.Str(required=True)
    section_id = fields.Str(required=True)
    test_name = fields.Str(required=True, validate=lambda x: len(x.strip()) > 0)

create_test_schema = CreateTestSchema()

def create_app():
    """Application factory pattern"""
    global socketio
    
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Enable CORS for all routes
    CORS(app)
    
    # Initialize database
    init_db(app)
    
    # Initialize SocketIO with custom path
    socketio = SocketIO(
        app, 
        cors_allowed_origins="*", 
        async_mode="eventlet",
        logger=True,
        engineio_logger=True,
        path="/socketio3"
    )
    logger.info("SocketIO initialized successfully with path: /socketio3")
    
    # Register Socket.IO event handlers
    register_socketio_handlers()
    
    # Health check endpoint
    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            'status': 'healthy',
            'service': 'notification-service',
            'version': '1.0.0',
            'socketio_enabled': True,
            'connected_students': len(connected_students),
            'connected_faculty': len(connected_faculty),
            'total_student_connections': sum(len(sids) for sids in connected_students.values()),
            'total_faculty_connections': sum(len(sids) for sids in connected_faculty.values())
        }), 200
    
    # Web interface route
    @app.route('/', methods=['GET'])
    def index():
        return render_template('index.html')
    
    # ==================== FACULTY ENDPOINTS ====================
    
    @app.route('/create-test-notification/faculty/tests', methods=['POST'])
    def create_test():
        """
        Create a new test and send notifications to students
        
        Request Body:
        {
            "faculty_id": "uuid",
            "class_id": "uuid", 
            "section_id": "uuid",
            "test_name": "string",
            "text": "string",
            "body": "string",
            "route": "string" (e.g., "/student/tests/test-123")
        }
        
        Example:
        POST /create-test-notification/faculty/tests
        Body: {
            "faculty_id": "...", 
            "class_id": "...",
            "section_id": "...",
            "test_name": "...",
            "text": "New test available",
            "body": "A new test has been created for your class",
            "route": "/student/tests/test-123"
        }
        """
        try:
            # Check Content-Type
            if not request.is_json:
                return jsonify({
                    'success': False,
                    'message': 'Content-Type must be application/json'
                }), 415
            
            # Get request data
            data = request.get_json()
            
            if not data:
                return jsonify({
                    'success': False,
                    'message': 'Request body is empty or invalid JSON'
                }), 400
            
            # Validate required fields
            required_fields = ['faculty_id', 'class_id', 'section_id']
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                return jsonify({
                    'success': False,
                    'message': f'Missing required fields: {", ".join(missing_fields)}'
                }), 400
            
            # Validate UUIDs
            try:
                uuid.UUID(data['faculty_id'])
                uuid.UUID(data['class_id'])
                uuid.UUID(data['section_id'])
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid UUID format in faculty_id, class_id, or section_id'
                }), 400
            
            # Get optional fields with defaults
            test_name = data.get('test_name', 'New Test')
            text = data.get('text', 'Test Notification')
            body = data.get('body', 'Your faculty has created a new test for your class and section. Kindly review the schedule and prepare accordingly.')
            route = data.get('route', '')
            
            # Validate test_name, text, and body are not empty if provided
            if test_name and len(test_name.strip()) == 0:
                return jsonify({
                    'success': False,
                    'message': 'test_name cannot be empty'
                }), 400
            
            if text and len(text.strip()) == 0:
                return jsonify({
                    'success': False,
                    'message': 'text cannot be empty'
                }), 400
            
            if body and len(body.strip()) == 0:
                return jsonify({
                    'success': False,
                    'message': 'body cannot be empty'
                }), 400
            
            # Create test and send notifications with better error handling
            try:
                result = NotificationSystemService.create_test(
                    faculty_id=data['faculty_id'],
                    class_id=data['class_id'],
                    section_id=data['section_id'],
                    test_name=test_name.strip(),
                    text=text.strip(),
                    body=body.strip(),
                    socketio_instance=socketio
                )
                
                # Add route to result if provided
                if route:
                    result['route'] = route
                
                return jsonify({
                    'success': True,
                    'data': result
                }), 201
                
            except Exception as db_error:
                # Check if it's a database connection error
                if "server closed the connection unexpectedly" in str(db_error):
                    logger.error(f"Database connection error in create_test: {str(db_error)}")
                    return jsonify({
                        'success': False,
                        'message': 'Database connection error. Please try again in a moment.',
                        'error_type': 'database_connection_error'
                    }), 503  # Service Unavailable
                else:
                    logger.error(f"Unexpected error in create_test: {str(db_error)}")
                    return jsonify({
                        'success': False,
                        'message': 'An unexpected error occurred while creating the test.',
                        'error_type': 'unexpected_error'
                    }), 500
            
        except Exception as e:
            logger.error(f"Error in create_test endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500

    # ==================== STUDENT ENDPOINTS ====================
    
    @app.route('/create-test-notification/student/submit-test', methods=['POST'])
    def submit_test():
        """
        Student submits a test and faculty gets notified
        
        Request Body:
        {
            "student_id": "uuid",
            "faculty_id": "uuid",
            "class_id": "uuid",
            "section_id": "uuid",
            "title": "string",
            "body": "string",
            "time": "string" (optional)
        }
        
        Example:
        POST /create-test-notification/student/submit-test
        Body: {
          "student_id": "aa7ee1de-86d7-4b0c-a444-70096770f2ae",
          "faculty_id": "7f7bdfdf-1467-4456-af87-dec9d4219af5",
          "class_id": "ce6d24ae-732a-48b0-9b06-049fbf4daaf6",
          "section_id": "24a5b428-9247-4bbf-aa69-9d7c5cbed0cc",
          "title": "DailyTest submitted by - Hemanathan A S",
          "body": "Hemanathan A S has submitted DailyTest at 02/03/2026, 11:39:05",
          "time": "02/03/2026, 11:39:05"
        }
        """
        try:
            # Check Content-Type
            if not request.is_json:
                return jsonify({
                    'success': False,
                    'message': 'Content-Type must be application/json'
                }), 415
            
            data = request.get_json()
            
            if not data:
                return jsonify({
                    'success': False,
                    'message': 'Request body is empty or invalid JSON'
                }), 400
            
            # Validate required fields
            required_fields = ['student_id', 'faculty_id', 'class_id', 'section_id', 'title', 'body']
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                return jsonify({
                    'success': False,
                    'message': f'Missing required fields: {", ".join(missing_fields)}'
                }), 400
            
            # Validate UUIDs
            try:
                uuid.UUID(data['student_id'])
                uuid.UUID(data['faculty_id'])
                uuid.UUID(data['class_id'])
                uuid.UUID(data['section_id'])
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid UUID format in student_id, faculty_id, class_id, or section_id'
                }), 400
            
            # Validate title and body
            if not data['title'] or len(data['title'].strip()) == 0:
                return jsonify({
                    'success': False,
                    'message': 'title cannot be empty'
                }), 400
            
            if not data['body'] or len(data['body'].strip()) == 0:
                return jsonify({
                    'success': False,
                    'message': 'body cannot be empty'
                }), 400
            
            # Get optional time field
            time = data.get('time', datetime.now(timezone.utc).strftime('%m/%d/%Y, %H:%M:%S'))
            
            # Submit test and notify faculty
            result = NotificationSystemService.submit_test(
                student_id=data['student_id'],
                faculty_id=data['faculty_id'],
                class_id=data['class_id'],
                section_id=data['section_id'],
                title=data['title'].strip(),
                body=data['body'].strip(),
                time=time,
                socketio_instance=socketio
            )
            
            return jsonify({
                'success': True,
                'data': result
            }), 201
            
        except Exception as e:
            logger.error(f"Error in submit_test endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500
    
    @app.route('/create-test-notification/student/notifications/<student_id>', methods=['GET'])
    def get_notifications(student_id):
        """
        Get notifications for a student
        
        Query Parameters:
        - limit: Number of notifications to return (default: 50)
        - offset: Number of notifications to skip (default: 0)
        """
        try:
            # Validate student_id UUID
            try:
                uuid.UUID(student_id)
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid student_id UUID format'
                }), 400
            
            # Get query parameters
            limit = min(int(request.args.get('limit', 50)), 100)  # Max 100
            offset = max(int(request.args.get('offset', 0)), 0)
            
            # Get notifications
            notifications = NotificationSystemService.get_student_notifications(student_id, limit, offset)
            
            return jsonify({
                'success': True,
                'data': {
                    'notifications': notifications,
                    'count': len(notifications),
                    'limit': limit,
                    'offset': offset
                }
            }), 200
            
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid limit or offset parameter'
            }), 400
        except Exception as e:
            logger.error(f"Error in get_notifications endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500

    @app.route('/create-test-notification/student/notifications/<student_id>/<notification_id>/seen', methods=['PUT'])
    def mark_notification_seen(student_id, notification_id):
        """
        Mark a notification as seen by a student
        """
        try:
            # Validate UUIDs
            try:
                uuid.UUID(student_id)
                uuid.UUID(notification_id)
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid UUID format in student_id or notification_id'
                }), 400
            
            # Mark notification as seen
            result = NotificationSystemService.mark_notification_as_seen(
                notification_id, 
                student_id,
                socketio_instance=socketio
            )
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': result['message'],
                    'data': result['notification']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message']
                }), 404
            
        except Exception as e:
            logger.error(f"Error in mark_notification_seen endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500

    @app.route('/create-test-notification/student/profile/<student_id>/update-status', methods=['PUT'])
    def update_student_profile_status(student_id):
        """
        Update student profile status when they interact with notifications
        
        Request Body:
        {
            "notification_id": "uuid",
            "status": "seen" (optional, default: "seen")
        }
        """
        try:
            # Validate student_id UUID
            try:
                uuid.UUID(student_id)
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid student_id UUID format'
                }), 400
            
            # Get request data
            data = request.get_json()
            if not data or 'notification_id' not in data:
                return jsonify({
                    'success': False,
                    'message': 'notification_id is required in request body'
                }), 400
            
            notification_id = data['notification_id']
            status = data.get('status', 'seen')
            
            # Validate notification_id UUID
            try:
                uuid.UUID(notification_id)
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid notification_id UUID format'
                }), 400
            
            # Update student profile in MongoDB
            success = mongodb_service.update_student_profile_status(student_id, notification_id, status)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Student profile updated successfully with status: {status}',
                    'data': {
                        'student_id': student_id,
                        'notification_id': notification_id,
                        'status': status,
                        'updated_at': datetime.utcnow().isoformat()
                    }
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to update student profile or notification not found'
                }), 404
            
        except Exception as e:
            logger.error(f"Error in update_student_profile_status endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500

    @app.route('/create-test-notification/student/notifications/<student_id>/stats', methods=['GET'])
    def get_notification_stats(student_id):
        """
        Get notification statistics for a student
        """
        try:
            # Validate student_id UUID
            try:
                uuid.UUID(student_id)
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid student_id UUID format'
                }), 400
            
            # Get notification stats
            stats = NotificationSystemService.get_notification_stats(student_id)
            
            return jsonify({
                'success': True,
                'data': stats
            }), 200
            
        except Exception as e:
            logger.error(f"Error in get_notification_stats endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500

    # ==================== UTILITY ENDPOINTS ====================
    
    @app.route('/create-test-notification/admin/notifications', methods=['GET'])
    def get_all_admin_notifications():
        """
        Get all notifications from MongoDB admin.notification collection
        
        Query Parameters:
        - limit: Number of notifications to return (default: 50, max: 200)
        - offset: Number of notifications to skip (default: 0)
        """
        try:
            # Get query parameters
            limit = min(int(request.args.get('limit', 50)), 200)  # Max 200
            offset = max(int(request.args.get('offset', 0)), 0)
            
            # Get all notifications from MongoDB
            data = mongodb_service.get_all_notifications(limit, offset)
            
            return jsonify({
                'success': True,
                'data': data,
                'pagination': {
                    'limit': limit,
                    'offset': offset,
                    'total_count': data['total_count'],
                    'returned_count': data['returned_count']
                },
                'source': 'admin.notification collection'
            }), 200
            
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid limit or offset parameter'
            }), 400
        except Exception as e:
            logger.error(f"Error in get_all_admin_notifications endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500

    @app.route('/create-test-notification/admin/notifications/faculty/<faculty_id>', methods=['GET'])
    def get_faculty_admin_notifications(faculty_id):
        """
        Get all notifications sent by a specific faculty from admin.notification collection
        
        Query Parameters:
        - limit: Number of notifications to return (default: 50, max: 200)
        - offset: Number of notifications to skip (default: 0)
        """
        try:
            # Validate faculty_id UUID
            try:
                uuid.UUID(faculty_id)
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid faculty_id UUID format'
                }), 400
            
            # Get query parameters
            limit = min(int(request.args.get('limit', 50)), 200)  # Max 200
            offset = max(int(request.args.get('offset', 0)), 0)
            
            # Get faculty notifications from MongoDB
            data = mongodb_service.get_faculty_notifications(faculty_id, limit, offset)
            
            return jsonify({
                'success': True,
                'data': data,
                'pagination': {
                    'limit': limit,
                    'offset': offset,
                    'total_count': data['total_count'],
                    'returned_count': data['returned_count']
                },
                'source': 'admin.notification collection',
                'faculty_id': faculty_id
            }), 200
            
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid limit or offset parameter'
            }), 400
        except Exception as e:
            logger.error(f"Error in get_faculty_admin_notifications endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500
    
    @app.route('/create-test-notification/students/class/<class_id>/section/<section_id>', methods=['GET'])
    def get_students_by_class_section(class_id, section_id):
        """Get all students for a given class and section"""
        try:
            # Validate UUIDs
            try:
                uuid.UUID(class_id)
                uuid.UUID(section_id)
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid UUID format in class_id or section_id'
                }), 400
            
            # Get students
            students = NotificationSystemService.get_students_by_class_section(class_id, section_id)
            
            return jsonify({
                'success': True,
                'data': {
                    'students': students,
                    'count': len(students)
                }
            }), 200
            
        except Exception as e:
            logger.error(f"Error in get_students_by_class_section endpoint: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Internal server error'
            }), 500
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'success': False,
            'message': 'Endpoint not found'
        }), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({
            'success': False,
            'message': 'Internal server error'
        }), 500
    
    return app


# ==================== SOCKET.IO EVENT HANDLERS ====================

def register_socketio_handlers():
    """Register all Socket.IO event handlers"""
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        logger.info(f"Client connected: {request.sid}")
        emit('connection_response', {
            'status': 'connected',
            'message': 'Successfully connected to notification service',
            'sid': request.sid
        })
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        logger.info(f"Client disconnected: {request.sid}")
        
        # Remove from connected_students tracking
        for student_id, sids in list(connected_students.items()):
            if request.sid in sids:
                sids.remove(request.sid)
                if not sids:  # Remove student_id if no more connections
                    del connected_students[student_id]
                logger.info(f"Student {student_id} disconnected (sid: {request.sid})")
                break
        
        # Remove from connected_faculty tracking
        for faculty_id, sids in list(connected_faculty.items()):
            if request.sid in sids:
                sids.remove(request.sid)
                if not sids:  # Remove faculty_id if no more connections
                    del connected_faculty[faculty_id]
                logger.info(f"Faculty {faculty_id} disconnected (sid: {request.sid})")
                break
    
    @socketio.on('join_student_room')
    def handle_join_student_room(data):
        """
        Student joins their personal room
        
        Expected data:
        {
            "student_id": "uuid"
        }
        """
        try:
            student_id = data.get('student_id')
            
            if not student_id:
                emit('error', {
                    'message': 'student_id is required',
                    'code': 'MISSING_STUDENT_ID'
                })
                return
            
            # Join the student-specific room
            room = f"student_{student_id}"
            join_room(room)
            
            # Track connected student
            if student_id not in connected_students:
                connected_students[student_id] = []
            if request.sid not in connected_students[student_id]:
                connected_students[student_id].append(request.sid)
            
            logger.info(f"Student {student_id} joined room: {room} (sid: {request.sid})")
            
            emit('room_joined', {
                'status': 'success',
                'message': f'Successfully joined room for student {student_id}',
                'room': room,
                'student_id': student_id
            })
            
        except Exception as e:
            logger.error(f"Error in join_student_room: {str(e)}")
            emit('error', {
                'message': 'Failed to join student room',
                'error': str(e),
                'code': 'JOIN_ROOM_ERROR'
            })
    
    @socketio.on('leave_student_room')
    def handle_leave_student_room(data):
        """
        Student leaves their personal room
        
        Expected data:
        {
            "student_id": "uuid"
        }
        """
        try:
            student_id = data.get('student_id')
            
            if not student_id:
                emit('error', {
                    'message': 'student_id is required',
                    'code': 'MISSING_STUDENT_ID'
                })
                return
            
            # Leave the student-specific room
            room = f"student_{student_id}"
            leave_room(room)
            
            # Remove from tracking
            if student_id in connected_students and request.sid in connected_students[student_id]:
                connected_students[student_id].remove(request.sid)
                if not connected_students[student_id]:
                    del connected_students[student_id]
            
            logger.info(f"Student {student_id} left room: {room} (sid: {request.sid})")
            
            emit('room_left', {
                'status': 'success',
                'message': f'Successfully left room for student {student_id}',
                'room': room,
                'student_id': student_id
            })
            
        except Exception as e:
            logger.error(f"Error in leave_student_room: {str(e)}")
            emit('error', {
                'message': 'Failed to leave student room',
                'error': str(e),
                'code': 'LEAVE_ROOM_ERROR'
            })
    
    @socketio.on('join_faculty_room')
    def handle_join_faculty_room(data):
        """
        Faculty joins their personal room to receive test submission notifications
        
        Expected data:
        {
            "faculty_id": "uuid"
        }
        """
        try:
            faculty_id = data.get('faculty_id')
            
            if not faculty_id:
                emit('error', {
                    'message': 'faculty_id is required',
                    'code': 'MISSING_FACULTY_ID'
                })
                return
            
            # Join the faculty-specific room
            room = f"faculty_{faculty_id}"
            join_room(room)
            
            # Track connected faculty
            if faculty_id not in connected_faculty:
                connected_faculty[faculty_id] = []
            if request.sid not in connected_faculty[faculty_id]:
                connected_faculty[faculty_id].append(request.sid)
            
            logger.info(f"Faculty {faculty_id} joined room: {room} (sid: {request.sid})")
            
            emit('room_joined', {
                'status': 'success',
                'message': f'Successfully joined room for faculty {faculty_id}',
                'room': room,
                'faculty_id': faculty_id
            })
            
        except Exception as e:
            logger.error(f"Error in join_faculty_room: {str(e)}")
            emit('error', {
                'message': 'Failed to join faculty room',
                'error': str(e),
                'code': 'JOIN_ROOM_ERROR'
            })
    
    @socketio.on('leave_faculty_room')
    def handle_leave_faculty_room(data):
        """
        Faculty leaves their personal room
        
        Expected data:
        {
            "faculty_id": "uuid"
        }
        """
        try:
            faculty_id = data.get('faculty_id')
            
            if not faculty_id:
                emit('error', {
                    'message': 'faculty_id is required',
                    'code': 'MISSING_FACULTY_ID'
                })
                return
            
            # Leave the faculty-specific room
            room = f"faculty_{faculty_id}"
            leave_room(room)
            
            # Remove from tracking
            if faculty_id in connected_faculty and request.sid in connected_faculty[faculty_id]:
                connected_faculty[faculty_id].remove(request.sid)
                if not connected_faculty[faculty_id]:
                    del connected_faculty[faculty_id]
            
            logger.info(f"Faculty {faculty_id} left room: {room} (sid: {request.sid})")
            
            emit('room_left', {
                'status': 'success',
                'message': f'Successfully left room for faculty {faculty_id}',
                'room': room,
                'faculty_id': faculty_id
            })
            
        except Exception as e:
            logger.error(f"Error in leave_faculty_room: {str(e)}")
            emit('error', {
                'message': 'Failed to leave faculty room',
                'error': str(e),
                'code': 'LEAVE_ROOM_ERROR'
            })
    
    @socketio.on('ping')
    def handle_ping():
        """Handle ping from client for connection health check"""
        emit('pong', {'timestamp': request.sid})


# ==================== SOCKET.IO UTILITY FUNCTIONS ====================

def emit_new_test_notification(student_id, notification_data):
    """
    Emit new test notification to a specific student's room
    
    Args:
        student_id: UUID of the student
        notification_data: Dictionary containing notification details
    """
    try:
        room = f"student_{student_id}"
        socketio.emit('new_test_notification', notification_data, room=room)
        logger.info(f"Emitted new_test_notification to room {room}")
        return True
    except Exception as e:
        logger.error(f"Error emitting new_test_notification to student {student_id}: {str(e)}")
        return False


def emit_notification_seen(student_id, notification_data):
    """
    Emit notification seen confirmation to a specific student's room
    
    Args:
        student_id: UUID of the student
        notification_data: Dictionary containing notification details
    """
    try:
        room = f"student_{student_id}"
        socketio.emit('notification_seen', notification_data, room=room)
        logger.info(f"Emitted notification_seen to room {room}")
        return True
    except Exception as e:
        logger.error(f"Error emitting notification_seen to student {student_id}: {str(e)}")
        return False


def is_student_connected(student_id):
    """Check if a student is currently connected"""
    return student_id in connected_students and len(connected_students[student_id]) > 0

def initialize_database(app):
    """Initialize database tables and schema"""
    with app.app_context():
        try:
            # Create tables using SQLAlchemy
            from database import db
            db.create_all()
            logger.info("Database tables created successfully using SQLAlchemy")
                
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            logger.error("Please make sure PostgreSQL is running and DATABASE_URL is configured correctly in .env")
            raise

def start_kafka_consumer(app):
    """Start Kafka notification consumer in background"""
    try:
        consumer = NotificationConsumer(app)
        consumer.start_consuming()
        logger.info("Kafka notification consumer started successfully")
        
        # Register cleanup function
        def cleanup():
            logger.info("Shutting down Kafka notification consumer...")
            consumer.stop_consuming()
        
        atexit.register(cleanup)
        return consumer
        
    except Exception as e:
        logger.info("Kafka notification consumer not available - running in test mode without Kafka")
        return None

def start_submission_consumer(app):
    """Start Kafka submission consumer in background"""
    try:
        consumer = SubmissionConsumer(app)
        consumer.start_consuming()
        logger.info("Kafka submission consumer started successfully")
        
        # Register cleanup function
        def cleanup():
            logger.info("Shutting down Kafka submission consumer...")
            consumer.stop_consuming()
        
        atexit.register(cleanup)
        return consumer
        
    except Exception as e:
        logger.info("Kafka submission consumer not available - running in test mode without Kafka")
        return None

if __name__ == '__main__':
    # Create Flask app
    app = create_app()
    
    # Initialize database
    initialize_database(app)
    
    # Start Kafka consumers
    notification_consumer = start_kafka_consumer(app)
    submission_consumer = start_submission_consumer(app)
    
    # Start Flask app with SocketIO
    logger.info("Starting Flask application with SocketIO (eventlet)...")
    socketio.run(
        app,
        host='0.0.0.0',
        port=1018,
        debug=Config.DEBUG
    )

    #gjk