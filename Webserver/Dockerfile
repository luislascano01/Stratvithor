# Webserver/Dockerfile
FROM alpine AS resolver
WORKDIR /tmp

# Copy the entire build context (which must include both Webserver and branding)
COPY . .

# Create a tar archive of the Frontend folder.
# The --dereference option makes tar follow symlinks and include the actual files.
RUN tar -c --dereference -f frontend.tar -C . Webserver/Frontend

FROM nginx:latest
WORKDIR /usr/share/nginx/html

# Extract the tar archive.
# --strip-components=2 removes the leading "Webserver/Frontend" directories so that
# the files are placed directly into /usr/share/nginx/html.
COPY --from=resolver /tmp/frontend.tar .
RUN tar -xf frontend.tar --strip-components=2 && rm frontend.tar

# Copy the nginx configuration file
COPY Webserver/nginx/nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]