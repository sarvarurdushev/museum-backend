import os
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
import asyncio
from bleak import BleakScanner
import threading

# Load environmental variables from .env
load_dotenv()

# Setup Gemini with your API Key
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# FIXED: Switched back to Gemini 3 as requested
model = genai.GenerativeModel('gemini-3-flash-preview')

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# BLE Beacon to Exhibit Mapping
# Maps ESP32 beacon names to exhibit IDs
# Your ESP32 beacons broadcast these names:
BLE_BEACON_MAP = {
    "museum_trex": "t-rex",
    "museum_mona": "mona-lisa",
    "museum_rosetta": "rosetta-stone",
    "museum_apollo": "apollo-11"
}

# Reverse mapping for quick lookup by exhibit ID
EXHIBIT_TO_BEACON = {v: k for k, v in BLE_BEACON_MAP.items()}

# Single, unified database for all exhibits
EXHIBIT_DATA = {
    "t-rex": "The T-Rex (Tyrannosaurus rex) lived 66 million years ago. It had the strongest bite force of any terrestrial animal.",
    "mona-lisa": "The Mona Lisa was painted by Leonardo da Vinci between 1503 and 1506. It is famous for its subject's mysterious smile.",
    "rosetta-stone": "The Rosetta Stone is a granodiorite stele discovered in 1799. It was the key to deciphering Egyptian hieroglyphs because it features the same text in three scripts.",
    "apollo-11": "The Apollo 11 mission was the first to land humans on the Moon in 1969. The Lunar Module 'Eagle' landed in the Sea of Tranquility."
}

@app.route('/')
def home():
    """Serve the home page"""
    return send_file('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json or {}
    exhibit_id = data.get('exhibit_id')
    language = data.get('language', 'English')
    user_msg = data.get('message')

    # Get exhibit context safely
    description = EXHIBIT_DATA.get(exhibit_id, "A museum artifact.")

    # System prompt that stops the greeting loop for follow-up questions
    system_instruction = (
        f"You are a museum guide at the {exhibit_id} exhibit. Description: {description}. "
        f"Respond in {language}. CRITICAL DIRECTION: Only say 'Welcome' if this is the very first "
        f"message of the entire chat session. If this is a follow-up question, do NOT greet the user, "
        f"do NOT say welcome, and do NOT re-introduce the exhibit. Answer the question immediately and directly."
    )

    try:
        # FIXED FOR GEMINI 3: Use generate_content instead of start_chat to avoid SDK 404/500 routing crashes
        full_prompt = f"{system_instruction}\n\nVisitor: {user_msg}"
        response = model.generate_content(full_prompt)
        
        return jsonify({
            "response": response.text
        })

    except Exception as e:
        print(f"Gemini API Error Details: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/scan-beacons', methods=['GET'])
def scan_beacons():
    """
    Scan for nearby BLE beacons and return detected beacons with mapped exhibits.
    Matches beacon names (e.g., "museum_trex") to exhibit IDs.
    Timeout can be controlled via query parameter: ?timeout=2 (default 2 seconds, much faster)
    """
    timeout = request.args.get('timeout', 2, type=float)
    
    def run_scan():
        try:
            # Run the async scan in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            devices = loop.run_until_complete(BleakScanner.discover(timeout=timeout))
            loop.close()
            return devices
        except Exception as e:
            print(f"BLE Scan Error: {str(e)}")
            return []
    
    # Run scan in thread to avoid blocking
    devices = run_scan()
    
    detected_beacons = []
    for device in devices:
        device_name = device.name.lower() if device.name else ""
        
        # Check if this beacon name matches any mapped exhibit
        exhibit_id = BLE_BEACON_MAP.get(device_name)
        
        beacon_data = {
            "address": device.address,
            "name": device.name or "Unknown",
            "rssi": device.rssi,
            "exhibit_id": exhibit_id,
            "exhibit_name": EXHIBIT_DATA.get(exhibit_id, None) if exhibit_id else None,
            "is_museum_beacon": exhibit_id is not None
        }
        detected_beacons.append(beacon_data)
    
    # Sort beacons: mapped exhibits first, then by signal strength
    detected_beacons.sort(key=lambda x: (not x["is_museum_beacon"], -x["rssi"]))
    
    return jsonify({
        "beacons": detected_beacons,
        "total_detected": len(detected_beacons),
        "mapped_exhibits": [b for b in detected_beacons if b["exhibit_id"]],
        "beacon_map": BLE_BEACON_MAP
    })


@app.route('/beacon-exhibits', methods=['GET'])
def get_beacon_mapping():
    """Get the current beacon-to-exhibit mapping with details"""
    mapping_with_details = []
    for beacon_name, exhibit_id in BLE_BEACON_MAP.items():
        mapping_with_details.append({
            "beacon_name": beacon_name,
            "exhibit_id": exhibit_id,
            "exhibit_description": EXHIBIT_DATA.get(exhibit_id, "Unknown exhibit")
        })
    
    return jsonify({
        "beacon_map": BLE_BEACON_MAP,
        "mapping_details": mapping_with_details,
        "total_mapped": len(BLE_BEACON_MAP)
    })

if __name__ == '__main__':
    app.run(port=5000, debug=True)