import os
import re
import uuid
from datetime import datetime

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

import google.generativeai as genai
from dotenv import load_dotenv

# local imports - adjust to your project structure
from database import SessionLocal, engine
from models import Base, User, Consultant, ConsultantPost, Like, Comment, Follower, HealthQuiz
from auth import register_user, login_user, get_current_user, logout_user

# -------------------------------
# Load environment variables & Gemini
# -------------------------------
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# -------------------------------
# App setup
# -------------------------------
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "supersecretkey"))

# serve static files (images/videos)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ----- ROOT ROUTE (redirect to /home or /login) -----
@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    user_email = request.session.get("user_email") or request.session.get("user")
    consultant = request.session.get("consultant") or request.session.get("consultant_email")
    if consultant:
        return RedirectResponse("/consultant_post")
    if user_email:
        return RedirectResponse("/home")
    return RedirectResponse("/login")

# ensure DB tables exist
Base.metadata.create_all(bind=engine)

# uploads directory
UPLOADS_DIR = os.path.join("static", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# -------------------------------
# Helpers
# -------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _sanitize_filename(name: str) -> str:
    # Keep safe filename characters
    return re.sub(r"[^\w\-_\. ]", "_", name)

def save_upload(file: UploadFile) -> str:
    """Save an UploadFile into static/uploads and return just the filename (or None)."""
    if not file or not getattr(file, "filename", None):
        return None
    ext = os.path.splitext(file.filename)[1].lower() or ""
    uniq = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]
    fname = f"{uniq}{ext}"
    fname = _sanitize_filename(fname)
    dest = os.path.join(UPLOADS_DIR, fname)
    # read bytes from upload
    file.file.seek(0)
    with open(dest, "wb") as f:
        f.write(file.file.read())
    return fname

def media_url_for(filename: str) -> str:
    if not filename:
        return None
    # used in templates: "/static/uploads/<filename>"
    return f"static/uploads/{filename}"

# -------------------------------
# health quiz page (GET)
# -------------------------------
@app.get("/health_quiz", response_class=HTMLResponse)
def health_quiz_form(request: Request):
    return templates.TemplateResponse("health_quiz.html", {"request": request})


# -------------------------------
# health quiz submit (POST)
# -------------------------------
@app.post("/health_quiz", response_class=HTMLResponse)
async def submit_health_quiz(
    request: Request,
    question_1: str = Form(...),
    question_2: str = Form(...),
    question_3: str = Form(""),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    user_email = request.session.get("user_email") or request.session.get("user")
    if not user_email:
        return RedirectResponse("/login", status_code=303)

    user = get_current_user(db, user_email)
    image_filename = save_upload(image) if image and image.filename else None

    # Save quiz to DB
    quiz = HealthQuiz(
        user_id=user.id,
        question_1=question_1,
        question_2=question_2,
        question_3=question_3,
        image_path=image_filename,
        timestamp=datetime.utcnow()
    )
    db.add(quiz)
    db.commit()

    # Prepare result for display
    result = {
        "question_1": question_1,
        "question_2": question_2,
        "question_3": question_3,
        "image_path": media_url_for(image_filename) if image_filename else None
    }

    # -------------------------------
    # AI recommendations
    # -------------------------------
    recommendations = []
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        prompt = f"""
        You are a health assistant. Analyze the following quiz answers and provide 3 short recommendations:
        Q1: {question_1}
        Q2: {question_2}
        Q3: {question_3}
        """
        if image_filename:
            image_path = os.path.join(UPLOADS_DIR, image_filename)
            with open(image_path, "rb") as img_file:
                response = model.generate_content([
                    prompt,
                    {"mime_type": image.content_type, "data": img_file.read()}
                ])
        else:
            response = model.generate_content([prompt])

        text = getattr(response, "text", "")
        recommendations = [r.strip() for r in text.split("\n") if r.strip()]
    except Exception as e:
        recommendations = [f"AI could not generate recommendations: {str(e)}"]

    return templates.TemplateResponse(
        "health_quiz.html",
        {
            "request": request,
            "user": user,
            "message": "Your quiz has been submitted successfully!",
            "result": result,
            "recommendations": recommendations
        }
    )

# -------------------------------
# Auth / user routes
# -------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
def login_user_route(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = login_user(db, email, password)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Incorrect email or password."})
    # store user id/email in session
    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    return RedirectResponse("/home", status_code=303)

@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "error": None})

