FROM python:3.10-slim

# Install system dependencies for OpenCV and YOLO
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir websockets wsproto uvicorn[standard]

# Default runtime prefers CUDA when a compatible torch build is installed.
ENV UTT_PREFER_CUDA=1

# Copy all application files
COPY . .

# Ensure the models directory exists
RUN mkdir -p models

EXPOSE 5001

# Command to run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5001", "--workers", "1"]
