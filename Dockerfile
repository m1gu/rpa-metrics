FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browsers are pre-bundled, this ensures Chromium is present.
RUN python -m playwright install chromium

COPY . /app

CMD ["python", "robot_metrc.py", "--days", "30"]
