import os
import logging
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

class LLMService:
    """
    Service class for interacting with Google Gemini API.
    Tries models in order: gemini-2.0-flash → gemini-1.5-flash → gemini-1.5-pro
    """

    # Model priority list — first available/working one wins
    MODELS = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro",
    ]

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.active_model = None
        self.client = None

        if not self.api_key:
            logging.error("GEMINI_API_KEY is not set in environment variables.")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
            # Probe models to find a working one
            self.active_model = self._probe_model()
            if self.active_model:
                logging.info(f"Gemini client ready. Active model: {self.active_model}")
            else:
                logging.error("No working Gemini model found during probe.")
                self.client = None
        except Exception as e:
            logging.error(f"Gemini client initialization failed: {e}")
            self.client = None

    def _probe_model(self):
        """Try each model with a tiny test prompt to find one that works."""
        for model in self.MODELS:
            try:
                resp = self.client.models.generate_content(
                    model=model,
                    contents="Hi",
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=5
                    )
                )
                if resp and hasattr(resp, "text"):
                    logging.info(f"Model probe success: {model}")
                    return model
            except Exception as e:
                logging.warning(f"Model {model} unavailable: {e}")
                continue
        return None

    def is_available(self):
        return self.client is not None and self.active_model is not None

    def get_generative_response(self, prompt, context="You are a helpful and inclusive chatbot."):
        """Generate a response using the active Gemini model."""
        if not self.is_available():
            return "AI service is currently unavailable. Please try again later."
        return self._generate_content_sync(prompt, context)

    def _generate_content_sync(self, prompt, context):
        """Synchronous Gemini API call with retry and model fallback."""
        full_prompt = f"{context}\n\nUser: {prompt}"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.active_model,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=1024
                    )
                )
                if response and hasattr(response, "text") and response.text:
                    return response.text.strip()
                return "I couldn't generate a response. Please try again."

            except Exception as e:
                error_str = str(e).upper()

                # Quota exhausted — no point retrying
                if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                    if attempt < max_retries - 1:
                        wait = 4 * (2 ** attempt)
                        logging.warning(f"Rate limit hit on {self.active_model}. Retrying in {wait}s...")
                        time.sleep(wait)
                        continue
                    # Try falling back to next model
                    logging.error("Quota exhausted on active model. Trying fallback model...")
                    fallback = self._try_fallback_model()
                    if fallback:
                        self.active_model = fallback
                        return self._generate_content_sync(prompt, context)
                    return "Gemini API quota exhausted. Please try again later."

                # Model not found — switch to next
                if "NOT_FOUND" in error_str or "404" in error_str or "INVALID_ARGUMENT" in error_str:
                    logging.error(f"Model {self.active_model} not found. Switching...")
                    fallback = self._try_fallback_model()
                    if fallback:
                        self.active_model = fallback
                        return self._generate_content_sync(prompt, context)
                    return "AI model unavailable. Please contact support."

                logging.error(f"Gemini error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue

        return "Unable to generate a response after multiple attempts."

    def _try_fallback_model(self):
        """Find the next working model after the current active one fails."""
        current_idx = self.MODELS.index(self.active_model) if self.active_model in self.MODELS else -1
        for model in self.MODELS[current_idx + 1:]:
            try:
                resp = self.client.models.generate_content(
                    model=model,
                    contents="Hi",
                    config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=5)
                )
                if resp and hasattr(resp, "text"):
                    logging.info(f"Fallback model selected: {model}")
                    return model
            except Exception as e:
                logging.warning(f"Fallback model {model} also failed: {e}")
        return None


# Shared singleton instance
llm_service = LLMService()
