# models.py
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
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
    qr_file_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    verifications = relationship("TaskVerification", back_populates="student")
    purchases = relationship("Purchase", back_populates="student")
    attendances = relationship("Attendance", back_populates="student")
    event_participations = relationship("EventParticipant", back_populates="student")


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
    deadline = Column(DateTime, nullable=True)
    show_deadline = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    verifications = relationship("TaskVerification", back_populates="task")
    event_links = relationship("EventTask", back_populates="task")


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
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    purchases = relationship("Purchase", back_populates="merchandise")
    event_links = relationship("EventMerch", back_populates="merchandise")


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


# ── Мероприятия ──────────────────────────────────────────────────────────────

class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    points = Column(Integer, nullable=False, default=0)   # баллы за лекцию
    status = Column(String(20), default='active')          # active / closed
    created_at = Column(DateTime, default=datetime.utcnow)
    participants = relationship("EventParticipant", back_populates="event")
    lectures = relationship("Lecture", back_populates="event")
    event_tasks = relationship("EventTask", back_populates="event")
    event_merch = relationship("EventMerch", back_populates="event")
    attendances = relationship("Attendance", back_populates="event")
    unmatched = relationship("UnmatchedBarcode", back_populates="event")


class EventParticipant(Base):
    """Студент зарегистрирован на мероприятие. Хранит индивидуальный баланс мероприятия."""
    __tablename__ = 'event_participants'
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    event_balance = Column(Integer, default=0)   # баллы этого мероприятия (сгорают при закрытии)
    registered_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('event_id', 'student_id', name='uq_event_student'),)
    event = relationship("Event", back_populates="participants")
    student = relationship("Student", back_populates="event_participations")


class Lecture(Base):
    """Лекция внутри мероприятия — за посещение начисляются баллы."""
    __tablename__ = 'lectures'
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    title = Column(String(255), nullable=False)
    points = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    event = relationship("Event", back_populates="lectures")
    scans = relationship("LectureScan", back_populates="lecture")


class LectureScan(Base):
    """Факт посещения лекции студентом — уникален (нельзя дважды)."""
    __tablename__ = 'lecture_scans'
    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey('lectures.id'), nullable=False)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('lecture_id', 'student_id', name='uq_lecture_student'),)
    lecture = relationship("Lecture", back_populates="scans")


class EventTask(Base):
    """Задание привязано к мероприятию — доступно только участникам."""
    __tablename__ = 'event_tasks'
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=False)
    __table_args__ = (UniqueConstraint('event_id', 'task_id', name='uq_event_task'),)
    event = relationship("Event", back_populates="event_tasks")
    task = relationship("Task", back_populates="event_links")


class EventMerch(Base):
    """Товар привязан к мероприятию — доступен только участникам."""
    __tablename__ = 'event_merch'
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    merch_id = Column(Integer, ForeignKey('merchandise.id'), nullable=False)
    __table_args__ = (UniqueConstraint('event_id', 'merch_id', name='uq_event_merch'),)
    event = relationship("Event", back_populates="event_merch")
    merchandise = relationship("Merchandise", back_populates="event_links")


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
