import os
import json
import functions_framework
from google.cloud import bigquery, pubsub_v1
import anthropic
from datetime import datetime

bq_client     = bigquery.Client()
pubsub_client = pubsub_v1.PublisherClient()
ai_client     = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PROJECT_ID      = os.environ["GCP_PROJECT_ID"]
BILLING_DATASET = os.environ.get("BILLING_DATASET", "billing_export")
BILLING_TABLE   = os.environ["BILLING_TABLE"]
TOPIC_NAME      = os.environ["PUBSUB_TOPIC"]
THRESHOLD_PCT   = float(os.environ.get("ANOMALY_THRESHOLD_PCT", "50"))

SYSTEM_PROMPT = """
You are a GCP cost anomaly analyst. You receive data about a spending spike
and explain it in plain English for an engineering team.

Respond with ONLY a JSON object:
{
  "title": "short alert title",
  "explanation": "plain English explanation of what caused the spike",
  "impact": "what this means for the monthly bill",
  "actions": ["action 1", "action 2", "action 3"]
}
"""


def detect_anomalies() -> list:
    """Detect services with >50% cost increase day over day."""
    query = f"""
    WITH daily_costs AS (
        SELECT
            service.description as service,
            DATE(usage_start_time) as usage_date,
            SUM(cost) as daily_cost
        FROM `{PROJECT_ID}.{BILLING_DATASET}.{BILLING_TABLE}`
        WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
        GROUP BY service, usage_date
    ),
    cost_changes AS (
        SELECT
            service,
            usage_date,
            daily_cost,
            LAG(daily_cost) OVER (PARTITION BY service ORDER BY usage_date) as prev_cost,
            SAFE_DIVIDE(
                daily_cost - LAG(daily_cost) OVER (PARTITION BY service ORDER BY usage_date),
                LAG(daily_cost) OVER (PARTITION BY service ORDER BY usage_date)
            ) * 100 as pct_change
        FROM daily_costs
    )
    SELECT service, usage_date, daily_cost, prev_cost, pct_change
    FROM cost_changes
    WHERE pct_change > {THRESHOLD_PCT}
    AND usage_date = CURRENT_DATE()
    ORDER BY pct_change DESC
    """

    results   = bq_client.query(query).result()
    anomalies = []

    for row in results:
        anomalies.append({
            "service":    row.service,
            "date":       str(row.usage_date),
            "daily_cost": float(row.daily_cost),
            "prev_cost":  float(row.prev_cost) if row.prev_cost else 0,
            "pct_change": float(row.pct_change)
        })

    return anomalies


def explain_anomaly(anomaly: dict) -> dict:
    """Ask Claude to explain the anomaly."""
    message = f"""
A GCP cost anomaly was detected:

Service: {anomaly['service']}
Today's cost: ${anomaly['daily_cost']:.2f}
Yesterday's cost: ${anomaly['prev_cost']:.2f}
Percentage increase: {anomaly['pct_change']:.1f}%

Explain this anomaly and suggest actions to investigate and resolve it.
"""

    response = ai_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


def publish_to_pubsub(anomaly: dict, explanation: dict):
    """Publish anomaly alert to Pub/Sub topic."""
    topic_path = pubsub_client.topic_path(PROJECT_ID, TOPIC_NAME)

    message = {
        "anomaly":     anomaly,
        "explanation": explanation,
        "timestamp":   datetime.now().isoformat()
    }

    data = json.dumps(message).encode()
    pubsub_client.publish(topic_path, data)
    print(f"Published anomaly for {anomaly['service']} to Pub/Sub")


@functions_framework.http
def anomaly_detector(request):
    """Main Cloud Function entry point."""
    print("Starting anomaly detection...")

    try:
        anomalies = detect_anomalies()
        print(f"Found {len(anomalies)} anomalies")

        for anomaly in anomalies:
            explanation = explain_anomaly(anomaly)
            publish_to_pubsub(anomaly, explanation)
            print(f"Processed anomaly: {explanation['title']}")

        return {
            "status":          "success",
            "anomalies_found": len(anomalies)
        }, 200

    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error", "message": str(e)}, 500