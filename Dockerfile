FROM node:12.13.1-alpine
WORKDIR /home/node
COPY . /home/node

# Set environment varibles
ENV TZ America/Toronto

CMD ["/bin/sh", "entrypoint.sh"]