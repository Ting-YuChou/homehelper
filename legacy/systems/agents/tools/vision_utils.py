"""
Vision utilities module for Home Helper.

This module provides image analysis and processing functions for the Home Helper system,
including appliance identification, feature extraction, and problem detection.
"""

import base64
import os
import requests

# API configuration
NRP_API_KEY = os.getenv("NRP_API_KEY", "")
NRP_API_URL = "https://llm.nrp-nautilus.io/v1/chat/completions"

# Define exports
__all__ = [
    'analyze_image',
    'detect_problem_from_image_and_text',
    'is_low_confidence_response',
    'retry_problem_detection',
    'scan_image_features'
]

def analyze_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {NRP_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama3",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Please make a concise list of the product (brand, model, etc.)"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.3,
        "max_tokens": 512,
        "stream": False
    }

    response = requests.post(NRP_API_URL, headers=headers, json=payload)
    try:
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Error parsing response] {e}"


def detect_problem_from_image_and_text(image_path: str, text_description: str, appliance_info: str, extracted_features: str) -> str:
    prompt = (
        f"The user provided this image of an appliance and reported the following issue:\n"
        f"➡️ {text_description}\n\n"
        f"Based on the image and these known details:\n"
        f"- Appliance Info: {appliance_info or 'Unknown'}\n"
        f"- Visible Features: {extracted_features or 'None'}\n\n"
        f"Please infer the most likely problem and ask a relevant question to help the user diagnose the issue."
    )

    with open(image_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode("utf-8")

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
        "temperature": 0.4,
        "max_tokens": 512,
        "stream": False
    }

    headers = {
        "Authorization": f"Bearer {NRP_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(NRP_API_URL, headers=headers, json=payload)
    try:
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Diagnosis Error] {e}"


def is_low_confidence_response(response: str) -> bool:
    response_lower = response.lower()
    return any(phrase in response_lower for phrase in [
        "not sure", "can't determine", "unable to tell", "hard to say", "unclear", "no visible problem"
    ]) or len(response.strip()) < 20

def retry_problem_detection(image_path: str, text_description: str) -> str:
    prompt = (
        f"Try again to infer the problem with this appliance based on the image and the issue described:\n\n"
        f"{text_description}\n\n"
        f"If uncertain, consider suggesting what the user could check next."
    )

    with open(image_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode("utf-8")

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
        "temperature": 0.5,
        "max_tokens": 512
    }

    headers = {
        "Authorization": f"Bearer {NRP_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(NRP_API_URL, headers=headers, json=payload)
    try:
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Fallback Error] {e}"

def scan_image_features(image_path: str) -> str:
    with open(image_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        "Please analyze this appliance image and list any visible features, labels, or text.\n"
        "This might include water dispensers, digital panels, control knobs, stickers, etc.\n"
        "Keep it concise and useful."
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
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Feature Extraction Error] {e}"
