# Use official Python image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Install dependencies first (cached layer — only rebuilds when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose the port FastAPI runs on
EXPOSE 8000

# Start the API
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"] 
