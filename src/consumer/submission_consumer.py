import json
import logging
import threading
from confluent_kafka import Consumer, KafkaError
from config import Config
from database import db
from models.notification import Notification

logger = logging.getLogger(__name__)

class SubmissionConsumer:
    def __init__(self, app):
        self.app = app
        self.consumer = None
        self.topic = Config.KAFKA_SUBMISSION_TOPIC
        self.running = False
        self.consumer_thread = None
        self._initialize_consumer()
    
    def _initialize_consumer(self):
        """Initialize Kafka consumer for test submissions"""
        try:
            # Handle both single server and comma-separated servers
            bootstrap_servers = Config.KAFKA_BOOTSTRAP_SERVERS
            if isinstance(bootstrap_servers, list):
                bootstrap_servers = ','.join(bootstrap_servers)
            
            config = {
                'bootstrap.servers': bootstrap_servers,
                'group.id': 'submission-consumers',
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
            logger.info(f"Submission consumer initialized successfully for topic: {self.topic}")
        except Exception as e:
            logger.info(f"Submission consumer not available - running in test mode without Kafka: {str(e)}")
            self.consumer = None
    
    def start_consuming(self):
        """Start consuming messages in a separate thread"""
        if not self.consumer:
            logger.info("Submission consumer not available - skipping message consumption")
            return
            
        if self.running:
            logger.warning("Submission consumer is already running")
            return
        
        self.running = True
        self.consumer_thread = threading.Thread(target=self._consume_messages)
        self.consumer_thread.daemon = True
        self.consumer_thread.start()
        logger.info("Submission consumer started")
    
    def stop_consuming(self):
        """Stop consuming messages"""
        self.running = False
        if self.consumer_thread:
            self.consumer_thread.join(timeout=5)
        if self.consumer:
            self.consumer.close()
        logger.info("Submission consumer stopped")
    
    def _consume_messages(self):
        """Main consumer loop"""
        logger.info("Starting to consume submission messages...")
        
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
                            logger.error(f"Submission consumer error: {msg.error()}")
                        continue
                    
                    # Process the message
                    try:
                        self._process_message(msg)
                        # Commit the message offset
                        self.consumer.commit(msg)
                    except Exception as e:
                        logger.error(f"Error processing submission message: {str(e)}")
                        # Continue processing other messages
                        
                except Exception as e:
                    logger.error(f"Unexpected error in submission consumer loop: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Fatal error in submission consumer thread: {str(e)}")
        finally:
            logger.info("Submission consumer thread exiting")
    
    def _process_message(self, msg):
        """Process a single test submission message"""
        try:
            # Decode message value
            message_value = msg.value().decode('utf-8')
            data = json.loads(message_value)
            
            logger.info(f"Processing submission for test_id: {data.get('test_id')}, student: {data.get('student_name')}")
            
            # Extract message data
            submission_id = data.get('submission_id')
            test_id = data['test_id']
            test_name = data['test_name']
            student_id = data['student_id']
            student_name = data['student_name']
            faculty_id = data['faculty_id']
            message_template = data.get('message_template', f"Student '{student_name}' has submitted the test '{test_name}'.")
            
            # Use Flask app context for database operations
            with self.app.app_context():
                try:
                    # Create notification for faculty
                    notification = Notification.create_notification(
                        student_id=faculty_id,  # Faculty receives the notification
                        test_id=test_id,
                        message=message_template
                    )
                    
                    # Mark as delivered immediately
                    notification.mark_as_delivered()
                    
                    logger.info(f"Created submission notification {notification.notification_id} for faculty {faculty_id}")
                    logger.info(f"Student '{student_name}' submitted test '{test_name}'")
                    
                except Exception as e:
                    logger.error(f"Failed to create submission notification for faculty {faculty_id}: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error processing submission message: {str(e)}")
            raise
