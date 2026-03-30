from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("postgresql+pg8000://postgres:aaa77755@localhost:5433/student_bot", echo=False)
Session = sessionmaker(bind=engine)
