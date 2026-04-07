import os

# Bind to Render's PORT automatically
bind = f"0.0.0.0:{os.environ.get('PORT', '5056')}"
workers = 1
timeout = 300  # 5 minutes — enough for heavy model loading

# Preload the app so that models load BEFORE gunicorn
# signals the port as ready. This is critical for Render's port scan.
preload_app = True
