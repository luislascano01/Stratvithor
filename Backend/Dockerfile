# Backend/Dockerfile
FROM python:3.11-slim

# Copy the requirements file.
# (If Environment is outside Backend, ensure your build context is set to a directory that contains both.)
COPY ../Environment/requirements_linux.txt /app/requirements_linux.txt

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


# Install uvicorn (and any other needed Python packages)
# Install packages individually and ignore failures
RUN while IFS= read -r pkg; do \
      echo "Installing $pkg"; \
      pip install "$pkg" || echo "WARNING: Failed to install $pkg, continuing..."; \
    done < /app/requirements_linux.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set a working directory where your backend code will live
# Copy the backend code Change
COPY Backend /app/Backend

# Copy credentials if needed by your code
COPY Credentials /app/Credentials

COPY Prompts /app/Prompts

# Expose the port used by the request manager (internally)
EXPOSE 8181
EXPOSE 8383

ENV NAME World

# Default CMD for debugging; overridden by docker-compose commands
CMD ["/bin/bash"]
