"""App del chat de FAQ — esqueleto del hito 0.

Sirve la interfaz web y un endpoint de salud. En el hito 6-7 esta misma app se
empaqueta en Docker para la EC2 y luego se migra el backend a Lambda.
"""

from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

VERSION = "0.1.0"


@app.get("/health")
def health():
    return jsonify(status="ok", service="gtn-faq-chat", version=VERSION)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
