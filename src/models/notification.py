import uuid
from datetime import datetime
from database import db, retry_db_operation
from sqlalchemy import text

class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = {'schema': 'sos'}
    
    notification_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(db.String(36), nullable=False)
    test_id = db.Column(db.String(36), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='PENDING')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    seen_at = db.Column(db.DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'notification_id': self.notification_id,
            'student_id': self.student_id,
            'test_id': self.test_id,
            'message': self.message,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'seen_at': self.seen_at.isoformat() if self.seen_at else None
        }
    
    @classmethod
    def create_notification(cls, student_id, test_id, message):
        """Create a new notification with retry logic"""
        def _create_notification():
            notification = cls(
                student_id=student_id,
                test_id=test_id,
                message=message
            )
            db.session.add(notification)
            db.session.commit()
            return notification
        
        return retry_db_operation(_create_notification)
    
    @classmethod
    def get_student_notifications(cls, student_id, limit=50, offset=0):
        """Get notifications for a student with retry logic"""
        def _get_notifications():
            return cls.query.filter_by(student_id=student_id)\
                           .order_by(cls.created_at.desc())\
                           .limit(limit)\
                           .offset(offset)\
                           .all()
        
        return retry_db_operation(_get_notifications)
    
    def mark_as_seen(self):
        """Mark notification as seen with retry logic"""
        def _mark_seen():
            self.status = 'SEEN'
            self.seen_at = datetime.utcnow()
            db.session.commit()
        
        return retry_db_operation(_mark_seen)
    
    def mark_as_delivered(self):
        """Mark notification as delivered with retry logic"""
        def _mark_delivered():
            self.status = 'DELIVERED'
            db.session.commit()
        
        return retry_db_operation(_mark_delivered)
    
    @classmethod
    def get_students_by_class_section(cls, class_id, section_id):
        """Get all students for a given class and section from PostgreSQL sos.student table with retry logic"""
        def _get_students():
            query = text("""
                SELECT studentid, firstname || ' ' || COALESCE(lastname, '') as student_name, email 
                FROM sos.student 
                WHERE clsid = :class_id AND secid = :section_id
            """)
            result = db.session.execute(query, {
                'class_id': class_id,
                'section_id': section_id
            })
            return [{'student_id': row[0], 'student_name': row[1].strip(), 'email': row[2] or ''} 
                    for row in result.fetchall()]
        
        return retry_db_operation(_get_students)
    
    @classmethod
    def get_faculty_by_class_section(cls, class_id, section_id):
        """Get all faculty for a given class and section from PostgreSQL sos.faculty table with retry logic"""
        def _get_faculty():
            query = text("""
                SELECT DISTINCT f.facultyid, f.firstname || ' ' || COALESCE(f.lastname, '') as faculty_name, f.email 
                FROM sos.faculty f
                INNER JOIN sos.class c ON f.facultyid = c.facultyid
                WHERE c.clsid = :class_id AND c.secid = :section_id
            """)
            result = db.session.execute(query, {
                'class_id': class_id,
                'section_id': section_id
            })
            return [{'faculty_id': row[0], 'faculty_name': row[1].strip(), 'email': row[2] or ''} 
                    for row in result.fetchall()]
        
        return retry_db_operation(_get_faculty)