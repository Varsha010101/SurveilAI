from twilio.rest import Client
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Twilio credentials from .env
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
ALERT_PHONE_NUMBER = os.getenv("ALERT_PHONE_NUMBER")  # Your number to receive alerts


def send_alert(label, confidence):
    """
    Sends SMS alert with threat details using Twilio API.
    """
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        message_body = f"🚨 ALERT! Possible Threat Detected!\n" \
                       f"Type: {label}\n" \
                       f"Confidence: {confidence:.2f}"

        message = client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=ALERT_PHONE_NUMBER
        )

        print(f"✅ SMS Sent! SID: {message.sid}")
    except Exception as e:
        print(f"❌ Failed to send SMS: {str(e)}")
