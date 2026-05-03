import os
import json
from flask import Flask, render_template, jsonify
from google.cloud import bigquery, pubsub_v1
from datetime import datetime

app = Flask(__name__)

bq_client     = bigquery.Client()
pubsub_client = pubsub_v1.SubscriberClient()

PROJECT_ID    = os.environ["GCP_PROJECT_ID"]
TOPIC_NAME    = os.environ.get("PUBSUB_TOPIC", "cost-anomalies-dev")
SUBSCRIPTION  = os.environ.get("PUBSUB_SUBSCRIPTION", "cost-anomalies-sub-dev")


def get_latest_report() -> dict:
    """Fetch the most recent daily report from BigQuery."""
    query = f"""
    SELECT *
    FROM `{PROJECT_ID}.cost_analysis.daily_reports`
    ORDER BY report_date DESC
    LIMIT 1
    """
    try:
        results = bq_client.query(query).result()
        for row in results:
            return {
                "report_date":     row.report_date,
                "total_cost":      float(row.total_cost),
                "summary":         row.summary,
                "recommendations": json.loads(row.recommendations),
                "anomalies":       json.loads(row.anomalies),
                "top_services":    json.loads(row.top_services),
            }
    except Exception as e:
        print(f"BigQuery error: {e}")
        return get_sample_report()


def get_sample_report() -> dict:
    """Return sample data for demo purposes."""
    return {
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "total_cost":  847.32,
        "summary":     "GCP spending increased 12% this week, driven primarily by BigQuery and Cloud Run usage. Three optimization opportunities identified that could save approximately $180/month.",
        "top_services": [
            {"service": "BigQuery",       "cost": 312.40, "trend": "increasing"},
            {"service": "Cloud Run",      "cost": 198.20, "trend": "stable"},
            {"service": "Cloud Storage",  "cost": 145.80, "trend": "stable"},
            {"service": "Cloud Functions","cost": 98.50,  "trend": "decreasing"},
            {"service": "Pub/Sub",        "cost": 92.42,  "trend": "stable"},
        ],
        "anomalies": [
            {
                "description": "BigQuery costs increased 68% vs last week",
                "impact":      "$120 above expected weekly spend",
                "severity":    "high"
            }
        ],
        "recommendations": [
            {
                "title":              "Partition BigQuery tables by date",
                "description":        "Your top 3 BigQuery tables are unpartitioned. Adding date partitioning reduces query costs by scanning less data.",
                "estimated_savings":  "$90/month",
                "effort":             "low"
            },
            {
                "title":              "Set Cloud Run minimum instances to 0",
                "description":        "Two Cloud Run services have minimum instances set to 1 and receive minimal traffic outside business hours.",
                "estimated_savings":  "$55/month",
                "effort":             "low"
            },
            {
                "title":              "Move Cloud Storage to Nearline for infrequent data",
                "description":        "85% of your Cloud Storage objects were last accessed over 30 days ago. Moving to Nearline storage reduces costs significantly.",
                "estimated_savings":  "$35/month",
                "effort":             "medium"
            }
        ]
    }


def get_recent_anomalies() -> list:
    """Pull recent anomaly messages from Pub/Sub."""
    subscription_path = pubsub_client.subscription_path(PROJECT_ID, SUBSCRIPTION)
    anomalies = []

    try:
        response = pubsub_client.pull(
            request={"subscription": subscription_path, "max_messages": 10}
        )
        for msg in response.received_messages:
            data = json.loads(msg.message.data.decode())
            anomalies.append(data)
    except Exception as e:
        print(f"Pub/Sub error: {e}")

    return anomalies


@app.route("/")
def index():
    report   = get_latest_report()
    anomalies = get_recent_anomalies()
    return render_template("index.html", report=report, anomalies=anomalies)


@app.route("/api/report")
def api_report():
    return jsonify(get_latest_report())


@app.route("/api/anomalies")
def api_anomalies():
    return jsonify(get_recent_anomalies())


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)