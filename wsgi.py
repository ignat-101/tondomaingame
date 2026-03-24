import sys
import os

# Add your project directory to the sys.path
project_home = u'/home/yourusername/ton-domain-game'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Set environment variable for config
os.environ['FLASK_ENV'] = 'production'

# Import the Flask app
from app import app as application