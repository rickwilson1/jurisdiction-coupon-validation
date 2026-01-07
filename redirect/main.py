from flask import Flask, redirect
import os

app = Flask(__name__)

# Your new Cloud Run URL (update after deploying tax-lookup)
NEW_URL = os.environ.get("REDIRECT_URL", "https://tax-lookup-751008504644.us-west1.run.app")

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def redirect_all(path):
    return redirect(NEW_URL, code=301)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

