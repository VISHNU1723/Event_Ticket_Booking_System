
from dotenv import load_dotenv
from app.services.notification_service import send_email_notification

load_dotenv()

recipient = input("Enter the email address to receive the test: ").strip()

success = send_email_notification(
    recipient=recipient,
    subject="Event Ticket Booking System - SMTP Test",
    body="SMTP email delivery is working for your Event Ticket Booking System.",
)

print("Email sent successfully." if success else "Email failed. Check the terminal logs and SMTP settings.")
