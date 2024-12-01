# Note: You can use any Debian/Ubuntu based image you want. 
FROM mcr.microsoft.com/devcontainers/base:bullseye

# [Optional] Uncomment this section to install additional OS packages.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends python3 python3-pip

# Create a non-root user
RUN useradd -m -s /bin/bash devuser

# Set the user to the new non-root user
USER devuser

# Set the working directory
WORKDIR /home/devuser

# Add devuser to the docker group
# RUN usermod -aG docker devuser

# Copy the requirements file and install dependencies as the non-root user
COPY --chown=devuser:devuser requirements.txt /tmp/
RUN pip3 install --user -r /tmp/requirements.txt