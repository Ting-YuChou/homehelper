import streamlit as st
import io
import base64
from datetime import datetime
from PIL import Image
from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.messages import HumanMessage

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
load_dotenv(override=True)

llm_sources = ["ollama","nautilus"]
global_llm_source = "ollama"  # Default to ollama

def get_llm(model_type):
    global global_llm_source

    models = {"nautilus": {"text": "llama3-sdsc", "vision":"llava-onevision","tools":"groq-tools"},
              "ollama": {"text": "llama3", "vision":"llava","tools":"qwq","embeddings":"nomic-embed-text"}}
    model_name = models[global_llm_source][model_type]
    if global_llm_source == "ollama":
        return ChatOllama(
            model=model_name,
            temperature=0,
        )
    elif global_llm_source == "nautilus":
        return ChatOpenAI(
            openai_api_base="https://llm.nrp-nautilus.io",
            openai_api_key=os.environ.get("NRP_API_KEY"),
            model=model_name,
            temperature=0.2
        )
    else:
        raise ValueError(f"Unknown model type: {model_type}")

llm = get_llm("text")
llm_vision = get_llm("vision")

# Configure page
st.set_page_config(page_title="Echo Chat Bot", layout="centered")

# Minimal styling
st.markdown("""
<style>
    .chat-message {
        padding: 0.75rem;
        border-radius: 0.25rem;
        margin-bottom: 0.5rem;
    }
    .chat-message.user {
        background-color: #0000;
    }
    .chat-message.bot {
        background-color: #0000;
    }
    .chat-message img {
        max-width: 250px;
        border-radius: 0.25rem;
    }
    .stButton button {
        width: 100%;
    }
    div.block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    div.stButton > button {
        margin-top: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "camera_active" not in st.session_state:
    st.session_state.camera_active = False
if "image_process_key" not in st.session_state:
    st.session_state.image_process_key = 0

# Compact title
st.write("### Echo Chat Bot")

# Function to process text input
def send_text():
    message_text = st.session_state.text_input
    if message_text.strip():
        # Format current time
        current_time = datetime.now().strftime("%H:%M")
        
        # Add messages to chat history
        st.session_state.messages.append({
            "role": "user",
            "content": f"<p>{message_text}</p>",
            "timestamp": current_time
        })
        
        st.session_state.messages.append({
            "role": "bot",
            "content": f"<p>{llm.invoke(message_text)}</p>",
            "timestamp": current_time
        })

# Function to toggle camera
def toggle_camera():
    st.session_state.camera_active = not st.session_state.camera_active

# Function to clear chat
def clear_chat():
    st.session_state.messages = []



# Function to process uploaded image
def process_uploaded_image():
    if st.session_state.uploaded_file is not None:
        current_time = datetime.now().strftime("%H:%M")
        
        # Read the file
        image = Image.open(st.session_state.uploaded_file)
        
        # Convert to base64
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Add to chat history
        st.session_state.messages.append({
            "role": "user",
            "content": f'<img src="data:image/jpeg;base64,{img_str}" alt="User image">',
            "timestamp": current_time
        })
        
        st.session_state.messages.append({
            "role": "bot",
            "content": f'<p>Echo image:</p><img src="data:image/jpeg;base64,{img_str}" alt="Echo image">',
            "timestamp": current_time
        })
        
        # Increment process key to prevent repeat processing
        st.session_state.image_process_key += 1

# Function to process camera image
def process_camera_image():
    if st.session_state.camera_image is not None:
        current_time = datetime.now().strftime("%H:%M")
        
        # Read the file
        image = Image.open(st.session_state.camera_image)
        
        # Convert to base64
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Add to chat history
        st.session_state.messages.append({
            "role": "user",
            "content": f'<img src="data:image/jpeg;base64,{img_str}" alt="Camera image">',
            "timestamp": current_time
        })
        image_part = {
        "type": "image_url",
        "image_url": f"data:image/jpeg;base64,{img_str}",
        }
        text_part = {
        "type": "text","text": "give a detailed description of all the objects in the image, with finer details about each like what kind of prodict, what is the model type, model number, if you can find it, else say wasn't able to find out.",
        }
        messages = [HumanMessage(content = [image_part, text_part])]
        st.session_state.messages.append({
            "role": "bot",
            "content": f'<p>{llm_vision.invoke(messages)}</p>',
            "timestamp": current_time
        })
        
        # Reset camera and increment process key
        st.session_state.camera_active = False
        st.session_state.image_process_key += 1

# Display chat history
for message in st.session_state.messages:
    role = message["role"]
    content = message["content"]
    timestamp = message["timestamp"]
    
    st.markdown(f"""
    <div class="chat-message {role}">
        {content}
        <div style="font-size:0.7rem; text-align:right;">{timestamp}</div>
    </div>
    """, unsafe_allow_html=True)

# Input container
with st.container():
    # Text input with send button
    col1, col2 = st.columns([4, 1])
    with col1:
        st.text_input("Message", key="text_input", on_change=send_text)
    with col2:
        st.button("Send", on_click=send_text)
    
    # Image options
    img_col1, img_col2 = st.columns(2)
    
    with img_col1:
        # Use a key that includes the process key to force widget recreation
        uploaded_file = st.file_uploader(
            "Upload image", 
            type=["jpg", "jpeg", "png"], 
            label_visibility="collapsed",
            key=f"uploader_{st.session_state.image_process_key}"
        )
        
        # Store uploaded file in session state and process directly
        if uploaded_file is not None:
            st.session_state.uploaded_file = uploaded_file
            process_uploaded_image()
    
    with img_col2:
        st.button("📷 Camera" if not st.session_state.camera_active else "❌ Close", on_click=toggle_camera)
    
    if st.session_state.camera_active:
        # Use a key that includes the process key
        camera_image = st.camera_input(
            "Take a picture", 
            label_visibility="collapsed",
            key=f"camera_{st.session_state.image_process_key}"
        )
        
        # Store camera image in session state and process directly
        if camera_image is not None:
            st.session_state.camera_image = camera_image
            process_camera_image()

# Clear chat button at the bottom
st.button("Clear Chat", on_click=clear_chat)