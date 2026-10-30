# Event & Movie Ticket Booking System

A backend application for discovering events and movies, booking seats, processing payments, generating QR-code tickets, and managing event operations.

## 1. Technology Stack

- Python 3.9+
- FastAPI
- SQLAlchemy ORM
- MySQL
- Redis
- Alembic
- JWT Authentication
- Razorpay Payment Gateway (Test Mode)
- SMTP Email Notifications
- WebSockets
- Uvicorn
- Pytest

## 2. Project Setup

### Prerequisites

Install the following:

- Python 3.9 or above
- MySQL Server
- Redis
- Git

### Clone the Repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd Event_Ticket_Booking_System
```

### Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

## 3. Environment Configuration

Create a `.env` file in the project root or in the configuration location expected by the application.

Configure the following settings according to `.env.example`:

- Database connection URL
- JWT secret key and algorithm
- Redis connection URL
- SMTP host, port, username and password
- Razorpay Test Mode Key ID
- Razorpay Test Mode Key Secret
- Razorpay Webhook Secret

**Security:** Never upload `.env`, passwords, API keys, JWT secrets or SMTP credentials to GitHub.

Use `.env.example` to document the required configuration variables without including actual secrets.

## 4. MySQL Database Setup

1. Start MySQL Server.
2. Open MySQL Workbench.
3. Create the project database.
4. Configure the database connection URL in `.env`.
5. Verify that the database credentials are correct.

Example database creation:

```sql
CREATE DATABASE event_ticket_booking;
```

Use the actual database name configured in your application.

## 5. Redis Setup

Redis is used for temporary seat locking, caching and rate limiting.

### macOS Installation

```bash
brew install redis
```

### Start Redis

```bash
brew services start redis
```

### Verify Redis

```bash
redis-cli ping
```

Expected response:

```text
PONG
```

Configure the Redis connection URL in `.env` according to the application's settings.

## 6. Alembic Database Migrations

Alembic manages database schema migrations.

### Apply Existing Migrations

```bash
alembic upgrade head
```

### Check Current Migration

```bash
alembic current
```

### View Migration History

```bash
alembic history
```

### Generate a New Migration

```bash
alembic revision --autogenerate -m "describe_changes"
```

### Apply New Migration

```bash
alembic upgrade head
```

The migration files are available in the `alembic/versions/` directory.

## 7. Run the Application

Start the FastAPI server:

```bash
uvicorn app.main:app --reload --log-level info
```

### Application URLs

| Resource | URL |
|---|---|
| API Base URL | http://127.0.0.1:8000 |
| Swagger Documentation | http://127.0.0.1:8000/docs |
| ReDoc | http://127.0.0.1:8000/redoc |
| Health Check | http://127.0.0.1:8000/health |
| Payment Checkout | http://127.0.0.1:8000/checkout |

## 8. User Roles and Test Credentials

The application supports role-based access control.

| Role | Permissions |
|---|---|
| Admin | Manage users, events, bookings and reports |
| Organizer | Create and manage own events and shows |
| Customer | Browse events and book tickets |
| Staff | Manage ticket scanning and entry validation |

### Test Account Credentials

Add the actual test accounts created in your database before submission.

| Role | Username / Email | Password |
|---|---|---|
| Admin | ADD_ADMIN_EMAIL | ADD_TEST_PASSWORD |
| Organizer | ADD_ORGANIZER_EMAIL | ADD_TEST_PASSWORD |
| Customer | ADD_CUSTOMER_EMAIL | ADD_TEST_PASSWORD |
| Staff | ADD_STAFF_EMAIL | ADD_TEST_PASSWORD |

Use dedicated demo accounts only. Never document production credentials or real user passwords.

## 9. SMTP Email Configuration

SMTP is used for:

- Booking confirmation emails
- Ticket delivery emails
- Payment failure notifications
- Booking cancellation notifications
- Show cancellation notifications
- Upcoming show reminders

### Configuration

Configure the SMTP host, port, sender email, username and app password using the environment variables expected by the application.

For Gmail SMTP, the typical settings are:

```text
SMTP Host: smtp.gmail.com
SMTP Port: 587
Encryption: STARTTLS
```

Use a Gmail App Password when applicable. Do not use or publish your normal Gmail password.

## 10. WebSocket Testing

WebSockets provide real-time seat availability updates.

### Testing Steps

1. Start the FastAPI backend.
2. Open Swagger or the frontend checkout page.
3. Open two browser tabs.
4. Authenticate as appropriate test users.
5. Connect both browser sessions to the same show's seat-map WebSocket.
6. Lock a seat in the first browser.
7. Observe the seat status update in the second browser.
8. Release the seat lock and observe the updated availability.

Use the actual WebSocket endpoint implemented in the project.

## 11. Payment Integration

The application integrates Razorpay in Test Mode.

Features include:

- Payment order creation
- Razorpay Checkout integration
- Payment signature verification
- Payment status tracking
- Payment failure handling
- Razorpay webhook integration

### Payment Testing

1. Create a booking.
2. Lock the selected seats.
3. Open the checkout page.
4. Complete a Razorpay Test Mode payment.
5. Verify the payment through the backend.
6. Confirm the booking status.
7. Check the webhook response.

Only use Razorpay Test Mode credentials for testing.

## 12. Ticket Generation and QR Code Scanning

The application supports:

- PDF ticket generation
- QR-code generation
- Ticket validation
- Successful ticket scanning
- Duplicate ticket scan prevention

A ticket should be validated before allowing event entry.

## 13. Assumptions and Limitations

- The application is intended as a backend demonstration project.
- Razorpay is configured in Test Mode; no real payment is processed.
- Payment verification is performed on the backend.
- Seat locking uses Redis with temporary expiration.
- Booking confirmation depends on successful payment verification.
- Email delivery requires valid SMTP configuration.
- WebSocket updates require an active backend connection.
- Event organizers can manage only their authorized events.
- Customers can access their own booking information.
- Refund processing and policies follow the implementation configured in the application.
- Database migrations are managed using Alembic.
- Environment-specific settings must be configured before running the application.

## 14. Important Project Directories

```text
Event_Ticket_Booking_System/
│
├── app/
│   ├── auth/
│   ├── models/
│   ├── routers/
│   ├── schemas/
│   ├── services/
│   ├── utils/
│   ├── websockets/
│   ├── database.py
│   └── main.py
│
├── alembic/
│   └── versions/
│
├── static/
│   └── checkout.html
│
├── tickets/
├── .env.example
├── .gitignore
├── alembic.ini
├── README.md
└── requirements.txt
```

## 15. Author

Event & Movie Ticket Booking System

Developed using FastAPI, Python, MySQL, Redis and Razorpay.