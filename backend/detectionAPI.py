from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import cv2
import asyncio
import httpx
import concurrent.futures
from model import Model
import sqlite3
from twilio_service import send_alert
from fastapi.staticfiles import StaticFiles
import os

# --------------------------------------
# 📚 Constants
# --------------------------------------
DB_PATH = "threat_history.db"
BUZZER_API_URL = "http://192.168.61.103/buzz?buzz=on"
IMAGE_SAVE_PATH = "./images/"
# Threat Classification Labels
threat_labels = {
    "fight on a street",
    "fire on a street",
    "street violence",
    "car crash",
    "violence in office",
    "fire in office",
    "person holding knife"
}

# --------------------------------------
# 🌐 FastAPI Initialization
# --------------------------------------
app = FastAPI()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------
# 🎥 Global Variables
# --------------------------------------
model = Model(settings_path="./settings.yaml")
frame_buffer = None
lock = asyncio.Lock()
threat_status = ""
cap = cv2.VideoCapture(0)

# Alert tracking to prevent spamming
last_alert_label = None
alert_cooldown = 5  # Cooldown period in seconds
last_alert_time = 0

# Executors for Concurrent Tasks
process_executor = concurrent.futures.ProcessPoolExecutor(max_workers=3)
thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
os.makedirs(IMAGE_SAVE_PATH, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGE_SAVE_PATH), name="images")



