# train_critic.py
from transformers import T5ForConditionalGeneration, T5Tokenizer, Trainer, TrainingArguments
import json
import torch
from torch.utils.data import Dataset
import pandas as pd
import os
from pathlib import Path

class CriticDataset(Dataset):
    def __init__(self, data_file, tokenizer, max_length=512):
        self.tokenizer = tokenizer
        self.max_length = max_length
        
        # Load data
        with open(data_file, 'r') as f:
            data = json.load(f)
        
        self.examples = []
        
        for item in data:
            # Format input with more concise structure
            context = " | ".join(item["context"]) if item["context"] else "No context"
            
            # Truncate context if too long (leave room for other components)
            max_context_length = 200  # Adjust this value based on your needs
            if len(context) > max_context_length:
                context = context[:max_context_length] + "..."
            
            input_text = f"Question: {item['question']}\nContext: {context}\nAnswer: {item['answer']}\nRationale: {item['rationale']}\nIs this answer sufficient?"
            
            # Format output
            output_text = item["label"]  # "Accept" or "Reject"
            
            self.examples.append({
                "input_text": input_text.strip(),
                "output_text": output_text
            })
    
    def __len__(self):
        return len(self.examples)
    
    def __getitem__(self, idx):
        example = self.examples[idx]
        
        # Tokenize with proper truncation
        input_encoding = self.tokenizer(
            example["input_text"],
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt"
        )
        
        # For output, we only need a short sequence
        output_encoding = self.tokenizer(
            example["output_text"],
            max_length=10,  # Short output
            padding="max_length",
            truncation=True,
            return_tensors="pt"
        )
        
        return {
            "input_ids": input_encoding.input_ids.flatten(),
            "attention_mask": input_encoding.attention_mask.flatten(),
            "labels": output_encoding.input_ids.flatten()
        }

def train_critic_model():
    # Create directories
    Path("models/critic_model").mkdir(parents=True, exist_ok=True)
    Path("results").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    
    # Initialize tokenizer and model
    model_name = "google/flan-t5-small"  # or small
    tokenizer = T5Tokenizer.from_pretrained(model_name)
    model = T5ForConditionalGeneration.from_pretrained(model_name)
    
    # Load dataset
    train_dataset = CriticDataset("data/training/critic_training_data.json", tokenizer)
    
    # Training arguments
    training_args = TrainingArguments(
        output_dir="./results",
        num_train_epochs=10,
        per_device_train_batch_size=8,
        save_steps=1000,
        save_total_limit=2,
        warmup_steps=1000,
        logging_dir="./logs",
    )
    
    # Initialize trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
    )
    
    # Train model
    trainer.train()
    
    # Save model
    model.save_pretrained("./models/critic_model")
    tokenizer.save_pretrained("./models/critic_model")
    
    print("Critic model training complete. Model saved to ./models/critic_model")

if __name__ == "__main__":
    train_critic_model()