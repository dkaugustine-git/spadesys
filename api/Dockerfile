FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
 && python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print('\n'.join(d['project']['dependencies']+d['project']['optional-dependencies']['dev']))" > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt

COPY . .
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "spadesys.main:app", "--host", "0.0.0.0", "--port", "8000"]
