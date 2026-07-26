# ──────────────────────────────────────────────────────────────────────────
# Dockerfile — AI-Assisted HVAC Control System
# Includes EnergyPlus 24.2.0 + Python runtime + all project components
# ──────────────────────────────────────────────────────────────────────────
FROM --platform=linux/amd64 python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    libx11-6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install EnergyPlus 24.2.0
ARG ENERGYPLUS_VERSION=24.2.0
ARG ENERGYPLUS_SHA=e7ecb2d53b
ARG ENERGYPLUS_INSTALL_DIR=/usr/local/EnergyPlus-24-2-0
RUN wget -q "https://github.com/NREL/EnergyPlus/releases/download/v${ENERGYPLUS_VERSION}/EnergyPlus-${ENERGYPLUS_VERSION}-${ENERGYPLUS_SHA}-Linux-Ubuntu22.04-x86_64.sh" \
    -O /tmp/ep_install.sh \
    && chmod +x /tmp/ep_install.sh \
    && printf "y\n\n\n" | /tmp/ep_install.sh \
    && rm /tmp/ep_install.sh
ENV ENERGYPLUS_DIR=${ENERGYPLUS_INSTALL_DIR}
ENV LD_LIBRARY_PATH=${ENERGYPLUS_INSTALL_DIR}
ENV PYTHONPATH=${ENERGYPLUS_INSTALL_DIR}

# Set working directory
WORKDIR /app

# Copy requirements and install Python deps
COPY agent/mcp_server/requirements.txt /app/agent/mcp_server/requirements.txt
RUN pip install --no-cache-dir \
    streamlit \
    pandas \
    && pip install --no-cache-dir -r /app/agent/mcp_server/requirements.txt

# Copy project source
COPY . /app/

# Expose dashboard port
EXPOSE 8501

# Default: run the evaluation engine then launch the dashboard
CMD ["bash", "-c", "python evaluation/engine.py && streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0"]
