import json
import logging
import threading
from confluent_kafka import Consumer, KafkaError
from config import Config
from database import db
from models.notification import Notification

logger = logging.getLogger(__name__)

class NotificationConsumer:
    def __init__(self, app):
        self.app = app
        self.consumer = None
        self.topic = Config.KAFKA_NOTIFICATION_TOPIC
        self.running = False
        self.consumer_thread = None
        self._initialize_consumer()
    
    def _initialize_consumer(self):
        """Initialize Kafka consumer"""
        try:
            # Handle both single server and comma-separated servers
            bootstrap_servers = Config.KAFKA_BOOTSTRAP_SERVERS
            if isinstance(bootstrap_servers, list):
                bootstrap_servers = ','.join(bootstrap_servers)
            
            config = {
                'bootstrap.servers': bootstrap_servers,
                'group.id': Config.KAFKA_CONSUMER_GROUP,
                'auto.offset.reset': 'earliest',
                'enable.auto.commit': False,
                'max.poll.interval.ms': 300000,
                'session.timeout.ms': 30000,
                'heartbeat.interval.ms': 10000,
                'allow.auto.create.topics': 'true',  # Auto-create topics
                'log_level': 0  # Disable Kafka logs
            }
            
            self.consumer = Consumer(config)
            self.consumer.subscribe([self.topic])
            logger.info("Kafka consumer initialized successfully with auto-create topics enabled")
        except Exception as e:
            logger.info("Kafka consumer not available - running in test mode without Kafka")
            self.consumer = None
    
    def start_consuming(self):
        """Start consuming messages in a separate thread"""
        if not self.consumer:
            logger.info("Kafka consumer not available - skipping message consumption")
            return
            
        if self.running:
            logger.warning("Consumer is already running")
            return
        
        self.running = True
        self.consumer_thread = threading.Thread(target=self._consume_messages)
        self.consumer_thread.daemon = True
        self.consumer_thread.start()
        logger.info("Notification consumer started")
    
    def stop_consuming(self):
        """Stop consuming messages"""
        self.running = False
        if self.consumer_thread:
            self.consumer_thread.join(timeout=5)
        if self.consumer:
            self.consumer.close()
        logger.info("Notification consumer stopped")
    
    def _consume_messages(self):
        """Main consumer loop"""
        logger.info("Starting to consume messages...")
        
        try:
            while self.running:
                try:
                    # Poll for messages with timeout
                    msg = self.consumer.poll(timeout=1.0)
                    
                    if msg is None:
                        continue
                    
                    if msg.error():
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            # End of partition event
                            logger.debug(f"Reached end of partition {msg.partition()}")
                        else:
                            logger.error(f"Consumer error: {msg.error()}")
                        continue
                    
                    # Process the message
                    try:
                        self._process_message(msg)
                        # Commit the message offset
                        self.consumer.commit(msg)
                    except Exception as e:
                        logger.error(f"Error processing message: {str(e)}")
                        # Continue processing other messages
                        
                except Exception as e:
                    logger.error(f"Unexpected error in consumer loop: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Fatal error in consumer thread: {str(e)}")
        finally:
            logger.info("Consumer thread exiting")
    
    def _process_message(self, msg):
        """Process a single notification message"""
        try:
            # Decode message value
            message_value = msg.value().decode('utf-8')
            data = json.loads(message_value)
            
            logger.info(f"Processing message for test_id: {data.get('test_id')}")
            
            # Extract message data
            test_id = data['test_id']
            test_name = data['test_name']
            students = data['students']
            message_template = data['message_template']
            
            # Use Flask app context for database operations
            with self.app.app_context():
                # Create notifications for each student
                notifications_created = 0
                for student in students:
                    try:
                        notification = Notification.create_notification(
                            student_id=student['student_id'],
                            test_id=test_id,
                            message=message_template
                        )
                        
                        # Mark as delivered immediately (simulating successful delivery)
                        notification.mark_as_delivered()
                        notifications_created += 1
                        
                        logger.debug(f"Created notification {notification.notification_id} "
                                   f"for student {student['student_id']}")
                        
                    except Exception as e:
                        logger.error(f"Failed to create notification for student "
                                   f"{student['student_id']}: {str(e)}")
                        # Continue with other students
                
                logger.info(f"Successfully created {notifications_created} notifications "
                           f"for test '{test_name}' (test_id: {test_id})")
                
        except Exception as e:
            logger.error(f"Error processing notification message: {str(e)}")
            raise