@app.post("/signup", response_class=HTMLResponse)
def signup_user_route(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    try:
        register_user(db, email, password)
        return RedirectResponse("/login", status_code=303)
    except ValueError as e:
        return templates.TemplateResponse("signup.html", {"request": request, "error": str(e)})

@app.get("/home", response_class=HTMLResponse)
def home_page(request: Request, db: Session = Depends(get_db)):
    # try both session keys (compat with older file-based code)
    user_email = request.session.get("user_email") or request.session.get("user")
    user = None
    if user_email:
        user = get_current_user(db, user_email)
    return templates.TemplateResponse("home.html", {"request": request, "user": user})

# -------------------------------
# Forgot Password (GET)
# -------------------------------
@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "message": None}
    )


# -------------------------------
# Forgot Password (POST)
# -------------------------------
@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):

    # Check if email exists
    user = db.query(User).filter(User.email == email).first()

    if not user:
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "message": "❌ Email not found! Please try again."
            }
        )

    # If email exists → pretend to send reset link
    # (We can later add OTP or email sending)
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "message": "✔ A password reset link has been sent to your email!"
        }
    )


# -------------------------------
# Consultant register (profile pic)
# -------------------------------
@app.get("/consultant-register", response_class=HTMLResponse)
@app.get("/consultant_register", response_class=HTMLResponse)
def consultant_register_form(request: Request):
    return templates.TemplateResponse("consultant_register.html", {"request": request})

@app.post("/consultant-register", response_class=HTMLResponse)
@app.post("/consultant_register", response_class=HTMLResponse)
async def consultant_register_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    specialization: str = Form(...),
    bio: str = Form(""),
    media: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    try:
        pic_filename = save_upload(media) if media and media.filename else None

        # create or update consultant
        consultant = db.query(Consultant).filter_by(email=email).first()
        if not consultant:
            consultant = Consultant(
                name=name,
                email=email,
                specialization=specialization,
                bio=bio,
                media_path=pic_filename,
                media_type="image" if pic_filename else None
            )
            db.add(consultant)
            db.commit()
        else:
            consultant.name = name
            consultant.specialization = specialization
            consultant.bio = bio
            if pic_filename:
                # remove old file if exists
                try:
                    if consultant.media_path:
                        old_path = os.path.join(UPLOADS_DIR, consultant.media_path)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                except Exception:
                    pass
                consultant.media_path = pic_filename
                consultant.media_type = "image"
            db.commit()

        # keep track in session (for dashboard flow)
        request.session["consultant_id"] = consultant.id
        request.session["consultant_email"] = consultant.email
        # legacy compatibility
        request.session["consultant"] = {"name": consultant.name, "email": consultant.email, "specialization": consultant.specialization, "profile_pic": consultant.media_path}

        return RedirectResponse("/consultant_post", status_code=303)

    except Exception as e:
        return templates.TemplateResponse("consultant_register.html", {"request": request, "message": f"Error: {str(e)}"})

# -------------------------------
# Consultant dashboard — list posts for logged-in consultant
# -------------------------------
@app.get("/consultant_post", response_class=HTMLResponse)
def consultant_post_page(request: Request, db: Session = Depends(get_db)):
    # prefer consultant_id in session (DB-driven)
    consultant_id = request.session.get("consultant_id")
    if not consultant_id:
        # fallback to legacy session "consultant" (email)
        consultant_session = request.session.get("consultant")
        if consultant_session:
            # try find consultant by email
            consultant = db.query(Consultant).filter_by(email=consultant_session.get("email")).first()
            if consultant:
                consultant_id = consultant.id
                request.session["consultant_id"] = consultant_id

    if not consultant_id:
        return RedirectResponse("/consultant-register")

    consultant = db.query(Consultant).get(consultant_id)
    posts = db.query(ConsultantPost).filter_by(consultant_id=consultant_id).order_by(ConsultantPost.timestamp.desc()).all()
    for p in posts:
        p.likes_count = db.query(Like).filter(Like.post_id == p.id).count()
        p.comments_count = db.query(Comment).filter(Comment.post_id == p.id).count()
    # pass profile_pic for template compatibility
    profile_pic = consultant.media_path if consultant and consultant.media_path else None
    return templates.TemplateResponse("consultant_post.html", {"request": request, "consultant": consultant, "posts": posts, "profile_pic": profile_pic})

