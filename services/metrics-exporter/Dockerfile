FROM python:3.12-slim

# Never write .pyc files or buffer stdout: pyc files bloat the image and
# buffered output means container logs arrive late or not at all on a crash.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY exporter.py .

# Run as a non-root user. A container process that does not need root should
# not have it, so a container escape does not start from a privileged shell.
RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 9102

CMD ["python", "exporter.py"]
