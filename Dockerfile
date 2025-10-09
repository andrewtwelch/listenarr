FROM ghcr.io/astral-sh/uv:alpine

# Set build arguments
ARG RELEASE_VERSION
ENV RELEASE_VERSION=${RELEASE_VERSION}

# Create directories and set permissions
COPY . /listenarr
WORKDIR /listenarr

RUN uv sync --locked

# Expose port
EXPOSE 5000

# Start the app
CMD ["uv", "run", "src/Listenarr.py"]