# -------------------------------
# Create a post (DB-backed)
# -------------------------------
@app.post("/consultant_post", response_class=HTMLResponse)
async def consultant_post_submit(
    request: Request,
    content: str = Form(...),
    media: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    consultant_id = request.session.get("consultant_id")
    if not consultant_id:
        return RedirectResponse("/consultant-register")

    filename = save_upload(media) if media and media.filename else None
    media_type = None
    if filename:
        media_type = "video" if os.path.splitext(filename)[1].lower() in [".mp4", ".mov", ".avi", ".webm"] else "image"

    post = ConsultantPost(
        consultant_id=consultant_id,
        content=content,
        media_path=filename,
        media_type=media_type,
        timestamp=datetime.utcnow()
    )
    db.add(post)
    db.commit()

    # Update legacy session list if present (for old templates expecting file list)
    # Not strictly required if templates use DB data.
    return RedirectResponse("/consultant_post", status_code=303)

# -------------------------------
# Edit Post (owner only)
# -------------------------------
@app.post("/edit_post", response_class=HTMLResponse)
async def edit_post(
    request: Request,
    post_id: int = Form(...),
    new_bio: str = Form(...),
    new_media: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    consultant_id = request.session.get("consultant_id")
    if not consultant_id:
        return RedirectResponse("/consultant-register")

    post = db.query(ConsultantPost).get(post_id)
    if not post or post.consultant_id != consultant_id:
        raise HTTPException(status_code=403, detail="Not authorized to edit")

    # replace media if provided
    if new_media and new_media.filename:
        if post.media_path:
            old_path = os.path.join(UPLOADS_DIR, post.media_path)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        post.media_path = save_upload(new_media)
        post.media_type = "video" if os.path.splitext(post.media_path)[1].lower() in [".mp4", ".mov", ".avi", ".webm"] else "image"

    post.content = new_bio
    post.timestamp = datetime.utcnow()
    db.commit()
    return RedirectResponse("/consultant_post", status_code=303)

# -------------------------------
# Delete Post (owner only)
# -------------------------------
@app.post("/delete_post", response_class=HTMLResponse)
def delete_post(request: Request, post_id: int = Form(...), db: Session = Depends(get_db)):
    consultant_id = request.session.get("consultant_id")
    if not consultant_id:
        return RedirectResponse("/consultant-register")

    post = db.query(ConsultantPost).get(post_id)
    if not post or post.consultant_id != consultant_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete")

    # delete file if exists
    if post.media_path:
        p = os.path.join(UPLOADS_DIR, post.media_path)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    db.delete(post)
    db.commit()
    return RedirectResponse("/consultant_post", status_code=303)

# -------------------------------
# Public feed (filter by specialization / search)
# -------------------------------
@app.get("/consultants", response_class=HTMLResponse)
def consultants_page(request: Request, q: str = None, specialization: str = None, db: Session = Depends(get_db)):
    # Build base query joining consultant
    query = db.query(ConsultantPost).join(Consultant)
    if specialization:
        query = query.filter(Consultant.specialization.ilike(f"%{specialization}%"))
    if q:
        q_like = f"%{q}%"
        query = query.filter(
            (Consultant.name.ilike(q_like)) |
            (Consultant.bio.ilike(q_like)) |
            (ConsultantPost.content.ilike(q_like)) |
            (Consultant.specialization.ilike(q_like))
        )
    posts = query.order_by(ConsultantPost.timestamp.desc()).all()

    # Construct result list for template
    result = []
    for p in posts:
        c = db.query(Consultant).get(p.consultant_id)
        likes_count = db.query(Like).filter(Like.post_id == p.id).count()
        comments = db.query(Comment).filter(Comment.post_id == p.id).order_by(Comment.timestamp.asc()).all()
        followers_count = db.query(Follower).filter(Follower.consultant_id == c.id).count()
        result.append({
            "post": p,
            "consultant": c,
            "likes_count": likes_count,
            "comments": comments,
            "followers_count": followers_count,
            "profile_pic": media_url_for(c.media_path) if c.media_path else None,
            "media_url": media_url_for(p.media_path) if p.media_path else None
        })

    # Also pass logged-in user if present (for UI)
    user_email = request.session.get("user_email") or request.session.get("user")
    user = None
    if user_email:
        user = get_current_user(db, user_email)
    return templates.TemplateResponse("consultants.html", {"request": request, "posts": result, "q": q, "selected_specialization": specialization, "user": user})

# -------------------------------
# Consultant profile page (shows consultant and their posts)
# -------------------------------
@app.get("/consultant/{consultant_id}", response_class=HTMLResponse)
def consultant_profile(request: Request, consultant_id: int, db: Session = Depends(get_db)):
    c = db.query(Consultant).get(consultant_id)
    if not c:
        raise HTTPException(status_code=404, detail="Consultant not found")
    posts = db.query(ConsultantPost).filter_by(consultant_id=consultant_id).order_by(ConsultantPost.timestamp.desc()).all()
    for p in posts:
        p.likes_count = db.query(Like).filter(Like.post_id == p.id).count()
        p.comments = db.query(Comment).filter(Comment.post_id == p.id).order_by(Comment.timestamp.asc()).all()
    profile_pic = media_url_for(c.media_path) if c.media_path else None
    # pass logged-in user as well
    user_email = request.session.get("user_email") or request.session.get("user")
    user = None
    if user_email:
        user = get_current_user(db, user_email)
    return templates.TemplateResponse("consultant_profile.html", {"request": request, "consultant": c, "posts": posts, "profile_pic": profile_pic, "user": user})

# -------------------------------
# Like / Unlike a post
# -------------------------------
@app.post("/post/{post_id}/like")
def like_post(request: Request, post_id: int, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")  # may be None (anonymous)
    existing = db.query(Like).filter(Like.post_id == post_id, Like.user_id == user_id).first()
    if existing:
        db.delete(existing)
        db.commit()
        return RedirectResponse(request.headers.get("Referer", "/consultants"), status_code=303)
    like = Like(user_id=user_id, post_id=post_id, consultant_id=db.query(ConsultantPost).get(post_id).consultant_id if db.query(ConsultantPost).get(post_id) else None)
    db.add(like)
    db.commit()
    return RedirectResponse(request.headers.get("Referer", "/consultants"), status_code=303)

# -------------------------------
# Comment on a post
# -------------------------------
@app.post("/post/{post_id}/comment")
def comment_post(request: Request, post_id: int, comment_text: str = Form(...), db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")  # may be None
    if not comment_text or not comment_text.strip():
        return RedirectResponse(request.headers.get("Referer", "/consultants"), status_code=303)
    post = db.query(ConsultantPost).get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    c = Comment(user_id=user_id, post_id=post_id, consultant_id=post.consultant_id, comment_text=comment_text)
    db.add(c)
    db.commit()
    return RedirectResponse(request.headers.get("Referer", "/consultants"), status_code=303)

# -------------------------------
# Follow / Unfollow consultant
# -------------------------------
@app.post("/consultant/{consultant_id}/follow")
def follow_consultant(request: Request, consultant_id: int, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")  # may be None
    existing = db.query(Follower).filter(Follower.consultant_id == consultant_id, Follower.user_id == user_id).first()
    if existing:
        db.delete(existing)
        db.commit()
        return RedirectResponse(request.headers.get("Referer", "/consultants"), status_code=303)
    f = Follower(user_id=user_id, consultant_id=consultant_id)
    db.add(f)
    db.commit()
    return RedirectResponse(request.headers.get("Referer", "/consultants"), status_code=303)

# -------------------------------
# AI: upload_and_query (keeps your original behavior but uses UPLOADS_DIR)
# -------------------------------
@app.post("/upload_and_query")
async def upload_and_query(request: Request, image: UploadFile = File(...), query: str = Form(...)):
    try:
        # save temporary file into uploads
        tmp_filename = save_upload(image)
        file_path = os.path.join(UPLOADS_DIR, tmp_filename)
        model = genai.GenerativeModel(MODEL_NAME)
        with open(file_path, "rb") as img_file:
            result = model.generate_content([query, {"mime_type": image.content_type, "data": img_file.read()}])
        # remove temp
        try:
            os.remove(file_path)
        except Exception:
            pass
        return JSONResponse({"response": getattr(result, "text", "No response received."), "model": MODEL_NAME})
    except Exception as e:
        return JSONResponse({"detail": f"Error: {str(e)}"}, status_code=500)

# -------------------------------
# Logout (User)
# -------------------------------
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
