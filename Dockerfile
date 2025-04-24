# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Install curl for healthcheck in ECS
RUN apt-get update && apt-get install -y curl

# Set the working directory to /app
WORKDIR /app

# Copy the application code into the container
COPY todo_app /app/todo_app
COPY requirements.txt /app/requirements.txt

# Install any dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container
EXPOSE 5000

# Define the command to run the application
CMD ["python", "/app/todo_app/app.py"]
