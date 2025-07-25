import secrets

# 32바이트(256비트)의 무작위 URL 안전 텍스트 문자열 생성
secret_key = secrets.token_urlsafe(32)
print(secret_key)