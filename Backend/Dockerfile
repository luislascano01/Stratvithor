# Backend/Dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE} as base

RUN echo "Base image: " && ${BASE_IMAGE}

# For GPU images (e.g. nvidia/cuda:11.7.1-cudnn8-runtime-ubuntu20.04) Python might not be installed.
# If Python 3.11 isn't present, add deadsnakes and install it.
RUN if ! command -v python3.11 > /dev/null; then \
      apt-get update && \
      apt-get install -y --no-install-recommends software-properties-common && \
      add-apt-repository ppa:deadsnakes/ppa -y && \
      apt-get update && \
      apt-get install -y --no-install-recommends \
          python3.11 \
          python3.11-distutils \
          python3-pip \
          build-essential \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Create a symlink for 'python' if it does not exist.
RUN if ! command -v python > /dev/null; then \
      ln -s /usr/bin/python3.11 /usr/bin/python; \
    fi

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
RUN apt-get update && \
    { apt-get install -y --no-install-recommends chromium chromium-driver || \
      (echo "WARNING: chromium or chromium-driver not available, skipping installation" && true); } && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip and explicitly install uvicorn.
RUN python -m pip install --upgrade pip && \
    python -m pip install uvicorn || echo "WARN: Failed to install uvicorn"
RUN pip3 install uvicorn
RUN pip3 install python-docx

# Output Python version to verify installation.
RUN echo "Python version:" && python --version

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