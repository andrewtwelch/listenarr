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
ENTRYPOINT ["uv", "run", "gunicorn", "--workers=1", "--threads=4", "--bind=0.0.0.0:5000", "--worker-class=geventwebsocket.gunicorn.workers.GeventWebSocketWorker", "src.Listenarr:app"]
