
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort
import firebase_admin
from firebase_admin import credentials, firestore
import numpy as np
from PIL import Image
from io import BytesIO
from flask_cors import CORS
import cv2
from insightface.app import FaceAnalysis
import os
import secrets
import pyrebase
import json
from datetime import datetime

app = Flask(__name__)
CORS(app) 

# Set secret key securely
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
cred = credentials.Certificate('./ServiceAccountKey.json')
firebase_admin.initialize_app(cred)
store = firestore.client()
COLLECTION_NAME = "academy:register"

faceapp = FaceAnalysis(name='buffalo_sc', root='insightface_model', providers=[
                       'CPUExecutionProvider'])
faceapp.prepare(ctx_id=0, det_size=(640, 640), det_thresh=0.5)

# Firebase auth initialization 
with open('google-services.json') as f:
    firebase_config = json.load(f)

firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()
db = firebase.database()

# Shared session state
received_embeddings = []
sample_limit = 50
current_name_role = None

@app.before_request
def check_maintenance_mode():
    # Skip checks for static files
    if request.path.startswith("/static"):
        return None

    # Fetch the current site status
    try:
        site_status = bool(db.child("site_status/enabled").get().val())
        print("[DEBUG] site_status:", site_status)
    except Exception as e:
        print(f"[DEBUG] Error reading site_status: {e}")
        site_status = True  # Fail-safe: assume site is up

    # Route-specific logic
    if request.path == "/maintenance":
        if site_status:
            return redirect(url_for("index_page"))  # Site is up, block maintenance page

    elif not site_status:
        # Site is down, block all pages except maintenance
        return redirect(url_for("maintenance"))

    return None  # Allow request


@app.route('/maintenance')
def maintenance():
    return '''
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;">
      <h1 style="color:#d32f2f;font-size:2.5rem;">Server Unavailable</h1>
      <p style="font-size:1.2rem;">The server is currently unavailable due to maintenance.<br>Please check back later.</p>
    </div>
    ''', 503

@app.route('/')
def home():
    return redirect(url_for('index_page'))

@app.route('/index')
def index_page():
    return render_template("index.html")

@app.route('/start-face-collection', methods=['POST'])
def start_face_collection():
    global received_embeddings, current_name_role
    
    print("=== DEBUG: Starting face collection ===")
    
    data = request.get_json()
    print(f"DEBUG: Received data: {data}")
    
    name = data['name']
    role = data['role']
    received_embeddings = []
    # Extract student info
    ssn_email_id = data.get('email')
    dob = data.get('dob')
    stop = data.get('busStop')
    name_role = f"{name}@{role}"
    current_name_role = name_role
    received_embeddings = []

    print(f"DEBUG: Extracted values:")
    print(f"  - Name: {name}")
    print(f"  - Role: {role}")
    print(f"  - Email: {ssn_email_id}")
    print(f"  - DOB (original): {dob}")
    print(f"  - Bus Stop: {stop}")
    print(f"  - Name Role: {name_role}")

    # Validate required fields
    if not all([name, role, ssn_email_id, dob, stop]):
        print("DEBUG: Missing required fields")
        return jsonify({'error': 'Missing required fields'}), 400

    print("DEBUG: All required fields present")

    # Convert date format from YYYY-MM-DD to DD-MM-YYYY for Firebase Auth
    try:
        date_obj = datetime.strptime(dob, '%Y-%m-%d')
        dob_converted = date_obj.strftime('%d-%m-%Y')
        print(f"DEBUG: DOB converted from '{dob}' to '{dob_converted}'")
    except ValueError as e:
        print(f"DEBUG: Date conversion failed: {e}")
        return jsonify({'error': 'Invalid date format'}), 400

    # Create user in Firebase Auth
    try:
        print(f"DEBUG: Attempting to create Firebase Auth user with email: '{ssn_email_id}' and password: '{dob_converted}'")
        user = auth.create_user_with_email_and_password(ssn_email_id, dob_converted)
        print(f"DEBUG: User created successfully: {user}")
    except Exception as e:
        error_str = str(e)
        print(f"DEBUG: Error creating user: {error_str}")
        # If user already exists, Firebase returns an error; inform the user and do not proceed
        if 'EMAIL_EXISTS' in error_str:
            print(f"DEBUG: User already exists, aborting registration.")
            return jsonify({'error': 'User already exists with this email.'}), 409
        else:
            return jsonify({'error': 'User creation failed', 'details': error_str}), 400

    try:
        print("DEBUG: Starting Firestore operations")
        users_ref = store.collection("users")
        docs = users_ref.stream()
        existing_user_ids = [int(doc.id) for doc in docs if doc.id.isdigit()]
        user_id = max(existing_user_ids, default=0) + 1
        print(f"DEBUG: Generated user_id: {user_id}")
        user_data = {
            "ssn_email_id": ssn_email_id,
            "password": dob_converted,  # Store the converted format
            name_role: "face_data",  # placeholder
            "stop": stop
        }
        print(f"DEBUG: User data to store: {user_data}")
        users_ref.document(str(user_id)).set(user_data)
        print(f"DEBUG: User data stored successfully in Firestore")
        print(f"Registered student {name_role} with user_id {user_id}")
        return jsonify({"message": "Collection started and student registered"})
    except Exception as e:
        print(f"DEBUG: Firestore operation failed: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload-frame', methods=['POST'])
def upload_frame():
    global received_embeddings, current_name_role

    if not current_name_role:
        return jsonify({"error": "Collection not started"}), 400

    file = request.files['frame']
    img = Image.open(BytesIO(file.read()))
    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    results = faceapp.get(frame, max_num=1)

    if results:
        embedding = results[0]['embedding']
        if len(received_embeddings) < sample_limit:
            received_embeddings.append(embedding)
            print(f"Sample {len(received_embeddings)}/{sample_limit}")

    if len(received_embeddings) == sample_limit:
        final_embedding = np.mean(received_embeddings, axis=0)
        received_embeddings = []

        doc_ref = store.collection(COLLECTION_NAME).document("facial_features")
        doc = doc_ref.get()
        embedding_bytes = final_embedding.tobytes()

        if doc.exists:
            existing = doc.to_dict()
            if current_name_role in existing:
                print("User already exists.")
            else:
                doc_ref.set({current_name_role: embedding_bytes}, merge=True)
        else:
            doc_ref.set({current_name_role: embedding_bytes})

        print(" Face data saved for:", current_name_role)
        current_name_role = None
        return jsonify({"done": True})

    return jsonify({"done": False})

@app.route('/firebase-config')
def firebase_config():
    with open('google-services.json') as f:
        config = json.load(f)
    # Optionally, remove sensitive fields if needed
    return jsonify(config)

@app.route('/debug-site-status')
def debug_site_status():
    try:
        # Use pyrebase to access the Realtime Database
        site_status = db.child("site_status/enabled").get().val()
        print(f"[DEBUG] Current site_status/enabled: {site_status}")
        return jsonify({"site_status_enabled": site_status})
    except Exception as e:
        print(f"[DEBUG] Error fetching site_status/enabled: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
