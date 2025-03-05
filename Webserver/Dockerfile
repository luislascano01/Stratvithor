#Webserver/Dockerfile
FROM nginx:latest

WORKDIR /usr/share/nginx/html
# Change
COPY ./Webserver/Frontend /usr/share/nginx/html
COPY ./Webserver/nginx/nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]