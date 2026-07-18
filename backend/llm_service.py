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
    Service class for Google Gemini API (google-genai v2 SDK).
    Automatically falls back through model list on quota/not-found errors.
    No startup probe — saves quota for real user requests.
    """

    # All models compatible with google-genai v2 SDK
    MODELS = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = None
        self.active_model = None

        if not self.api_key:
            logging.error("GEMINI_API_KEY is not set. AI responses will be unavailable.")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
            self.active_model = self.MODELS[0]  # start with best model
            logging.info(f"Gemini client ready. Default model: {self.active_model}")
        except Exception as e:
            logging.error(f"Gemini client init failed: {e}")
            self.client = None

    def is_available(self):
        return self.client is not None

    def get_generative_response(self, prompt, context="You are a helpful inclusive chatbot."):
        if not self.is_available():
            return "AI service unavailable. Please ensure GEMINI_API_KEY is set correctly."
        return self._generate_with_fallback(prompt, context)

    def _generate_with_fallback(self, prompt, context):
        """Try each model in sequence until one works."""
        full_prompt = f"{context}\n\nUser: {prompt}"

        for model in self.MODELS:
            try:
                logging.info(f"Trying Gemini model: {model}")
                response = self.client.models.generate_content(
                    model=model,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=1024
                    )
                )
                if response and hasattr(response, "text") and response.text:
                    self.active_model = model
                    logging.info(f"Response from {model}: OK")
                    return response.text.strip()

            except Exception as e:
                err = str(e).upper()

                if "RESOURCE_EXHAUSTED" in err or "429" in err:
                    logging.warning(f"{model}: Quota exhausted → trying next model")
                    time.sleep(1)
                    continue

                if "NOT_FOUND" in err or "404" in err:
                    logging.warning(f"{model}: Not found → trying next model")
                    continue

                if "INVALID_ARGUMENT" in err or "400" in err:
                    logging.warning(f"{model}: Invalid argument → trying next model")
                    continue

                logging.error(f"{model}: Unexpected error: {e} → trying next model")
                time.sleep(1)
                continue

        logging.error("All Gemini models failed.")
        return "I'm temporarily unavailable due to API limits. Please try again shortly."


# Shared singleton
llm_service = LLMService()
