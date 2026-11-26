FROM python:3.12-slim
WORKDIR /srv/quiz
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py answers.json ./
COPY static ./static
ENV DB_PATH=/data/quiz.db
VOLUME /data
EXPOSE 8080
CMD ["uvicorn", "app:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8080"]
