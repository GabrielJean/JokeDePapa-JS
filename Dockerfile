FROM python:3.12-slim

# Install ffmpeg and other dependencies
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Set environment variables (optional, for UTF-8 support)
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=UTF-8

# Run the bot
CMD ["python", "bot.py"]