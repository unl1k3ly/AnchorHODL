FROM python:3.8
WORKDIR /app
COPY ./requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000

ENV FLASK_ENV "production"
ENV FLASK_DEBUG False
ENV FLASK_APP "webview.py"
ENV MNEMONIC ""

CMD ["flask", "run", "--host", "0.0.0.0", "--port", "5000"]
