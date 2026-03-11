FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY timotion/ timotion/
COPY desk_server.py .
RUN pip install --no-cache-dir .

EXPOSE 8741

CMD ["python", "desk_server.py"]
