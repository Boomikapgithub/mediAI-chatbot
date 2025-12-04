from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


# ------------------------------
# User Table
# ------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    likes = relationship("Like", back_populates="user", cascade="all, delete")
    comments = relationship("Comment", back_populates="user", cascade="all, delete")
    following = relationship("Follower", back_populates="user", cascade="all, delete")


# ------------------------------
# Consultant Table
# ------------------------------
class Consultant(Base):
    __tablename__ = "consultants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    specialization = Column(String, nullable=False)
    bio = Column(Text, nullable=True)

    media_path = Column(String, nullable=True)
    media_type = Column(String, nullable=True)

    posts = relationship("ConsultantPost", back_populates="consultant", cascade="all, delete")
    likes = relationship("Like", back_populates="consultant", cascade="all, delete")
    comments = relationship("Comment", back_populates="consultant", cascade="all, delete")
    followers = relationship("Follower", back_populates="consultant", cascade="all, delete")


# ------------------------------
# Consultant Posts Table
# ------------------------------
class ConsultantPost(Base):
    __tablename__ = "consultant_posts"

    id = Column(Integer, primary_key=True, index=True)
    consultant_id = Column(Integer, ForeignKey("consultants.id"))
    
    # Title made optional for smoother usage
    title = Column(String, nullable=True)

    content = Column(Text, nullable=True)
    media_path = Column(String, nullable=True)
    media_type = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    consultant = relationship("Consultant", back_populates="posts")
    likes = relationship("Like", back_populates="post", cascade="all, delete")
    comments = relationship("Comment", back_populates="post", cascade="all, delete")


# ------------------------------
# Likes Table
# ------------------------------
class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    consultant_id = Column(Integer, ForeignKey("consultants.id"))
    post_id = Column(Integer, ForeignKey("consultant_posts.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="likes")
    consultant = relationship("Consultant", back_populates="likes")
    post = relationship("ConsultantPost", back_populates="likes")


# ------------------------------
# Comments Table
# ------------------------------
class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    consultant_id = Column(Integer, ForeignKey("consultants.id"))
    post_id = Column(Integer, ForeignKey("consultant_posts.id"))
    comment_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="comments")
    consultant = relationship("Consultant", back_populates="comments")
    post = relationship("ConsultantPost", back_populates="comments")


# ------------------------------
# Followers Table
# ------------------------------
class Follower(Base):
    __tablename__ = "followers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    consultant_id = Column(Integer, ForeignKey("consultants.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="following")
    consultant = relationship("Consultant", back_populates="followers")

# ------------------------------
# Health Quiz Table
# ------------------------------
class HealthQuiz(Base):
    __tablename__ = "health_quizzes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))  # Who submitted the quiz
    consultant_id = Column(Integer, ForeignKey("consultants.id"), nullable=True)  # Optional: assigned consultant
    question_1 = Column(Text, nullable=False)
    question_2 = Column(Text, nullable=False)
    question_3 = Column(Text, nullable=True)
    image_path = Column(String, nullable=True)  # Optional uploaded image
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="health_quizzes")
    consultant = relationship("Consultant", backref="health_quizzes")

