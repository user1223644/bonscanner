"""
Receipt Scanner API
Flask backend for OCR-based receipt processing.
"""

from flask import Flask
from flask_cors import CORS

from database import (
    init_db, seed_default_category_rules,
)
from server.services.default_rules import DEFAULT_CATEGORY_RULES
from server.routes.categories import categories_bp
from server.routes.exports import exports_bp
from server.routes.meta import meta_bp
from server.routes.receipts import receipts_bp

app = Flask(__name__)
CORS(app)
app.register_blueprint(categories_bp)
app.register_blueprint(exports_bp)
app.register_blueprint(meta_bp)
app.register_blueprint(receipts_bp)



# Initialize database on startup
init_db()
seed_default_category_rules(DEFAULT_CATEGORY_RULES)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
