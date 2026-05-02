mkdir -p certs
cd certs
openssl genrsa -out ca.key 2048
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -subj "/CN=localhost" -keyout ca.key -out ca.crt
openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "/CN=localhost" -sha256 -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256
cd ..
