FROM python:3.12-slim
RUN pip install --no-cache-dir aiohttp
COPY proxy.py /app/proxy.py
CMD ["python", "/app/proxy.py"]
