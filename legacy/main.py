from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List, Optional
import uvicorn
import os
import uuid
import json
from datetime import datetime
import sys
from dotenv import load_dotenv
from systems import run_agent
from systems import agents
from systems.OrchestratorSystem import run_orchestrator
import redis
import re
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, ChatMessage
from datetime import UTC
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker as async_sessionmaker
import asyncio

# SQLite file-based database
DATABASE_URL = "sqlite:///./chat_history.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# Replace engine and SessionLocal with async versions
ASYNC_DATABASE_URL = "sqlite+aiosqlite:///./chat_history.db"
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

# Create tables
Base.metadata.create_all(bind=engine)
# import markdown
load_dotenv(override=True)
# Add the current directory to the path to ensure modules can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


# Set up API key for MainAgent
if 'NRP_API_KEY' in os.environ:
    os.environ['OPENAI_API_KEY'] = os.environ['NRP_API_KEY']
    print("Using NRP_API_KEY for OpenAI API calls")
else:
    print("Warning: NRP_API_KEY environment variable is not set. MainAgent may not work properly.")

# Import run_agent function with error handling

# Initialize FastAPI app
app = FastAPI(title="Home Helper")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up templates
templates = Jinja2Templates(directory="templates")

# Simple in-memory storage for chat history
# chat_history = []

