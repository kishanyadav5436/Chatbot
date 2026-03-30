import os
import logging
import time
import asyncio
from google import genai
from google.genai import types # Required for modern type handling
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

class LLMService:
    """
    Service class for interacting with Google Gemini API (2026 production-ready).
    """
    def __init__(self):
        # Uses standard environment variable GEMINI_API_KEY
        self.api_key = os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            logging.error("GEMINI_API_KEY is not set in environment.")
            self.client = None
        else:
            try:
                # Initialize using the modern Client object
                self.client = genai.Client(api_key=self.api_key)
                logging.info("Gemini 3 client initialized successfully.")
            except Exception as e:
                logging.error(f"Gemini initialization failed: {e}")
                self.client = None

    def is_available(self):
        return self.client is not None

    def get_generative_response(self, prompt, context="You are a helpful and inclusive chatbot."):
        """
        ⭐ CONCURRENCY UPGRADE: Synchronous wrapper offloads blocking Gemini call 
        to asyncio thread pool → non-blocking for concurrent requests!
        """
        if not self.is_available():
            return "AI service unavailable."
        
        try:
            # Offload sync Gemini call to thread → Flask stays responsive
            loop = asyncio.get_event_loop()
            return loop.run_in_executor(None, self._generate_content_sync, prompt, context)
        except RuntimeError:
            # Fallback for pure sync contexts
            return self._generate_content_sync(prompt, context)
    
    def _generate_content_sync(self, prompt, context):
        """
        Pure sync Gemini implementation (thread-safe).
        """
        model_name = "gemini-3-flash-preview" 
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=f"{context}\n\n{prompt}",
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        thinking_config=types.ThinkingConfig(
                            thinking_level="low"
                        )
                    )
                )

                if response and hasattr(response, "text"):
                    return response.text.strip()
                return "No response generated."

            except Exception as e:
                error_str = str(e).upper()
                if "RESOURCE_EXHAUSTED" in error_str or "LIMIT: 0" in error_str:
                    logging.error("Gemini quota exhausted.")
                    return "Gemini quota exhausted. Please wait for reset."
                if "429" in error_str and attempt < max_retries - 1:
                    wait_time = 3 * (2 ** attempt)
                    logging.warning(f"Rate limit hit. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                logging.error(f"Gemini error: {e}")
                return f"AI temporarily unavailable: {e}"

        return "Unable to generate response after retries."

# Shared instance for use throughout the app
llm_service = LLMService()

