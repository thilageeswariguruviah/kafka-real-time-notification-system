import logging
from datetime import datetime
from pymongo import MongoClient
from config import Config

logger = logging.getLogger(__name__)

class MongoDBService:
    """Service for handling MongoDB operations"""
    
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self.notification_collection = None
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize MongoDB connection"""
        try:
            # Create MongoDB connection with timeout
            self.client = MongoClient(
                Config.MONGO_URI,
                serverSelectionTimeoutMS=5000,  # 5 second timeout
                connectTimeoutMS=5000,
                socketTimeoutMS=5000
            )
            
            # Test connection with ping
            self.client.admin.command('ping')
            
            # Set database and collections
            self.db = self.client[Config.MONGO_DB_NAME]
            self.collection = self.db[Config.MONGO_COLLECTION_NAME]  # For tests
            self.notification_collection = self.db[Config.MONGO_NOTIFICATION_COLLECTION]  # For notifications
            
            # Test collection access
            self.collection.count_documents({}, limit=1)
            self.notification_collection.count_documents({}, limit=1)
            
            logger.info(f"MongoDB connection established successfully to {Config.MONGO_DB_NAME}")
            logger.info(f"Using collections: {Config.MONGO_COLLECTION_NAME} (tests), {Config.MONGO_NOTIFICATION_COLLECTION} (notifications)")
            
        except Exception as e:
            logger.warning(f"MongoDB connection failed (continuing without MongoDB): {str(e)}")
            self.client = None
            self.db = None
            self.collection = None
            self.notification_collection = None
    
    def store_test_data(self, test_data):
        """
        Store test data in MongoDB
        
        Args:
            test_data: Dictionary containing test information
            
        Returns:
            bool: True if successful, False otherwise
        """
        if self.collection is None:
            logger.warning("MongoDB not available - test data not stored")
            return False
            
        try:
            # Prepare document for MongoDB
            document = {
                'test_id': test_data['test_id'],
                'faculty_id': test_data['faculty_id'],
                'class_id': test_data['class_id'],
                'section_id': test_data['section_id'],
                'test_name': test_data['test_name'],
                'created_at': datetime.utcnow(),
                'status': 'active',
                'metadata': {
                    'source': 'notification_system',
                    'version': '1.0'
                }
            }
            
            # Insert document
            result = self.collection.insert_one(document)
            
            logger.info(f"Test data stored in MongoDB with ID: {result.inserted_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error storing test data in MongoDB: {str(e)}")
            return False
    
    def get_test_data(self, test_id):
        """
        Retrieve test data from MongoDB
        
        Args:
            test_id: Test ID to retrieve
            
        Returns:
            dict: Test data or None if not found
        """
        if self.collection is None:
            logger.warning("MongoDB not available")
            return None
            
        try:
            document = self.collection.find_one({'test_id': test_id})
            
            if document:
                # Convert ObjectId to string for JSON serialization
                document['_id'] = str(document['_id'])
                return document
            
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving test data from MongoDB: {str(e)}")
            return None
    
    def get_tests_by_faculty(self, faculty_id, limit=50, skip=0):
        """
        Get tests created by a faculty member from MongoDB
        
        Args:
            faculty_id: Faculty ID
            limit: Maximum number of tests to return
            skip: Number of tests to skip
            
        Returns:
            list: List of test documents
        """
        if self.collection is None:
            logger.warning("MongoDB not available")
            return []
            
        try:
            cursor = self.collection.find(
                {'faculty_id': faculty_id}
            ).sort('created_at', -1).limit(limit).skip(skip)
            
            tests = []
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                tests.append(doc)
            
            return tests
            
        except Exception as e:
            logger.error(f"Error retrieving faculty tests from MongoDB: {str(e)}")
            return []
    
    def store_notification_data(self, notification_data, faculty_info=None, student_info=None, test_info=None):
        """
        Store comprehensive notification data in MongoDB admin.notification collection
        
        Args:
            notification_data: Dictionary containing notification information
            faculty_info: Dictionary containing faculty information (optional)
            student_info: Dictionary containing student information (optional)
            test_info: Dictionary containing test information (optional)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if self.notification_collection is None:
            logger.warning("MongoDB not available - notification data not stored")
            return False
            
        try:
            # Helper function to convert UUIDs to strings recursively
            def convert_uuids(obj):
                if isinstance(obj, dict):
                    return {k: convert_uuids(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_uuids(item) for item in obj]
                elif hasattr(obj, 'hex'):  # UUID objects have a hex attribute
                    return str(obj)
                else:
                    return obj
            
            # Convert all UUIDs to strings
            notification_data = convert_uuids(notification_data)
            faculty_info = convert_uuids(faculty_info) if faculty_info else {}
            student_info = convert_uuids(student_info) if student_info else {}
            test_info = convert_uuids(test_info) if test_info else {}
            
            # Prepare comprehensive document for MongoDB admin.notification collection
            document = {
                # Core notification data
                'notification_id': str(notification_data['notification_id']),
                'student_id': str(notification_data['student_id']),
                'test_id': str(notification_data['test_id']),
                'message': notification_data['message'],
                'status': notification_data['status'],
                'created_at': datetime.utcnow(),
                'seen_at': notification_data.get('seen_at'),
                
                # Faculty information
                'faculty_info': faculty_info,
                
                # Student information
                'student_info': student_info,
                
                # Test information
                'test_info': test_info,
                
                # System metadata
                'metadata': {
                    'source': 'notification_system',
                    'version': '1.0',
                    'type': 'notification',
                    'database': 'admin',
                    'collection': 'notification',
                    'stored_at': datetime.utcnow().isoformat()
                }
            }
            
            # Insert document into admin.notification collection
            result = self.notification_collection.insert_one(document)
            
            logger.info(f"Comprehensive notification data stored in MongoDB admin.notification collection with ID: {result.inserted_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error storing notification data in MongoDB admin.notification: {str(e)}")
            return False
    
    def get_all_stored_data(self, limit=100, skip=0):
        """
        Get all stored data from MongoDB (tests and notifications)
        
        Args:
            limit: Maximum number of documents to return
            skip: Number of documents to skip
            
        Returns:
            dict: Categorized data (tests, notifications, total_count)
        """
        if self.collection is None:
            logger.warning("MongoDB not available")
            return {'tests': [], 'notifications': [], 'total_count': 0}
            
        try:
            # Get all documents
            cursor = self.collection.find().sort('created_at', -1).limit(limit).skip(skip)
            
            tests = []
            notifications = []
            
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                
                # Categorize by metadata type or presence of test_name
                if 'test_name' in doc or (doc.get('metadata', {}).get('type') == 'test'):
                    tests.append(doc)
                elif 'notification_id' in doc or (doc.get('metadata', {}).get('type') == 'notification'):
                    notifications.append(doc)
                else:
                    # Default to test if unclear
                    tests.append(doc)
            
            total_count = self.collection.count_documents({})
            
            return {
                'tests': tests,
                'notifications': notifications,
                'total_count': total_count,
                'returned_count': len(tests) + len(notifications)
            }
            
        except Exception as e:
            logger.error(f"Error retrieving all data from MongoDB: {str(e)}")
            return {'tests': [], 'notifications': [], 'total_count': 0}
    
    def get_delivered_notifications_by_student(self, student_id, limit=100, skip=0):
        """
        Get only DELIVERED notifications for a specific student from MongoDB
        
        Args:
            student_id: Student ID to filter by
            limit: Maximum number of notifications to return
            skip: Number of notifications to skip
            
        Returns:
            dict: Delivered notifications data
        """
        if self.collection is None:
            logger.warning("MongoDB not available")
            return {'notifications': [], 'total_count': 0}
            
        try:
            # Query for delivered notifications for specific student
            query = {
                'student_id': student_id,
                'status': 'DELIVERED',
                'metadata.type': 'notification'
            }
            
            # Get notifications
            cursor = self.collection.find(query).sort('created_at', -1).limit(limit).skip(skip)
            
            notifications = []
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                notifications.append(doc)
            
            # Get total count for this student with DELIVERED status
            total_count = self.collection.count_documents(query)
            
            return {
                'notifications': notifications,
                'total_count': total_count,
                'returned_count': len(notifications),
                'student_id': student_id,
                'status_filter': 'DELIVERED'
            }
            
        except Exception as e:
            logger.error(f"Error retrieving delivered notifications for student {student_id}: {str(e)}")
            return {'notifications': [], 'total_count': 0}

    def update_student_profile_status(self, student_id, notification_id, status='seen'):
        """
        Update student profile status when they interact with notifications
        
        Args:
            student_id: Student ID
            notification_id: Notification ID that was clicked
            status: New status (default: 'seen')
            
        Returns:
            bool: True if successful, False otherwise
        """
        if self.notification_collection is None:
            logger.warning("MongoDB not available - student profile not updated")
            return False
            
        try:
            # Update the notification document in notifications collection
            result = self.notification_collection.update_one(
                {'notification_id': notification_id, 'student_id': student_id},
                {
                    '$set': {
                        'status': status,
                        'seen_at': datetime.utcnow(),
                        'last_updated': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Student profile updated in MongoDB notifications collection - Student: {student_id}, Notification: {notification_id}")
                return True
            else:
                logger.warning(f"No notification document found to update - Student: {student_id}, Notification: {notification_id}")
                return False
            
        except Exception as e:
            logger.error(f"Error updating student profile in MongoDB: {str(e)}")
            return False

    def get_faculty_notifications(self, faculty_id, limit=100, skip=0):
        """
        Get all notifications sent by a specific faculty from admin.notification collection
        
        Args:
            faculty_id: Faculty ID to filter by
            limit: Maximum number of notifications to return
            skip: Number of notifications to skip
            
        Returns:
            dict: Faculty notifications data
        """
        if self.notification_collection is None:
            logger.warning("MongoDB not available")
            return {'notifications': [], 'total_count': 0}
            
        try:
            # Query for notifications sent by specific faculty
            query = {
                'faculty_info.faculty_id': faculty_id,
                'metadata.type': 'notification'
            }
            
            # Get notifications
            cursor = self.notification_collection.find(query).sort('created_at', -1).limit(limit).skip(skip)
            
            notifications = []
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                notifications.append(doc)
            
            # Get total count for this faculty
            total_count = self.notification_collection.count_documents(query)
            
            return {
                'notifications': notifications,
                'total_count': total_count,
                'returned_count': len(notifications),
                'faculty_id': faculty_id
            }
            
        except Exception as e:
            logger.error(f"Error retrieving faculty notifications for faculty {faculty_id}: {str(e)}")
            return {'notifications': [], 'total_count': 0}

    def get_all_notifications(self, limit=100, skip=0):
        """
        Get all notifications from admin.notification collection
        
        Args:
            limit: Maximum number of notifications to return
            skip: Number of notifications to skip
            
        Returns:
            dict: All notifications data
        """
        if self.notification_collection is None:
            logger.warning("MongoDB not available")
            return {'notifications': [], 'total_count': 0}
            
        try:
            # Query for all notifications
            query = {'metadata.type': 'notification'}
            
            # Get notifications
            cursor = self.notification_collection.find(query).sort('created_at', -1).limit(limit).skip(skip)
            
            notifications = []
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                notifications.append(doc)
            
            # Get total count
            total_count = self.notification_collection.count_documents(query)
            
            return {
                'notifications': notifications,
                'total_count': total_count,
                'returned_count': len(notifications)
            }
            
        except Exception as e:
            logger.error(f"Error retrieving all notifications: {str(e)}")
            return {'notifications': [], 'total_count': 0}

    def close_connection(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Singleton instance
mongodb_service = MongoDBService()