# Multi-agent system with media handling capabilities
class MultiAgentSystem:
    def __init__(self):
        """Initialize the multi-agent system"""
        self.run_agent_available = True
        self.db = SessionLocal()
        print(f"MultiAgentSystem initialized with run_agent: {self.run_agent_available}")
        
        # Create necessary directories
        os.makedirs("static/uploads/images", exist_ok=True)
        os.makedirs("static/uploads/videos", exist_ok=True)
    
    def retrieve_history(self):
        """Retrieve conversation history from database"""
        try:
            with SessionLocal() as db:
                # Get all unique session IDs
                sessions = db.query(ChatMessage.session_id).distinct().all()
                return {session[0]: [] for session in sessions}
        except Exception as e:
            print(f"Error retrieving history: {e}")
            return {}

    def save_history(self):
        """Save conversation history to database"""
        try:
            with SessionLocal() as db:
                db.commit()
        except Exception as e:
            print(f"Error saving history: {e}")

    def create_new_conversation(self, title: str = None) -> str:
        """Create a new conversation and return its ID"""
        try:
            session_id = str(uuid.uuid4())
            with SessionLocal() as db:
                # Create initial system message
                db_message = ChatMessage(
                    session_id=session_id,
                    user_message="",
                    agent_response="Hello! I'm your Home Helper. How can I assist you today?",
                    product_links="",
                    files=None,
                    timestamp=datetime.now(UTC)
                )
                db.add(db_message)
                db.commit()
            return session_id
        except Exception as e:
            print(f"Error creating new conversation: {e}")
            return None

    def delete_conversation(self, session_id: str) -> bool:
        """Delete a conversation and its messages"""
        try:
            with SessionLocal() as db:
                # Delete all messages for this session
                db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
                db.commit()
            return True
        except Exception as e:
            print(f"Error deleting conversation: {e}")
            return False

    def get_all_conversations(self):
        """Get all conversations with their metadata"""
        try:
            with SessionLocal() as db:
                # Get unique session IDs
                sessions = db.query(ChatMessage.session_id).distinct().all()
                conversations = []
                
                for session_id in sessions:
                    session_id = session_id[0]  # Extract from tuple
                    # Get first and last message for metadata
                    first_msg = db.query(ChatMessage).filter(
                        ChatMessage.session_id == session_id
                    ).order_by(ChatMessage.timestamp).first()
                    
                    last_msg = db.query(ChatMessage).filter(
                        ChatMessage.session_id == session_id
                    ).order_by(ChatMessage.timestamp.desc()).first()
                    
                    if first_msg and last_msg:
                        conversations.append({
                            "session_id": session_id,
                            "created_at": first_msg.timestamp.isoformat(),
                            "last_updated": last_msg.timestamp.isoformat(),
                            "first_message": first_msg.agent_response,
                            "message_count": db.query(ChatMessage).filter(
                                ChatMessage.session_id == session_id
                            ).count()
                        })
                
                return conversations
        except Exception as e:
            print(f"Error getting all conversations: {e}")
            return []

    def clean_llm_response(self, text):
        # Convert to string if input is a dictionary
        if isinstance(text, dict):
            text = str(text)
        elif isinstance(text, list):
            text = " ".join(str(item) for item in text)
        
        # Remove think tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        
        # Remove any remaining XML-like tags
        text = re.sub(r"<[^>]+>", "", text)
        
        # Remove multiple newlines
        text = re.sub(r"\n\s*\n", "\n\n", text)
        
        # Remove leading/trailing whitespace
        text = text.strip()
        
        return text

    # clean the product links
    def clean_product_links(self, text: str) -> str:
        """Format product links for frontend display"""
        if not text:
            return ""
            
        # If text is already a string, try to parse it as JSON
        if isinstance(text, str):
            try:
                # Try to parse as JSON first
                data = json.loads(text)
                if isinstance(data, list):
                    # If it's a list of results, format each one
                    formatted_links = []
                    for item in data:
                        if isinstance(item, dict):
                            title = item.get('title', '')
                            url = item.get('url', '')
                            description = item.get('description', '')
                            if title and url:
                                formatted_links.append(f"[{title}]({url}): {description}")
                    return "\n".join(formatted_links)
            except json.JSONDecodeError:
                # If not JSON, treat as markdown
                pass
        
        # Handle markdown format
        text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1: \2', text)
        
        # Split into lines and clean each line
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:
                # If line doesn't have a URL, try to extract one
                if 'http' not in line:
                    urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', line)
                    if urls:
                        line = f"{line.split(urls[0])[0].strip()}: {urls[0]}"
                cleaned_lines.append(line)
        
        return "\n".join(cleaned_lines)
    
    async def process_message(self, session_id: str, message: str, files: List[str] = None):
        """Process a message and return the response"""
        try:
            # Get chat history for the current session
            async with AsyncSessionLocal() as db:
                chat_history = (await db.execute(
                    ChatMessage.__table__.select()
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.timestamp.asc())
                )).fetchall()
                
                # Convert chat history to list of dicts
                history_list = []
                for msg in chat_history:
                    history_list.append({
                        'user_message': msg.user_message,
                        'agent_response': msg.agent_response,
                        'timestamp': msg.timestamp.isoformat()
                    })

            # Process any uploaded files
            processed_files = []
            if files:
                for file in files:
                    # Handle both string paths and UploadFile objects
                    if isinstance(file, str):
                        # If it's already a string path, just add it
                        file_path = file
                        file_ext = os.path.splitext(file_path)[1].lower()
                    else:
                        # If it's an UploadFile object, save it
                        file_ext = os.path.splitext(file.filename)[1].lower()
                        file_path = os.path.join('static', 'uploads', 'images' if file_ext in ['.jpg', '.jpeg', '.png'] else 'videos', f"{uuid.uuid4()}{file_ext}")
                        with open(file_path, 'wb') as f:
                            f.write(await file.read())
                    
                    # Add to processed files if it's a supported type
                    if file_ext in ['.jpg', '.jpeg', '.png', '.mp4', '.mov', '.avi']:
                        processed_files.append(file_path)

            # Run the orchestrator in a thread to avoid blocking
            loop = asyncio.get_event_loop()
            response, product_links = await loop.run_in_executor(
                None, 
                run_orchestrator,
                message,
                [f for f in processed_files if f.endswith(('.mp4', '.mov', '.avi'))],
                [f for f in processed_files if f.endswith(('.jpg', '.jpeg', '.png'))],
                history_list
            )

            # Clean and format the response
            cleaned_response = self.clean_llm_response(response)
            cleaned_product_links = self.clean_product_links(product_links)

            # Store the message in the database
            async with AsyncSessionLocal() as db:
                db_message = ChatMessage(
                    session_id=session_id,
                    user_message=message,
                    agent_response=cleaned_response,
                    product_links=cleaned_product_links,
                    files=json.dumps(processed_files) if processed_files else None,
                    timestamp=datetime.now(UTC)
                )
                db.add(db_message)
                await db.commit()

            return {
                "response": cleaned_response,
                "product_links": cleaned_product_links,
                "files": processed_files
            }

        except Exception as e:
            print(f"Error processing message: {e}")
            return {
                "response": "I apologize, but I encountered an error processing your request. Please try again.",
                "product_links": "",
                "files": []
            }

