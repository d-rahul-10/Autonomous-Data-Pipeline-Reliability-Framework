import os
os.environ["FLASK_APP"] = "app:app"
os.environ["FLASK_ENV"] = "development"
from app import create_app
app = create_app()
app.run(host="127.0.0.1", port=5000, debug=True)
