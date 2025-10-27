FROM python:3.12-slim

# Create a non-root user to run the application
RUN useradd -m appuser

# Set working directory in the container
WORKDIR /app

# Copy requirements first (for better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only necessary files to the container
COPY server.py .

# Create the rooms directory where files will be stored
RUN mkdir -p rooms

# Change ownership of the app directory to appuser
RUN chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 8888

# Command to run the application
CMD ["python", "server.py"]