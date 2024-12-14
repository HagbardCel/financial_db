# Note: You can use any Debian/Ubuntu based image you want. 
FROM mcr.microsoft.com/devcontainers/base:bullseye

# [Optional] Uncomment this section to install additional OS packages.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends python3 python3-pip

# Create a non-root user
RUN useradd -m -s /bin/bash devuser

# Add the user to the docker group
RUN groupadd docker || true && usermod -aG docker devuser

# Add devuser to sudoers with no password
RUN echo "devuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Set the user to the new non-root user
USER devuser

# Set the working directory
WORKDIR /home/devuser

# Copy the requirements file and install dependencies as the non-root user
COPY --chown=devuser:devuser requirements.txt /tmp/
RUN pip3 install --user -r /tmp/requirements.txt