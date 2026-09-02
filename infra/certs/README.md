# TLS Certificates

Place your TLS certificate files here:

- `fullchain.pem` — Full certificate chain (cert + intermediate CAs)
- `privkey.pem` — Private key

## Development (self-signed)

Generate a self-signed certificate for local development:

```bash
openssl req -x509 -newkey rsa:4096 -keyout privkey.pem -out fullchain.pem \
  -days 365 -nodes -subj "/CN=localhost"
```

## Production

Use Let's Encrypt (Certbot) or your organisation's PKI.
Never commit real private keys to version control.

The `.gitignore` excludes `*.pem` files from this directory.
