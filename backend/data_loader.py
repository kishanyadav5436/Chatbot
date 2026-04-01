import os
import sys
import logging
import yaml
import pandas as pd
from dotenv import load_dotenv
import pymongo
from pymongo.errors import BulkWriteError

# Setup
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_mongo_client():
    """Connect to MongoDB using env vars."""
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    client = pymongo.MongoClient(mongo_uri)
    db = client["inclusivity-chatbot"]
    logging.info(f"Connected to MongoDB at {mongo_uri}")
    return db

def load_dei_csv(db, csv_path):
    """Load DEI Dataset.csv to dei_dataset collection."""
    df = pd.read_csv(csv_path)
    data = df.to_dict('records')
    collection = db['dei_dataset']
    try:
        result = collection.insert_many(data, ordered=False)
        logging.info(f"Inserted {len(result.inserted_ids)} DEI records")
    except BulkWriteError as bwe:
        logging.info(f"Bulk write errors (likely dupes): {len(bwe.details['writeErrors'])}")

def load_principles_csv(db, csv_path):
    """Load diversity_equity_inclusion_data.csv to dei_principles."""
    df = pd.read_csv(csv_path)
    data = df.to_dict('records')
    collection = db['dei_principles']
    try:
        result = collection.insert_many(data, ordered=False)
        logging.info(f"Inserted {len(result.inserted_ids)} principles")
    except BulkWriteError as bwe:
        logging.info(f"Bulk write errors (likely dupes): {len(bwe.details['writeErrors'])}")

def load_nlu_yaml(db, yaml_path):
    """Load nlu.yml to nlu_intents (append/replace)."""
    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)
    collection = db['nlu_intents']
    collection.delete_many({})  # Clear existing for YAML replace
    result = collection.insert_one({'nlu': data['nlu']})
    logging.info(f"Inserted NLU data")

def append_data_from_folder(db, data_dir):
    """Append all data from data/ folder to MongoDB (handles duplicates gracefully)."""
    load_dei_csv(db, os.path.join(data_dir, 'DEI Dataset.csv'))
    load_principles_csv(db, os.path.join(data_dir, 'diversity_equity_inclusion_data.csv'))
    load_nlu_yaml(db, os.path.join(data_dir, 'nlu.yml'))
    logging.info("Data append complete!")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data')
    
    db = get_mongo_client()
    
    # Load files (existing behavior)
    load_dei_csv(db, os.path.join(data_dir, 'DEI Dataset.csv'))
    load_principles_csv(db, os.path.join(data_dir, 'diversity_equity_inclusion_data.csv'))
    load_nlu_yaml(db, os.path.join(data_dir, 'nlu.yml'))
    
    logging.info("Data loading complete!")
