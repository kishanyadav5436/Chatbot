import os
import sys
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect, url_for
from flask_cors import CORS, cross_origin
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import pymongo
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from authlib.integrations.flask_client import OAuth
from functools import wraps
from nlp_service import intent_classifier
from llm_service import llm_service
from conversation_tracker import conversation_tracker

# --- SETUP ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- Validate and Set Secrets ---
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    logging.warning("JWT_SECRET not set in .env! Using default fallback for development.")
    JWT_SECRET = "default-insecure-dev-secret" 

app = Flask(__name__)
app.secret_key = JWT_SECRET 

from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

import re

# Configure CORS - restricted to known frontend origins
# Regex added to allow any vercel.app subdomain for deployment flexibility
ALLOWED_ORIGINS = [
    "https://inclusionchatbot.vercel.app",
    "https://www.inclusionchatbot.vercel.app",
    "https://chatbot-3-hpx2.onrender.com",
    "http://localhost:5500",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:5500",
    "http://127.0.0.1:5501"
]

# Configure CORS - restricted to known frontend origins
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}}, supports_credentials=True)

# Removed manual preflight handler to let flask-cors handle it

# Rate Limiting (Temporarily disabled for debugging)
# limiter = Limiter(
#     get_remote_address,
#     app=app,
#     default_limits=["200 per day", "50 per hour"],
#     storage_uri="memory://",
#     request_filter=lambda: request.method == "OPTIONS" # Never rate-limit preflight checks
# )
class FakeLimiter:
    def limit(self, *args, **kwargs):
        return lambda f: f
limiter = FakeLimiter()

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "status": "Chatbot API running on port 5056", 
        "version": "1.6-final",
        "routes": ["/api/auth/guest", "/api/chat", "/api/chat/history", "/api/admin/login"]
    })

# --- DATABASE CONNECTION ---
try:
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        logging.error("CRITICAL: MONGO_URI not set! Check your environment variables.")
        if os.getenv("RENDER"):
            db = None
            client = None
        else:
            mongo_uri = "mongodb://localhost:27017/"
            client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
            db = client["inclusivity-chatbot"]
            logging.info("MongoDB connected locally.")
    else:
        # serverSelectionTimeoutMS=5000 — fail fast, don't hang the worker boot
        client = pymongo.MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
            tls=True,
            tlsAllowInvalidCertificates=True
        )
        # Ping to verify connection
        client.admin.command('ping')
        db = client["inclusivity-chatbot"]
        logging.info("MongoDB connected successfully.")

    if db is not None:
        users_collection = db["users"]
        conversations_collection = db["conversations"]
    else:
        users_collection = None
        conversations_collection = None
except Exception as e:
    logging.error(f"Could not connect to MongoDB: {e}")
    client = None
    db = None
    users_collection = None
    conversations_collection = None

# --- OAUTH 2.0 SETUP (FINAL FIX FOR 'iss' CLAIM) ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={'scope': 'openid email profile'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    issuer='https://accounts.google.com',
    # ⭐ CORE FIX: Tell Authlib to ignore the issuer validation during ID Token processing
    resource_server_kwargs={'verify_iss': False} 
)

def retrieve_relevant_data(query, db):
    """Retrieve relevant data from MongoDB datasets using full-text search."""
    if not db:
        return ""
        
    knowledge_parts = []
    try:
        # 1. Clean the query (remove common filler words for better text search)
        stop_words = {"what", "is", "how", "does", "the", "a", "an", "tell", "me", "about", "defined", "meaning"}
        clean_query = " ".join([word for word in query.lower().split() if word not in stop_words])
        if not clean_query: clean_query = query # Fallback if empty
        
        for col_name in ['dei_dataset', 'dei_principles']:
            if col_name not in db.list_collection_names():
                continue
            col = db[col_name]
            # Ensure text index is created on all fields
            try:
                col.create_index([("$**", pymongo.TEXT)], background=True)
            except Exception:
                pass
                
            # Perform text search with the cleaned query
            docs = list(col.find({"$text": {"$search": clean_query}}).limit(3))
            for doc in docs:
                doc.pop("_id", None)  # Remove object IDs
                # Format nicely for the LLM
                parts = [f"{k}: {v}" for k, v in doc.items() if v]
                knowledge_parts.append(" | ".join(parts))
                
    except Exception as e:
        logging.error(f"RAG Retrieval Error: {e}")
        
    if knowledge_parts:
        # Deduplicate and limit
        unique_knowledge = list(set(knowledge_parts))[:5]
        return "Knowledge Base Context:\n" + "\n".join(unique_knowledge)
    return ""

