import os
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect, url_for
from flask_cors import CORS
import pymongo
import bcrypt
import jwt
from datetime import datetime, timedelta
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

# Configure CORS
CORS(app, origins=[ "https://inclusionchatbot.vercel.app","http://localhost:8000", "http://localhost:*", "http://127.0.0.1:*", "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5500", "http://127.0.0.1:5500", "file://*", "null"], supports_credentials=True)

@app.route('/', methods=['GET'])
def root():
    return jsonify({"status": "Chatbot API running on port 5056", "routes": ["/api/auth/guest", "/api/chat", "/api/chat/history"]})

# --- DATABASE CONNECTION ---
try:
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        logging.warning("MONGO_URI not set in .env! Using default localhost URI.")
        mongo_uri = "mongodb://localhost:27017/"

    client = pymongo.MongoClient(mongo_uri)
    db = client["inclusivity-chatbot"]
    users_collection = db["users"]
    conversations_collection = db["conversations"]
    logging.info("MongoDB connected successfully.")
except Exception as e:
    logging.error(f"Could not connect to MongoDB: {e}")
    client = None
    db = None

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

# --- BOT RESPONSE LOGIC (Hybrid ML/LLM) ---
def get_bot_response(classification, user_message): 
    responses = {
        "greet": "Hello! How can I help you learn about inclusion today?",
        "goodbye": "Bye! Feel free to ask more questions anytime.",
        "thanks": "You're welcome!",
        "ask_diversity": "Diversity is the practice of including people from a range of different social and ethnic backgrounds, genders, sexual orientations, etc.",
        "ask_equity": "Equity is about fairness and justice. Unlike equality, equity gives people what they need to be successful.",
        "ask_inclusion": "Inclusion is the act of creating an environment where every individual feels welcomed, respected, and supported.",
        "ask_accessibility": "Accessibility means designing products, services, or environments for people with disabilities.",
        "ask_bias": "Unconscious bias refers to the stereotypes we have about others without realizing it.",
        "affirm": "I'm glad to hear that!",
        "deny": "Understood. Let me know if you have any other questions.",
        "nlu_fallback": None 
    }
    
    bot_reply = responses.get(classification)
    
    if bot_reply is None:
        if llm_service.is_available():
            logging.info(f"ML Fallback: Using Gemini for dynamic response to intent '{classification}'")
            
            llm_context = (
                "You are a highly knowledgeable and friendly inclusion and diversity expert. "
                "Always provide clear, encouraging, and informative answers. Keep your responses concise."
            )
            
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
        {"user_id": str(user_id), "email": email, "exp": datetime.utcnow() + timedelta(hours=5)},
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
    # Validate database connection
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    message = request.json.get("message")
    conversation_id_str = request.json.get("conversationId")
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
        
        # Step 4: Get the response (passing the original message for LLM fallback)
        bot_reply = get_bot_response(intent, message)
        llm_available = llm_service.is_available()
        logging.info(f"LLM available: {llm_available}, Reply length: {len(bot_reply) if bot_reply else 0}, Preview: '{bot_reply[:100] if bot_reply else 'EMPTY'}'")

        if not is_guest:
            conversation_id = ObjectId(conversation_id_str) if conversation_id_str else None
            
            new_messages = [
                {"sender": "user", "content": message, "timestamp": datetime.utcnow()},
                {"sender": "bot", "content": bot_reply, "timestamp": datetime.utcnow()}
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
                    "createdAt": datetime.utcnow()
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

@app.route("/api/auth/register", methods=["POST"])
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
def guest_login():
    # Validate database connection
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    try:
        guest_id = ObjectId()
        guest_email = f"guest_{guest_id}@chat.local"
        token = generate_app_token(guest_id, guest_email)
        return jsonify({"token": token, "email": guest_email})
    except Exception as e:
        logging.error(f"Guest login error: {e}")
        return jsonify({"msg": "Guest login failed"}), 500

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
        logging.error(f"Google OAuth Error: {e}")
        # Return a simple, safe error message to the client
        return "An error occurred during Google authentication. Please check logs for details.", 500

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


@app.route("/api/admin/load-data", methods=["POST"])
@token_required
def load_data(user_id, email, is_guest):
    """Reload data from files (admin only)."""
    if "admin" not in email:
        return jsonify({"error": "Admin only"}), 403
    
    sys.path.append(os.path.dirname(__file__))
    from data_loader import load_dei_csv, load_principles_csv, load_nlu_yaml, get_mongo_client, append_data_from_folder
    
    db = get_mongo_client()
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    
    load_dei_csv(db, os.path.join(data_dir, 'DEI Dataset.csv'))
    load_principles_csv(db, os.path.join(data_dir, 'diversity_equity_inclusion_data.csv'))
    load_nlu_yaml(db, os.path.join(data_dir, 'nlu.yml'))
    
    return jsonify({"status": "Data reloaded successfully"})


@app.route("/api/admin/append-data", methods=["POST"])
@token_required
def append_data(user_id, email, is_guest):
    """Append data from data/ folder (admin only, handles duplicates)."""
    if "admin" not in email:
        return jsonify({"error": "Admin only"}), 403
    
    sys.path.append(os.path.dirname(__file__))
    from data_loader import append_data_from_folder, get_mongo_client
    
    db = get_mongo_client()
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    
    append_data_from_folder(db, data_dir)
    
    return jsonify({"status": "Data appended successfully from data/ folder"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5056))
    app.run(host="0.0.0.0", port=port, debug=False)
