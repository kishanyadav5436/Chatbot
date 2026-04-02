# nlp_service.py

import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import Pipeline
import yaml
import logging
import numpy as np # Import numpy for array handling

# Load the spaCy model
try:
    # Ensure you run 'python -m spacy download en_core_web_sm' if this fails
    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    logging.info("spaCy model 'en_core_web_sm' loaded successfully.")
except OSError:
    logging.error("spaCy model 'en_core_web_sm' not found. Please run 'python -m spacy download en_core_web_sm'")
    nlp = None

class IntentClassifier:
    def __init__(self):
        # ⭐ CORE FIX 1: Change loss to 'log_loss' to enable predict_proba (confidence scoring)
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(tokenizer=self.spacy_tokenizer, token_pattern=None)),
            ('clf', SGDClassifier(loss='log_loss', penalty='l2', alpha=1e-3, random_state=42, max_iter=10, tol=None)),
        ])
        self.is_trained = False
        self.CONFIDENCE_THRESHOLD = 0.50  # ⭐ CORE FIX 2: Set a confidence floor (e.g., 50%)

    def spacy_tokenizer(self, text):
        if not nlp: return []
        # Lemmatize and remove stop words/punctuation
        tokens = [token.lemma_.lower() for token in nlp(text)]
        filtered_tokens = [t for t in tokens if not nlp.vocab[t].is_punct and not nlp.vocab[t].is_stop]
        # If all tokens were removed (e.g., only stop words or short phrases), return the original ones to avoid empty vocabulary errors
        return filtered_tokens if filtered_tokens else tokens

    def train(self, nlu_data_path="data/nlu.yml"):
        """Trains the classifier on the NLU data."""
        logging.info("Training intent classifier...")
        try:
            with open(nlu_data_path, 'r') as f:
                nlu_data = yaml.safe_load(f)

            texts = []
            labels = []
            for item in nlu_data.get('nlu', []):
                intent = item.get('intent')
                examples_text = item.get('examples', '')
                if isinstance(examples_text, str):
                    examples = [line.strip().lstrip('- ').strip() for line in examples_text.split('\n') if line.strip().lstrip('- ').strip()]
                else:
                    examples = item.get('examples', [])

                for example in examples:
                    cleaned_example = str(example).strip()
                    if cleaned_example and cleaned_example != '-':
                        texts.append(cleaned_example)
                        labels.append(intent)

            if not texts or not labels:
                logging.warning("No training data found in NLU file.")
                return

            self.pipeline.fit(texts, labels)
            self.is_trained = True
            logging.info(f"Intent classifier training complete. Trained on {len(texts)} examples for {len(set(labels))} intents.")
        except FileNotFoundError:
            logging.error(f"NLU data file not found at {nlu_data_path}")
        except yaml.YAMLError as e:
            logging.error(f"Error parsing NLU YAML file: {e}")
        except Exception as e:
            logging.error(f"An error occurred during training: {e}")

    def predict(self, text):
        """
        Predicts the intent of a given text message.
        If confidence is below the threshold, it forces 'nlu_fallback'.
        """
        if not self.is_trained or not nlp:
            logging.error("Classifier is not trained or spaCy model is not loaded.")
            return "nlu_fallback"

        try:
            # ⭐ CORE FIX 3: Use predict_proba to get confidence scores
            probabilities = self.pipeline.predict_proba([text])
            
            # Find the index and value of the highest probability
            max_prob_index = np.argmax(probabilities, axis=1)[0]
            max_confidence = probabilities[0][max_prob_index]
            
            # Find the corresponding label (intent)
            predicted_intent = self.pipeline.classes_[max_prob_index]

            logging.info(f"Prediction: '{text}' -> '{predicted_intent}' (Confidence: {max_confidence:.2f})")

            # ⭐ CORE FIX 4: Check if confidence meets the threshold
            if max_confidence >= self.CONFIDENCE_THRESHOLD:
                return predicted_intent
            else:
                logging.info(f"Confidence too low ({max_confidence:.2f}), defaulting to nlu_fallback.")
                return "nlu_fallback"
                
        except Exception as e:
            logging.error(f"Error during prediction: {e}")
            return "nlu_fallback"

# Create a single, shared instance of the classifier to be used by the API server
intent_classifier = IntentClassifier()
print("Training classifier...")
intent_classifier.train()
print(f"Classifier trained: {intent_classifier.is_trained}")