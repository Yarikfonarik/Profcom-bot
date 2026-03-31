# models.py
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    full_name = Column(String(255), nullable=False)
    barcode = Column(String(13), unique=True)
    telegram_id = Column(Integer, unique=True)
    faculty = Column(String(100))
    balance = Column(Integer, default=0)
    role = Column(String(20), default='student')
    status = Column(String(20), default='active')
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    verifications = relationship("TaskVerification", back_populates="student")
    purchases = relationship("Purchase", back_populates="student")
    attendances = relationship("Attendance", back_populates="student")


class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    points = Column(Integer, nullable=False)
    check_type = Column(String(20), nullable=True)
    verification_type = Column(String(20), nullable=False, default='manual')
    correct_answer = Column(Text, nullable=True)
    proof_text = Column(Text, nullable=True)
    deadline = Column(DateTime, nullable=True)   # дедлайн — после него задание скрыто
    created_at = Column(DateTime, default=datetime.utcnow)
    verifications = relationship("TaskVerification", back_populates="task")


class TaskVerification(Base):
    __tablename__ = 'task_verifications'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=False)
    proof_text = Column(Text)
    proof_file = Column(String(255))
    status = Column(String(20), default='pending')
    submitted_at = Column(DateTime, default=datetime.utcnow)
    student = relationship("Student", back_populates="verifications")
    task = relationship("Task", back_populates="verifications")


class Merchandise(Base):
    __tablename__ = 'merchandise'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    price = Column(Integer, nullable=False)
    stock = Column(Integer, default=0)
    photo_file_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    purchases = relationship("Purchase", back_populates="merchandise")


class Purchase(Base):
    __tablename__ = 'purchases'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    merch_id = Column(Integer, ForeignKey('merchandise.id'), nullable=False)
    quantity = Column(Integer, default=1)
    total_points = Column(Integer, nullable=False)
    purchased_at = Column(DateTime, default=datetime.utcnow)
    student = relationship("Student", back_populates="purchases")
    merchandise = relationship("Merchandise", back_populates="purchases")


class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    points = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    attendances = relationship("Attendance", back_populates="event")
    unmatched = relationship("UnmatchedBarcode", back_populates="event")


class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    student = relationship("Student", back_populates="attendances")
    event = relationship("Event", back_populates="attendances")


class UnmatchedBarcode(Base):
    __tablename__ = 'unmatched_barcodes'
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    barcode = Column(String(13), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    event = relationship("Event", back_populates="unmatched")
