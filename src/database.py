from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
import time

db = SQLAlchemy()

def init_db(app):
    """Initialize database with Flask app"""
    db.init_app(app)
    
def create_tables():
    """Create all tables"""
    db.create_all()

def execute_sql_file(filepath):
    """Execute SQL file for schema creation"""
    try:
        with open(filepath, 'r') as file:
            sql_commands = file.read()
            db.session.execute(text(sql_commands))
            db.session.commit()
            print(f"Successfully executed SQL file: {filepath}")
    except Exception as e:
        db.session.rollback()
        print(f"Error executing SQL file {filepath}: {str(e)}")
        raise

def retry_db_operation(operation, max_retries=3, delay=1):
    """
    Retry database operations with exponential backoff
    
    Args:
        operation: Function to execute
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
    
    Returns:
        Result of the operation
    """
    for attempt in range(max_retries):
        try:
            return operation()
        except OperationalError as e:
            if "server closed the connection unexpectedly" in str(e) and attempt < max_retries - 1:
                print(f"Database connection lost, retrying in {delay} seconds... (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
                
                # Try to reconnect
                try:
                    db.session.rollback()
                    db.session.remove()
                except:
                    pass
                    
                continue
            else:
                raise
        except Exception as e:
            raise
    
    raise Exception(f"Database operation failed after {max_retries} attempts")