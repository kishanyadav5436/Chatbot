"""
Test script to verify Gemini API configuration
Run this script to check if your GEMINI_API_KEY is working correctly.
"""
import os
import sys

# Add the parent directory to the path so we can import the llm_service
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check if API key is set
api_key = os.getenv("GEMINI_API_KEY")
print(f"API Key present: {api_key is not None}")
if api_key:
    # Show first few and last few characters for verification
    masked_key = api_key[:5] + "..." + api_key[-4:] if len(api_key) > 9 else "***"
    print(f"API Key (masked): {masked_key}")
else:
    print("ERROR: GEMINI_API_KEY is not set in environment variables!")
    print("\nTo fix this:")
    print("1. Open the .env file in backend/.env")
    print("2. Add or update: GEMINI_API_KEY=your_api_key_here")
    print("3. Get your API key from: https://aistudio.google.com/app/apikey")
    sys.exit(1)

# Now test the actual Gemini API
print("\nTesting Gemini API connection...")
try:
    from google import genai
    
    client = genai.Client(api_key=api_key)
    
    # Try a simple request
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Hello, respond with just 'API is working!'"
    )
    
    if response.text:
        print(f"✅ SUCCESS! Gemini API is working correctly!")
        print(f"Response: {response.text}")
    else:
        print("⚠️ WARNING: API returned empty response")
        
except Exception as e:
    print(f"❌ ERROR: Gemini API test failed!")
    print(f"Error type: {type(e).__name__}")
    print(f"Error details: {str(e)}")
    
    # Print more details if available
    import traceback
    print("\nFull traceback:")
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*50)
print("Gemini API configuration test completed!")
