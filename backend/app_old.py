# app.py

import os
import shutil
import logging
import csv
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect, url_for
from flask_cors import CORS
import pymongo
import bcrypt
import jwt
from datetime import datetime, timedelta
from bson import ObjectId
from authlib.integrations.flask_client import OAuth
from sentence_transformers import SentenceTransformer, util
import torch
from functools import wraps

# Local Service Imports
from nlp_service import intent_classifier
from llm_service import llm_service

# --- SETUP ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- PATH SETUP ---
_basedir = os.path.abspath(os.path.dirname(__file__))

# Load DEI data
dei_data = []
try:
    with open(os.path.join(_basedir, 'data', 'diversity_equity_inclusion_data.csv'), 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dei_data.append(row)
    logging.info(f"Loaded {len(dei_data)} DEI entries.")
except Exception as e:
    logging.error(f"Failed to load DEI data: {e}")
    dei_data = []

# --- SEMANTIC SEARCH SETUP (Sentence Transformer) ---
embedding_model = None
dei_embeddings = None

if dei_data:
    try:
        logging.info("Loading multilingual sentence transformer model...")
        # Using a pre-trained model that's good for semantic search in many languages
        embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        logging.info("Model loaded. Creating embeddings for DEI data...")
        dei_instructions = [row['instruction'] for row in dei_data]
        dei_embeddings = embedding_model.encode(dei_instructions, convert_to_tensor=True)
        logging.info(f"Embeddings created for {len(dei_instructions)} DEI entries.")
    except Exception as e:
        logging.error(f"Failed to load sentence transformer model or create embeddings: {e}")

# Validate JWT Secret and set Flask secret key
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    logging.error("JWT_SECRET environment variable is not set!")
    raise ValueError("JWT_SECRET is required for security.")

app = Flask(__name__)
app.secret_key = JWT_SECRET # Use the validated secret

# Configure CORS to allow requests from frontend
CORS(app, origins=[
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
], supports_credentials=True)

# --- DATABASE CONNECTION ---
try:
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        logging.error("MONGO_URI environment variable is not set")
        raise ValueError("MONGO_URI is required")

    client = pymongo.MongoClient(mongo_uri)
    db = client["inclusivity-chatbot"]
    users_collection = db["users"]
    conversations_collection = db["conversations"]
    logging.info("MongoDB connected successfully.")
except Exception as e:
    logging.error(f"Could not connect to MongoDB: {e}")
    client = None
    db = None


# --- OAUTH 2.0 SETUP ---
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
    issuer='https://accounts.google.com'
)