# --- BOT RESPONSE LOGIC (Hybrid ML/LLM) ---
def get_bot_response(classification, user_message, conversation_context=None, db=None, language='en'): 
    # Language mapping for LLM instructions
    lang_names = {
        'en': 'English', 'hi': 'Hindi', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'bn': 'Bengali', 'mr': 'Marathi', 'te': 'Telugu',
        'ta': 'Tamil', 'gu': 'Gujarati', 'kn': 'Kannada', 'ml': 'Malayalam'
    }
    target_lang = lang_names.get(language, 'English')

    # Localized responses for fixed intents
    localized_responses = {
        'en': {
            "greet": "Hello! How can I help you learn about inclusion today?",
            "goodbye": "Bye! Feel free to ask more questions anytime.",
            "thanks": "You're welcome!",
            "ask_diversity": "Diversity is the practice of including people from a range of different social and ethnic backgrounds, genders, sexual orientations, etc.",
            "ask_equity": "Equity is about fairness and justice. Unlike equality, equity gives people what they need to be successful.",
            "ask_inclusion": "Inclusion is the act of creating an environment where every individual feels welcomed, respected, and supported.",
            "ask_accessibility": "Accessibility means designing products, services, or environments for people with disabilities.",
            "ask_bias": "Unconscious bias refers to the stereotypes we have about others without realizing it.",
            "affirm": "I'm glad to hear that!",
            "deny": "Understood. Let me know if you have any other questions."
        },
        'hi': {
            "greet": "नमस्ते! मैं आज आपको समावेश के बारे में सीखने में कैसे मदद कर सकता हूँ?",
            "goodbye": "अलविदा! किसी भी समय और प्रश्न पूछने के लिए स्वतंत्र महसूस करें।",
            "thanks": "आपका स्वागत है!",
            "ask_diversity": "विविधता विभिन्न सामाजिक और जातीय पृष्ठभूमियों, लिंगों, यौन अभिविन्यासों आदि के लोगों को शामिल करने का अभ्यास है।",
            "ask_equity": "समानता निष्पक्षता और न्याय के बारे में है। समानता के विपरीत, निष्पक्षता लोगों को वह देती है जिसकी उन्हें सफल होने के लिए आवश्यकता होती है।",
            "ask_inclusion": "समावेश एक ऐसा वातावरण बनाने का कार्य है जहाँ प्रत्येक व्यक्ति स्वागत, सम्मानित और समर्थित महसूस करता है।",
            "ask_accessibility": "पहुँच का अर्थ है विकलांग लोगों के लिए उत्पादों, सेवाओं या वातावरण को डिजाइन करना।",
            "ask_bias": "अचेतन पूर्वाग्रह उन रूढ़ियों को संदर्भित करता है जो हमारे पास दूसरों के बारे में बिना महसूस किए होती हैं।",
            "affirm": "मुझे यह सुनकर खुशी हुई!",
            "deny": "समझ गया। मुझे बताएं कि क्या आपके पास कोई अन्य प्रश्न हैं।"
        },
        'es': {
            "greet": "¡Hola! ¿Cómo puedo ayudarte a aprender sobre la inclusión hoy?",
            "goodbye": "¡Adiós! Siéntete libre de hacer más preguntas en cualquier momento.",
            "thanks": "¡De nada!",
            "ask_diversity": "La diversidad es la práctica de incluir a personas de diversos orígenes sociales y étnicos, géneros, orientaciones sexuales, etc.",
            "ask_equity": "La equidad se trata de justicia y rectitud. A diferencia de la igualdad, la equidad da a las personas lo que necesitan para tener éxito.",
            "ask_inclusion": "La inclusión es el acto de crear un ambiente donde cada individuo se sienta bienvenido, respetado y apoyado.",
            "ask_accessibility": "La accesibilidad significa diseñar productos, servicios o entornos para personas con discapacidades.",
            "ask_bias": "El sesgo inconsciente se refiere a los estereotipos que tenemos sobre los demás sin darnos cuenta.",
            "affirm": "¡Me alegra saber eso!",
            "deny": "Entendido. Avísame si tienes alguna otra pregunta."
        }
    }
    
    # Get response for the specific language, fallback to LLM if language not in localized_responses
    # OR if the specific intent is not translated.
    lang_responses = localized_responses.get(language, {})
    bot_reply = lang_responses.get(classification)
    
    # If no static response, and it's not English, fallback to LLM
    # (LLM is better at translation than a hardcoded dict for all 12 languages)
    if bot_reply is None and language != 'en':
        # Force LLM for other languages if not in our dict
        classification = "nlu_fallback" 
    elif bot_reply is None:
        # Fallback to English static responses if still nothing (e.g. for unknown language)
        bot_reply = localized_responses['en'].get(classification)
    
    
    if bot_reply is None:
        if llm_service.is_available():
            logging.info(f"ML Fallback: Using Gemini for dynamic response to intent '{classification}'")
            
            # 1. Fetch relevant RAG data from MongoDB
            rag_context = retrieve_relevant_data(user_message, db)
            
            # 2. Build the LLM Context
            llm_context = (
                "You are a highly knowledgeable and friendly inclusion and diversity expert. "
                "Always provide clear, encouraging, and informative answers. Keep your responses concise. "
                f"IMPORTANT: You MUST respond in {target_lang}."
            )
            
            if rag_context:
                logging.info("RAG Context found and injected into LLM prompt.")
                llm_context += f"\n\n{rag_context}"
                
            if conversation_context:
                llm_context += f"\n\nHere is the recent conversation history for context: {conversation_context}"
            
            llm_reply = llm_service.get_generative_response(
                prompt=user_message,
                context=llm_context
            )
            return llm_reply
        else:
            return "I'm sorry, I'm currently unable to process your request. Could you try asking in a different way?"

    return bot_reply

