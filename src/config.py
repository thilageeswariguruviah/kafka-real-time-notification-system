import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Database Configuration with connection pooling
    POSTGRES_URL = os.getenv('POSTGRES_URL')
    SQLALCHEMY_DATABASE_URI = POSTGRES_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Database connection pool settings
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 120,
        'pool_pre_ping': True,
        'max_overflow': 20,
        'pool_timeout': 30
    }
    
    # MongoDB Configuration
    MONGO_URI = os.getenv('MONGO_URI')
    MONGO_DB_NAME = 'admin'  # Changed to admin database
    MONGO_COLLECTION_NAME = 'academia_test'  # Keep for tests
    MONGO_NOTIFICATION_COLLECTION = 'notification'  # Changed to 'notification' (singular)
    
    # Kafka Configuration (Remote Server)
    KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS')
    KAFKA_NOTIFICATION_TOPIC = os.getenv('KAFKA_NOTIFICATION_TOPIC')
    KAFKA_SUBMISSION_TOPIC = os.getenv('KAFKA_SUBMISSION_TOPIC', 'test-submissions')  # New topic for submissions
    KAFKA_CONSUMER_GROUP = os.getenv('KAFKA_CONSUMER_GROUP')
    
    # Local Docker Kafka Configuration (for reference)
    LOCAL_KAFKA_BOOTSTRAP_SERVERS = 'localhost:9092'
    LOCAL_KAFKA_UI = 'http://localhost:8080'
    LOCAL_ZOOKEEPER = 'localhost:2181'
    
    # Flask Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Application Configuration
    SCHEMA_NAME = 'sos'
    
    @staticmethod
    def print_config():
        """Print all configuration credentials"""
        print("=" * 70)
        print(" " * 20 + "CONFIGURATION CREDENTIALS")
        print("=" * 70)
        
        print("\n📊 POSTGRESQL DATABASE")
        print("-" * 70)
        print(f"Database URL:  {Config.POSTGRES_URL}")
        print(f"Schema Name:   {Config.SCHEMA_NAME}")
        print(f"Track Modifications: {Config.SQLALCHEMY_TRACK_MODIFICATIONS}")
        
        print("\n📦 MONGODB DATABASE")
        print("-" * 70)
        print(f"MongoDB URI:   {Config.MONGO_URI}")
        print(f"Database:      {Config.MONGO_DB_NAME}")
        print(f"Test Collection: {Config.MONGO_COLLECTION_NAME}")
        print(f"Notification Collection: {Config.MONGO_NOTIFICATION_COLLECTION}")
        
        print("\n🔄 KAFKA MESSAGE BROKER (REMOTE SERVER)")
        print("-" * 70)
        print(f"Bootstrap Servers: {Config.KAFKA_BOOTSTRAP_SERVERS}")
        print(f"Topic Name:        {Config.KAFKA_NOTIFICATION_TOPIC}")
        print(f"Consumer Group:    {Config.KAFKA_CONSUMER_GROUP}")
        print("Note: This is the REMOTE Kafka server your app connects to")
        
        print("\n🐳 LOCAL DOCKER KAFKA (for testing)")
        print("-" * 70)
        print(f"Kafka Broker:      {Config.LOCAL_KAFKA_BOOTSTRAP_SERVERS}")
        print(f"Kafka UI:          {Config.LOCAL_KAFKA_UI}")
        print(f"Zookeeper:         {Config.LOCAL_ZOOKEEPER}")
        print("Note: This is LOCAL Docker Kafka for development/testing")
        
        print("\n🌐 FLASK APPLICATION")
        print("-" * 70)
        print(f"Secret Key:    {Config.SECRET_KEY}")
        print(f"Debug Mode:    {Config.DEBUG}")
        
        print("\n" + "=" * 70)


# For direct execution
if __name__ == "__main__":
    Config.print_config()