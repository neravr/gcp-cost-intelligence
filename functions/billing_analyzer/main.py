import os
import json
import functions_framework
from google.cloud import bigquery
import anthropic
from datetime import datetime, timedelta

# Initialize clients
bq_client  = bigquery.Client()
ai_client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PROJECT_ID      = os.environ["GCP_PROJECT_ID"]
BILLING_DATASET = os.environ.get("BILLING_DATASET", "billing_export")
BILLING_TABLE   = os.environ["BILLING_TABLE"]
REPORT_EMAIL    = os.environ["REPORT_EMAIL"]

SYSTEM_PROMPT = """
You are a GCP cloud cost analyst. You receive billing data from BigQuery
and your job is to analyze it and provide actionable cost optimization recommendations.

Always respond with ONLY a JSON object:
{
  "summary": "2-3 sentence plain English summary of overall spending",
  "total_cost": number,
  "currency": "USD",
  "top_services": [
    {"service": "name", "cost": number, "trend": "increasing|stable|decreasing"}
  ],
  "anomalies": [
    {"description": "what changed", "impact": "cost impact", "severity": "high|medium|low"}
  ],
  "recommendations": [
    {
      "title": "short title",
      "description": "what to do and why",
      "estimated_savings": "monthly savings estimate",
      "effort": "low|medium|high"
    }
  ]
}
"""

def query_billing_data() -> dict:
    """Query last 7 days of billing data from BigQuery."""
    query = f"""
    SELECT
        service.description as service,
        SUM(cost) as total_cost,
        SUM(cost) - LAG(SUM(cost)) OVER (
            PARTITION BY service.description
            ORDER BY DATE_TRUNC(usage_start_time, WEEK)
        ) as week_over_week_change,
        DATE_TRUNC(usage_start_time, DAY) as usage_date
    FROM `{PROJECT_ID}.{BILLING_DATASET}.{BILLING_TABLE}`
    WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY service, usage_date
    ORDER BY total_cost DESC
    LIMIT 50
    """

    query_job = bq_client.query(query)
    results   = query_job.result()

    rows = []
    for row in results:
        rows.append({
            "service":              row.service,
            "total_cost":           float(row.total_cost),
            "week_over_week_change": float(row.week_over_week_change) if row.week_over_week_change else 0,
            "usage_date":           str(row.usage_date)
        })

    return rows


def analyze_with_claude(billing_data: list) -> dict:
    """Send billing data to Claude for analysis."""
    message = f"""
Analyze this GCP billing data from the last 7 days and provide cost optimization recommendations.

Billing data:
{json.dumps(billing_data, indent=2)}

Today's date: {datetime.now().strftime('%Y-%m-%d')}
"""

    response = ai_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


def send_email_report(analysis: dict):
    """Send cost report via SendGrid."""
    import urllib.request

    sendgrid_key = os.environ["SENDGRID_API_KEY"]

    recommendations_html = ""
    for rec in analysis.get("recommendations", []):
        recommendations_html += f"""
        <div style="margin-bottom:16px;padding:12px;border-left:3px solid #4285f4;">
            <strong>{rec['title']}</strong><br>
            {rec['description']}<br>
            <small>Estimated savings: {rec['estimated_savings']} | Effort: {rec['effort']}</small>
        </div>
        """

    html_content = f"""
    <h2>GCP Cost Intelligence Report</h2>
    <p>{analysis['summary']}</p>
    <h3>Total spend (last 7 days): ${analysis['total_cost']:.2f}</h3>
    <h3>Recommendations</h3>
    {recommendations_html}
    """

    payload = json.dumps({
        "personalizations": [{"to": [{"email": REPORT_EMAIL}]}],
        "from":    {"email": "cost-intelligence@yourdomain.com"},
        "subject": f"GCP Cost Report {datetime.now().strftime('%Y-%m-%d')}",
        "content": [{"type": "text/html", "value": html_content}]
    }).encode()

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {sendgrid_key}",
            "Content-Type":  "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(req) as resp:
        print(f"Email sent: {resp.status}")


def save_analysis_to_bq(analysis: dict):
    """Save Claude's analysis results to BigQuery for dashboard use."""
    table_id = f"{PROJECT_ID}.cost_analysis.daily_reports"

    rows = [{
        "report_date":       datetime.now().strftime("%Y-%m-%d"),
        "total_cost":        analysis["total_cost"],
        "summary":           analysis["summary"],
        "recommendations":   json.dumps(analysis.get("recommendations", [])),
        "anomalies":         json.dumps(analysis.get("anomalies", [])),
        "top_services":      json.dumps(analysis.get("top_services", [])),
        "created_at":        datetime.now().isoformat()
    }]

    errors = bq_client.insert_rows_json(table_id, rows)
    if errors:
        print(f"BigQuery insert errors: {errors}")
    else:
        print("Analysis saved to BigQuery")


@functions_framework.http
def billing_analyzer(request):
    """Main Cloud Function entry point."""
    print("Starting billing analysis...")

    try:
        billing_data = query_billing_data()
        print(f"Queried {len(billing_data)} rows from BigQuery")

        analysis = analyze_with_claude(billing_data)
        print(f"Claude analysis complete: {analysis['summary'][:100]}")

        save_analysis_to_bq(analysis)
        send_email_report(analysis)

        return {"status": "success", "summary": analysis["summary"]}, 200

    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error", "message": str(e)}, 500