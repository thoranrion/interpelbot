# Use Alpine Linux for minimal image size
FROM python:3.11

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt update && apt install -y cron

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY interpelbot.py .

# Create data directory
RUN mkdir -p /app/data

# Create crontab file (runs every hour)
# Create log file
RUN touch /var/log/cron.log

# Create startup script
RUN echo '#!/bin/sh' > /start.sh && \
    echo 'crond -f -d 8' >> /start.sh && \
    chmod +x /start.sh

# Expose port (if needed for health checks)
EXPOSE 8080

# Set default command
CMD ["/start.sh"] 
