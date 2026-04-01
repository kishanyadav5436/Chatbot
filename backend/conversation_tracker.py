"""
conversation_tracker.py

A service to help the bot track the conversation context, including:
- Intent sequence history
- Topics discussed
- Key entities extracted
- Conversation state
"""

import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)


class ConversationMap:
    """
    A class to track conversation context for each user/session.
    Helps the bot maintain context across multiple messages.
    """
    
    def __init__(self, max_history=10):
        """
        Initialize the conversation map.
        
        Args:
            max_history: Maximum number of intents to keep in history (default: 10)
        """
        self.max_history = max_history
        self.intent_history = deque(maxlen=max_history)  # Track intent sequence
        self.topics_discussed = set()  # Track unique topics
        self.entities = {}  # Track extracted entities by type
        self.conversation_state = {
            "is_active": True,
            "start_time": datetime.utcnow(),
            "last_updated": datetime.utcnow(),
            "message_count": 0,
            "current_topic": None,
            "context_stack": []  # Stack for maintaining context
        }
        self.user_profile = {
            "preferences": {},
            "asked_questions": [],
            "concerns": []
        }
    
    def add_message(self, user_message: str, intent: str, entities: dict = None):
        """
        Add a message to the conversation map.
        
        Args:
            user_message: The user's message
            intent: The predicted intent
            entities: Optional dictionary of extracted entities
        """
        # Add intent to history
        self.intent_history.append({
            "intent": intent,
            "timestamp": datetime.utcnow()
        })
        
        # Update topic based on intent
        topic = self._intent_to_topic(intent)
        if topic:
            self.topics_discussed.add(topic)
            self.conversation_state["current_topic"] = topic
        
        # Add entities if provided
        if entities:
            for entity_type, entity_value in entities.items():
                if entity_type not in self.entities:
                    self.entities[entity_type] = []
                if entity_value not in self.entities[entity_type]:
                    self.entities[entity_type].append(entity_value)
        
        # Update conversation state
        self.conversation_state["last_updated"] = datetime.utcnow()
        self.conversation_state["message_count"] += 1
        
        logger.info(f"Conversation map updated - Intent: {intent}, Topic: {topic}, Total messages: {self.conversation_state['message_count']}")
    
    def _intent_to_topic(self, intent: str) -> str:
        """
        Map intent to a topic category.
        
        Args:
            intent: The intent string
            
        Returns:
            Topic category string
        """
        topic_mapping = {
            "greet": "greeting",
            "goodbye": "closing",
            "thanks": "acknowledgment",
            "ask_diversity": "diversity",
            "ask_equity": "equity",
            "ask_inclusion": "inclusion",
            "ask_accessibility": "accessibility",
            "ask_bias": "bias",
            "affirm": "feedback",
            "deny": "feedback",
            "nlu_fallback": "general"
        }
        return topic_mapping.get(intent, "general")
    
    def get_context_for_llm(self) -> dict:
        """
        Get formatted context information to pass to the LLM.
        
        Returns:
            Dictionary with conversation context
        """
        recent_intents = [item["intent"] for item in list(self.intent_history)[-3:]]
        
        return {
            "recent_intents": recent_intents,
            "topics_discussed": list(self.topics_discussed),
            "current_topic": self.conversation_state.get("current_topic"),
            "message_count": self.conversation_state.get("message_count", 0),
            "entities": self.entities,
            "user_concerns": self.user_profile.get("concerns", [])
        }
    
    def get_last_intent(self) -> str:
        """
        Get the most recent intent.
        
        Returns:
            Last intent string or None
        """
        if self.intent_history:
            return list(self.intent_history)[-1]["intent"]
        return None
    
    def get_previous_intents(self, count: int = 3) -> list:
        """
        Get the last N intents.
        
        Args:
            count: Number of intents to return
            
        Returns:
            List of recent intents
        """
        return [item["intent"] for item in list(self.intent_history)[-count:]]
    
    def is_new_conversation(self) -> bool:
        """
        Check if this is a new conversation (no messages yet).
        
        Returns:
            True if no messages have been sent
        """
        return self.conversation_state["message_count"] == 0
    
    def add_user_concern(self, concern: str):
        """
        Add a user concern or question to their profile.
        
        Args:
            concern: The concern/question string
        """
        if concern not in self.user_profile["concerns"]:
            self.user_profile["concerns"].append(concern)
    
    def reset(self):
        """Reset the conversation map for a new conversation."""
        self.intent_history.clear()
        self.topics_discussed.clear()
        self.entities.clear()
        self.conversation_state = {
            "is_active": True,
            "start_time": datetime.utcnow(),
            "last_updated": datetime.utcnow(),
            "message_count": 0,
            "current_topic": None,
            "context_stack": []
        }
        self.user_profile = {
            "preferences": {},
            "asked_questions": [],
            "concerns": []
        }
        logger.info("Conversation map reset")


class ConversationTracker:
    """
    Manages conversation maps for multiple users/sessions.
    Uses a singleton pattern to maintain maps across requests.
    """
    
    def __init__(self):
        self._maps = {}  # Dictionary of user_id -> ConversationMap
    
    def get_map(self, user_id: str) -> ConversationMap:
        """
        Get or create a conversation map for a user.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            ConversationMap instance for the user
        """
        if user_id not in self._maps:
            self._maps[user_id] = ConversationMap()
            logger.info(f"Created new conversation map for user: {user_id}")
        return self._maps[user_id]
    
    def remove_map(self, user_id: str):
        """
        Remove a user's conversation map.
        
        Args:
            user_id: The user's unique identifier
        """
        if user_id in self._maps:
            del self._maps[user_id]
            logger.info(f"Removed conversation map for user: {user_id}")
    
    def reset_map(self, user_id: str):
        """
        Reset a user's conversation map.
        
        Args:
            user_id: The user's unique identifier
        """
        conversation_map = self.get_map(user_id)
        conversation_map.reset()


# Global singleton instance
conversation_tracker = ConversationTracker()
