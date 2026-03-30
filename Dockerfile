# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (Poppler)
# Poppler-utils is needed by pdf2image for PDF to image conversion
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user and switch to it
# Running as non-root is a security best practice
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Add the user's local bin directory to the PATH
ENV PATH="/home/appuser/.local/bin:${PATH}"

# Copy the requirements file into the container at /app
# Must be copied after user switch if requirements.txt needs user permissions
COPY --chown=appuser:appuser requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container at /app
# The 'src' directory from the build context will be copied to /app/src
COPY --chown=appuser:appuser . .

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run main.py when the container launches
# The application's main.py is located at /app/src/main.py
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