# --------------------------------------
# 🗂️ Initialize SQLite Database
# --------------------------------------
def init_db():
    """ Create database and history table if not exists """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            threat_type TEXT NOT NULL,
            image_link TEXT
        )
        """
    )
    conn.commit()
    conn.close()

init_db()

# --------------------------------------
# 📸 Background Frame Capture Task
# --------------------------------------
async def capture_frames():
    """ Continuously capture frames in the background """
    global frame_buffer
    while True:
        success, frame = cap.read()
        if success:
            async with lock:
                frame_buffer = frame
        await asyncio.sleep(0.03)  # Capture every 30 ms (~30 FPS)

# Start frame capturing as a background task
asyncio.create_task(capture_frames())

# --------------------------------------
# 📡 API 1: Video Feed to Frontend
# --------------------------------------
def generate_frames():
    """ Continuously stream frames to frontend """
    global frame_buffer
    while True:
        if frame_buffer is not None:
            success, buffer = cv2.imencode('.jpg', frame_buffer)
            if success:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


@app.get("/video_feed")
def video_feed():
    """ Serve video feed to the frontend """
    return StreamingResponse(generate_frames(),
                             media_type="multipart/x-mixed-replace;boundary=frame")

# --------------------------------------
# 🔥 Prediction Task (Run in Process)
# --------------------------------------
async def run_model_prediction(frame):
    """ Run model prediction in a separate process """
    loop = asyncio.get_running_loop()
    prediction = await loop.run_in_executor(process_executor, model.predict, frame)
    return prediction

# --------------------------------------
# 🤖 API 2: Get Prediction Results
# --------------------------------------
@app.get("/predict")
async def get_prediction():
    """ Get prediction result from the current frame """
    async with lock:
        if frame_buffer is None:
            return JSONResponse(content={"error": "No frame available"}, status_code=500)

        # Run model prediction using ProcessPoolExecutor
        prediction = await run_model_prediction(frame_buffer)

        # Check and trigger SMS alert if needed
        asyncio.create_task(maybe_send_alert(prediction))
        asyncio.create_task(maybe_trigger_buzzer(prediction))

        return JSONResponse(content=prediction)

# --------------------------------------
# 🌐 API 3: WebSocket for Live Predictions
# --------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """ Send real-time predictions over WebSocket """
    global threat_status
    await websocket.accept()
    while True:
        async with lock:
            if frame_buffer is not None:
                prediction = await run_model_prediction(frame_buffer)

                # Update threat status
                threat_status = "Threat" if prediction['label'] in threat_labels else "Non-Threat"
                prediction["threat_status"] = threat_status

                # Trigger alerts and buzzer
                asyncio.create_task(maybe_send_alert(prediction))
                asyncio.create_task(maybe_trigger_buzzer(prediction))

                # Send prediction to WebSocket
                await websocket.send_json(prediction)

        await asyncio.sleep(0.5)  # Limit prediction frequency

# --------------------------------------
# 📢 Trigger SMS Alert
# --------------------------------------
async def maybe_send_alert(prediction):
    """ Check confidence and send SMS alert if needed """
    global last_alert_label, last_alert_time, threat_status

    label = prediction['label']
    confidence = prediction['confidence']

    # Check confidence threshold and avoid spamming
    if confidence >= 0.25 and threat_status == "Threat":
        current_time = asyncio.get_event_loop().time()

        # Only send alert if cooldown is passed or label has changed
        if (label != last_alert_label) or (current_time - last_alert_time > alert_cooldown):
            # Send SMS alert
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(thread_executor, send_alert, label, confidence)
            print("✅ SMS Sent!")

            # Save threat to history with frame
            if frame_buffer is not None:
                await loop.run_in_executor(thread_executor, save_to_history_sync, label, frame_buffer)
                print("✅ Threat and frame saved to history!")

            last_alert_label = label
            last_alert_time = current_time

# --------------------------------------
# 🚨 Trigger Buzzer via ESP32 API
# --------------------------------------
async def maybe_trigger_buzzer(prediction):
    """ Hit ESP32 API to turn on the buzzer if high-confidence threat is detected """
    if prediction['threat_status'] == "Threat" and prediction['confidence'] >= 0.25:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(thread_executor, trigger_buzzer_sync)

def trigger_buzzer_sync():
    """ Synchronous function to trigger ESP32 API """
    try:
        response = httpx.get(BUZZER_API_URL)  # Use sync version of httpx
        if response.status_code == 200:
            print("✅ Buzzer activated!")
        else:
            print(f"⚠️ Failed to trigger buzzer: {response.status_code}")
    except Exception as e:
        print(f"❌ Error hitting ESP32 API: {e}")

# --------------------------------------
# 📝 Save Threats to History
# --------------------------------------
def save_to_history_sync(threat_type, frame):
    """ Synchronous function to save threat to the database """
    try:
        image_path = save_frame(frame, threat_type)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT INTO history (timestamp, threat_type, image_link) VALUES (?, ?, ?)",
            (timestamp, threat_type, image_path),
        )
        conn.commit()
        conn.close()
        print(f"✅ Threat logged: {threat_type} at {timestamp}")
    except Exception as e:
        print(f"❌ Error saving to history: {e}")

# --------------------------------------
# 📜 API 4: Get History from Database
# --------------------------------------
@app.get("/history")
def get_history():
    """ Fetch all saved threats from the database """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM history ORDER BY timestamp DESC")
        history = cursor.fetchall()
        conn.close()

        if history:
            print(f"✅ Retrieved {len(history)} records from history.")
        else:
            print("⚠️ No threat history found.")

        return JSONResponse(
            content={"history": [
                {"id": row[0], "timestamp": row[1], "threat_type": row[2], "image_link": row[3]} for row in history
            ]},
            status_code=200
        )
    except Exception as e:
        print(f"❌ Error fetching history: {e}")
        return JSONResponse(content={"error": "Failed to fetch history"}, status_code=500)

def save_frame(frame, label):
    """ Save frame as an image to disk """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{label.replace(' ', '_')}_{timestamp}.jpg"
    filepath = os.path.join(IMAGE_SAVE_PATH, filename)
    
    # Save frame as image
    cv2.imwrite(filepath, frame)
    print(f"📸 Frame saved: {filepath}")
    
    return filepath

# --------------------------------------
# 🧹 Cleanup on Shutdown
# --------------------------------------
@app.on_event("shutdown")
def shutdown_event():
    """ Release resources when FastAPI stops """
    cap.release()
    process_executor.shutdown(wait=True)
    thread_executor.shutdown(wait=True)
    print("⚡ Resources released successfully!")