# Helper to generate JWT
def generate_app_token(user_id, email):
    return jwt.encode(
        {"user_id": str(user_id), "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=5)},
        JWT_SECRET,
        algorithm="HS256"
    )

# Decorator to protect routes
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("x-auth-token")
        if not token:
            return jsonify({"msg": "No token, authorization denied"}), 401
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            user_id = ObjectId(payload["user_id"])
            email = payload["email"]
            is_guest = "guest_" in email
        except jwt.ExpiredSignatureError:
            return jsonify({"msg": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"msg": "Token is not valid"}), 401
        except Exception as e:
            logging.error(f"Token validation error: {e}")
            return jsonify({"msg": "Token validation failed"}), 401

        # Pass payload data to the decorated function
        return f(user_id, email, is_guest, *args, **kwargs)
    return decorated

# =============== API ROUTES ===============

@app.route("/api/chat", methods=["POST"])
@token_required
def chat(user_id, email, is_guest):
    # Guest users can chat without DB (no history saved)
    if not is_guest and (client is None or db is None):
        return jsonify({"error": "Database connection unavailable"}), 503

    message = request.json.get("message")
    conversation_id_str = request.json.get("conversationId")
    language = request.json.get("language", "en")
    if not message or not message.strip():
        return jsonify({"error": "No message provided"}), 400

    # Validate message length
    if len(message.strip()) > 1000:
        return jsonify({"error": "Message too long (max 1000 characters)"}), 400

    try:
# Step 1: Predict intent
        intent = intent_classifier.predict(message)
        logging.info(f"User message: '{message}' -> Intent: '{intent}'")
        
        # Step 2: Update conversation tracker
        user_identifier = str(user_id) if not is_guest else email
        conv_map = conversation_tracker.get_map(user_identifier)
        conv_map.add_message(message, intent)
        
        # Step 3: Get context for LLM (optional enhancement)
        context_for_llm = conv_map.get_context_for_llm() if intent == "nlu_fallback" else None
        
        # Step 4: Get the response (passing the original message for LLM fallback and context)
        bot_reply = get_bot_response(intent, message, conversation_context=context_for_llm, db=db, language=language)
        llm_available = llm_service.is_available()
        logging.info(f"LLM available: {llm_available}, Reply length: {len(bot_reply) if bot_reply else 0}, Preview: '{bot_reply[:100] if bot_reply else 'EMPTY'}'")

        if not is_guest:
            conversation_id = ObjectId(conversation_id_str) if conversation_id_str else None
            
            new_messages = [
                {"sender": "user", "content": message, "timestamp": datetime.now(timezone.utc)},
                {"sender": "bot", "content": bot_reply, "timestamp": datetime.now(timezone.utc)}
            ]

            if conversation_id:
                # Append to an existing conversation
                conversations_collection.update_one(
                    {"_id": conversation_id, "userId": user_id},
                    {"$push": {"messages": {"$each": new_messages}}}
                )
                return jsonify({"reply": bot_reply, "conversationId": str(conversation_id)})
            else:
                # Create a new conversation
                # Use the first user message as the title, truncated
                title = (message[:35] + '...') if len(message) > 35 else message

                new_conversation = {
                    "userId": user_id,
                    "title": title,
                    "messages": new_messages,
                    "createdAt": datetime.now(timezone.utc)
                }
                result = conversations_collection.insert_one(new_conversation)
                new_id = result.inserted_id
                return jsonify({
                    "reply": bot_reply, 
                    "conversationId": str(new_id),
                    "title": title
                })

        # For guests, just return the reply without saving
        return jsonify({"reply": bot_reply, "conversationId": None})
    except Exception as e:
        logging.error(f"Error processing chat message: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("10 per minute")
def register():
    # Validate database connection
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    try:
        data = request.json
        if not data:
            return jsonify({"msg": "Request body is required"}), 400

        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"msg": "Email and password are required"}), 400

        # Validate email format
        if not isinstance(email, str) or "@" not in email:
            return jsonify({"msg": "Valid email address is required"}), 400

        # Validate password strength
        if len(password) < 6:
            return jsonify({"msg": "Password must be at least 6 characters long"}), 400

        if users_collection.find_one({"email": email}):
            return jsonify({"msg": "User with this email already exists"}), 400

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user_id = users_collection.insert_one({"email": email, "password": hashed_password, "auth_provider": "email"}).inserted_id
        token = generate_app_token(user_id, email)
        return jsonify({"token": token}), 201
    except Exception as e:
        logging.error(f"Registration error: {e}")
        return jsonify({"msg": "Registration failed"}), 500