# --- BOT RESPONSE LOGIC (Hybrid ML/LLM) ---
def get_bot_response(classification, user_message, lang='en'):
    """
    Determines the response: first checking ML, then falling back to LLM or DEI data.
    """
    # Multi-language responses
    canned_responses = {
        'en': {
            "greet": "Hello! How can I help you learn about inclusion today?",
            "goodbye": "Bye! Feel free to ask more questions anytime.",
            "thanks": "You're welcome!",
            "ask_diversity": "Diversity is the practice of including people from a range of different social and ethnic backgrounds, genders, sexual orientations, etc.",
            "ask_equity": "Equity is about fairness and justice. Unlike equality, equity gives people what they need to be successful.",
            "ask_inclusion": "Inclusion is the act of creating an environment where every individual feels welcomed, respected, and supported.",
            "ask_accessibility": "Accessibility means designing products, services, or environments for people with disabilities.",
            "ask_bias": "Unconscious bias refers to the stereotypes we have about others without realizing it.",
            "ask_data_inclusion": "Inclusive data modeling ensures fields are flexible, non-mandatory where possible, and support diverse human experiences, like name formats or non-binary gender options.",
            "ask_name_fields": "Avoid forcing 'First Name' and 'Last Name.' Use a single 'Full Name' field and allow for preferred names and cultural naming conventions.",
            "ask_gender_fields": "Offer a free-text 'Gender Identity' field or use options like 'Man,' 'Woman,' 'Non-Binary,' and 'Prefer not to say.' Never conflate gender with sex.",
            "affirm": "I'm glad to hear that!",
            "deny": "Understood. Let me know if you have any other questions.",
            "nlu_fallback": None
        },
        'hi': {
            "greet": "नमस्ते! मैं आज समावेशन के बारे में जानने में आपकी कैसे मदद कर सकता हूँ?",
            "goodbye": "अलविदा! आप किसी भी समय और प्रश्न पूछ सकते हैं।",
            "thanks": "आपका स्वागत है!",
            "ask_diversity": "विविधता का अर्थ है विभिन्न सामाजिक और जातीय पृष्ठभूमि, लिंग, यौन रुझान आदि के लोगों को शामिल करने की प्रथा।",
            "ask_equity": "इक्विटी का संबंध निष्पक्षता और न्याय से है। समानता के विपरीत, इक्विटी लोगों को वह देती है जिसकी उन्हें सफल होने के लिए आवश्यकता होती है।",
            "ask_inclusion": "समावेशन एक ऐसा वातावरण बनाने का कार्य है जहाँ प्रत्येक व्यक्ति का स्वागत, सम्मान और समर्थन महसूस होता है।",
            "ask_accessibility": "सरल पहुंच का अर्थ है विकलांग लोगों के लिए उत्पादों, सेवाओं या वातावरणों को डिजाइन करना।",
            "ask_bias": "अचेतन पूर्वाग्रह उन रूढ़ियों को संदर्भित करता है जो हम दूसरों के बारे में बिना महसूस किए रखते हैं।",
            "affirm": "मुझे यह सुनकर खुशी हुई!",
            "deny": "समझ गया। यदि आपके कोई अन्य प्रश्न हैं तो मुझे बताएं।",
            "nlu_fallback": None
        },
        'bn': {
            "greet": "নমস্কার! আমি আজ আপনাকে অন্তর্ভুক্তি সম্পর্কে জানতে কীভাবে সাহায্য করতে পারি?",
            "goodbye": "বিদায়! যেকোনো সময় আরও প্রশ্ন করতে পারেন।",
            "thanks": "আপনাকে স্বাগতম!",
            "ask_diversity": "বৈচিত্র্য হল বিভিন্ন সামাজিক ও জাতিগত পটভূমি, লিঙ্গ, যৌন অভিমুখিতা ইত্যাদি থেকে মানুষকে অন্তর্ভুক্ত করার অনুশীলন।",
            "ask_equity": "সমতা মানে ন্যায্যতা এবং ন্যায়বিচার। সমতার বিপরীতে, সমতা মানুষকে সফল হওয়ার জন্য যা প্রয়োজন তা দেয়।",
            "ask_inclusion": "অন্তর্ভুক্তি এমন একটি পরিবেশ তৈরি করার কাজ যেখানে প্রত্যেক ব্যক্তি স্বাগত, সম্মানিত এবং সমর্থিত বোধ করে।",
            "affirm": "আমি এটা শুনে আনন্দিত!",
            "deny": "বুঝেছি। আপনার যদি অন্য কোন প্রশ্ন থাকে তবে আমাকে জানান।",
            "nlu_fallback": None
        },
        'ta': {
            "greet": "வணக்கம்! இன்று உள்ளடக்கம் பற்றி அறிய நான் உங்களுக்கு எப்படி உதவ முடியும்?",
            "goodbye": "വിടைகிறேன்! எப்போது வேண்டுமானாலும் மேலும் கேள்விகளைக் கேட்கலாம்.",
            "thanks": "நல்வரவு!",
            "ask_diversity": "பன்முகத்தன்மை என்பது பல்வேறு சமூக மற்றும் இனப் பின்னணிகள், பாலினங்கள், பாலியல் சார்புகள் போன்றவற்றிலிருந்து மக்களை உள்ளடக்கிய நடைமுறையாகும்.",
            "ask_equity": "சமபங்கு என்பது நேர்மை மற்றும் நீதியைப் பற்றியது. சமத்துவத்தைப் போலல்லாமல், சமபங்கு மக்களுக்கு அவர்கள் வெற்றிபெறத் தேவையானதை வழங்குகிறது.",
            "ask_inclusion": "உள்ளடக்கம் என்பது ஒவ்வொரு தனிநபரும் வரவேற்கப்பட்ட, மதிக்கப்படும் மற்றும் ஆதரிக்கப்படும் ஒரு சூழலை உருவாக்கும் செயலாகும்.",
            "affirm": "அதைக் கேட்பதில் மகிழ்ச்சி!",
            "deny": "புரிந்தது. உங்களுக்கு வேறு ஏதேனும் கேள்விகள் இருந்தால் எனக்குத் தெரியப்படுத்துங்கள்.",
            "nlu_fallback": None
        },
        'te': {
            "greet": "నమస్కారం! ఈ రోజు నేను మీకు చేరిక గురించి తెలుసుకోవడానికి ఎలా సహాయపడగలను?",
            "goodbye": "వీడ్కోలు! ఎప్పుడైనా మరిన్ని ప్రశ్నలు అడగడానికి సంకోచించకండి.",
            "thanks": "మీకు స్వాగతం!",
            "ask_diversity": "వైవిధ్యం అంటే వివిధ సామాజిక మరియు జాతి నేపథ్యాలు, లింగాలు, లైంగిక ధోరణులు మొదలైన వాటి నుండి ప్రజలను చేర్చే పద్ధతి.",
            "ask_equity": "ఈక్విటీ అనేది న్యాయం మరియు انصافం గురించి. సమానత్వానికి భిన్నంగా, ఈక్విటీ ప్రజలకు విజయవంతం కావడానికి అవసరమైన వాటిని ఇస్తుంది.",
            "ask_inclusion": "చేరిక అనేది ప్రతి వ్యక్తికి స్వాగతం, గౌరవం మరియు మద్దతు లభించే వాతావరణాన్ని సృష్టించే చర్య.",
            "affirm": "అది విన్నందుకు నాకు సంతోషంగా ఉంది!",
            "deny": "అర్థమైంది. మీకు ఏవైనా ఇతర ప్రశ్నలు ఉంటే నాకు తెలియజేయండి.",
            "nlu_fallback": None
        },
        'bn': {
            "greet": "হ্যালো! আজ অন্তর্ভুক্তি সম্পর্কে জানতে আমি কীভাবে সাহায্য করতে পারি?",
            "goodbye": "বিদায়! যেকোনো সময় আরও প্রশ্ন জিজ্ঞাসা করুন।",
            "thanks": "আপনাকে ধন্যবাদ!",
            "ask_diversity": "বৈচিত্র্য হল বিভিন্ন সামাজিক এবং জাতিগত পটভূমি, লিঙ্গ, যৌন অভিযোজন ইত্যাদি থেকে লোকেদের অন্তর্ভুক্ত করার অনুশীলন।",
            "ask_equity": "ইকুইটি ন্যায়সঙ্গত এবং ন্যায় সম্পর্কিত। সমতার বিপরীতে, ইকুইটি লোকেদের সফল হওয়ার জন্য যা প্রয়োজন তা দেয়।",
            "ask_inclusion": "অন্তর্ভুক্তি হল একটি পরিবেশ তৈরির কাজ যেখানে প্রতিটি ব্যক্তি স্বাগত, সম্মানিত এবং সমর্থিত অনুভব করে।",
            "ask_accessibility": "প্রবেশযোগ্যতা অর্থ হল অক্ষম ব্যক্তিদের জন্য পণ্য, পরিষেবা বা পরিবেশগুলি ডিজাইন করা।",
            "ask_bias": "অচেতন পক্ষপাত হল অন্যদের সম্পর্কে রূপক যা আমরা বুঝতে পারি না।",
            "affirm": "আমি এটি শুনে খুশি!",
            "deny": "বুঝেছি। আপনার অন্য কোন প্রশ্ন আছে কি?",
            "nlu_fallback": None
        },
        'ta': {
            "greet": "வணக்கம்! இன்று உள்ளடக்கம் பற்றி அறிய உங்களுக்கு எப்படி உதவ முடியும்?",
            "goodbye": "பிரியாவிடை! எப்போது வேண்டுமானாலும் மேலும் கேள்விகளைக் கேளுங்கள்।",
            "thanks": "நன்றி!",
            "ask_diversity": "பன்முகத்தன்மை என்பது பல்வேறு சமூக மற்றும் இனப் பின்னணி, பாலினம், பாலியல் திசைகள் போன்றவற்றிலிருந்து மக்களை உள்ளடக்கிய செயல்.",
            "ask_equity": "இக்விட்டி நீதி மற்றும் நியாயத்துடன் தொடர்புடையது. சமத்துவத்திற்கு மாறாக, இக்விட்டி மக்களுக்கு வெற்றியடைய தேவையானதை வழங்குகிறது.",
            "ask_inclusion": "உள்ளடக்கம் என்பது ஒவ்வொரு நபரும் வரவேற்கப்படுவது, மரியாதை செய்யப்படுவது மற்றும் ஆதரிக்கப்படுவது உணரும் ஒரு சூழலை உருவாக்கும் செயல்.",
            "ask_accessibility": "அணுகல் என்பது இயலாமை உள்ளவர்களுக்கு தயாரிப்புகள், சேவைகள் அல்லது சூழல்களை வடிவமைப்பது.",
            "ask_bias": "அறிவில்லாத பக்கச்சார்பு என்பது நாம் மற்றவர்களைப் பற்றி வைத்திருக்கும் வடிவங்கள், அவற்றை நாம் உணர்வதில்லை.",
            "affirm": "இதை கேட்டு மகிழ்ச்சி!",
            "deny": "புரிந்தது. உங்களுக்கு வேறு கேள்விகள் உள்ளனவா?",
            "nlu_fallback": None
        },
        'te': {
            "greet": "హలో! నేటి ఉద్దేశం గురించి తెలుసుకోవడానికి నేను ఎలా సహాయం చేయగలను?",
            "goodbye": "వీడ్కోలు! ఎప్పుడైనా మరిన్ని ప్రశ్నలు అడగండి.",
            "thanks": "ధన్యవాదాలు!",
            "ask_diversity": "వైవిధ్యం అంటే వివిధ సామాజిక మరియు జాతీయ నేపథ్యాలు, లింగాలు, లైంగిక దిశలు మొదలైనవి నుండి వ్యక్తులను చేర్చే అభ్యాసం.",
            "ask_equity": "ఈక్విటీ న్యాయం మరియు నీతితో సంబంధం కలిగి ఉంది. సమానత్వానికి వ్యతిరేకంగా, ఈక్విటీ వ్యక్తులకు విజయం సాధించడానికి అవసరమైనది అందిస్తుంది.",
            "ask_inclusion": "చేర్పు అంటే ప్రతి వ్యక్తి స్వాగతం, గౌరవం మరియు మద్దతు అనుభవించే వాతావరణాన్ని సృష్టించే కార్యం.",
            "ask_accessibility": "ప్రాప్యత అంటే వైకల్యం ఉన్న వ్యక్తుల కోసం ఉత్పత్తులు, సేవలు లేదా వాతావరణాలను రూపొందించడం.",
            "ask_bias": "అచేతన పక్షపాతం అంటే మనం మిగతా వ్యక్తుల గురించి కలిగి ఉన్న రూపకాలు, వాటిని మనం అర్థం చేసుకోలేము.",
            "affirm": "దీనిని విన్నందున సంతోషంగా ఉన్నాను!",
            "deny": "అర్థమైంది. మీకు మరిన్ని ప్రశ్నలు ఉన్నాయా?",
            "nlu_fallback": None
        }
    }

    # Select the language, defaulting to English if the requested language is not available.
    responses = canned_responses.get(lang, canned_responses['en'])
    final_fallback_message = {
        'en': "I'm sorry, I'm currently unable to process your request. Could you try asking in a different way?",
        'hi': "मुझे खेद है, मैं वर्तमान में आपके अनुरोध को संसाधित करने में असमर्थ हूँ। क्या आप एक अलग तरीके से पूछने की कोशिश कर सकते हैं?",
        'bn': "আমি দুঃখিত, আমি বর্তমানে আপনার অনুরোধ প্রক্রিয়া করতে পারছি না। আপনি কি অন্যভাবে জিজ্ঞাসা করার চেষ্টা করতে পারেন?",
        'ta': "மன்னிக்கவும், தற்போது உங்கள் கோரிக்கையைச் செயல்படுத்த முடியவில்லை. வேறு வழியில் கேட்க முயற்சிப்பீர்களா?",
        'te': "క్షమించండి, నేను ప్రస్తుతం మీ అభ్యర్థనను ప్రాసెస్ చేయలేకపోతున్నాను. మీరు వేరే విధంగా అడగడానికి ప్రయత్నించగలరా?"
    }

    # 1. Check for a direct ML match
    bot_reply = responses.get(classification)

    # 2. If ML didn't return a specific answer, try DEI data similarity search
    if bot_reply is None:
        # Use the sentence transformer for semantic search if it's available
        if embedding_model is not None and dei_embeddings is not None:
            # Encode the user's message
            query_embedding = embedding_model.encode(user_message, convert_to_tensor=True)

            # Use semantic_search to find the top 3 most similar entries
            hits = util.semantic_search(query_embedding, dei_embeddings, top_k=3)

            # The result is a list of lists, one for each query. We only have one query.
            if hits and hits[0]:
                best_hit = hits[0][0]  # The first hit is the best one
                score = best_hit['score']
                corpus_id = best_hit['corpus_id']
                threshold = 0.5  # Increased threshold for better relevance

                if score > threshold:
                    return dei_data[corpus_id].get('response', final_fallback_message.get(lang, final_fallback_message['en']))
        
        # 3. If no DEI match, fallback to LLM if available
        if llm_service.is_available():
            logging.info(f"ML Fallback: Using Gemini for dynamic response to intent '{classification}'")

            llm_context = (
                "You are a highly knowledgeable and friendly inclusion and diversity expert. "
                "Always provide clear, encouraging, and informative answers. Keep your responses concise. "
                f"The user is asking in '{lang}' language, so you MUST respond in the same language."
            )

            # Use the LLM to generate a custom answer based on the full message
            llm_reply = llm_service.get_generative_response(
                prompt=user_message,
                context=llm_context
            )
            return llm_reply
        else:
            # Final fallback if the LLM service is also unavailable
            return final_fallback_message.get(lang, final_fallback_message['en'])

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
    lang = request.json.get("lang", "en")  # Default to English
    if not message or not message.strip():
        return jsonify({"error": "No message provided"}), 400

    # Validate message length
    if len(message.strip()) > 1000:
        return jsonify({"error": "Message too long (max 1000 characters)"}), 400

    try:
        # Step 1: Predict intent
        intent = intent_classifier.predict(message)
        
        # Step 2: Get the response (passing the original message for LLM fallback)
        bot_reply = get_bot_response(intent, message, lang) 

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
        return jsonify({"error": "Failed to process message"}), 500

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
        token = google.authorize_access_token()
        user_info = google.get('userinfo').json()
        user_email = user_info.get('email')
        if not user_email:
            return "Could not fetch email from Google.", 400

        user = users_collection.find_one({"email": user_email})
        if not user:
            user_id = users_collection.insert_one({"email": user_email, "name": user_info.get('name'), "auth_provider": "google"}).inserted_id
            user = users_collection.find_one({"_id": user_id})

        app_token = generate_app_token(user["_id"], user["email"])
        # NOTE: Ensure the frontend URL here matches the one your frontend expects
        frontend_url = f"http://localhost:8000?token={app_token}&email={user['email']}" 
        return redirect(frontend_url)
    except Exception as e:
        logging.error(f"Google OAuth Error: {e}")
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

        # Find all conversations for the user, sorted by creation date
        history_cursor = conversations_collection.find(
            {"userId": user_id},
            {"_id": 1, "title": 1, "createdAt": 1} # Projection
        ).sort("createdAt", -1)

        history_list = [
            {"id": str(conv["_id"]), "title": conv["title"]} for conv in history_cursor
        ]

        return jsonify({"history": history_list})
    except jwt.ExpiredSignatureError:
        return jsonify({"msg": "Token has expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"msg": "Token is not valid"}), 401
    except Exception as e:
        logging.error(f"Chat history error: {e}")
        return jsonify({"msg": "Failed to fetch chat history"}), 500

@app.route("/api/chat/history/<conversation_id>", methods=["GET"])
def get_conversation_messages(conversation_id):
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    token = request.headers.get("x-auth-token")
    if not token:
        return jsonify({"msg": "No token, authorization denied"}), 401

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = ObjectId(payload["user_id"])
        
        conversation = conversations_collection.find_one({
            "_id": ObjectId(conversation_id),
            "userId": user_id
        })
        
        messages = conversation.get("messages", []) if conversation else []
        return jsonify({"messages": messages})
    except Exception as e:
        logging.error(f"Error fetching conversation messages: {e}")
        return jsonify({"msg": "Failed to fetch messages"}), 500

@app.route("/api/chat/history/<conversation_id>", methods=["DELETE"])
def delete_conversation(conversation_id):
    # Validate database connection
    if client is None or db is None:
        return jsonify({"error": "Database connection unavailable"}), 503

    token = request.headers.get("x-auth-token")
    if not token:
        return jsonify({"msg": "No token, authorization denied."}), 401

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = ObjectId(payload["user_id"])
        
        result = conversations_collection.delete_one(
            {"_id": ObjectId(conversation_id), "userId": user_id}
        )
        
        if result.deleted_count == 0:
            return jsonify({"msg": "Conversation not found or you do not have permission to delete it."}), 404
        
        return jsonify({"msg": "Conversation deleted successfully"}), 200
    except Exception as e:
        logging.error(f"Delete history error: {e}")
        return jsonify({"msg": "Failed to delete chat history"}), 500

if __name__ == "__main__":
    # Note: Flask will run on port 5056 in debug mode
    app.run(host='0.0.0.0', port=5056, debug=True)
    # In a production environment, use a WSGI server like Gunicorn.
    # For local development, you can uncomment the line below:
    # app.run(host='0.0.0.0', port=5056, debug=True)
