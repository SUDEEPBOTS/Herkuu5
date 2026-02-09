import os
import requests
import random
import string
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from pymongo import MongoClient

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- MONGODB CONNECTION ---
# Heroku Config Vars se MONGO_URL uthayega
MONGO_URL = os.getenv("MONGO_URL")
client = MongoClient(MONGO_URL)
db = client['render_logger_db']
codes_collection = db['access_codes']

# Render API Base
RENDER_API_BASE = "https://api.render.com/v1"

# Local storage for cleanup (Konse stream kiske hain)
active_streams = {}

# --- HELPER: Generate Random Code ---
def generate_short_code():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

# --- ROUTE 1: CREATE LOG LINK (Teri Deploy Website isko call karegi) ---
@app.route('/api/create_link', methods=['POST'])
def create_link():
    data = request.json
    api_key = data.get('api_key')
    service_id = data.get('service_id')

    if not api_key or not service_id:
        return jsonify({"error": "Data missing"}), 400

    # Ek unique code banao
    code = generate_short_code()

    # MongoDB mein save karo
    codes_collection.insert_one({
        "code": code,
        "api_key": api_key,
        "service_id": service_id
    })

    # Return the Link (Jo user ko dikhana hai)
    # Heroku App URL env se lena best hai
    app_url = os.getenv("APP_URL", "https://tera-app.herokuapp.com")
    full_link = f"{app_url}/view/{code}"

    return jsonify({
        "status": "success",
        "code": code,
        "link": full_link
    })

# --- ROUTE 2: VIEW LOGS (User ye link kholega) ---
@app.route('/view/<code>')
def view_logs(code):
    # DB se data nikalo
    entry = codes_collection.find_one({"code": code})
    
    if not entry:
        return "❌ Error: Invalid or Expired Code!", 404

    # HTML ko data pass karo (Hidden way mein)
    return render_template(
        'terminal.html', 
        api_key=entry['api_key'], 
        service_id=entry['service_id']
    )

# --- SOCKET & STREAM LOGIC (Wahi purana mast wala) ---

@app.route('/start_stream', methods=['POST'])
def start_stream():
    data = request.json
    api_key = data.get('api')
    service_id = data.get('srv')
    
    # Webhook URL setup
    my_webhook_url = os.getenv("APP_URL") + "/webhook"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # Stream Create via Render API
    payload = {"serviceId": service_id, "url": my_webhook_url}

    try:
        response = requests.post(f"{RENDER_API_BASE}/log-streams", json=payload, headers=headers)
        if response.status_code == 201:
            stream_id = response.json()['id']
            active_streams[stream_id] = api_key # Store for cleanup
            return jsonify({"status": "connected", "stream_id": stream_id})
        else:
            return jsonify({"error": f"Render Error: {response.text}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook_receiver():
    logs = request.json
    if logs:
        for log in logs:
            socketio.emit('new_log', {'message': log.get('message', ''), 'time': log.get('timestamp', '')})
    return "OK", 200

# Cleanup Stream (Jab user page band kare)
@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    # Cleanup logic remains similar
    return jsonify({"status": "stopped"})

if __name__ == '__main__':
    socketio.run(app, debug=True)