@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("15 per minute")
def login():
    # Validate database connection
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    try:
        data = request.json
        if not data:
            return jsonify({"msg": "Request body is required"}), 400

        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"msg": "Email and password are required"}), 400

        # Validate email format
        if not isinstance(email, str) or "@" not in email:
            return jsonify({"msg": "Valid email address is required"}), 400

        user = users_collection.find_one({"email": email})
        if user and user.get("auth_provider") == "email" and bcrypt.checkpw(password.encode('utf-8'), user["password"]):
            token = generate_app_token(user["_id"], user["email"])
            return jsonify({"token": token, "email": user["email"]})
        return jsonify({"msg": "Invalid credentials or user signed up with Google"}), 401
    except Exception as e:
        logging.error(f"Login error: {e}")
        return jsonify({"msg": "Login failed"}), 500
    
@app.route("/api/auth/guest", methods=["POST"])
@limiter.limit("20 per minute")
def guest_login():
    # Guest login does NOT require MongoDB — guests get a JWT-only session
    try:
        guest_id = ObjectId()
        guest_email = f"guest_{guest_id}@chat.local"
        token = generate_app_token(guest_id, guest_email)
        return jsonify({"token": token, "email": guest_email})
    except Exception as e:
        logging.error(f"Guest login error: {e}")
        return jsonify({"msg": "Guest login failed"}), 500

# Support both /api/auth/google (frontend) and /api/auth/google/login (legacy)
@app.route('/api/auth/google')
@app.route('/api/auth/google/login')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/api/auth/google/callback')
def google_callback():
    # Validate database connection
    if client is None or db is None:
        return "Database connection unavailable", 503

    try:
        # Authlib handles the token exchange and validation here.
        # We must authorize the token before accessing user info.
        token = google.authorize_access_token()
        user_info = google.get('userinfo').json() 
        user_email = user_info.get('email')
        
        if not user_email:
            # This happens if the scope/permissions weren't granted or fetched correctly
            return "Could not fetch email from Google.", 400

        user = users_collection.find_one({"email": user_email})
        if not user:
            # Register new user
            user_id = users_collection.insert_one({"email": user_email, "name": user_info.get('name'), "auth_provider": "google"}).inserted_id
            user = users_collection.find_one({"_id": user_id})

        app_token = generate_app_token(user["_id"], user["email"])
        
        # Redirect back to the frontend with the token
        base_frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8000")
        frontend_url = f"{base_frontend_url}?token={app_token}&email={user['email']}"
        return redirect(frontend_url)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logging.error(f"Google OAuth Error Tracker: {error_details}")
        
        # Return generic error - details are in server logs only
        base_frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8000")
        return f'<h1>Authentication Failed</h1><p>Google sign-in could not be completed. Please try again.</p><p><a href="{base_frontend_url}">Return to login</a></p>', 500

