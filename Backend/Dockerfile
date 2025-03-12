# Backend/Dockerfile
# Use a build argument for the base image.
ARG BASE_IMAGE
FROM ${BASE_IMAGE} as base

# For GPU images (e.g. nvidia/cuda:11.7.1-cudnn8-runtime-ubuntu20.04), Python might not be installed.
# This conditional installs Python 3.11, pip, and necessary tools only if not already present.
RUN if ! command -v python3.11 > /dev/null; then \
        apt-get update && \
        apt-get install -y --no-install-recommends \
          python3.11 \
          python3.11-distutils \
          python3-pip \
          build-essential \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# (For images that already include Python, this step is skipped.)
# Ensure build-essential is installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the requirements file (ensure your build context includes the Environment folder)
COPY ../Environment/requirements_linux.txt /app/requirements_linux.txt

# Install Python packages individually, preserving the try-catch structure.
RUN while IFS= read -r pkg; do \
      echo "Installing $pkg"; \
      pip install "$pkg" || echo "WARNING: Failed to install $pkg, continuing..."; \
    done < /app/requirements_linux.txt

# Install Chromium and its driver.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Copy your backend code and additional resources.
COPY Backend /app/Backend
COPY Credentials /app/Credentials
COPY Prompts /app/Prompts

# Expose the required ports.
EXPOSE 8181
EXPOSE 8383

ENV NAME World

# Default CMD for debugging; overridden by docker-compose commands.
CMD ["/bin/bash"]