import base64
import hashlib
import hmac
import re

from auth import authenticate
from constants import *
from flask import Flask, abort, request, json, send_file
from webhooks_data import EMAIL_PATTERN, SCAMMY_PATTERN


api = authenticate()
app = Flask(__name__)


def is_valid_webhook(req):
    """Check the webhook signature to ensure this came from Twitter"""
    if req.headers.has_key("x-twitter-webhooks-signature"):
        signature = req.headers.get("x-twitter-webhooks-signature")
        request_body = req.get_data(as_text=True)
        sha256_hash_digest = hmac.new(
            bytes(os.environ.get("API_KEY_SECRET"), "utf-8"),
            msg=bytes(request_body, "utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        hash_val = "sha256=" + base64.b64encode(sha256_hash_digest).decode("utf-8")
        return hmac.compare_digest(signature, hash_val)
    return False


def is_probably_spam(tweet):
    """Some additional checks so that people who interact with the bot in good faith won't all get reported."""
    if len(tweet["entities"]["urls"]) > 0:
        # Contains a URL
        return True
    if re.search(EMAIL_PATTERN, tweet["text"]):
        # Contains an email address; https://www.geeksforgeeks.org/check-if-email-address-valid-or-not-in-python/
        return True
    if re.search(SCAMMY_PATTERN, tweet["text"]):
        # With the easy tells out of the way, check for some other common indicators
        return True
    return False


def report(user_ids):
    """Send reports and record the number of users reported"""
    for user_id in user_ids:
        api.report_spam(user_id=user_id)
        print("Reported ID:", user_id)

    if os.path.exists(REPORTED_FILE_PATH):
        with open(REPORTED_FILE_PATH, "r") as reported_file:
            reported = int(reported_file.read().strip())
    else:
        reported = 0

    reported += len(user_ids)
    print("Total # reported:", reported)

    with open(REPORTED_FILE_PATH, "w+") as reported_file:
        reported_file.write(str(reported))


def handle_events(events):
    """Handles tweets, retweets, replies, quote tweets, mentions"""
    to_report = []
    for event in events:
        if event["user"]["id"] in ALLOWLISTED_USER_IDS:
            # Avoid reporting the bot itself, Molly, etc.
            continue
        if event["in_reply_to_user_id"] == BOT_ID or (
            event["is_quote_status"] and event["quoted_status"]["user"]["id"] == BOT_ID
        ):
            # Reply to the bot, quote tweet of the bot
            if is_probably_spam(event):
                to_report.append(event["user"]["id"])
    if len(to_report) > 0:
        report(to_report)


@app.route("/", methods=["GET"])
def webhook_challenge():
    if request.args and request.args.get("crc_token"):
        sha256_hash_digest = hmac.new(
            bytes(os.environ.get("API_KEY_SECRET"), "utf-8"),
            msg=bytes(request.args.get("crc_token"), "utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        response = {
            "response_token": "sha256="
            + base64.b64encode(sha256_hash_digest).decode("utf-8")
        }
        return response
    else:
        return "Nothing to see here but us webhook handlers"


@app.route("/", methods=["POST"])
def handle_webhook():
    if not is_valid_webhook(request):
        abort(403)
    body = request.json
    if "tweet_create_events" in body:
        handle_events(body["tweet_create_events"])
    return "", 204


@app.route("/stats", methods=["GET"])
def show_stats():
    return send_file(REPORTED_FILE_PATH)
