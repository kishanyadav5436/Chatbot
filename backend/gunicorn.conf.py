import os

# Bind to Render's PORT automatically
bind = f"0.0.0.0:{os.environ.get('PORT', '5056')}"
workers = 1
timeout = 120