@app.route("/api/chat/history", methods=["GET"])
def get_history():
    # Validate database connection
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    token = request.headers.get("x-auth-token")
    if not token:
        return jsonify({"msg": "No token, authorization denied"}), 401

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = ObjectId(payload["user_id"])
        
        # Fetch all conversations for the user, sorted by creation date (newest first)
        conversations = list(conversations_collection.find(
            {"userId": user_id}
        ).sort("createdAt", -1))
        
        # Format the response to match frontend expectations
        history = []
        for conv in conversations:
            history.append({
                "id": str(conv["_id"]),
                "title": conv.get("title", "Untitled"),
                "messages": conv.get("messages", []),
                "createdAt": conv.get("createdAt").isoformat() if conv.get("createdAt") else None
            })
        
        return jsonify({"history": history})
    except jwt.ExpiredSignatureError:
        return jsonify({"msg": "Token has expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"msg": "Token is not valid"}), 401
    except Exception as e:
        logging.error(f"Chat history error: {e}")
        return jsonify({"msg": "Failed to fetch chat history"}), 500

@app.route("/api/chat/history/<conversation_id>", methods=["GET"])
@token_required
def get_conversation_messages(user_id, email, is_guest, conversation_id):
    # Validate database connection
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    try:
        # Fetch the specific conversation
        conversation = conversations_collection.find_one({
            "_id": ObjectId(conversation_id),
            "userId": user_id
        })
        
        if not conversation:
            return jsonify({"msg": "Conversation not found"}), 404
        
        return jsonify({
            "id": str(conversation["_id"]),
            "title": conversation.get("title", "Untitled"),
            "messages": conversation.get("messages", [])
        })
    except Exception as e:
        logging.error(f"Get conversation messages error: {e}")
        return jsonify({"msg": "Failed to fetch conversation messages"}), 500

@app.route("/api/chat/reset", methods=["POST"])
@token_required
def reset_conversation(user_id, email, is_guest):
    """Reset the conversation tracking map for the user."""
    try:
        user_identifier = str(user_id) if not is_guest else email
        conversation_tracker.reset_map(user_identifier)
        return jsonify({"message": "Conversation tracking reset successfully"})
    except Exception as e:
        logging.error(f"Error resetting conversation: {e}")
        return jsonify({"msg": "Failed to reset conversation"}), 500


# Admin email allowlist from environment variable
ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

def is_admin(email):
    """Check if the email is in the admin allowlist."""
    if email == "kishan.admin@inclusivity.ai":
        return True
    return email in ADMIN_EMAILS

@app.route("/api/admin/login", methods=["POST"])
@cross_origin()
def admin_login():
    """Specific admin login endpoint."""
        
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    
    logging.info(f"Admin login attempt for username: {username}")
    
    if username == "kishan" and password == "9236076711@123":
        logging.info("Admin login successful for 'kishan'")
        # Generate token with special admin email
        token = generate_app_token(ObjectId(), "kishan.admin@inclusivity.ai")
        return jsonify({"token": token, "email": "kishan.admin@inclusivity.ai"})
        
    logging.warning(f"Failed admin login attempt for username: {username}")
    return jsonify({"error": "Invalid admin credentials"}), 401

@app.route("/api/admin/load-data", methods=["POST"])
@cross_origin()
@token_required
def load_data(user_id, email, is_guest):
    """Reload data from files (admin only)."""
    if not is_admin(email):
        return jsonify({"error": "Admin only"}), 403
    
    try:
        sys.path.append(os.path.dirname(__file__))
        from data_loader import load_dei_csv, load_principles_csv, load_nlu_yaml, get_mongo_client
        
        db = get_mongo_client()
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        
        if os.path.exists(os.path.join(data_dir, 'DEI Dataset.csv')):
            load_dei_csv(db, os.path.join(data_dir, 'DEI Dataset.csv'))
        
        if os.path.exists(os.path.join(data_dir, 'diversity_equity_inclusion_data.csv')):
            load_principles_csv(db, os.path.join(data_dir, 'diversity_equity_inclusion_data.csv'))
            
        if os.path.exists(os.path.join(data_dir, 'nlu.yml')):
            load_nlu_yaml(db, os.path.join(data_dir, 'nlu.yml'))
            
        return jsonify({"status": "Data reloaded where files existed"})
    except Exception as e:
        logging.error(f"Error loading data: {e}")
        return jsonify({"error": f"Failed: {str(e)}"}), 500


@app.route("/api/admin/append-data", methods=["POST"])
@cross_origin()
@token_required
def append_data(user_id, email, is_guest):
    """Append data from data/ folder (admin only, handles duplicates)."""
    if not is_admin(email):
        return jsonify({"error": "Admin only"}), 403
    
    try:
        sys.path.append(os.path.dirname(__file__))
        from data_loader import load_dei_csv, load_principles_csv, load_nlu_yaml, get_mongo_client
        
        db = get_mongo_client()
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        
        if os.path.exists(os.path.join(data_dir, 'DEI Dataset.csv')):
            load_dei_csv(db, os.path.join(data_dir, 'DEI Dataset.csv'))
        
        if os.path.exists(os.path.join(data_dir, 'diversity_equity_inclusion_data.csv')):
            load_principles_csv(db, os.path.join(data_dir, 'diversity_equity_inclusion_data.csv'))
            
        if os.path.exists(os.path.join(data_dir, 'nlu.yml')):
            load_nlu_yaml(db, os.path.join(data_dir, 'nlu.yml'))
            
        return jsonify({"status": "Data appended successfully where files existed"})
    except Exception as e:
        logging.error(f"Error appending data: {e}")
        return jsonify({"error": f"Failed: {str(e)}"}), 500


@app.route("/api/admin/data", methods=["GET"])
@cross_origin()
@token_required
def get_admin_data(user_id, email, is_guest):
    """Retrieve DEI data with basic search/pagination."""
    if not is_admin(email):
        return jsonify({"error": "Admin only"}), 403
    
    try:
        search = request.args.get("search", "")
        limit = int(request.args.get("limit", 50))
        
        query = {}
        if search:
            query = {"$or": [
                {"Topic": {"$regex": search, "$options": "i"}},
                {"Content": {"$regex": search, "$options": "i"}},
                {"Keywords": {"$regex": search, "$options": "i"}}
            ]}
            
        data = list(db["dei_dataset"].find(query).limit(limit))
        for item in data:
            item["_id"] = str(item["_id"])
            
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/data", methods=["POST"])
@cross_origin()
@token_required
def add_admin_data(user_id, email, is_guest):
    """Add a new DEI record."""
    if not is_admin(email):
        return jsonify({"error": "Admin only"}), 403
    
    try:
        new_record = request.json
        if not new_record.get("Topic") or not new_record.get("Content"):
            return jsonify({"error": "Topic and Content are required"}), 400
            
        result = db["dei_dataset"].insert_one(new_record)
        return jsonify({"status": "Success", "id": str(result.inserted_id)}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/data/<record_id>", methods=["PUT", "DELETE"])
@cross_origin()
@token_required
def manage_admin_data(user_id, email, is_guest, record_id):
    """Update or delete a DEI record."""
    if not is_admin(email):
        return jsonify({"error": "Admin only"}), 403
    
    try:
        if request.method == "DELETE":
            db["dei_dataset"].delete_one({"_id": ObjectId(record_id)})
            return jsonify({"status": "Deleted"})
        
        updated_data = request.json
        updated_data.pop("_id", None)
        db["dei_dataset"].update_one({"_id": ObjectId(record_id)}, {"$set": updated_data})
        return jsonify({"status": "Updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/stats", methods=["GET"])
@cross_origin()
@token_required
def get_admin_stats(user_id, email, is_guest):
    """Get system-wide statistics."""
    if not is_admin(email):
        return jsonify({"error": "Admin only"}), 403
    
    try:
        total_users = users_collection.count_documents({})
        total_convos = conversations_collection.count_documents({})
        
        # Approximate message count
        pipeline = [
            {"$project": {"count": {"$size": "$messages"}}},
            {"$group": {"_id": None, "total": {"$sum": "$count"}}}
        ]
        msg_result = list(conversations_collection.aggregate(pipeline))
        total_messages = msg_result[0]["total"] if msg_result else 0
        
        return jsonify({
            "users": total_users,
            "conversations": total_convos,
            "messages": total_messages,
            "status": "Online"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Log all registered routes for debugging
    print("\n--- REGISTERED ROUTES ---")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule} ({rule.methods})")
    print("-------------------------\n")
    
    port = int(os.environ.get("PORT", 5056))
    app.run(host="0.0.0.0", port=port, debug=False)
