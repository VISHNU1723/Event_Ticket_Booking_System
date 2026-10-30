
from sqlalchemy import text
from app.database import engine

try:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        print("MySQL connection successful!")
        print("Test query result:", result.scalar())
except Exception as e:
    print("MySQL connection failed!")
    print("Error:", e)
