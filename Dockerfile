FROM node:18-slim
WORKDIR /home/node
COPY . /home/node

# Install Python and build tools for node-gyp
RUN apt-get update && apt-get install -y python3 make g++ && rm -rf /var/lib/apt/lists/*

# Set environment varibles
ENV TZ America/Toronto

CMD ["/bin/sh", "entrypoint.sh"]