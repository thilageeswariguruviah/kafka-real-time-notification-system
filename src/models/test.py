import uuid
from datetime import datetime
from database import db, retry_db_operation

class Test(db.Model):
    __tablename__ = 'tests'
    __table_args__ = {'schema': 'sos'}
    
    test_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    faculty_id = db.Column(db.String(36), nullable=False)
    class_id = db.Column(db.String(36), nullable=False)
    section_id = db.Column(db.String(36), nullable=False)
    test_name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'test_id': self.test_id,
            'faculty_id': self.faculty_id,
            'class_id': self.class_id,
            'section_id': self.section_id,
            'test_name': self.test_name,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def create_test(cls, faculty_id, class_id, section_id, test_name):
        """Create a new test with retry logic"""
        def _create_test():
            test = cls(
                faculty_id=faculty_id,
                class_id=class_id,
                section_id=section_id,
                test_name=test_name
            )
            db.session.add(test)
            db.session.commit()
            return test
        
        return retry_db_operation(_create_test)
    
    @classmethod
    def get_tests_by_faculty(cls, faculty_id, limit=50, offset=0):
        """Get tests created by a faculty member with retry logic"""
        def _get_tests():
            return cls.query.filter_by(faculty_id=faculty_id)\
                           .order_by(cls.created_at.desc())\
                           .limit(limit)\
                           .offset(offset)\
                           .all()
        
        return retry_db_operation(_get_tests)