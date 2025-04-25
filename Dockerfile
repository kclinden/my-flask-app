# Use an official Python runtime as a parent image
FROM --platform=arm64 python:slim-bookworm AS build_arm64

# Install curl for healthcheck in ECS
RUN apt update && apt install -y curl

# Set the working directory to /app
WORKDIR /app

# Copy the application code into the container
COPY todo_app /app/todo_app
COPY requirements.txt /app/requirements.txt

# Expose port 5000 for the Flask application
EXPOSE 5000
RUN pip install --no-cache-dir -r requirements.txt
# Add a healthcheck to ensure the application is running
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:5000/health || exit 1

# Define the command to run the application
CMD ["python", "/app/todo_app/app.py"]
