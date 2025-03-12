# Backend/Dockerfile
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE} as base

# Copy the requirements file.
COPY ../Environment/requirements_linux.txt /app/requirements_linux.txt

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install packages from the requirements file.
RUN while IFS= read -r pkg; do \
      echo "Installing $pkg"; \
      pip install "$pkg" || echo "WARNING: Failed to install $pkg, continuing..."; \
    done < /app/requirements_linux.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Copy your backend code and additional resources.
COPY Backend /app/Backend
COPY Credentials /app/Credentials
COPY Prompts /app/Prompts

EXPOSE 8181
EXPOSE 8383

ENV NAME World

CMD ["/bin/bash"]