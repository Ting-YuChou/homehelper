# video_agent.py

import torch
import cv2
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration
from systems.agents.tools.llm_config import config
from langchain_core.messages import HumanMessage, AIMessage
import requests
import io
import base64
from dotenv import load_dotenv
import os
load_dotenv()
NRP_API_KEY = os.environ.get("NRP_API_KEY", "")
NRP_API_URL = "https://llm.nrp-nautilus.io/v1/chat/completions"


video_llm = config.get_llm("tool_use")

# BLIP setup
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to(device)

def extract_keyframes(video_path, interval=15, max_frames=20):
    """Extract keyframes from video with error handling"""
    try:
        frames = []
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
        
        total = 0
        while True:
            success, frame = cap.read()
            if not success:
                break
            if total % interval == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(Image.fromarray(rgb))
                if len(frames) >= max_frames:
                    break
            total += 1
        cap.release()
        return frames
    except Exception as e:
        print(f"Error extracting keyframes: {e}")
        return []

def caption_with_llm(base64_image):

    prompt = (
        "Describe the image in detail. Make sure to include all the details of the image."
    )

    payload = {
        "model": "llama3",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }
        ],
        "temperature": 0.3,
        "max_tokens": 400
    }

    headers = {
        "Authorization": f"Bearer {NRP_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(NRP_API_URL, headers=headers, json=payload)
    try:
        response = response.json()
        print(response)
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Feature Extraction Error] {e}"



def caption_with_blip(image):
    """Generate caption for an image with error handling"""
    try:
        inputs = processor(images=image, return_tensors="pt").to(device)
        output = blip_model.generate(**inputs)
        return processor.decode(output[0], skip_special_tokens=True)
    except Exception as e:
        print(f"Error generating caption: {e}")
        return "Failed to generate caption"

def caption_video_frames(frames,fun=None):
    """Caption all video frames with error handling"""
    captions = []
    print(len(frames)," frame count")
    for i, frame in enumerate(frames):
        try:
            caption = caption_with_blip(frame)
              # Save to buffer as PNG
            if(i%10==0):
                buffer = io.BytesIO()
                frame.save(buffer, format="PNG")
                buffer.seek(0)
                # Encode buffer to Base64 string
                img_b64 = base64.b64encode(buffer.read()).decode("utf-8")
                caption2 = caption_with_llm(img_b64)
                caption = "blip2: " + caption + " llama3: " + caption2

            print(f"[Frame {i}] {caption}")
            captions.append(caption)
        except Exception as e:
            print(f"Failed on frame {i}: {e}")
            captions.append("Failed to process frame")
    return captions

def summarize_video(video_path,fun=None):
    """Summarize video content using visual information only"""
    try:
        # Visual Analysis
        frames = extract_keyframes(video_path)
        if not frames:
            return "Error: Could not extract frames from video"
        
        visual_captions = caption_video_frames(frames,fun)
        visual_text = " ".join(visual_captions)

        # Generate summary from visual content
        combined_input = f"Visual context: {visual_text}\n\n  The visual context is the guesses of the llm about each frame, make a smart summary of the issue shown in this home repair video. Make sure to identify the appliance and the problem.."

        summary = video_llm.invoke([HumanMessage(content=combined_input)])
        return AIMessage(content=summary.content).content
    except Exception as e:
        print(f"Error summarizing video: {e}")
        return f"Error processing video: {str(e)}"