# Initialize the multi-agent system
agent_system = MultiAgentSystem()

# Create necessary directories if they don't exist
os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/uploads/images", exist_ok=True)
os.makedirs("static/uploads/videos", exist_ok=True)

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main chat interface"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat")
async def chat(
    message: str = Form(...),
    session_id: str = Form(...),
    files: List[UploadFile] = File(None)
):
    """Process a chat message and return the response"""
    try:
        uploaded_files = []
        if files:
            for file in files:
                if not file.filename:
                    continue
                file_ext = os.path.splitext(file.filename)[1].lower()
                content_type = file.content_type if hasattr(file, 'content_type') else None
                if content_type and content_type.startswith('image/'):
                    subdir = "uploads/images"
                elif content_type and content_type.startswith('video/'):
                    subdir = "uploads/videos"
                elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                    subdir = "uploads/images"
                elif file_ext in ['.mp4', '.webm', '.ogg', '.mov', '.avi', '.mkv']:
                    subdir = "uploads/videos"
                else:
                    subdir = "uploads"
                os.makedirs(f"static/{subdir}", exist_ok=True)
                unique_filename = f"{uuid.uuid4()}{file_ext}"
                file_path = f"static/{subdir}/{unique_filename}"
                try:
                    with open(file_path, "wb") as f:
                        content = await file.read()
                        f.write(content)
                    uploaded_files.append(file_path)
                except Exception as e:
                    print(f"Error saving file {file.filename}: {e}")
                    continue
        response = await agent_system.process_message(session_id, message, uploaded_files)
        return {
            "text": response["response"],
            "product_links": response["product_links"],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        return {
            "text": "Sorry, there was an error processing your message. Please try again.",
            "product_links": "",
            "timestamp": datetime.now().isoformat()
        }

# @app.get("/chat_history")
# async def get_chat_history():
#     """Return the chat history"""
#     return JSONResponse(content=agent_system.get_chat_history(session_id))
    # return JSONResponse(content=agent_system.get_chat_history_from_redis())

@app.get("/chat_history", response_class=JSONResponse)
async def get_chat_history(session_id: str):
    db = SessionLocal()
    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.timestamp)
        .all()
    )
    return [
        {
            "user_message": m.user_message,
            "agent_response": m.agent_response,
            "product_links": m.product_links,
            "files": json.loads(m.files) if m.files else [],
            "timestamp": m.timestamp.isoformat()
        }
        for m in history
    ]

@app.post("/conversations/new")
async def create_conversation():
    """Create a new conversation"""
    session_id = agent_system.create_new_conversation()
    return {"session_id": session_id}

@app.delete("/conversations/{session_id}")
async def delete_conversation(session_id: str):
    """Delete a conversation"""
    success = agent_system.delete_conversation(session_id)
    if success:
        return {"status": "success"}
    return {"status": "error", "message": "Failed to delete conversation"}

@app.get("/conversations")
async def get_conversations():
    """Get all conversations"""
    conversations = agent_system.get_all_conversations()
    return conversations

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8006)